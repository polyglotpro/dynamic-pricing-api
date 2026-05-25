from typing import Dict, Any, List
from app.models import SKUInput, AgentDecision
from app.agents.pricing import pricing_agent
from app.agents.advertising import advertising_agent
from app.agents.inventory import inventory_agent
from app.agents.seasonality import seasonality_agent
from app.agents.orchestrator import orchestrate
from app.core.financials import contribution_margin, margin_pct, estimate_units_cleared


def _financials(payload: SKUInput, price_change_pct: float, ad_change_pct: float) -> Dict[str, Any]:
    projected_price = payload.current_price * (1 + price_change_pct / 100)
    projected_ad_spend = payload.current_ad_spend_per_unit * (1 + ad_change_pct / 100)

    current_margin = contribution_margin(
        payload.current_price,
        payload.cost,
        payload.current_ad_spend_per_unit
    )
    projected_margin = contribution_margin(
        projected_price,
        payload.cost,
        projected_ad_spend
    )

    return {
        "projected_price": round(projected_price, 2),
        "projected_ad_spend_per_unit": round(projected_ad_spend, 2),
        "current_unit_margin": round(current_margin, 2),
        "projected_unit_margin": round(projected_margin, 2),
        "unit_margin_change": round(projected_margin - current_margin, 2),
        "margin_pct_after_action": round(margin_pct(projected_price, payload.cost, projected_ad_spend), 2),
        "estimated_units_cleared": estimate_units_cleared(payload, price_change_pct, ad_change_pct)
    }


def run_separate_system(payload: SKUInput) -> Dict[str, Any]:
    pricing = pricing_agent(payload)
    advertising = advertising_agent(payload)

    price_change_pct = pricing.change_pct or 0
    ad_change_pct = advertising.change_pct or 0

    financials = _financials(payload, price_change_pct, ad_change_pct)

    return {
        "system": "separate_agents",
        "description": "Pricing and advertising agents act independently. No orchestrator resolves conflicts.",
        "price_action": pricing.recommended_action,
        "price_change_pct": price_change_pct,
        "ad_action": advertising.recommended_action,
        "ad_change_pct": ad_change_pct,
        "financials": financials,
        "agent_decisions": [
            pricing.model_dump(),
            advertising.model_dump()
        ],
        "reasoning": (
            "Separate system applies pricing and advertising recommendations independently. "
            f"Pricing reason: {pricing.reasoning}. "
            f"Advertising reason: {advertising.reasoning}."
        )
    }


def run_integrated_system(payload: SKUInput) -> Dict[str, Any]:
    decisions: List[AgentDecision] = [
        pricing_agent(payload),
        advertising_agent(payload),
        inventory_agent(payload),
        seasonality_agent(payload),
    ]
    result = orchestrate(payload, decisions)
    return {
        "system": "integrated_agents",
        "description": "Pricing, advertising, inventory, and seasonality signals are coordinated by the orchestrator.",
        "price_action": result.price_action,
        "price_change_pct": result.price_change_pct,
        "ad_action": result.ad_action,
        "ad_change_pct": result.ad_change_pct,
        "primary_objective": result.primary_objective,
        "confidence": result.confidence,
        "risk_level": result.risk_level,
        "approval_required": result.approval_required,
        "financials": result.financial_impact.model_dump(),
        "agent_decisions": [d.model_dump() for d in result.agent_decisions],
        "reasoning": result.reasoning,
        "decision_parameters": result.decision_parameters
    }


def compare_systems(payload: SKUInput) -> Dict[str, Any]:
    separate = run_separate_system(payload)
    integrated = run_integrated_system(payload)

    sep_fin = separate["financials"]
    int_fin = integrated["financials"]

    margin_delta = round(
        int_fin["projected_unit_margin"] - sep_fin["projected_unit_margin"],
        2
    )
    ad_spend_delta = round(
        int_fin["projected_ad_spend_per_unit"] - sep_fin["projected_ad_spend_per_unit"],
        2
    )
    units_delta = int_fin["estimated_units_cleared"] - sep_fin["estimated_units_cleared"]

    if margin_delta > 0 and units_delta >= 0:
        winner = "integrated_agents"
    elif margin_delta < 0 and units_delta <= 0:
        winner = "separate_agents"
    else:
        winner = "context_dependent"

    research_answer = _build_research_answer(
        winner=winner,
        margin_delta=margin_delta,
        ad_spend_delta=ad_spend_delta,
        units_delta=units_delta,
        integrated=integrated,
        separate=separate
    )

    return {
        "sku_id": payload.sku_id,
        "product_name": payload.product_name,
        "research_question": "Do we need to combine pricing and advertising agents?",
        "separate_system": separate,
        "integrated_system": integrated,
        "comparison": {
            "winner": winner,
            "unit_margin_delta_integrated_vs_separate": margin_delta,
            "ad_spend_delta_integrated_vs_separate": ad_spend_delta,
            "units_cleared_delta_integrated_vs_separate": units_delta,
            "integrated_reduces_ad_spend": ad_spend_delta < 0,
            "integrated_improves_unit_margin": margin_delta > 0,
            "integrated_improves_clearance": units_delta > 0,
            "research_answer": research_answer
        }
    }


def _build_research_answer(
    winner: str,
    margin_delta: float,
    ad_spend_delta: float,
    units_delta: int,
    integrated: Dict[str, Any],
    separate: Dict[str, Any],
) -> str:
    if winner == "integrated_agents":
        return (
            "Yes, for this SKU state, combining pricing and advertising agents is better. "
            f"The integrated system improves unit margin by ₹{margin_delta:.2f} versus the separate system. "
            f"Ad spend delta is ₹{ad_spend_delta:.2f} per unit and estimated clearance delta is {units_delta} units. "
            "The orchestrator prevents independent actions from damaging total contribution margin."
        )

    if winner == "separate_agents":
        return (
            "No, for this SKU state, the separate system performs better. "
            f"The integrated system reduces unit margin by ₹{abs(margin_delta):.2f} versus the separate system. "
            "This is a boundary case where coordination does not add value."
        )

    return (
        "The answer is context dependent for this SKU state. "
        f"The integrated system margin delta is ₹{margin_delta:.2f}, ad spend delta is ₹{ad_spend_delta:.2f}, "
        f"and clearance delta is {units_delta} units. "
        "This supports the capstone hypothesis that integration should be applied selectively."
    )
