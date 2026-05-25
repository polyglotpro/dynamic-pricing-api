from app.models import SKUInput, AgentDecision
from app.config import CONFIG


def seasonality_agent(payload: SKUInput) -> AgentDecision:
    drivers = []
    mode = "stable"
    action = "stable_mode"
    confidence = 0.72

    if payload.season_days_left is not None and payload.season_days_left <= CONFIG["seasonality"]["end_of_season_days"]:
        mode = "end_of_season"
        action = "end_of_season_mode"
        confidence = 0.88
        drivers.append(f"Only {payload.season_days_left} season days left")

    elif payload.sales_vs_baseline >= CONFIG["seasonality"]["peak_sales_multiplier"]:
        mode = "peak_demand"
        action = "peak_demand_mode"
        confidence = 0.82
        drivers.append(f"Sales are {payload.sales_vs_baseline:.1f}x baseline")

    elif payload.sales_vs_baseline < CONFIG["seasonality"]["decline_sales_multiplier"]:
        mode = "decline"
        action = "decline_mode"
        confidence = 0.80
        drivers.append(f"Sales are below baseline at {payload.sales_vs_baseline:.1f}x")

    elif payload.trend_change_7d_pct >= CONFIG["seasonality"]["trend_opportunity_pct"]:
        mode = "trend_opportunity"
        action = "trend_opportunity_mode"
        confidence = 0.78
        drivers.append(f"Trend is up {payload.trend_change_7d_pct:.1f}% in 7 days")

    else:
        drivers.append("Seasonality is stable")

    if payload.trend_change_7d_pct < -30:
        drivers.append(f"Trend is down {abs(payload.trend_change_7d_pct):.1f}% in 7 days")

    return AgentDecision(
        agent="seasonality",
        recommended_action=action,
        change_pct=None,
        state=mode,
        reasoning="; ".join(drivers),
        key_drivers=drivers,
        confidence=confidence,
        approval_required=False
    )
