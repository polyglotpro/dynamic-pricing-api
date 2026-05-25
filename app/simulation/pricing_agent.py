def pricing_agent(state) -> float:
    """
    Separate pricing agent logic.
    Returns the percentage change in price.
    """
    competitor_gap = (state.current_price - state.competitor_price) / state.competitor_price

    if competitor_gap > 0.05:
        return -0.05   # reduce price by 5%

    if competitor_gap < -0.08:
        return 0.02    # raise price by 2%

    return 0.0
