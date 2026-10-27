from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, enum_values, utcnow
from app.models.enums import DraftStatus, DraftType
from app.models.user import new_id


class OutreachDraft(Base, TimestampMixin):
    __tablename__ = "outreach_drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False)
    evaluation_id: Mapped[str | None] = mapped_column(ForeignKey("evaluations.id", ondelete="SET NULL"))
    draft_type: Mapped[DraftType] = mapped_column(
        Enum(DraftType, native_enum=False, length=24, validate_strings=True, values_callable=enum_values), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(16), nullable=False, default="template")  # template|llm|human
    evidence_references: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[DraftStatus] = mapped_column(
        Enum(DraftStatus, native_enum=False, length=20, validate_strings=True, values_callable=enum_values),
        default=DraftStatus.DRAFT,
        nullable=False,
        index=True,
    )
    sent_manually_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
