from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Lead, LeadSource
from app.models.enums import LeadStatus, Priority

SORTABLE = {
    "created_at": Lead.created_at,
    "updated_at": Lead.updated_at,
    "company_name": Lead.company_name,
    "latest_score": Lead.latest_score,
    "status": Lead.status,
    "priority": Lead.priority,
    "follow_up_date": Lead.follow_up_date,
}


def get(session: Session, lead_id: str) -> Lead | None:
    return session.get(Lead, lead_id)


def get_by_email(session: Session, email_normalized: str) -> Lead | None:
    return session.scalar(select(Lead).where(Lead.email_normalized == email_normalized))


def get_or_create_source(session: Session, name: str, kind: str = "manual") -> LeadSource:
    src = session.scalar(select(LeadSource).where(LeadSource.name == name))
    if src:
        return src
    src = LeadSource(name=name, kind=kind)
    session.add(src)
    session.flush()
    return src


def find_possible_duplicates(
    session: Session, *, first_name: str, last_name: str, company_name: str, website_domain: str | None, exclude_id: str | None = None
) -> list[tuple[Lead, str]]:
    found: list[tuple[Lead, str]] = []
    fn, ln, co = first_name.lower(), (last_name or "").lower(), company_name.lower()
    stmt = select(Lead).where(func.lower(Lead.first_name) == fn, func.lower(Lead.last_name) == ln)
    if website_domain:
        stmt_dom = stmt.where(Lead.website_domain == website_domain)
        for lead in session.scalars(stmt_dom):
            found.append((lead, "same name and company website"))
    for lead in session.scalars(stmt.where(func.lower(Lead.company_name) == co)):
        if all(lead.id != f[0].id for f in found):
            found.append((lead, "same name and company name"))
    return [(lead, why) for lead, why in found if lead.id != exclude_id and lead.status != LeadStatus.ARCHIVED]


def search(
    session: Session,
    *,
    q: str | None,
    status: str | None,
    priority: str | None,
    source: str | None,
    min_score: float | None,
    include_archived: bool,
    sort: str,
    order: str,
    page: int,
    page_size: int,
):
    stmt = select(Lead).outerjoin(LeadSource, Lead.source_id == LeadSource.id)
    if not include_archived and status != LeadStatus.ARCHIVED.value:
        stmt = stmt.where(Lead.status != LeadStatus.ARCHIVED)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Lead.first_name).like(like),
                func.lower(Lead.last_name).like(like),
                func.lower(Lead.company_name).like(like),
                func.lower(func.coalesce(Lead.email, "")).like(like),
            )
        )
    if status:
        stmt = stmt.where(Lead.status == LeadStatus(status))
    if priority:
        stmt = stmt.where(Lead.priority == Priority(priority))
    if source:
        stmt = stmt.where(LeadSource.name == source)
    if min_score is not None:
        stmt = stmt.where(Lead.latest_score >= min_score)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTABLE.get(sort, Lead.created_at)
    stmt = stmt.order_by(col.desc().nulls_last() if order == "desc" else col.asc().nulls_last(), Lead.id)
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)
    return list(session.scalars(stmt).unique()), total
