import math

def compute_demand(
    base_demand: float,
    price: float,
    benchmark_price: float,
    price_elasticity: float,
    ad_spend: float,
    benchmark_ad_spend: float,
    ad_elasticity: float,
    seasonality_factor: float,
    shock: float
) -> float:
    """
    Computes deterministic demand based on price, ads, and seasonality.
    As per section 5 of EDPE_Separate_vs_Integrated_Engine_Design_v3.md
    """
    # Avoid division by zero
    if benchmark_price <= 0:
        benchmark_price = price if price > 0 else 1.0
        
    demand = (
        base_demand
        * (price / benchmark_price) ** price_elasticity
        * ((ad_spend + 1) / (benchmark_ad_spend + 1)) ** ad_elasticity
        * seasonality_factor
        * math.exp(shock)
    )

    return max(0.0, demand)
