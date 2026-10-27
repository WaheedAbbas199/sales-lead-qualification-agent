from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import AdminUser, Container, CurrentUser, get_container, get_db
from app.models import User
from app.schemas.auth import LoginRequest, TokenResponse, UserCreate, UserOut
from app.services import auth_service
from app.services.audit_service import audit

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db), c: Container = Depends(get_container)):
    ip = request.client.host if request.client else "unknown"
    user, token = auth_service.authenticate(db, c.settings, c.limiter, email=body.email, password=body.password, client_ip=ip)
    return TokenResponse(access_token=token, expires_in=c.settings.access_token_minutes * 60, user=UserOut.model_validate(user))


@router.post("/auth/logout", status_code=204)
def logout(user: User = CurrentUser, db: Session = Depends(get_db)):
    """Tokens are stateless; the client discards its token. We record the event for the audit trail."""
    audit(db, actor_id=user.id, action="auth.logout", entity_type="user", entity_id=user.id)
    db.commit()


@router.get("/auth/me", response_model=UserOut)
def me(user: User = CurrentUser):
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = AdminUser, db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.created_at)))


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, admin: User = AdminUser, db: Session = Depends(get_db)):
    return auth_service.create_user(db, email=body.email, full_name=body.full_name, password=body.password, role=body.role, actor_id=admin.id)
