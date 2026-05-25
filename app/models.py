from typing import List, Optional, Literal
from pydantic import BaseModel, Field, model_validator


class SKUInput(BaseModel):
    sku_id: str
    product_name: str
    category: str = "Apparel"

    current_price: float = Field(gt=0)
    cost: float = Field(gt=0)
    current_ad_spend_per_unit: float = Field(ge=0)

    competitor_price: Optional[float] = Field(default=None, gt=0)
    conversion_rate: float = Field(ge=0)
    previous_conversion_rate: Optional[float] = Field(default=None, ge=0)
    roas: float = Field(ge=0)
    ctr: Optional[float] = Field(default=None, ge=0)

    stock_on_hand: int = Field(ge=0)
    days_of_cover: float = Field(ge=0)
    ageing_days: int = Field(ge=0)
    sell_through_rate_weekly: float = Field(ge=0)
    stockout_risk: float = Field(ge=0, le=1)

    season_days_left: Optional[int] = Field(default=None, ge=0)
    sales_vs_baseline: float = Field(default=1.0, ge=0)
    trend_change_7d_pct: float = 0

    hero_sku: bool = False

    @model_validator(mode="after")
    def validate_margin(self):
        return self


class AgentDecision(BaseModel):
    agent: str
    recommended_action: str
    change_pct: Optional[float] = None
    state: Optional[str] = None
    reasoning: str
    key_drivers: List[str]
    confidence: float = Field(ge=0, le=1)
    approval_required: bool = False


class FinancialImpact(BaseModel):
    current_unit_margin: float
    projected_unit_margin: float
    unit_margin_change: float
    projected_price: float
    projected_ad_spend_per_unit: float
    margin_pct_after_action: float
    estimated_units_cleared: Optional[int] = None
    impact_summary: str


class RecommendationResponse(BaseModel):
    sku_id: str
    product_name: str
    primary_objective: str
    price_action: str
    price_change_pct: float
    ad_action: str
    ad_change_pct: float
    confidence: float
    risk_level: Literal["Low", "Medium", "High"]
    approval_required: bool
    reasoning: str
    decision_parameters: List[str]
    agent_decisions: List[AgentDecision]
    financial_impact: FinancialImpact
