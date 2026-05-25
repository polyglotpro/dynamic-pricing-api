import json
import os
from datetime import datetime

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

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

def load_config():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            cfg = json.load(f)
            # Backward compatible defaults for older settings.json files.
            cfg.setdefault("config_version", 1)
            cfg.setdefault("config_updated_at", datetime.now().isoformat())
            return cfg
    return default_config()

def save_config(config):
    # Keep a simple monotonic version so the UI can show what logic was applied.
    try:
        config["config_version"] = int(config.get("config_version", 0)) + 1
    except Exception:
        config["config_version"] = 1
    config["config_updated_at"] = datetime.now().isoformat()
    with open(SETTINGS_FILE, "w") as f:
        json.dump(config, f, indent=4)

def reset_config_to_defaults():
    """
    Resets persisted settings back to baseline demo defaults.
    Used after a new data upload so each demo run starts from a known state.
    """
    cfg = default_config()
    # Treat reset as a new deploy (so the UI sees version/timestamp change).
    save_config(cfg)
    return load_config()

CONFIG = load_config()
