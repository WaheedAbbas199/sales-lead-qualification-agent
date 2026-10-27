from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import ICPProfile


def get_active(session: Session) -> ICPProfile | None:
    return session.scalar(select(ICPProfile).where(ICPProfile.is_active.is_(True)).order_by(ICPProfile.version.desc()))


def get(session: Session, icp_id: str) -> ICPProfile | None:
    return session.get(ICPProfile, icp_id)


def list_versions(session: Session) -> list[ICPProfile]:
    return list(session.scalars(select(ICPProfile).order_by(ICPProfile.version.desc())))


def create_version(session: Session, *, name: str, config: dict, user_id: str | None) -> ICPProfile:
    next_version = (session.scalar(select(func.max(ICPProfile.version)).where(ICPProfile.name == name)) or 0) + 1
    session.execute(update(ICPProfile).values(is_active=False))
    row = ICPProfile(name=name, version=next_version, is_active=True, config=config, created_by=user_id)
    session.add(row)
    session.flush()
    return row
