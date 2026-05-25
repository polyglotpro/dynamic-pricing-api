from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class SimulationState(BaseModel):
    sku_id: str
    product_name: str
    category: str
    scenario: str
    days: int

    current_price: float
    benchmark_price: float
    competitor_price: float
    cogs: float
    current_ad_spend: float
    benchmark_ad_spend: float

    current_stock: int
    base_demand: float
    price_elasticity: float
    ad_elasticity: float
    seasonality_factor: float
    
    # Optional fields for specific scenarios
    seasonal_decay_per_day: Optional[float] = 0.0
    days_to_season_end: Optional[int] = None
    roas: float
    conversion_rate: float

    shock_sequence: List[float] = Field(default_factory=lambda: [0.0])
    high_uncertainty_mode: bool = False
    
    low_stock_threshold: int = 30
    overstock_threshold: int = 300
    hero_sku: bool = False
    
    leftover_inventory_charge_per_unit: float = 0.0
    holding_cost_per_leftover_unit: float = 0.0
    
    min_margin_pct: float = 0.15
    max_ad_spend_pct_of_price: float = 0.18

class DailyRecord(BaseModel):
    day: int
    price: float
    ad_spend: float
    demand: float
    units_sold: int
    revenue: float
    profit: float
    margin_pct: float
    stock: int
    roas: float
    shock: float

class SimulationResult(BaseModel):
    scenario_id: str
    engine: str
    total_profit: float
    total_revenue: float
    units_sold: int
    ending_inventory: int
    avg_margin_per_unit: float
    avg_ad_spend_per_unit: float
    sell_through_pct: float
    net_profit: float  # After inventory charges
    daily_history: List[DailyRecord]
    brain_mapping: Dict[str, List[str]]

class ComparisonResult(BaseModel):
    scenario_id: str
    separate: SimulationResult
    integrated: SimulationResult
    delta: Dict[str, Any]
    winner: str
    scenario_name: Optional[str] = None
    interpretation: Optional[str] = None
    demo_message: Optional[str] = None
