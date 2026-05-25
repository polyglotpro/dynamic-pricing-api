from .pricing_agent import pricing_agent
from .advertising_agent import advertising_agent

def run_separate_agents(state):
    """
    Executes agents independently.
    """
    price_change = pricing_agent(state)
    ad_change = advertising_agent(state)
    
    return price_change, ad_change, []
