from pydantic import BaseModel, Field

from . import config as c


class ExtraCost(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    amount: float = Field(ge=0)
    scenario: str = Field(default="both", pattern="^(internal|contractor|both)$")


class EstimateRequest(BaseModel):
    description: str = Field(min_length=10, max_length=4000, description="Описание ИТ-задачи")
    complexity: float = Field(default=c.DEFAULTS["complexity"], ge=0.5, le=2.0)
    internal_rate: float = Field(default=c.DEFAULTS["internal_rate"], gt=0, le=100000)
    internal_overhead_pct: float = Field(default=c.DEFAULTS["internal_overhead_pct"], ge=0, le=200)
    risk_reserve_pct: float = Field(default=c.DEFAULTS["risk_reserve_pct"], ge=0, le=100)
    internal_team: int = Field(default=c.DEFAULTS["internal_team"], ge=1, le=50)
    internal_queue_days: int = Field(default=c.DEFAULTS["internal_queue_days"], ge=0, le=365)
    contractor_team: int = Field(default=c.DEFAULTS["contractor_team"], ge=1, le=100)
    contractor_mobilization_days: int = Field(default=c.DEFAULTS["contractor_mobilization_days"], ge=0, le=365)
    contractor_efficiency: float = Field(default=c.DEFAULTS["contractor_efficiency"], ge=0.3, le=1.5)
    coordination_pct: float = Field(default=c.DEFAULTS["coordination_pct"], ge=0, le=100)
    extra_costs: list[ExtraCost] = Field(default_factory=list, max_length=20)
