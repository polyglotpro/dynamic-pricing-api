def advertising_agent(state) -> float:
    """
    Separate advertising agent logic.
    Returns the percentage change in ad spend.
    """
    # In a real system, ROAS would be calculated from recent history.
    # Here we assume state.roas is provided by the simulator.
    if state.roas > 3.5:
        return 0.08    # increase ad spend by 8%

    if state.roas < 2.0:
        return -0.10   # reduce ad spend by 10%

    return 0.0
