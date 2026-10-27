"""ICP + scoring configuration schema (stored as JSON in icp_profiles.config)."""

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.normalization import normalize_country, normalize_industry

CRITERIA = ["industry_fit", "company_fit", "business_need", "decision_maker", "budget_fit", "timeline", "evidence_quality"]
CRITERIA_LABELS = {
    "industry_fit": "Industry fit",
    "company_fit": "Company fit (size and location)",
    "business_need": "Business need",
    "decision_maker": "Decision-maker relevance",
    "budget_fit": "Budget fit",
    "timeline": "Purchase timeline",
    "evidence_quality": "Evidence quality",
}
ENGINE_VERSION = "scoring-v1"
LEAD_FIELDS = ["industry", "company_size", "country", "job_title", "requirements", "budget_usd", "timeline", "website", "email"]


class ServiceOffering(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    keywords: list[str] = Field(default_factory=list)
    min_budget_usd: float | None = Field(None, ge=0)

    @field_validator("keywords")
    @classmethod
    def _lower(cls, v: list[str]) -> list[str]:
        return [k.strip().lower() for k in v if k and k.strip()]


class Thresholds(BaseModel):
    high_min: float = Field(80, ge=0, le=100)
    medium_min: float = Field(50, ge=0, le=100)

    @model_validator(mode="after")
    def _order(self) -> "Thresholds":
        if self.medium_min >= self.high_min:
            raise ValueError("medium_min must be lower than high_min")
        return self


class Disqualification(BaseModel):
    excluded_industries: list[str] = Field(default_factory=list)
    excluded_countries: list[str] = Field(default_factory=list)
    hard_min_budget_usd: float | None = Field(None, ge=0)
    disqualify_on_opt_out: bool = True

    @field_validator("excluded_industries")
    @classmethod
    def _ind(cls, v: list[str]) -> list[str]:
        return [normalize_industry(x) for x in v if normalize_industry(x)]

    @field_validator("excluded_countries")
    @classmethod
    def _ctry(cls, v: list[str]) -> list[str]:
        return [normalize_country(x) for x in v if normalize_country(x)]


class ICPConfig(BaseModel):
    description: str = Field("", max_length=1000)
    target_industries: list[str] = Field(default_factory=list)
    company_size_min: int | None = Field(None, ge=0)
    company_size_max: int | None = Field(None, ge=0)
    target_countries: list[str] = Field(default_factory=list)
    target_regions: list[str] = Field(default_factory=list)
    relevant_titles: list[str] = Field(default_factory=list)
    supported_problems: list[str] = Field(default_factory=list, description="keywords describing problems we solve")
    services: list[ServiceOffering] = Field(default_factory=list)
    min_budget_usd: float | None = Field(None, ge=0, description="soft minimum budget for full budget points")
    min_qualifying_score: float = Field(50, ge=0, le=100)
    required_fields: list[str] = Field(default_factory=lambda: ["requirements", "job_title"])
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "industry_fit": 20,
            "company_fit": 15,
            "business_need": 20,
            "decision_maker": 15,
            "budget_fit": 10,
            "timeline": 10,
            "evidence_quality": 10,
        }
    )
    thresholds: Thresholds = Field(default_factory=Thresholds)
    disqualification: Disqualification = Field(default_factory=Disqualification)

    @field_validator("target_industries")
    @classmethod
    def _norm_ind(cls, v: list[str]) -> list[str]:
        return [normalize_industry(x) for x in v if normalize_industry(x)]

    @field_validator("target_countries")
    @classmethod
    def _norm_ctry(cls, v: list[str]) -> list[str]:
        return [normalize_country(x) for x in v if normalize_country(x)]

    @field_validator("target_regions", "relevant_titles", "supported_problems")
    @classmethod
    def _lower_list(cls, v: list[str]) -> list[str]:
        return [x.strip().lower() for x in v if x and x.strip()]

    @field_validator("required_fields")
    @classmethod
    def _fields(cls, v: list[str]) -> list[str]:
        bad = [f for f in v if f not in LEAD_FIELDS]
        if bad:
            raise ValueError(f"Unknown required_fields: {bad}. Allowed: {LEAD_FIELDS}")
        return v

    @field_validator("weights")
    @classmethod
    def _weights(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = set(v) - set(CRITERIA)
        missing = set(CRITERIA) - set(v)
        if unknown or missing:
            raise ValueError(f"weights must contain exactly {CRITERIA} (unknown={sorted(unknown)}, missing={sorted(missing)})")
        if any(w < 0 for w in v.values()):
            raise ValueError("weights must be >= 0")
        if sum(v.values()) <= 0:
            raise ValueError("weights must not all be zero")
        return v

    @model_validator(mode="after")
    def _size_range(self) -> "ICPConfig":
        lo, hi = self.company_size_min, self.company_size_max
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("company_size_min must be <= company_size_max")
        return self

    def normalized_weights(self) -> dict[str, float]:
        total = sum(self.weights.values())
        return {k: round(v / total * 100, 4) for k, v in self.weights.items()}


def default_hvac_icp() -> ICPConfig:
    """Initial scenario: AI automation agency targeting US HVAC contractors."""
    return ICPConfig(
        description="US HVAC contractors that could benefit from AI customer support, missed-call follow-up, CRM automation or lead management.",
        target_industries=["hvac", "home services"],
        company_size_min=5,
        company_size_max=200,
        target_countries=["United States"],
        relevant_titles=[
            "owner",
            "founder",
            "ceo",
            "president",
            "general manager",
            "operations manager",
            "office manager",
            "director of operations",
            "vp operations",
            "marketing manager",
        ],
        supported_problems=[
            "missed call",
            "missed calls",
            "miss calls",
            "missing calls",
            "after-hours",
            "follow-up",
            "follow up",
            "lead management",
            "crm",
            "customer support",
            "scheduling",
            "dispatch",
            "automation",
            "response time",
            "chatbot",
            "answering",
        ],
        services=[
            ServiceOffering(
                name="AI Customer Support",
                description="24/7 AI chat and phone assistant",
                keywords=["customer support", "chatbot", "answering", "after-hours", "support"],
                min_budget_usd=2000,
            ),
            ServiceOffering(
                name="Missed-Call Follow-up",
                description="Automatic text-back and follow-up",
                keywords=["missed call", "missed calls", "miss calls", "missing calls", "follow-up", "follow up", "voicemail"],
                min_budget_usd=1000,
            ),
            ServiceOffering(
                name="CRM Automation",
                description="CRM workflows and pipeline automation",
                keywords=["crm", "pipeline", "automation", "workflow", "scheduling"],
                min_budget_usd=2500,
            ),
            ServiceOffering(
                name="Lead Management",
                description="Lead capture, routing and scoring",
                keywords=["lead management", "lead", "leads", "quote requests"],
                min_budget_usd=1500,
            ),
        ],
        min_budget_usd=2000,
        min_qualifying_score=50,
        required_fields=["requirements", "job_title"],
        thresholds=Thresholds(high_min=80, medium_min=50),
        disqualification=Disqualification(excluded_industries=[], excluded_countries=[], hard_min_budget_usd=250, disqualify_on_opt_out=True),
    )
