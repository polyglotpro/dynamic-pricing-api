from typing import Dict, Any, Tuple

def orchestrator_rules(state, proposed_price_change: float, proposed_ad_change: float) -> Tuple[float, float, list]:
    """
    Applies integrated orchestration rules (OR-01 to OR-06) and global margin floor.
    Returns (final_price_change, final_ad_change, rules_triggered).
    """
    rules_triggered = []
    
    current_price = state.current_price
    current_ad_spend = state.current_ad_spend
    cogs = state.cogs
    benchmark_price = state.benchmark_price
    benchmark_ad_spend = getattr(state, 'benchmark_ad_spend', current_ad_spend)
    
    new_price = current_price * (1.0 + proposed_price_change)
    new_ad_spend = current_ad_spend * (1.0 + proposed_ad_change)
    
    current_margin = (current_price - cogs) / current_price if current_price > 0 else 0.0
    
    # OR-01: Price cut + ad increase + thin margin
    if proposed_price_change < 0 and proposed_ad_change > 0 and current_margin < 0.45:
        new_ad_spend = current_ad_spend  # Block ad increase
        rules_triggered.append("OR-01")

    # OR-02: Seasonal Clearance Logic
    if getattr(state, 'days_to_season_end', None) is not None and state.days_to_season_end < 14 and state.current_stock > 100:
        min_ad_spend = benchmark_ad_spend * 0.2
        if min_ad_spend < 50:
            min_ad_spend = 50.0
            
        if current_ad_spend > min_ad_spend:
            # Aggressive ad spend reduction (30% of current)
            new_ad_spend = current_ad_spend * 0.4
            # Hold price while cuts are being evaluated
            new_price = current_price
        else:
            # After ad spend is low, apply modest price discount (max 5%)
            new_ad_spend = min_ad_spend
            tentative_price = min(current_price, benchmark_price * 0.97)
            # Ensure margin floor before applying
            avg_ad_per_unit = current_ad_spend / max(1.0, state.base_demand)
            projected_margin = (tentative_price - cogs - avg_ad_per_unit) / tentative_price if tentative_price > 0 else 0.0
            if projected_margin >= getattr(state, 'min_margin_pct', 0.15):
                new_price = tentative_price
            else:
                new_price = current_price  # block price cut
            
        rules_triggered.append("OR-02")

    # OR-04: Overstock Resolution
    elif state.current_stock > getattr(state, 'overstock_threshold', float('inf')):
        # Overstock: apply modest discount while respecting margin floor
        tentative_price = min(current_price, benchmark_price * 0.92)
        avg_ad_per_unit = current_ad_spend / max(1.0, state.base_demand)
        projected_margin = (tentative_price - cogs - avg_ad_per_unit) / tentative_price if tentative_price > 0 else 0.0
        if projected_margin >= getattr(state, 'min_margin_pct', 0.15):
            new_price = tentative_price
        else:
            new_price = current_price  # block discount
        # Reduce ad spend moderately (10%)
        new_ad_spend = min(current_ad_spend, benchmark_ad_spend * 0.9)

        rules_triggered.append("OR-04")

    # OR-03: Low stock
    elif state.current_stock < getattr(state, 'low_stock_threshold', 0):
        new_ad_spend = current_ad_spend * 0.85 # Cut ads gradually
        if new_price < current_price:
            new_price = current_price * 1.02 # Raise price instead of discounting
        rules_triggered.append("OR-03")

    # OR-05: High uncertainty
    if getattr(state, 'high_uncertainty_mode', False):
        # In high uncertainty, we might dampen changes
        new_price = current_price + (new_price - current_price) * 0.5
        new_ad_spend = current_ad_spend + (new_ad_spend - current_ad_spend) * 0.5
        rules_triggered.append("OR-05")

    # OR-06: Hero SKU
    if getattr(state, 'hero_sku', False) and state.current_stock > getattr(state, 'low_stock_threshold', 0):
        # Protect visibility for Hero SKUs
        new_ad_spend = max(new_ad_spend, current_ad_spend)
        rules_triggered.append("OR-06")
        
    # Margin Floor Enforcement (Global rule)
    avg_ad_per_unit = current_ad_spend / max(1.0, state.base_demand)
    projected_margin = (new_price - cogs - avg_ad_per_unit) / new_price if new_price > 0 else 0.0
    margin_floor = getattr(state, 'min_margin_pct', 0.15)
    
    if projected_margin < margin_floor and new_price < current_price:
        # Block reduction, escalate to human
        new_price = current_price  # Hold price
        rules_triggered.append("MARGIN_FLOOR")

    final_price_change = (new_price - current_price) / current_price if current_price > 0 else 0.0
    final_ad_change = (new_ad_spend - current_ad_spend) / current_ad_spend if current_ad_spend > 0 else 0.0
    
    return final_price_change, final_ad_change, rules_triggered
