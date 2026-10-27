from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, enum_values
from app.models.enums import Consent, LeadStatus, Priority, Timeline
from app.models.user import new_id


class LeadSource(Base, TimestampMixin):
    __tablename__ = "lead_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)  # manual|csv|api


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_status_priority", "status", "priority"),
        Index("ix_leads_company_domain", "website_domain"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    # Unique when present. Email is a *matching hint*, not proof of identity (see docs/ARCHITECTURE.md).
    email_normalized: Mapped[str | None] = mapped_column(String(320), unique=True)
    website: Mapped[str | None] = mapped_column(String(500))
    website_domain: Mapped[str | None] = mapped_column(String(255))
    industry: Mapped[str | None] = mapped_column(String(120))
    industry_normalized: Mapped[str | None] = mapped_column(String(120), index=True)
    country: Mapped[str | None] = mapped_column(String(80))
    region: Mapped[str | None] = mapped_column(String(80))
    company_size: Mapped[int | None] = mapped_column(Integer)
    job_title: Mapped[str | None] = mapped_column(String(160))
    is_decision_maker: Mapped[bool | None] = mapped_column(Boolean)  # None = unknown (NOT "no")
    requirements: Mapped[str | None] = mapped_column(Text)
    budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    timeline: Mapped[Timeline] = mapped_column(
        Enum(Timeline, native_enum=False, length=24, validate_strings=True, values_callable=enum_values), default=Timeline.UNKNOWN, nullable=False
    )
    consent: Mapped[Consent] = mapped_column(
        Enum(Consent, native_enum=False, length=16, validate_strings=True, values_callable=enum_values), default=Consent.UNKNOWN, nullable=False
    )
    source_id: Mapped[str | None] = mapped_column(ForeignKey("lead_sources.id", ondelete="SET NULL"))
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, native_enum=False, length=20, validate_strings=True, values_callable=enum_values), default=LeadStatus.NEW, nullable=False
    )
    priority: Mapped[Priority | None] = mapped_column(
        Enum(Priority, native_enum=False, length=10, validate_strings=True, values_callable=enum_values)
    )
    latest_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    latest_evaluation_id: Mapped[str | None] = mapped_column(String(32))
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    suspicious_content: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[LeadSource | None] = relationship(lazy="joined")

    @property
    def source_name(self) -> str | None:
        return self.source.name if self.source else None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
