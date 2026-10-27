from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import Consent, LeadStatus, Priority, Timeline
from app.services import normalization as n


class LeadBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field("", max_length=100)
    company_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(None, max_length=320)
    website: str | None = Field(None, max_length=500)
    industry: str | None = Field(None, max_length=120)
    country: str | None = Field(None, max_length=80)
    region: str | None = Field(None, max_length=80)
    company_size: int | None = Field(None, ge=1, le=10_000_000)
    job_title: str | None = Field(None, max_length=160)
    is_decision_maker: bool | None = None
    requirements: str | None = Field(None, max_length=5000)
    budget_usd: Decimal | None = Field(None, ge=0, le=1_000_000_000)
    timeline: Timeline = Timeline.UNKNOWN
    consent: Consent = Consent.UNKNOWN
    source: str | None = Field(None, max_length=120, description="lead source name, e.g. 'Website form'")
    follow_up_date: date | None = None

    @field_validator("first_name", "last_name", "company_name", "job_title", "industry", "country", "region", "source")
    @classmethod
    def _clean(cls, v):
        return n.clean_text(v, max_len=200) if v is not None else v

    @field_validator("first_name", "company_name")
    @classmethod
    def _required_not_blank(cls, v):
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("requirements")
    @classmethod
    def _multiline(cls, v):
        return n.clean_multiline(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return n.normalize_email(v) if v else None

    @field_validator("website")
    @classmethod
    def _site(cls, v):
        return n.normalize_url(v)[0] if v else None


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    """PATCH semantics: only provided fields change (exclude_unset)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    company_name: str | None = Field(None, min_length=1, max_length=200)
    email: str | None = Field(None, max_length=320)
    website: str | None = Field(None, max_length=500)
    industry: str | None = Field(None, max_length=120)
    country: str | None = Field(None, max_length=80)
    region: str | None = Field(None, max_length=80)
    company_size: int | None = Field(None, ge=1, le=10_000_000)
    job_title: str | None = Field(None, max_length=160)
    is_decision_maker: bool | None = None
    requirements: str | None = Field(None, max_length=5000)
    budget_usd: Decimal | None = Field(None, ge=0, le=1_000_000_000)
    timeline: Timeline | None = None
    consent: Consent | None = None
    source: str | None = Field(None, max_length=120)
    follow_up_date: date | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return n.normalize_email(v) if v else None

    @field_validator("website")
    @classmethod
    def _site(cls, v):
        return n.normalize_url(v)[0] if v else None

    @field_validator("requirements")
    @classmethod
    def _multiline(cls, v):
        return n.clean_multiline(v)

    @model_validator(mode="after")
    def _not_empty(self):
        if not self.model_fields_set:
            raise ValueError("No fields provided")
        return self


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    first_name: str
    last_name: str
    company_name: str
    email: str | None
    website: str | None
    industry: str | None
    country: str | None
    region: str | None
    company_size: int | None
    job_title: str | None
    is_decision_maker: bool | None
    requirements: str | None
    budget_usd: Decimal | None
    timeline: Timeline
    consent: Consent
    status: LeadStatus
    priority: Priority | None
    latest_score: float | None
    latest_evaluation_id: str | None
    follow_up_date: date | None
    suspicious_content: bool
    source_name: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class DuplicateCandidate(BaseModel):
    lead_id: str
    full_name: str
    company_name: str
    email: str | None
    reason: str


class LeadCreateResult(BaseModel):
    lead: LeadOut
    possible_duplicates: list[DuplicateCandidate] = []


class MergeRequest(BaseModel):
    duplicate_id: str = Field(min_length=1, max_length=32, description="lead to merge INTO the path lead (it gets archived)")


class ImportRowError(BaseModel):
    row: int
    errors: list[str]


class ImportResult(BaseModel):
    total_rows: int
    created: int
    skipped_duplicates: int
    rejected: int
    possible_duplicates: int
    errors: list[ImportRowError]
    ignored_columns: list[str] = []
    error_report_csv: str | None = None  # CSV text of rejected rows (downloaded by the UI)
