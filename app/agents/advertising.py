from app.models import SKUInput, AgentDecision
from app.config import CONFIG


def advertising_agent(payload: SKUInput) -> AgentDecision:
    drivers = []
    action = "hold_spend"
    change_pct = 0
    confidence = 0.70
    approval_required = False

    if payload.stockout_risk > CONFIG["inventory"]["stockout_risk_block_ads"]:
        action = "reduce_spend"
        change_pct = CONFIG["actions"]["reduce_ad_pct"]
        confidence = 0.90
        drivers.append(f"Stockout risk {payload.stockout_risk:.0%} exceeds threshold")

    elif payload.roas < CONFIG["roas"]["pause"]:
        action = "pause_aggressive_support"
        change_pct = CONFIG["actions"]["pause_ad_pct"]
        confidence = 0.86
        drivers.append(f"ROAS {payload.roas:.2f} is below pause threshold")

    elif payload.roas < CONFIG["roas"]["hold_low"]:
        action = "reduce_spend"
        change_pct = CONFIG["actions"]["reduce_ad_pct"]
        confidence = 0.80
        drivers.append(f"ROAS {payload.roas:.2f} is below efficiency threshold")

    elif payload.roas > CONFIG["roas"]["increase"]:
        action = "increase_spend"
        change_pct = CONFIG["actions"]["increase_ad_pct"]
        confidence = 0.82
        drivers.append(f"ROAS {payload.roas:.2f} exceeds growth threshold")

    elif payload.hero_sku and payload.roas > 2.0:
        action = "defend_visibility"
        change_pct = CONFIG["actions"]["defend_visibility_pct"]
        confidence = 0.76
        drivers.append("Hero SKU with acceptable ROAS")

    else:
        drivers.append(f"ROAS {payload.roas:.2f} is within hold range")

    if payload.days_of_cover <= CONFIG["inventory"]["healthy_cover_min"]:
        drivers.append("Low days of cover limits advertising expansion")

    return AgentDecision(
        agent="advertising",
        recommended_action=action,
        change_pct=change_pct,
        reasoning="; ".join(drivers),
        key_drivers=drivers,
        confidence=confidence,
        approval_required=approval_required
    )
