from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.exceptions import AuthenticationFailed, PermissionDenied
from app.core.security import LoginRateLimiter, decode_access_token
from app.integrations.gemini.client import LLMClient
from app.integrations.web_search.provider import ResearchProvider
from app.models import User
from app.models.enums import Role
from app.workers.runner import WorkflowRunner

bearer = HTTPBearer(auto_error=False)


@dataclass
class Container:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    llm: LLMClient
    research: ResearchProvider
    runner: WorkflowRunner
    limiter: LoginRateLimiter


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_settings_dep(c: Container = Depends(get_container)) -> Settings:
    return c.settings


def get_db(c: Container = Depends(get_container)) -> Iterator[Session]:
    session = c.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db), c: Container = Depends(get_container)
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise AuthenticationFailed("Authentication required")
    payload = decode_access_token(c.settings, creds.credentials)
    user = db.get(User, payload["sub"])
    # Role comes from the DB, not the token, so demotions/deactivations apply immediately.
    if user is None or not user.is_active:
        raise AuthenticationFailed("Account is inactive or no longer exists")
    return user


def require_roles(*roles: Role):
    allowed = set(roles) | {Role.ADMIN}

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise PermissionDenied("You do not have permission to perform this action")
        return user

    return checker


CurrentUser = Depends(get_current_user)
SalesUser = Depends(require_roles(Role.SALES, Role.REVIEWER))
ReviewerUser = Depends(require_roles(Role.REVIEWER))
AdminUser = Depends(require_roles())
