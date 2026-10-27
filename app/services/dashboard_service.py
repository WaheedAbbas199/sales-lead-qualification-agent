from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Activity, Approval, Evaluation, Lead, LeadSource, OutreachDraft
from app.models.enums import ApprovalStatus, DraftStatus, LeadStatus, Priority

REPORT_NOTE = (
    "These are descriptive counts of the qualification process. They are NOT conversion rates and do not show "
    "revenue impact; link outcomes (meetings held, deals won) before claiming business results."
)


def _count_by(session: Session, column, where=None) -> dict[str, int]:
    stmt = select(column, func.count()).group_by(column)
    if where is not None:
        stmt = stmt.where(where)
    return {(k.value if hasattr(k, "value") else (k or "unknown")): v for k, v in session.execute(stmt).all()}


def stats(session: Session) -> dict:
    live = Lead.status != LeadStatus.ARCHIVED
    total = session.scalar(select(func.count()).select_from(Lead).where(live)) or 0
    qualified = session.scalar(select(func.count()).select_from(Lead).where(Lead.status == LeadStatus.QUALIFIED)) or 0
    high = session.scalar(select(func.count()).select_from(Lead).where(live, Lead.priority == Priority.HIGH)) or 0
    awaiting = session.scalar(select(func.count()).select_from(Approval).where(Approval.status == ApprovalStatus.PENDING)) or 0
    today = date.today()
    due_leads = (
        session.scalar(select(func.count()).select_from(Lead).where(live, Lead.follow_up_date.is_not(None), Lead.follow_up_date <= today)) or 0
    )
    recent = session.execute(
        select(Activity, Lead.first_name, Lead.last_name, Lead.company_name)
        .join(Lead, Lead.id == Activity.lead_id)
        .order_by(Activity.created_at.desc())
        .limit(10)
    ).all()
    return {
        "total_leads": total,
        "qualified_leads": qualified,
        "high_priority_leads": high,
        "awaiting_review": awaiting,
        "follow_ups_due": due_leads,
        "recent_activity": [
            {"lead_id": a.lead_id, "lead": f"{fn} {ln}".strip(), "company": co, "kind": a.kind, "message": a.message, "at": a.created_at.isoformat()}
            for a, fn, ln, co in recent
        ],
    }


def reports(session: Session) -> dict:
    since = utcnow() - timedelta(days=14)
    live = Lead.status != LeadStatus.ARCHIVED
    by_day = session.execute(
        select(func.date(Evaluation.created_at), func.count(), func.avg(Evaluation.total_score))
        .where(Evaluation.created_at >= since)
        .group_by(func.date(Evaluation.created_at))
        .order_by(func.date(Evaluation.created_at))
    ).all()
    source_name = func.coalesce(LeadSource.name, "unspecified")
    sources = session.execute(
        select(source_name, func.count())
        .select_from(Lead)
        .outerjoin(LeadSource, Lead.source_id == LeadSource.id)
        .where(live)
        .group_by(source_name)
    ).all()
    return {
        "note": REPORT_NOTE,
        "priority_distribution": _count_by(session, Lead.priority, live),
        "status_distribution": _count_by(session, Lead.status),
        "lead_sources": {name: c for name, c in sources},
        "follow_up_activity": _count_by(session, OutreachDraft.status),
        "drafts_sent_manually": session.scalar(
            select(func.count()).select_from(OutreachDraft).where(OutreachDraft.status == DraftStatus.SENT_MANUALLY)
        )
        or 0,
        "ai_status_distribution": _count_by(session, Evaluation.ai_status),
        "evaluation_history": [{"day": str(d), "evaluations": c, "avg_score": round(float(a or 0), 1)} for d, c, a in by_day],
        "approval_outcomes": _count_by(session, Approval.status),
    }
