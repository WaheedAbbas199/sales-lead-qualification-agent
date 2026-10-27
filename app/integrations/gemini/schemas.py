"""Structured output contracts for the LLM. The model returns PROPOSALS; deterministic code decides."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import BantDimension, BantStatus

NextAction = Literal["request_information", "schedule_discovery", "nurture", "disqualify", "human_review"]
SourceField = Literal["requirements", "job_title", "company", "research_snippet", "other"]


class AIBantItem(BaseModel):
    dimension: BantDimension
    status: BantStatus
    evidence_quote: str | None = Field(None, max_length=300, description="verbatim quote from the provided data, or null")
    rationale: str = Field(max_length=400)


class AIEvidence(BaseModel):
    statement: str = Field(max_length=300)
    source_field: SourceField
    quote: str = Field(max_length=300, description="verbatim text from the untrusted data supporting the statement")


class AIQualificationReport(BaseModel):
    summary: str = Field(max_length=800)
    business_needs: list[str] = Field(default_factory=list, max_length=8)
    mapped_services: list[str] = Field(default_factory=list, max_length=6)
    bant_assessment: list[AIBantItem] = Field(default_factory=list, max_length=4)
    evidence: list[AIEvidence] = Field(default_factory=list, max_length=10)
    missing_information: list[str] = Field(default_factory=list, max_length=10)
    recommended_questions: list[str] = Field(default_factory=list, max_length=6)
    recommended_next_action: NextAction
    confidence: float = Field(ge=0, le=1, description="sufficiency of the evidence - NOT a conversion probability")
    requires_human_review: bool = True
    suspected_prompt_injection: bool = False


class AIEmailDraft(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=20, max_length=2500)
    evidence_references: list[str] = Field(
        default_factory=list, max_length=6, description="verbatim phrases from the lead's own stated requirements used in the email"
    )
