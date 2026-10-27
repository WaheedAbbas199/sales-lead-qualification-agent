from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AuthenticationFailed, ConflictError
from app.core.security import LoginRateLimiter, create_access_token, hash_password, verify_password
from app.db.base import utcnow
from app.models import User
from app.models.enums import Role
from app.services.audit_service import audit

# Verified against when the e-mail is unknown, so unknown and wrong-password take comparable time.
_DUMMY_HASH = hash_password("Dummy-password-1")


def authenticate(session: Session, settings: Settings, limiter: LoginRateLimiter, *, email: str, password: str, client_ip: str) -> tuple[User, str]:
    key = f"{client_ip}|{email.lower()}"
    limiter.check(key)
    user = session.scalar(select(User).where(User.email == email.lower()))
    ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        limiter.record_failure(key)
        audit(
            session,
            actor_id=user.id if user else None,
            action="auth.login_failed",
            entity_type="user",
            details={"email_hash_hint": email[:2] + "***", "ip": client_ip},
        )
        session.commit()
        raise AuthenticationFailed("Invalid email or password")
    limiter.reset(key)
    user.last_login_at = utcnow()
    audit(session, actor_id=user.id, action="auth.login", entity_type="user", entity_id=user.id, details={"ip": client_ip})
    session.commit()
    return user, create_access_token(settings, user.id, user.role.value)


def create_user(session: Session, *, email: str, full_name: str, password: str, role: Role, actor_id: str | None) -> User:
    if session.scalar(select(User).where(User.email == email.lower())):
        raise ConflictError("A user with this email already exists")
    user = User(email=email.lower(), full_name=full_name.strip(), password_hash=hash_password(password), role=role)
    session.add(user)
    session.flush()
    audit(session, actor_id=actor_id, action="user.create", entity_type="user", entity_id=user.id, details={"role": role.value})
    session.commit()
    return user
