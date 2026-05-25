from app.models import SKUInput, AgentDecision
from app.config import CONFIG


def inventory_agent(payload: SKUInput) -> AgentDecision:
    drivers = []
    state = "healthy_stock"
    action = "signal_healthy_stock"
    confidence = 0.78

    if payload.stockout_risk > CONFIG["inventory"]["stockout_risk_block_ads"]:
        state = "low_stock"
        action = "restrict_aggressive_promotion"
        confidence = 0.92
        drivers.append(f"Stockout risk is {payload.stockout_risk:.0%}")

    elif payload.days_of_cover > CONFIG["inventory"]["overstock_days_of_cover"] and payload.sell_through_rate_weekly < 0.05:
        state = "overstock"
        action = "allow_aggressive_sell_through"
        confidence = 0.91
        drivers.append(f"Days of cover {payload.days_of_cover:.0f} and sell-through {payload.sell_through_rate_weekly:.1%}/week indicate overstock")

    elif payload.ageing_days > CONFIG["inventory"]["ageing_alert_days"]:
        state = "ageing"
        action = "trigger_ageing_alert"
        confidence = 0.86
        drivers.append(f"Ageing inventory is {payload.ageing_days} days")

    else:
        drivers.append(f"Days of cover {payload.days_of_cover:.0f} is within acceptable range")

    return AgentDecision(
        agent="inventory",
        recommended_action=action,
        change_pct=None,
        state=state,
        reasoning="; ".join(drivers),
        key_drivers=drivers,
        confidence=confidence,
        approval_required=False
    )
