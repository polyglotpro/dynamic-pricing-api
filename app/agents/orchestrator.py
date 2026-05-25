from typing import List
from app.models import SKUInput, AgentDecision, RecommendationResponse, FinancialImpact
from app.config import CONFIG
from app.core.financials import contribution_margin, margin_pct, estimate_units_cleared


def orchestrate(payload: SKUInput, decisions: List[AgentDecision]) -> RecommendationResponse:
    by_agent = {d.agent: d for d in decisions}

    pricing = by_agent["pricing"]
    ads = by_agent["advertising"]
    inventory = by_agent["inventory"]
    seasonality = by_agent["seasonality"]

    price_action = pricing.recommended_action
    price_change_pct = pricing.change_pct or 0
    ad_action = ads.recommended_action
    ad_change_pct = ads.change_pct or 0

    objective = "efficiency"
    risk_level = "Low"
    approval_required = any(d.approval_required for d in decisions)
    decision_parameters = []

    inventory_state = inventory.state
    seasonality_state = seasonality.state

    if inventory_state in ["overstock", "ageing"] and seasonality_state in ["decline", "end_of_season"]:
        objective = "sell_through"
        decision_parameters.append("Inventory pressure and declining seasonality favor clearance")
        if price_change_pct == 0:
            price_action = "reduce_price"
            price_change_pct = CONFIG["actions"]["reduce_price_pct"]
        if payload.roas < CONFIG["roas"]["hold_low"]:
            ad_action = "reduce_spend"
            ad_change_pct = CONFIG["actions"]["reduce_ad_pct"]

    elif inventory_state == "low_stock":
        objective = "margin_protection"
        decision_parameters.append("Low stock requires margin protection")
        if price_change_pct < 0:
            price_action = "hold_price"
            price_change_pct = 0
        if ad_change_pct > 0:
            ad_action = "reduce_spend"
            ad_change_pct = CONFIG["actions"]["reduce_ad_pct"]

    elif payload.hero_sku and payload.roas > 2.0:
        objective = "visibility"
        decision_parameters.append("Hero SKU with acceptable ROAS supports visibility defense")

    elif payload.roas < CONFIG["roas"]["hold_low"]:
        objective = "efficiency"
        decision_parameters.append("Weak ROAS requires spend control")

    current_margin = contribution_margin(
        payload.current_price,
        payload.cost,
        payload.current_ad_spend_per_unit
    )

    projected_price = payload.current_price * (1 + price_change_pct / 100)
    projected_ad_spend = payload.current_ad_spend_per_unit * (1 + ad_change_pct / 100)

    projected_margin = contribution_margin(projected_price, payload.cost, projected_ad_spend)
    projected_margin_pct = margin_pct(projected_price, payload.cost, projected_ad_spend)

    if projected_margin_pct < CONFIG["margin_floor_pct"]:
        approval_required = True
        risk_level = "High"
        decision_parameters.append(f"Projected margin {projected_margin_pct:.1f}% is below margin floor")
    elif projected_margin_pct < CONFIG["approval_margin_floor_pct"]:
        risk_level = "Medium"
        decision_parameters.append(f"Projected margin {projected_margin_pct:.1f}% needs monitoring")

    if inventory_state == "overstock":
        decision_parameters.append("Product has high days of cover")
    if seasonality_state == "end_of_season":
        decision_parameters.append("Product is close to end of season")
    if payload.trend_change_7d_pct < -30:
        decision_parameters.append("Market interest is declining")
    if payload.roas < CONFIG["roas"]["hold_low"]:
        decision_parameters.append("Ad efficiency is weak")

    confidence = round(sum(d.confidence for d in decisions) / len(decisions), 2)

    if not decision_parameters:
        decision_parameters.append("Signals are stable across agents")

    estimated_units = estimate_units_cleared(payload, price_change_pct, ad_change_pct)

    impact_summary = _build_impact_summary(
        objective=objective,
        unit_margin_change=projected_margin - current_margin,
        estimated_units=estimated_units
    )

    reasoning = _build_reasoning(objective, price_action, price_change_pct, ad_action, ad_change_pct, decision_parameters)

    financial_impact = FinancialImpact(
        current_unit_margin=round(current_margin, 2),
        projected_unit_margin=round(projected_margin, 2),
        unit_margin_change=round(projected_margin - current_margin, 2),
        projected_price=round(projected_price, 2),
        projected_ad_spend_per_unit=round(projected_ad_spend, 2),
        margin_pct_after_action=round(projected_margin_pct, 2),
        estimated_units_cleared=estimated_units,
        impact_summary=impact_summary
    )

    return RecommendationResponse(
        sku_id=payload.sku_id,
        product_name=payload.product_name,
        primary_objective=objective,
        price_action=price_action,
        price_change_pct=price_change_pct,
        ad_action=ad_action,
        ad_change_pct=ad_change_pct,
        confidence=confidence,
        risk_level=risk_level,
        approval_required=approval_required,
        reasoning=reasoning,
        decision_parameters=decision_parameters,
        agent_decisions=decisions,
        financial_impact=financial_impact
    )


def _build_reasoning(objective, price_action, price_change_pct, ad_action, ad_change_pct, params):
    return (
        f"Primary objective is {objective}. "
        f"Recommended price action: {price_action} ({price_change_pct:+.0f}%). "
        f"Recommended ad action: {ad_action} ({ad_change_pct:+.0f}%). "
        f"Key reasons: " + "; ".join(params)
    )


def _build_impact_summary(objective, unit_margin_change, estimated_units):
    if objective == "sell_through":
        return f"Prioritizes clearing approximately {estimated_units} units while controlling further ad waste."
    if objective == "margin_protection":
        return f"Protects unit margin. Projected unit margin change is ₹{unit_margin_change:.2f}."
    if objective == "visibility":
        return f"Maintains visibility with controlled spend. Projected unit margin change is ₹{unit_margin_change:.2f}."
    return f"Improves operating efficiency. Projected unit margin change is ₹{unit_margin_change:.2f}."
