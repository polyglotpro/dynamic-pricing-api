from app.models import SKUInput
from app.config import CONFIG


def contribution_margin(price: float, cost: float, ad_spend: float) -> float:
    return price - cost - ad_spend


def margin_pct(price: float, cost: float, ad_spend: float) -> float:
    if price <= 0:
        return 0
    return ((price - cost - ad_spend) / price) * 100


def estimate_units_cleared(payload: SKUInput, price_change_pct: float, ad_change_pct: float) -> int:
    # Simple demo estimate. This is not a production forecasting model.
    # It gives the UI a reasonable directional number.
    base_clearance = max(1, int(payload.stock_on_hand * min(payload.sell_through_rate_weekly, 1)))

    price_boost = 0
    if price_change_pct <= -15:
        price_boost = int(payload.stock_on_hand * 0.25)
    elif price_change_pct < 0:
        price_boost = int(payload.stock_on_hand * 0.10)

    ad_boost = 0
    if ad_change_pct > 0:
        ad_boost = int(payload.stock_on_hand * 0.08)
    elif ad_change_pct < 0:
        ad_boost = -int(payload.stock_on_hand * 0.03)

    urgency_boost = 0
    if payload.season_days_left is not None and payload.season_days_left <= CONFIG["seasonality"]["end_of_season_days"]:
        urgency_boost = int(payload.stock_on_hand * 0.10)

    return max(0, min(payload.stock_on_hand, base_clearance + price_boost + ad_boost + urgency_boost))
