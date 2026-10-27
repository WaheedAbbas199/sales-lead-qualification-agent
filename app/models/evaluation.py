from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, enum_values, utcnow
from app.models.enums import BantDimension, BantStatus, Priority, Provenance
from app.models.user import new_id


class Evaluation(Base):
    """One immutable qualification result. Recalculation creates a new row; history is never overwritten."""

    __tablename__ = "evaluations"
    __table_args__ = (Index("ix_eval_lead_created", "lead_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(String(32), index=True)
    icp_id: Mapped[str] = mapped_column(ForeignKey("icp_profiles.id"), nullable=False)
    icp_version: Mapped[int] = mapped_column(Integer, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="score_only", nullable=False)  # score_only|full
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, native_enum=False, length=10, validate_strings=True, values_callable=enum_values), nullable=False
    )
    breakdown: Mapped[list] = mapped_column(JSON, nullable=False)
    missing_information: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    disqualified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disqualification_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ai_status: Mapped[str] = mapped_column(String(24), default="not_run", nullable=False)  # not_run|ok|unavailable|malformed|not_configured
    ai_report: Mapped[dict | None] = mapped_column(JSON)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    bant: Mapped[list["BantAssessment"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    evidence: Mapped[list["Evidence"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class BantAssessment(Base):
    __tablename__ = "bant_assessments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True, nullable=False)
    dimension: Mapped[BantDimension] = mapped_column(
        Enum(BantDimension, native_enum=False, length=12, validate_strings=True, values_callable=enum_values), nullable=False
    )
    status: Mapped[BantStatus] = mapped_column(
        Enum(BantStatus, native_enum=False, length=24, validate_strings=True, values_callable=enum_values), nullable=False
    )
    origin: Mapped[str] = mapped_column(String(10), default="rules", nullable=False)  # rules|ai
    evidence_text: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[Provenance] = mapped_column(
        Enum(Provenance, native_enum=False, length=20, validate_strings=True, values_callable=enum_values), nullable=False
    )
    rationale: Mapped[str | None] = mapped_column(Text)
    clarification_needed: Mapped[str | None] = mapped_column(Text)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True, nullable=False)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[Provenance] = mapped_column(
        Enum(Provenance, native_enum=False, length=20, validate_strings=True, values_callable=enum_values), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(1000))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float | None] = mapped_column(Float)
