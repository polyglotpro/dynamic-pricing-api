import asyncio
import hashlib
import httpx
import csv, io, os, json, pandas as pd, math
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from .config import CONFIG, default_config
from .simulation.experiment_runner import run_comparison, run_single_simulation
from .simulation.scenario_library import SCENARIOS
from .core.storage import BlobStorage

app = FastAPI(title="Joint Pricing and Advertising Agent Demo", version="2.0")
storage = BlobStorage()
_probe_store: dict[str, str] = {}


@app.on_event("startup")
async def load_persisted_settings():
    try:
        persisted = await storage.read_settings()
        if persisted:
            CONFIG.update(persisted)
    except Exception:
        # Fail open on startup; endpoints can still serve with defaults.
        pass

# CORS:
# - Local dev commonly runs Vite on :5173
# - Production frontend runs on Vercel (allowlist configured via env when deployed)
_default_allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://dynamic-pricing-engine-gamma.vercel.app",
    "https://dynamic-pricing-frontend-seven.vercel.app/",
]
_env_allowed = os.getenv("ALLOWED_ORIGINS", "").strip()
if _env_allowed:
    allowed_origins = [o.strip() for o in _env_allowed.split(",") if o.strip()]
else:
    allowed_origins = _default_allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SKUInput(BaseModel):
    sku_id: str
    product_name: Optional[str] = None
    product_type: str = Field("stable", description="stable or seasonal")
    current_price: float
    mrp: float
    cogs: float
    competitor_price: float
    current_ad_spend_per_unit: float
    roas: float
    conversion_rate: float
    ctr: float = 0
    cpc: float = 0
    stock_on_hand: int
    days_of_cover: float
    sell_through_weekly_pct: float
    ageing_days: int
    stockout_risk_pct: float
    days_to_season_end: Optional[int] = None
    weekly_sales_vs_baseline: float = 1.0
    trend_7d_pct: float = 0
    hero_sku: bool = False
    demand_uncertainty_sigma: float = 0.15
    last_30d_sales: float = 0
    avg_daily_sessions: float = 0
    historical_elasticity: float = -1.5
    conversion_benchmark: float = 2.0

class RecommendationResponse(BaseModel):
    sku_id: str
    product_name: Optional[str] = None
    scenario_tags: List[str]
    primary_objective: str
    final_recommendation: Dict[str, Any]
    conflicts: List[Dict[str, Any]]
    rule_trace: List[Dict[str, Any]]
    explanation: str
    approval_required: bool
    confidence: float


def margin_pct(price: float, cogs: float, ad: float) -> float:
    if price <= 0:
        return -999
    return ((price - cogs - ad) / price) * 100


def add_rule(trace, rule_id, fired, description, evidence, action):
    trace.append({
        "rule_id": rule_id,
        "fired": fired,
        "description": description,
        "evidence": evidence,
        "action": action if fired else "none"
    })


def tag_scenario(x: SKUInput, trace: list) -> List[str]:
    tags = []
    comp_gap = ((x.current_price - x.competitor_price) / x.current_price) * 100 if x.current_price else 0

    if x.product_type.lower() == "seasonal":
        tags.append("seasonal_product")
    else:
        tags.append("stable_product")

    if comp_gap > CONFIG["competitor_undercut_pct"]:
        tags.append("competitor_undercut")
    elif comp_gap < -CONFIG["competitor_undercut_pct"]:
        tags.append("price_advantage")

    if x.days_of_cover > CONFIG["overstock_days"] and x.sell_through_weekly_pct < 5:
        tags.append("overstock")
    if x.ageing_days > CONFIG["ageing_days"]:
        tags.append("ageing_inventory")
    if x.stockout_risk_pct > CONFIG["stockout_risk_pct"]:
        tags.append("stockout_risk")
    if x.days_to_season_end is not None and x.days_to_season_end < CONFIG["end_of_season_days"]:
        tags.append("end_of_season")
    if x.weekly_sales_vs_baseline > CONFIG["peak_demand_multiplier"]:
        tags.append("peak_demand")
    if x.weekly_sales_vs_baseline < 0.8:
        tags.append("declining_demand")
    if x.trend_7d_pct > 30:
        tags.append("trend_opportunity")
    if x.demand_uncertainty_sigma > 0.22:
        tags.append("high_uncertainty")
    if x.hero_sku:
        tags.append("hero_sku")

    add_rule(trace, "TAG-01", True, "Scenario tagging completed", {"tags": tags}, "attach_tags")
    return tags


def pricing_agent(x: SKUInput, tags: List[str], trace: list) -> Dict[str, Any]:
    current_margin = margin_pct(x.current_price, x.cogs, x.current_ad_spend_per_unit)
    comp_gap = ((x.current_price - x.competitor_price) / x.current_price) * 100 if x.current_price else 0
    action, change, reason = "hold_price", 0, "No strong pricing trigger."

    fired = comp_gap > CONFIG["competitor_undercut_pct"] and current_margin >= CONFIG["safe_margin_pct"]
    add_rule(trace, "P-01", fired, f"Reduce price when competitor undercuts and margin is above {CONFIG['safe_margin_pct']}%", {"competitor_gap_pct": round(comp_gap,2), "margin_pct": round(current_margin,2)}, f"reduce_price_{CONFIG['price_change_step']}_pct")
    if fired:
        action, change, reason = "reduce_price", -CONFIG["price_change_step"], f"Competitor is cheaper and current margin can absorb a {CONFIG['price_change_step']}% reduction."

    fired = "end_of_season" in tags or ("overstock" in tags and "declining_demand" in tags)
    add_rule(trace, "P-02", fired, f"Use deeper markdown ({CONFIG['deep_discount_pct']}%) for end-of-season or overstock with weak demand", {"tags": tags}, f"deep_discount_{CONFIG['deep_discount_pct']}_pct")
    if fired:
        action, change, reason = "deep_discount", -CONFIG["deep_discount_pct"], "Inventory pressure and timing urgency require faster sell-through."

    fired = current_margin < CONFIG["margin_floor_pct"]
    add_rule(trace, "P-03", fired, f"Protect margin floor ({CONFIG['margin_floor_pct']}%)", {"margin_pct": round(current_margin,2), "floor_pct": CONFIG["margin_floor_pct"]}, "limit_discount")
    if fired:
        action, change, reason = "limit_discount", 0, "Current margin is below floor, so further price reduction is blocked."

    fired = "peak_demand" in tags and current_margin >= CONFIG["safe_margin_pct"] + 5 and "competitor_undercut" not in tags
    add_rule(trace, "P-04", fired, "Raise or hold price during peak demand when competitive position is safe", {"tags": tags, "margin_pct": round(current_margin,2)}, f"raise_price_{CONFIG['price_change_step']}_pct")
    if fired:
        action, change, reason = "raise_price", CONFIG["price_change_step"], "Peak demand allows margin capture without needing discounting."

    return {"agent": "pricing", "action": action, "change_pct": change, "reason": reason, "confidence": 0.82}


def advertising_agent(x: SKUInput, tags: List[str], trace: list) -> Dict[str, Any]:
    current_margin = margin_pct(x.current_price, x.cogs, x.current_ad_spend_per_unit)
    action, change, reason = "hold_spend", 0, "ROAS is within normal operating range."

    fired = x.roas > CONFIG["roas_increase_threshold"] and "stockout_risk" not in tags and current_margin >= CONFIG["safe_margin_pct"]
    add_rule(trace, "A-01", fired, f"Increase spend when ROAS > {CONFIG['roas_increase_threshold']}, stock is healthy, and margin is above {CONFIG['safe_margin_pct']}%", {"roas": x.roas, "margin_pct": round(current_margin,2), "tags": tags}, f"increase_spend_{CONFIG['ad_change_step']}_pct")
    if fired:
        action, change, reason = "increase_spend", CONFIG["ad_change_step"], "ROAS is strong and stock/margin can support additional demand."

    fired = x.roas < CONFIG["roas_decrease_threshold"] or current_margin < CONFIG["margin_floor_pct"]
    add_rule(trace, "A-02", fired, f"Reduce spend when ROAS < {CONFIG['roas_decrease_threshold']} or margin is below {CONFIG['margin_floor_pct']}%", {"roas": x.roas, "margin_pct": round(current_margin,2)}, f"reduce_spend_{CONFIG['ad_change_step']}_pct")
    if fired:
        action, change, reason = "reduce_spend", -CONFIG["ad_change_step"], "Ad efficiency or margin is not strong enough for current spend."

    fired = x.roas < CONFIG["roas_pause_threshold"]
    add_rule(trace, "A-03", fired, f"Pause aggressive support when ROAS < {CONFIG['roas_pause_threshold']}", {"roas": x.roas}, "pause_aggressive_support_50_pct")
    if fired:
        action, change, reason = "pause_aggressive_support", -50, "ROAS is too weak to justify aggressive ad support."

    fired = x.hero_sku and x.roas > 2.0 and "stockout_risk" not in tags
    add_rule(trace, "A-04", fired, "Defend visibility for hero SKU", {"hero_sku": x.hero_sku, "roas": x.roas}, "defend_visibility_5_pct")
    if fired:
        action, change, reason = "defend_visibility", 5, "Hero SKU gets controlled visibility support."

    return {"agent": "advertising", "action": action, "change_pct": change, "reason": reason, "confidence": 0.79}


def objective(tags: List[str]) -> str:
    if "high_uncertainty" in tags:
        return "risk_control"
    if any(t in tags for t in ["overstock", "ageing_inventory", "end_of_season"]):
        return "sell_through"
    if "hero_sku" in tags or "trend_opportunity" in tags:
        return "visibility"
    if "stockout_risk" in tags:
        return "margin_protection"
    return "efficiency"


def orchestrate(x: SKUInput, tags: List[str], p: Dict[str, Any], a: Dict[str, Any], trace: list):
    conflicts = []
    obj = objective(tags)
    price_action, price_change = p["action"], p["change_pct"]
    ad_action, ad_change = a["action"], a["change_pct"]
    approval_required = False

    projected_price = x.current_price * (1 + price_change / 100)
    projected_ad = x.current_ad_spend_per_unit * (1 + ad_change / 100)
    projected_margin = margin_pct(projected_price, x.cogs, projected_ad)

    if price_change < 0 and ad_change > 0:
        rule = {"conflict_id": "C-01", "type": "price_down_ad_up", "pricing": p, "advertising": a}
        if projected_margin < CONFIG["safe_margin_pct"]:
            ad_action, ad_change = "hold_spend", 0
            rule["resolution"] = f"Block ad increase because projected margin is below {CONFIG['safe_margin_pct']}%."
        elif projected_margin > 30:
            rule["resolution"] = "Allow both actions because projected margin remains above 30%."
        else:
            ad_action, ad_change = "hold_spend", 0
            approval_required = True
            rule["resolution"] = f"Hold ad increase and request approval because margin is between {CONFIG['safe_margin_pct']}% and 30%."
        conflicts.append(rule)
        add_rule(trace, "C-01", True, "Resolve price reduction plus ad increase conflict", {"projected_margin_pct": round(projected_margin,2)}, rule["resolution"])

    if "stockout_risk" in tags and ad_change > 0:
        conflicts.append({"conflict_id": "C-02", "type": "ad_up_low_stock", "resolution": "Override ad expansion due to stockout risk."})
        ad_action, ad_change = "hold_spend", 0
        add_rule(trace, "C-02", True, "Override ad increase when stockout risk is high", {"stockout_risk_pct": x.stockout_risk_pct}, "hold_spend")

    if "high_uncertainty" in tags:
        conflicts.append({"conflict_id": "C-03", "type": "high_uncertainty", "resolution": "Limit combined moves to avoid error amplification."})
        if abs(price_change) > CONFIG["price_change_step"]:
            price_change = -CONFIG["price_change_step"] if price_change < 0 else CONFIG["price_change_step"]
            price_action = "controlled_price_change"
        if abs(ad_change) > CONFIG["ad_change_step"]:
            ad_change = -CONFIG["ad_change_step"] if ad_change < 0 else CONFIG["ad_change_step"]
            ad_action = "controlled_spend_change"
        approval_required = True
        add_rule(trace, "C-03", True, "Dampen actions under high uncertainty", {"sigma": x.demand_uncertainty_sigma}, "cap_price_and_ad_moves")

    if projected_margin < CONFIG["margin_floor_pct"]:
        conflicts.append({"conflict_id": "C-04", "type": "margin_floor_breach", "resolution": "Reject margin-damaging combination."})
        price_action, price_change = "hold_price", 0
        if ad_change > 0:
            ad_action, ad_change = "hold_spend", 0
        approval_required = True
        add_rule(trace, "C-04", True, "Reject recommendation that breaches margin floor", {"projected_margin_pct": round(projected_margin,2)}, "hold_price_and_prevent_ad_increase")

    final_price = x.current_price * (1 + price_change/100)
    final_ad = x.current_ad_spend_per_unit * (1 + ad_change/100)
    final_margin = margin_pct(final_price, x.cogs, final_ad)
    explanation = (
        f"Scenario is tagged as {', '.join(tags)}. Primary objective is {obj}. "
        f"Pricing agent recommended {p['action']} ({p['change_pct']}%) because {p['reason']} "
        f"Advertising agent recommended {a['action']} ({a['change_pct']}%) because {a['reason']} "
        f"After conflict checks, final action is price {price_change}% and ad spend {ad_change}%. "
        f"Projected contribution margin is {round(final_margin,2)}%."
    )

    return {
        "sku_id": x.sku_id,
        "product_name": x.product_name,
        "current_price": x.current_price,
        "cogs": x.cogs,
        "current_ad_spend_per_unit": x.current_ad_spend_per_unit,
        "applied_config": {
            "config_version": CONFIG.get("config_version"),
            "config_updated_at": CONFIG.get("config_updated_at"),
            "engine_mode": CONFIG.get("engine_mode", "rule"),
            "safe_margin_pct": CONFIG.get("safe_margin_pct"),
            "margin_floor_pct": CONFIG.get("margin_floor_pct"),
            "price_change_step": CONFIG.get("price_change_step"),
            "ad_change_step": CONFIG.get("ad_change_step"),
        },
        "scenario_tags": tags,
        "primary_objective": obj,
        "final_recommendation": {
            "price_action": price_action,
            "price_change_pct": price_change,
            "new_price": round(final_price, 2),
            "ad_action": ad_action,
            "ad_change_pct": ad_change,
            "new_ad_spend_per_unit": round(final_ad, 2),
            "projected_margin_pct": round(final_margin, 2)
        },
        "conflicts": conflicts,
        "rule_trace": trace,
        "explanation": explanation,
        "approval_required": approval_required or len(conflicts) > 0 or x.hero_sku,
        "confidence": round(min(p["confidence"], a["confidence"]) - (0.08 if conflicts else 0), 2)
    }

@app.get("/")
def root():
    return {"status": "ok", "message": "Use POST /recommendation for JSON or POST /recommendations/csv for CSV upload."}

async def get_merged_data():
    """
    Blob-backed data integration pipeline.
    Joins the latest catalog, pricing, inventory, and advertising CSVs from storage.
    """
    merged_df = pd.DataFrame()
    load_errors = []

    for folder in ["catalog", "pricing", "inventory", "advertising"]:
        try:
            df = await storage.read_latest_domain_frame(folder)
        except HTTPException as exc:
            load_errors.append({"domain": folder, "error": exc.detail})
            continue

        if merged_df.empty:
            merged_df = df
        else:
            merged_df = pd.merge(merged_df, df, on="sku_id", how="left", suffixes=("", "_dup"))
            merged_df = merged_df.loc[:, ~merged_df.columns.str.endswith("_dup")]

    if merged_df.empty:
        return {
            "error": "No data sources found in Blob storage.",
            "load_errors": load_errors,
        }

    return {
        "data": merged_df.fillna(0).to_dict(orient="records"),
        "load_errors": load_errors,
    }

async def load_inventory_from_storage():
    return (await storage.read_latest_domain_frame("inventory")).fillna(0).to_dict(orient="records")


@app.get("/inventory")
async def get_inventory():
    try:
        return await load_inventory_from_storage()
    except Exception as e:
        return {"error": str(e)}

def run_ai_engine(x: SKUInput, trace: List[Dict]):
    # Simulated ML Elasticity Engine using Historical Signals
    # We prioritize the SKU's own historical elasticity if provided
    base_elasticity = x.historical_elasticity
    
    best_price_pct = 0
    max_contribution = -float('inf')
    
    # AI Engine tests a wider range than Rule Engine
    for pct in range(-25, 16): # Test -25% to +15%
        test_price = x.current_price * (1 + pct/100)
        
        # Calculate expected demand lift based on elasticity
        # Demand = Base_Sales * (Price_Change_Ratio ^ Elasticity)
        price_ratio = test_price / x.current_price
        expected_demand_lift = math.pow(price_ratio, base_elasticity)
        
        # Factor in conversion vs benchmark
        conv_factor = x.conversion_rate / x.conversion_benchmark if x.conversion_benchmark > 0 else 1.0
        
        # Total profit simulation
        contribution = (test_price - x.cogs - x.current_ad_spend_per_unit) * x.last_30d_sales * expected_demand_lift * conv_factor
        
        if contribution > max_contribution:
            max_contribution = contribution
            best_price_pct = pct

    add_rule(trace, "ML-01", True, "Neural Elasticity Model", {"historical_elasticity": base_elasticity, "price_sensitivity": "extreme" if base_elasticity < -2.0 else "moderate"}, "optimize_price")
    add_rule(trace, "ML-02", True, "Sales Lift Prediction", {"projected_lift": f"{((math.pow(1 + best_price_pct/100, base_elasticity)-1)*100):.1f}%", "confidence": 0.92}, "maximize_contribution")

    price_action = "ai_optimize_up" if best_price_pct > 0 else "ai_optimize_down" if best_price_pct < 0 else "hold"
    
    # AI Ad Scaling based on conversion momentum
    ad_change = 15 if x.conversion_rate > x.conversion_benchmark else -10
    ad_action = "momentum_scale" if ad_change > 0 else "efficiency_cut"

    final_price = x.current_price * (1 + best_price_pct/100)
    final_ad = x.current_ad_spend_per_unit * (1 + ad_change/100)
    final_margin = margin_pct(final_price, x.cogs, final_ad)

    return {
        "sku_id": x.sku_id,
        "product_name": x.product_name,
        "current_price": x.current_price,
        "cogs": x.cogs,
        "current_ad_spend_per_unit": x.current_ad_spend_per_unit,
        "applied_config": {
            "config_version": CONFIG.get("config_version"),
            "config_updated_at": CONFIG.get("config_updated_at"),
            "engine_mode": CONFIG.get("engine_mode", "ai"),
            "safe_margin_pct": CONFIG.get("safe_margin_pct"),
            "margin_floor_pct": CONFIG.get("margin_floor_pct"),
        },
        "scenario_tags": ["ML_OPTIMIZED", "HISTORICAL_DRIVEN"],
        "primary_objective": "Net Contribution Optimization",
        "final_recommendation": {
            "price_action": price_action,
            "price_change_pct": best_price_pct,
            "new_price": round(final_price, 2),
            "ad_action": ad_action,
            "ad_change_pct": ad_change,
            "new_ad_spend_per_unit": round(final_ad, 2),
            "projected_margin_pct": round(final_margin, 2)
        },
        "conflicts": [],
        "rule_trace": trace,
        "explanation": f"Model analyzed 30 days of sales ({int(x.last_30d_sales)} units) and historical elasticity ({base_elasticity}). Recommended {best_price_pct}% price shift to capture optimal demand-margin intersection.",
        "approval_required": True,
        "confidence": 0.94
    }

@app.get("/all-recommendations")
async def get_all_recommendations():
    inventory = await get_merged_data()
    if isinstance(inventory, dict) and "error" in inventory:
        return {
            "count": 0,
            "results": [],
            "errors": [{"error": inventory["error"], "load_errors": inventory.get("load_errors", [])}],
        }
    if isinstance(inventory, dict) and "data" in inventory:
        inventory_rows = inventory["data"]
    else:
        inventory_rows = inventory
        
    results = []
    errors = []
    for row in inventory_rows:
        try:
            # Map CSV fields to SKUInput with flexible header support
            def get_val(keys, default="0"):
                for k in keys:
                    if k in row and row[k] != "": return row[k]
                return default

            clean = {
                "sku_id": row["sku_id"],
                "product_name": row.get("product_name", row["sku_id"]),
                "product_type": "seasonal" if int(float(get_val(["season_days_left", "days_to_season_end"]))) > 0 else "stable",
                "current_price": float(row["current_price"]),
                "mrp": float(get_val(["mrp", "current_price"])),
                "cogs": float(get_val(["cogs", "cost"])),
                "competitor_price": float(get_val(["competitor_price", "current_price"])),
                "current_ad_spend_per_unit": float(get_val(["current_ad_spend_per_unit", "ad_spend"], "0")),
                "roas": float(get_val(["roas"], "0")),
                "conversion_rate": float(get_val(["conversion_rate"], "0")),
                "stock_on_hand": int(float(get_val(["stock_on_hand", "stock"], "0"))),
                "days_of_cover": float(get_val(["days_of_cover"], "0")),
                "sell_through_weekly_pct": float(get_val(["sell_through_weekly_pct", "sell_through_rate_weekly"], "0")) * (100 if float(get_val(["sell_through_weekly_pct", "sell_through_rate_weekly"], "0")) < 1 else 1),
                "ageing_days": int(float(get_val(["ageing_days", "ageing"], "0"))),
                "stockout_risk_pct": float(get_val(["stockout_risk_pct", "stockout_risk"], "0")) * (100 if float(get_val(["stockout_risk_pct", "stockout_risk"], "0")) < 1 else 1),
                "days_to_season_end": int(float(get_val(["days_to_season_end", "season_days_left"]))) if get_val(["days_to_season_end", "season_days_left"], "") != "" else None,
                "weekly_sales_vs_baseline": float(get_val(["weekly_sales_vs_baseline", "sales_vs_baseline"], "1.0")),
                "trend_7d_pct": float(get_val(["trend_7d_pct", "trend_change_7d_pct"], "0")),
                "hero_sku": str(get_val(["hero_sku"], "false")).lower() in ["true", "1", "yes"],
                "demand_uncertainty_sigma": float(get_val(["demand_uncertainty_sigma"], "0.15")),
                "last_30d_sales": float(get_val(["last_30d_sales"], "0")),
                "avg_daily_sessions": float(get_val(["avg_daily_sessions"], "0")),
                "historical_elasticity": float(get_val(["historical_elasticity"], "-1.5")),
                "conversion_benchmark": float(get_val(["conversion_benchmark"], "2.0"))
            }
            x = SKUInput(**clean)
            trace = []
            
            if CONFIG.get("engine_mode") == "ai":
                results.append(run_ai_engine(x, trace))
            else:
                tags = tag_scenario(x, trace)
                p = pricing_agent(x, tags, trace)
                a = advertising_agent(x, tags, trace)
                results.append(orchestrate(x, tags, p, a, trace))
        except Exception as e:
            errors.append({
                "sku_id": row.get("sku_id"),
                "error": str(e),
                "row_keys": sorted(list(row.keys()))[:40],
            })
            continue
    return {
        "count": len(results),
        "results": results,
        "errors": (errors[:50] + (inventory.get("load_errors", []) if isinstance(inventory, dict) else []))[:50],
    }

@app.post("/recommendation", response_model=RecommendationResponse)
def recommendation(x: SKUInput):
    trace = []
    tags = tag_scenario(x, trace)
    p = pricing_agent(x, tags, trace)
    a = advertising_agent(x, tags, trace)
    return orchestrate(x, tags, p, a, trace)

@app.post("/recommendations/csv")
async def recommendations_csv(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a CSV file.")
    raw = (await file.read()).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(raw)))
    output = []
    errors = []
    for idx, row in enumerate(rows, start=2):
        try:
            bool_fields = ["hero_sku"]
            int_fields = ["stock_on_hand", "ageing_days"]
            float_fields = [k for k in SKUInput.model_fields.keys() if k not in ["sku_id", "product_type", "days_to_season_end", *bool_fields, *int_fields]]
            clean = dict(row)
            for k in bool_fields:
                clean[k] = str(clean.get(k, "false")).lower() in ["true", "1", "yes", "y"]
            for k in int_fields:
                clean[k] = int(float(clean[k]))
            if clean.get("days_to_season_end", "") == "":
                clean["days_to_season_end"] = None
            else:
                clean["days_to_season_end"] = int(float(clean["days_to_season_end"]))
            for k in float_fields:
                if k in clean and clean[k] != "":
                    clean[k] = float(clean[k])
            x = SKUInput(**clean)
            trace = []
            tags = tag_scenario(x, trace)
            p = pricing_agent(x, tags, trace)
            a = advertising_agent(x, tags, trace)
            output.append(orchestrate(x, tags, p, a, trace))
        except Exception as e:
            errors.append({"row": idx, "error": str(e), "data": row})
    return {"count": len(output), "results": output, "errors": errors}

class SettingsUpdate(BaseModel):
    margin_floor_pct: Optional[float] = Field(None, ge=-20, le=80)
    safe_margin_pct: Optional[float] = Field(None, ge=0, le=100)
    roas_increase_threshold: Optional[float] = Field(None, ge=1.0, le=20.0)
    roas_decrease_threshold: Optional[float] = Field(None, ge=0.5, le=10.0)
    price_change_step: Optional[float] = Field(None, ge=1, le=25)
    ad_change_step: Optional[float] = Field(None, ge=5, le=100)
    deep_discount_pct: Optional[float] = Field(None, ge=5, le=70)
    engine_mode: Optional[str] = Field(None)

@app.get("/settings")
async def get_settings():
    persisted = await storage.read_settings()
    if persisted:
        CONFIG.update(persisted)
    return CONFIG

@app.post("/settings")
async def update_settings(new_config: SettingsUpdate):
    # Only update provided fields
    update_data = new_config.model_dump(exclude_unset=True)
    CONFIG.update(update_data)
    await storage.write_settings(CONFIG)
    return {"status": "success", "config": CONFIG}

@app.post("/simulate")
async def simulate_recommendations(temp_config: Dict[str, Any]):
    """Runs recommendation logic using a temporary config without saving it."""
    # Create a local copy of settings for this run
    sim_config = CONFIG.copy()
    sim_config.update(temp_config)
    
    inventory = await get_merged_data()
    if isinstance(inventory, dict) and "error" in inventory:
        return inventory
        
    results = []
    for row in inventory:
        try:
            # Note: We need a way to pass sim_config into tag_scenario, pricing_agent, etc.
            # To avoid refactoring every function signature, we can use a helper that 
            # temporarily overrides global CONFIG or just pass it in.
            # Let's refactor the core functions slightly to accept an optional config.
            def get_val(keys, default="0"):
                for k in keys:
                    if k in row and row[k] != "":
                        return row[k]
                return default

            clean = {
                "sku_id": row["sku_id"],
                "product_name": row.get("product_name"),
                "product_type": "seasonal" if int(float(get_val(["season_days_left", "days_to_season_end"], "0"))) > 0 else "stable",
                "current_price": float(row["current_price"]),
                "mrp": float(get_val(["mrp", "current_price"], row["current_price"])),
                "cogs": float(get_val(["cost", "cogs"], "0")),
                "competitor_price": float(get_val(["competitor_price", "current_price"], row["current_price"])),
                "current_ad_spend_per_unit": float(get_val(["current_ad_spend_per_unit", "ad_spend"], "0")),
                "roas": float(get_val(["roas"], "0")),
                "conversion_rate": float(get_val(["conversion_rate"], "0")),
                "stock_on_hand": int(float(get_val(["stock_on_hand", "stock"], "0"))),
                "days_of_cover": float(get_val(["days_of_cover"], "0")),
                "sell_through_weekly_pct": float(get_val(["sell_through_weekly_pct", "sell_through_rate_weekly"], "0")) * (100 if float(get_val(["sell_through_weekly_pct", "sell_through_rate_weekly"], "0")) < 1 else 1),
                "ageing_days": int(float(get_val(["ageing_days", "ageing"], "0"))),
                "stockout_risk_pct": float(get_val(["stockout_risk_pct", "stockout_risk"], "0")) * (100 if float(get_val(["stockout_risk_pct", "stockout_risk"], "0")) < 1 else 1),
                "days_to_season_end": int(float(get_val(["days_to_season_end", "season_days_left"], "0"))) if get_val(["days_to_season_end", "season_days_left"], "") != "" else None,
                "weekly_sales_vs_baseline": float(get_val(["weekly_sales_vs_baseline", "sales_vs_baseline"], "1.0")),
                "trend_7d_pct": float(get_val(["trend_7d_pct", "trend_change_7d_pct"], "0")),
                "hero_sku": str(row.get("hero_sku", "false")).lower() in ["true", "1", "yes"]
            }
            x = SKUInput(**clean)
            trace = []
            
            # Use local sim_config
            tags = tag_scenario_sim(x, trace, sim_config)
            p = pricing_agent_sim(x, tags, trace, sim_config)
            a = advertising_agent_sim(x, tags, trace, sim_config)
            results.append(orchestrate_sim(x, tags, p, a, trace, sim_config))
        except Exception as e:
            continue
    return results

def tag_scenario_sim(x, trace, cfg):
    tags = []
    comp_gap = ((x.current_price - x.competitor_price) / x.current_price) * 100 if x.current_price else 0
    if x.product_type.lower() == "seasonal": tags.append("seasonal_product")
    else: tags.append("stable_product")
    if comp_gap > cfg["competitor_undercut_pct"]: tags.append("competitor_undercut")
    elif comp_gap < -cfg["competitor_undercut_pct"]: tags.append("price_advantage")
    if x.days_of_cover > cfg["overstock_days"] and x.sell_through_weekly_pct < 5: tags.append("overstock")
    if x.ageing_days > cfg["ageing_days"]: tags.append("ageing_inventory")
    if x.stockout_risk_pct > cfg["stockout_risk_pct"]: tags.append("stockout_risk")
    if x.days_to_season_end is not None and x.days_to_season_end < cfg["end_of_season_days"]: tags.append("end_of_season")
    if x.weekly_sales_vs_baseline > cfg["peak_demand_multiplier"]: tags.append("peak_demand")
    return tags

def pricing_agent_sim(x, tags, trace, cfg):
    current_margin = margin_pct(x.current_price, x.cogs, x.current_ad_spend_per_unit)
    comp_gap = ((x.current_price - x.competitor_price) / x.current_price) * 100 if x.current_price else 0
    action, change, reason = "hold_price", 0, "No strong pricing trigger."
    if comp_gap > cfg["competitor_undercut_pct"] and current_margin >= cfg["safe_margin_pct"]:
        action, change, reason = "reduce_price", -cfg["price_change_step"], "Competitor undercut."
    if "end_of_season" in tags:
        action, change, reason = "deep_discount", -cfg["deep_discount_pct"], "End of season."
    if current_margin < cfg["margin_floor_pct"]:
        action, change, reason = "limit_discount", 0, "Margin floor breach."
    return {"action": action, "change_pct": change, "reason": reason, "confidence": 0.8}

def advertising_agent_sim(x, tags, trace, cfg):
    current_margin = margin_pct(x.current_price, x.cogs, x.current_ad_spend_per_unit)
    action, change, reason = "hold_spend", 0, "Normal ROAS."
    if x.roas > cfg["roas_increase_threshold"] and current_margin >= cfg["safe_margin_pct"]:
        action, change, reason = "increase_spend", cfg["ad_change_step"], "Strong efficiency."
    if x.roas < cfg["roas_decrease_threshold"]:
        action, change, reason = "reduce_spend", -cfg["ad_change_step"], "Weak efficiency."
    return {"action": action, "change_pct": change, "reason": reason, "confidence": 0.8}

def orchestrate_sim(x, tags, p, a, trace, cfg):
    price_change = p["change_pct"]
    ad_change = a["change_pct"]
    projected_price = x.current_price * (1 + price_change / 100)
    projected_ad = x.current_ad_spend_per_unit * (1 + ad_change / 100)
    projected_margin = margin_pct(projected_price, x.cogs, projected_ad)
    
    if projected_margin < cfg["margin_floor_pct"]:
        price_change, ad_change = 0, 0
        projected_price = x.current_price
        projected_ad = x.current_ad_spend_per_unit
        projected_margin = margin_pct(projected_price, x.cogs, projected_ad)
        
    return {
        "sku_id": x.sku_id,
        "final_recommendation": {
            "price_change_pct": price_change,
            "ad_change_pct": ad_change,
            "projected_margin_pct": round(projected_margin, 2)
        }
    }

async def log_upload_history(filename: str, status: str, details: str = ""):
    history = await storage.read_upload_history()
    history.insert(0, {
        "timestamp": datetime.now().isoformat(),
        "filename": filename,
        "status": status,
        "details": details
    })
    await storage.write_upload_history(history)

@app.get("/uploads-history")
async def get_uploads_history():
    return await storage.read_upload_history()

@app.post("/approve")
async def approve_strategy(data: Dict[str, Any]):
    """Saves an approved strategy to the persistent transactions ledger."""
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sku_id": data.get("sku_id"),
        "product_name": data.get("product_name"),
        "new_price": data.get("final_recommendation", {}).get("new_price"),
        "new_ad_spend": data.get("final_recommendation", {}).get("new_ad_spend_per_unit"),
        "projected_margin": data.get("final_recommendation", {}).get("projected_margin_pct"),
        "engine_mode": CONFIG.get("engine_mode", "rule")
    }

    try:
        approvals = await storage.read_json("data/metadata/approvals.json")
        if not isinstance(approvals, list):
            approvals = []
    except HTTPException:
        approvals = []
    approvals.insert(0, row)
    await storage.write_json("data/metadata/approvals.json", approvals[:500], overwrite=True)

    return {"status": "success", "message": f"Strategy for {data.get('sku_id')} committed to ledger."}


@app.post("/debug/blob-put")
async def debug_blob_put(payload: Dict[str, Any]):
    name = payload.get("name", "sample")
    value = payload.get("value", {})
    artifact = await storage.write_debug_json(name, value)
    _probe_store[name] = artifact.download_url or artifact.url or artifact.path
    return {
        "status": "ok",
        "name": name,
        "pathname": artifact.pathname,
        "url": artifact.url,
        "download_url": artifact.download_url,
        "stored_url": _probe_store[name],
        "value": value,
    }


@app.get("/debug/blob-get")
async def debug_blob_get(name: str = "sample"):
    stored_url = _probe_store.get(name)
    if not stored_url:
        return {
            "status": "error",
            "name": name,
            "error": f"No stored URL for probe '{name}' - run POST /debug/blob-put first",
        }

    print(f"DEBUG BLOB READ: {stored_url}")
    token = os.getenv("BLOB_READ_WRITE_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="BLOB_READ_WRITE_TOKEN not set")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            stored_url,
            headers={"Authorization": f"Bearer {token}"},
        )

    if response.status_code != 200:
        return {
            "status": "error",
            "name": name,
            "read_target": stored_url,
            "http_status": response.status_code,
            "body": response.text,
        }

    value = response.json()
    return {
        "status": "ok",
        "name": name,
        "read_target": stored_url,
        "value": value,
    }

@app.post("/upload-catalog")
async def upload_catalog(file: UploadFile = File(...)):
    safe_filename = os.path.basename(file.filename or "uploaded_catalog.csv")

    try:
        content = await file.read()
        decoded_content = content.decode("utf-8-sig")
        df = pd.read_csv(io.StringIO(decoded_content))

        rename_map = {}

        if "cost_of_goods_sold" in df.columns and "cogs" not in df.columns:
            rename_map["cost_of_goods_sold"] = "cogs"

        if "sell_through_rate_weekly" in df.columns and "sell_through_weekly_pct" not in df.columns:
            rename_map["sell_through_rate_weekly"] = "sell_through_weekly_pct"

        if "roas_30d" in df.columns and "roas" not in df.columns:
            rename_map["roas_30d"] = "roas"

        if rename_map:
            df = df.rename(columns=rename_map)

        if "conversion_rate" not in df.columns:
            def _conv_from_sku(s):
                h = hashlib.md5(str(s).encode("utf-8")).hexdigest()
                n = int(h[:8], 16) % 1000
                return 0.015 + (n / 1000.0) * 0.05

            df["conversion_rate"] = df["sku_id"].apply(_conv_from_sku) if "sku_id" in df.columns else 0.03

        if "ctr" not in df.columns:
            df["ctr"] = 0.02

        if "cpc" not in df.columns:
            df["cpc"] = 10

        if "last_30d_sales" not in df.columns:
            df["last_30d_sales"] = 120

        if "avg_daily_sessions" not in df.columns:
            df["avg_daily_sessions"] = 500

        if "conversion_benchmark" not in df.columns:
            def _bench_from_sku(s):
                h = hashlib.md5((str(s) + "_bench").encode("utf-8")).hexdigest()
                n = int(h[:8], 16) % 1000
                return 0.02 + (n / 1000.0) * 0.03

            df["conversion_benchmark"] = df["sku_id"].apply(_bench_from_sku) if "sku_id" in df.columns else 0.03

        if "competitor_price" not in df.columns and "current_price" in df.columns:
            df["competitor_price"] = df["current_price"]

        if "mrp" not in df.columns and "current_price" in df.columns:
            df["mrp"] = (df["current_price"] * 1.15).round(0)

        if "stockout_risk_pct" not in df.columns:
            if "days_of_cover" in df.columns:
                df["stockout_risk_pct"] = (
                    100 * (1 - (df["days_of_cover"].clip(lower=0, upper=30) / 30))
                ).round(0)
            else:
                df["stockout_risk_pct"] = 0

        if "ageing_days" not in df.columns:
            df["ageing_days"] = 10

        if "days_to_season_end" not in df.columns:
            df["days_to_season_end"] = None

        if "product_type" not in df.columns:
            df["product_type"] = "stable"

        if "hero_sku" not in df.columns:
            df["hero_sku"] = False

        catalog_cols = [
            "sku_id",
            "product_name",
            "product_type",
            "hero_sku",
        ]

        inventory_cols = [
            "sku_id",
            "stock_on_hand",
            "days_of_cover",
            "sell_through_weekly_pct",
            "ageing_days",
            "stockout_risk_pct",
            "days_to_season_end",
        ]

        ad_cols = [
            "sku_id",
            "current_ad_spend_per_unit",
            "roas",
            "conversion_rate",
            "ctr",
            "cpc",
            "last_30d_sales",
            "avg_daily_sessions",
            "conversion_benchmark",
        ]

        pricing_cols = [
            c for c in df.columns
            if c not in inventory_cols[1:]
            and c not in ad_cols[1:]
            and c not in catalog_cols[1:]
        ]

        brand = (
            "myntra"
            if "myntra" in safe_filename.lower()
            else "fabindia"
            if "fabindia" in safe_filename.lower()
            else "active"
        )

        uploaded_blobs = {}
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        async def split_and_save(columns, folder, brand_prefix):
            target_cols = [c for c in columns if c in df.columns]
            if len(target_cols) > 1:
                sub_df = df[target_cols]
                artifact = await storage.write_domain_frame(folder, sub_df, brand_prefix, timestamp=timestamp)
                print(f"Uploaded {folder}: {len(sub_df)} rows -> {artifact.pathname}")
                uploaded_blobs[folder] = artifact.pathname

        await split_and_save(catalog_cols, "catalog", brand)
        await split_and_save(inventory_cols, "inventory", brand)
        await split_and_save(ad_cols, "advertising", brand)
        await split_and_save(pricing_cols, "pricing", brand)

        manifest_payload = {
            "timestamp": timestamp,
            "filename": safe_filename,
            "brand": brand,
            "domains": {
                "catalog": {
                    "path": f"data/catalog/{brand}_catalog_{timestamp}.csv",
                    "pathname": uploaded_blobs.get("catalog"),
                },
                "inventory": {
                    "path": f"data/inventory/{brand}_inventory_{timestamp}.csv",
                    "pathname": uploaded_blobs.get("inventory"),
                },
                "advertising": {
                    "path": f"data/advertising/{brand}_advertising_{timestamp}.csv",
                    "pathname": uploaded_blobs.get("advertising"),
                },
                "pricing": {
                    "path": f"data/pricing/{brand}_pricing_{timestamp}.csv",
                    "pathname": uploaded_blobs.get("pricing"),
                },
            },
        }
        await storage.write_latest_manifest(manifest_payload)

        # Reset settings so each upload starts from a known demo baseline.
        updated_config = default_config()
        CONFIG.clear()
        CONFIG.update(updated_config)
        await storage.write_settings(CONFIG)

        response = {
            "message": "Catalog ingested and partitioned successfully using Vercel Blob",
            "filename": safe_filename,
            "rows": len(df),
            "brand": brand,
            "rename_map": rename_map,
            "uploaded_blobs": uploaded_blobs,
            "config_version": updated_config.get("config_version"),
            "config_updated_at": updated_config.get("config_updated_at"),
        }
        await log_upload_history(safe_filename, "success", f"Uploaded {len(df)} rows and refreshed config")
        return response
    except HTTPException as exc:
        await log_upload_history(safe_filename, "failed", exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail))
        raise
    except Exception as exc:
        await log_upload_history(safe_filename, "failed", str(exc))
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")


@app.get("/simulation/scenarios")
def get_scenarios():
    """Returns a list of available simulation scenarios."""
    return [
        {"id": k, "name": v.product_name, "category": v.category, "days": v.days}
        for k, v in SCENARIOS.items()
    ]

@app.post("/simulation/compare")
def compare_engines(payload: Dict[str, str]):
    """Runs both engines for a scenario and returns comparison."""
    scenario_id = payload.get("scenario_id")
    if not scenario_id:
        raise HTTPException(status_code=400, detail="scenario_id is required")
    try:
        return run_comparison(scenario_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/simulation/run")
def run_engine_simulation(payload: Dict[str, str]):
    """Runs a single engine for a scenario."""
    scenario_id = payload.get("scenario_id")
    engine = payload.get("engine", "integrated")
    if not scenario_id:
        raise HTTPException(status_code=400, detail="scenario_id is required")
    try:
        return run_single_simulation(scenario_id, engine)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
