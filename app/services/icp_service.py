from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import ICPProfile, Lead
from app.models.enums import LeadStatus
from app.repositories import icp_repository as repo
from app.services import evaluation_service
from app.services.audit_service import audit
from app.services.icp_config import ICPConfig, default_hvac_icp


def ensure_default(session: Session) -> ICPProfile:
    active = repo.get_active(session)
    if active:
        return active
    row = repo.create_version(session, name="default", config=default_hvac_icp().model_dump(mode="json"), user_id=None)
    session.commit()
    return row


def get_active(session: Session) -> ICPProfile:
    row = repo.get_active(session)
    if not row:
        raise NotFoundError("No active ICP profile; start the app once or create one via the API")
    return row


def update(session: Session, *, config: ICPConfig, name: str | None, actor_id: str) -> ICPProfile:
    current = repo.get_active(session)
    row = repo.create_version(session, name=name or (current.name if current else "default"), config=config.model_dump(mode="json"), user_id=actor_id)
    audit(session, actor_id=actor_id, action="icp.update", entity_type="icp_profile", entity_id=row.id, details={"version": row.version})
    session.commit()
    return row


def recalculate_all(session: Session, *, actor_id: str) -> tuple[int, int]:
    """Re-score every non-archived lead against the active ICP. Old evaluations are preserved."""
    icp_row = get_active(session)
    leads = list(session.scalars(select(Lead).where(Lead.status != LeadStatus.ARCHIVED)))
    for lead in leads:
        evaluation_service.score_only(session, lead, icp_row)
    audit(
        session,
        actor_id=actor_id,
        action="icp.recalculate",
        entity_type="icp_profile",
        entity_id=icp_row.id,
        details={"leads": len(leads), "version": icp_row.version},
    )
    session.commit()
    return icp_row.version, len(leads)
