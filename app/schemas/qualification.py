from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ApprovalStatus,
    BantDimension,
    BantStatus,
    DraftStatus,
    DraftType,
    Priority,
    Provenance,
    WorkflowStatus,
)


class BantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    dimension: BantDimension
    status: BantStatus
    origin: str
    evidence_text: str | None
    provenance: Provenance
    rationale: str | None
    clarification_needed: str | None


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    statement: str
    provenance: Provenance
    source_url: str | None
    retrieved_at: datetime | None
    confidence: float | None


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    lead_id: str
    workflow_id: str | None
    icp_id: str
    icp_version: int
    engine_version: str
    kind: str
    total_score: float
    priority: Priority
    breakdown: list[dict]
    missing_information: list[str]
    disqualified: bool
    disqualification_reasons: list[str]
    ai_status: str
    ai_report: dict | None
    requires_human_review: bool
    created_at: datetime
    bant: list[BantOut] = []
    evidence: list[EvidenceOut] = []


class WorkflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    lead_id: str
    status: WorkflowStatus
    current_node: str | None
    trace: list[dict]
    error: str | None
    error_category: str | None
    attempt: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class ApprovalOut(BaseModel):
    id: str
    workflow_id: str
    lead_id: str
    lead_name: str | None = None
    company_name: str | None = None
    evaluation_id: str
    status: ApprovalStatus
    reviewer_id: str | None
    comment: str | None
    created_at: datetime
    decided_at: datetime | None
    score: float | None = None
    priority: Priority | None = None
    requires_human_review: bool | None = None
    suspicious_content: bool = False
    missing_information: list[str] = []
    ai_summary: str | None = None


class ApprovalDecision(BaseModel):
    decision: ApprovalStatus = Field(description="approved | rejected | revision_requested")
    comment: str | None = Field(None, max_length=2000)


class DraftRequest(BaseModel):
    draft_type: DraftType = DraftType.INTRODUCTION
    call_to_action: str | None = Field(None, max_length=200)


class DraftUpdate(BaseModel):
    subject: str | None = Field(None, min_length=3, max_length=300)
    body: str | None = Field(None, min_length=10, max_length=5000)
    follow_up_date: date | None = None


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    lead_id: str
    evaluation_id: str | None
    draft_type: DraftType
    subject: str
    body: str
    generated_by: str
    evidence_references: list[str]
    status: DraftStatus
    sent_manually_at: datetime | None
    follow_up_date: date | None = None
    created_at: datetime
    updated_at: datetime
    lead_name: str | None = None
    company_name: str | None = None


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: str
    message: str
    actor_id: str | None
    created_at: datetime
