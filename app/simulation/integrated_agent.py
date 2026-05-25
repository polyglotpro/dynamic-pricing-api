from .pricing_agent import pricing_agent
from .advertising_agent import advertising_agent
from .orchestrator import orchestrator_rules

def run_integrated_agent(state):
    """
    Executes agents and applies orchestration.
    """
    proposed_price_change = pricing_agent(state)
    proposed_ad_change = advertising_agent(state)
    
    final_price, final_ad, rules = orchestrator_rules(
        state, proposed_price_change, proposed_ad_change
    )
    
    return final_price, final_ad, rules
