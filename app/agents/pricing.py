from app.models import SKUInput, AgentDecision
from app.config import CONFIG
from app.core.financials import margin_pct


def pricing_agent(payload: SKUInput) -> AgentDecision:
    drivers = []
    action = "hold_price"
    change_pct = 0
    confidence = 0.70
    approval_required = False

    current_margin_pct = margin_pct(
        payload.current_price,
        payload.cost,
        payload.current_ad_spend_per_unit
    )

    competitor_gap_pct = None
    if payload.competitor_price:
        competitor_gap_pct = ((payload.current_price - payload.competitor_price) / payload.current_price) * 100
        if competitor_gap_pct > 5:
            drivers.append(f"Competitor is cheaper by {competitor_gap_pct:.1f}%")

    conversion_drop = False
    if payload.previous_conversion_rate and payload.previous_conversion_rate > 0:
        drop_pct = ((payload.previous_conversion_rate - payload.conversion_rate) / payload.previous_conversion_rate) * 100
        if drop_pct > 20:
            conversion_drop = True
            drivers.append(f"Conversion dropped by {drop_pct:.1f}%")

    if payload.ageing_days > CONFIG["inventory"]["ageing_alert_days"]:
        drivers.append(f"Inventory ageing is {payload.ageing_days} days")

    if payload.days_of_cover > CONFIG["inventory"]["overstock_days_of_cover"]:
        drivers.append(f"Days of cover is high at {payload.days_of_cover:.0f}")

    if payload.sales_vs_baseline >= CONFIG["seasonality"]["peak_sales_multiplier"]:
        drivers.append("Demand is above peak threshold")
        if current_margin_pct > CONFIG["approval_margin_floor_pct"]:
            action = "increase_price"
            change_pct = CONFIG["actions"]["increase_price_pct"]
            confidence = 0.78

    elif (
        payload.days_of_cover > CONFIG["inventory"]["overstock_days_of_cover"]
        and payload.ageing_days > CONFIG["inventory"]["ageing_alert_days"]
    ):
        action = "deep_discount"
        change_pct = CONFIG["actions"]["deep_discount_pct"]
        confidence = 0.88

    elif competitor_gap_pct and competitor_gap_pct > 5 and conversion_drop:
        action = "reduce_price"
        change_pct = CONFIG["actions"]["reduce_price_pct"]
        confidence = 0.82

    projected_price = payload.current_price * (1 + change_pct / 100)
    projected_margin_pct = margin_pct(projected_price, payload.cost, payload.current_ad_spend_per_unit)

    if projected_margin_pct < CONFIG["margin_floor_pct"]:
        approval_required = True
        drivers.append(f"Projected margin {projected_margin_pct:.1f}% is below margin floor")

    if not drivers:
        drivers.append("Price is competitive and conversion is stable")

    return AgentDecision(
        agent="pricing",
        recommended_action=action,
        change_pct=change_pct,
        reasoning="; ".join(drivers),
        key_drivers=drivers,
        confidence=confidence,
        approval_required=approval_required
    )
