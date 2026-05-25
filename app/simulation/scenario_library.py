from .models import SimulationState

SCENARIOS = {
    "stable_kurta": SimulationState(
        sku_id="SKU-KURTA-001",
        product_name="Regular Blue Kurta",
        category="Ethnic Wear",
        scenario="stable_kurta",
        days=30,
        current_price=1499,
        benchmark_price=1499,
        competitor_price=1299,
        cogs=800,
        current_ad_spend=180,
        benchmark_ad_spend=180,
        current_stock=300,
        base_demand=5.2,
        price_elasticity=-1.6,
        ad_elasticity=0.22,
        seasonality_factor=1.0,
        roas=4.0,
        conversion_rate=0.025,
        shock_sequence=[0.0]
    ),
    "seasonal_jacket": SimulationState(
        sku_id="SKU-JACKET-001",
        product_name="Winter Jacket",
        category="Winterwear",
        scenario="seasonal_jacket",
        days=45,
        current_price=3999,
        benchmark_price=3999,
        competitor_price=3999,
        cogs=2200,
        current_ad_spend=300,
        benchmark_ad_spend=300,
        current_stock=500,
        base_demand=6.2,
        price_elasticity=-1.4,
        ad_elasticity=0.22,
        seasonality_factor=1.15,
        seasonal_decay_per_day=0.012,
        days_to_season_end=40,
        roas=3.2,
        conversion_rate=0.02,
        leftover_inventory_charge_per_unit=1800,
        min_margin_pct=0.12,
        max_ad_spend_pct_of_price=0.16
    ),
    "high_uncertainty": SimulationState(
        sku_id="SKU-KURTA-UNCERTAIN-001",
        product_name="Regular Kurta - High Uncertainty",
        category="Ethnic Wear",
        scenario="high_uncertainty",
        days=30,
        current_price=1499,
        benchmark_price=1499,
        competitor_price=1299,
        cogs=800,
        current_ad_spend=180,
        benchmark_ad_spend=180,
        current_stock=300,
        base_demand=5.2,
        price_elasticity=-1.6,
        ad_elasticity=0.22,
        seasonality_factor=1.0,
        roas=4.0,
        conversion_rate=0.025,
        shock_sequence=[0.25, -0.35, 0.20, -0.30, 0.15, -0.25],
        high_uncertainty_mode=True
    ),
    "overstock_shirt": SimulationState(
        sku_id="SKU-SHIRT-OVERSTOCK-001",
        product_name="Casual Shirt Overstock",
        category="Menswear",
        scenario="overstock_shirt",
        days=45,
        current_price=1499,
        benchmark_price=1499,
        competitor_price=1450,
        cogs=750,
        current_ad_spend=150,
        benchmark_ad_spend=150,
        current_stock=450,
        base_demand=5.8,
        price_elasticity=-1.5,
        ad_elasticity=0.22,
        seasonality_factor=0.95,
        roas=3.8,
        conversion_rate=0.02,
        overstock_threshold=300,
        holding_cost_per_leftover_unit=250
    ),
    "low_stock_hero": SimulationState(
        sku_id="SKU-HERO-LOWSTOCK-001",
        product_name="Hero Black Jacket",
        category="Winterwear",
        scenario="low_stock_hero",
        days=20,
        current_price=2499,
        benchmark_price=2499,
        competitor_price=2499,
        cogs=1200,
        current_ad_spend=250,
        benchmark_ad_spend=250,
        current_stock=25,
        base_demand=4.5,
        price_elasticity=-1.2,
        ad_elasticity=0.22,
        seasonality_factor=1.25,
        roas=4.5,
        conversion_rate=0.035,
        low_stock_threshold=30,
        hero_sku=True
    )
}

BRAIN_MAPPINGS = {
    "stable_kurta": {
        "scenario_ids": ["S01", "S25"],
        "lever_ids": ["L01", "L05", "L06", "L08", "L21", "L24"],
        "interaction_ids": ["I01"]
    },
    "seasonal_jacket": {
        "scenario_ids": ["S05", "S08", "S32"],
        "lever_ids": ["L04", "L14", "L19", "L22", "L25"],
        "interaction_ids": ["I02", "I10"]
    },
    "high_uncertainty": {
        "scenario_ids": ["S29", "S25"],
        "lever_ids": ["L24", "L25"],
        "interaction_ids": ["RQ2"]
    },
    "overstock_shirt": {
        "scenario_ids": ["S03", "S04", "S08"],
        "lever_ids": ["L01", "L04", "L11", "L14", "L22"],
        "interaction_ids": ["I08", "I10"]
    },
    "low_stock_hero": {
        "scenario_ids": ["S21", "S27", "S28", "S34"],
        "lever_ids": ["L03", "L09", "L10", "L13", "L21", "L23"],
        "interaction_ids": ["I03", "I04"]
    }
}

RESEARCH_DATA = {
    "stable_kurta": {
        "scenario_name": "Stable Kurta Strategy",
        "interpretation": "Bought demand after margin cut | Protected margin | Integrated wins",
        "demo_message": "The integrated agent gives up a few units of volume, but improves profit because it stops buying traffic after the price cut has already compressed margin."
    },
    "seasonal_jacket": {
        "scenario_name": "Seasonal Jacket Clearance",
        "interpretation": "High margin but stuck inventory | Lower margin but cleaner exit | Integrated wins",
        "demo_message": "Separate agents look better before inventory charge. But after accounting for leftover seasonal stock, integrated wins clearly."
    },
    "high_uncertainty": {
        "scenario_name": "High Uncertainty Boundary",
        "interpretation": "Independent actions are more stable | Integrated overreacts to noisy signals | Separate wins",
        "demo_message": "Integration is not always better. Under high uncertainty, the orchestrator can overreact. This supports the research claim that companies should not integrate everything blindly."
    },
    "overstock_shirt": {
        "scenario_name": "Overstock Shirt Management",
        "interpretation": "More margin but inventory drag | Better sell-through and net outcome | Integrated wins",
        "demo_message": "Integrated accepts a small gross margin tradeoff to reduce inventory drag. Net outcome improves after holding cost."
    },
    "low_stock_hero": {
        "scenario_name": "Low Stock Hero SKU Scarcity",
        "interpretation": "Paid to sell stock that would sell anyway | Captured scarcity margin | Integrated wins",
        "demo_message": "When stock is scarce, buying more demand is wasteful. Integrated protects margin and reduces ad spend."
    }
}

def get_scenario(scenario_id: str) -> SimulationState:
    if scenario_id not in SCENARIOS:
        raise ValueError(f"Scenario {scenario_id} not found")
    # Return a copy to avoid mutating the library
    return SCENARIOS[scenario_id].model_copy()

def get_brain_mapping(scenario_id: str) -> dict:
    return BRAIN_MAPPINGS.get(scenario_id, {})

def get_research_data(scenario_id: str) -> dict:
    return RESEARCH_DATA.get(scenario_id, {})
