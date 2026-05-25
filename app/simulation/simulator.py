import math
from .models import SimulationState, DailyRecord, SimulationResult
from .demand_model import compute_demand
from .separate_agents import run_separate_agents
from .integrated_agent import run_integrated_agent
from .scenario_library import get_brain_mapping

def run_simulation(state: SimulationState, engine_type: str) -> SimulationResult:
    """
    Runs a time-stepping simulation for the given state and engine.
    """
    history = []
    total_revenue = 0.0
    total_profit = 0.0
    total_units_sold = 0
    total_ad_spend = 0.0
    
    current_stock = state.current_stock
    current_price = state.current_price
    current_ad_spend = state.current_ad_spend
    
    # Brain mapping for this scenario
    brain_mapping = get_brain_mapping(state.scenario)
    
    for day in range(1, state.days + 1):
        # 1. Update seasonal signals
        if state.days_to_season_end is not None:
            state.days_to_season_end -= 1
            if state.seasonal_decay_per_day:
                state.seasonality_factor -= state.seasonal_decay_per_day
        
        # 2. Get shock for the day
        shock = 0.0
        if state.shock_sequence:
            shock_index = (day - 1) % len(state.shock_sequence)
            shock = state.shock_sequence[shock_index]
        
        # 3. Agents make decisions
        if engine_type == "separate":
            price_change_pct, ad_change_pct, _ = run_separate_agents(state)
        else:
            price_change_pct, ad_change_pct, _ = run_integrated_agent(state)
            
        # Apply changes (bounded)
        current_price *= (1 + price_change_pct)
        current_ad_spend *= (1 + ad_change_pct)
        
        # 4. Compute Demand
        demand = compute_demand(
            base_demand=state.base_demand,
            price=current_price,
            benchmark_price=state.benchmark_price,
            price_elasticity=state.price_elasticity,
            ad_spend=current_ad_spend,
            benchmark_ad_spend=state.benchmark_ad_spend,
            ad_elasticity=state.ad_elasticity,
            seasonality_factor=state.seasonality_factor,
            shock=shock
        )
        
        # 5. Fulfill demand
        units_sold = min(int(demand), current_stock)
        current_stock -= units_sold
        
        # 6. Financials
        daily_revenue = units_sold * current_price
        daily_margin_per_unit = current_price - state.cogs - (current_ad_spend / max(1, units_sold))
        daily_profit = units_sold * (current_price - state.cogs) - current_ad_spend
        
        total_revenue += daily_revenue
        total_profit += daily_profit
        total_units_sold += units_sold
        total_ad_spend += current_ad_spend
        
        # Update state for next day
        state.current_price = current_price
        state.current_ad_spend = current_ad_spend
        state.current_stock = current_stock
        # Simple ROAS update for agents
        state.roas = daily_revenue / max(1.0, current_ad_spend)
        
        history.append(DailyRecord(
            day=day,
            price=current_price,
            ad_spend=current_ad_spend,
            demand=demand,
            units_sold=units_sold,
            revenue=daily_revenue,
            profit=daily_profit,
            margin_pct=(current_price - state.cogs) / current_price if current_price > 0 else 0,
            stock=current_stock,
            roas=state.roas,
            shock=shock
        ))
        
        if current_stock <= 0:
            break

    # Final calculations
    ending_inventory = current_stock
    inventory_charges = (ending_inventory * state.leftover_inventory_charge_per_unit) + \
                        (ending_inventory * state.holding_cost_per_leftover_unit)
    
    net_profit = total_profit - inventory_charges
    sell_through_pct = (total_units_sold / (total_units_sold + ending_inventory)) * 100 if (total_units_sold + ending_inventory) > 0 else 0

    return SimulationResult(
        scenario_id=state.scenario,
        engine=engine_type,
        total_profit=total_profit,
        total_revenue=total_revenue,
        units_sold=total_units_sold,
        ending_inventory=ending_inventory,
        avg_margin_per_unit=total_profit / max(1, total_units_sold),
        avg_ad_spend_per_unit=total_ad_spend / max(1, total_units_sold),
        sell_through_pct=sell_through_pct,
        net_profit=net_profit,
        daily_history=history,
        brain_mapping=brain_mapping
    )
