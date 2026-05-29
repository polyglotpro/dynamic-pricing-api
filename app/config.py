from datetime import datetime

def default_config():
    # Source of truth for baseline settings (\"original state\").
    return {
        "margin_floor_pct": 15.0,
        "safe_margin_pct": 20.0,
        "competitor_undercut_pct": 8.0,
        "roas_increase_threshold": 3.5,
        "roas_decrease_threshold": 2.5,
        "roas_pause_threshold": 1.5,
        "overstock_days": 60,
        "ageing_days": 45,
        "stockout_risk_pct": 30.0,
        "end_of_season_days": 14,
        "peak_demand_multiplier": 1.5,
        "price_change_step": 5.0,
        "deep_discount_pct": 20.0,
        "ad_change_step": 10.0,
        "engine_mode": "rule",
        "config_version": 1,
        "config_updated_at": datetime.now().isoformat(),
    }

CONFIG = default_config()
