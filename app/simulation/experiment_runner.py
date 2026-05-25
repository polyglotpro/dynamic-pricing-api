from .scenario_library import get_scenario
from .simulator import run_simulation
from .models import ComparisonResult

def run_comparison(scenario_id: str) -> ComparisonResult:
    """
    Runs both separate and integrated engines for a scenario and compares them.
    """
    # Run Separate
    state_sep = get_scenario(scenario_id)
    res_sep = run_simulation(state_sep, engine_type="separate")
    
    # Run Integrated
    state_int = get_scenario(scenario_id)
    res_int = run_simulation(state_int, engine_type="integrated")
    
    # Calculate Delta
    delta = {
        "net_profit": res_int.net_profit - res_sep.net_profit,
        "ending_inventory": res_int.ending_inventory - res_sep.ending_inventory,
        "sell_through_pct": res_int.sell_through_pct - res_sep.sell_through_pct,
        "units_sold": res_int.units_sold - res_sep.units_sold
    }
    
    # Determine winner
    winner = "integrated" if res_int.net_profit > res_sep.net_profit else "separate"
    
    # Get research metadata
    from .scenario_library import get_research_data
    research = get_research_data(scenario_id)
    
    return ComparisonResult(
        scenario_id=scenario_id,
        separate=res_sep,
        integrated=res_int,
        delta=delta,
        winner=winner,
        scenario_name=research.get("scenario_name"),
        interpretation=research.get("interpretation"),
        demo_message=research.get("demo_message")
    )

def run_single_simulation(scenario_id: str, engine_type: str):
    """
    Runs a single engine for a scenario.
    """
    state = get_scenario(scenario_id)
    return run_simulation(state, engine_type=engine_type)
