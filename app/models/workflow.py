from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, enum_values, utcnow
from app.models.enums import ApprovalStatus, WorkflowStatus
from app.models.user import new_id


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        # DB-level guarantee: at most ONE active execution per lead (race-safe duplicate protection).
        Index(
            "uq_workflow_active_per_lead",
            "lead_id",
            unique=True,
            sqlite_where=text("status IN ('queued','running','awaiting_approval')"),
            postgresql_where=text("status IN ('queued','running','awaiting_approval')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, native_enum=False, length=24, validate_strings=True, values_callable=enum_values),
        default=WorkflowStatus.QUEUED,
        nullable=False,
    )
    current_node: Mapped[str | None] = mapped_column(String(60))
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # serialisable graph state (no secrets)
    trace: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # per-node events
    error: Mapped[str | None] = mapped_column(Text)
    error_category: Mapped[str | None] = mapped_column(String(40))
    request_id: Mapped[str | None] = mapped_column(String(64))
    started_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_executions.id", ondelete="CASCADE"), unique=True, nullable=False)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # approval is bound to this exact result
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, native_enum=False, length=24, validate_strings=True, values_callable=enum_values),
        default=ApprovalStatus.PENDING,
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
