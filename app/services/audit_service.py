from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.models import Activity, AuditEvent

_SENSITIVE = {"password", "token", "api_key", "secret", "authorization"}


def audit(
    session: Session, *, actor_id: str | None, action: str, entity_type: str, entity_id: str | None = None, details: dict | None = None
) -> AuditEvent:
    clean = {k: v for k, v in (details or {}).items() if k.lower() not in _SENSITIVE}
    ev = AuditEvent(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, details=clean, request_id=request_id_var.get())
    session.add(ev)
    return ev


def activity(session: Session, *, lead_id: str, actor_id: str | None, kind: str, message: str) -> Activity:
    act = Activity(lead_id=lead_id, actor_id=actor_id, kind=kind, message=message[:2000])
    session.add(act)
    return act
