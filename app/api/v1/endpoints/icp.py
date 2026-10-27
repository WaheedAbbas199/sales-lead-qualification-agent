from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import AdminUser, CurrentUser, get_db
from app.models import User
from app.repositories import icp_repository as repo
from app.schemas.icp import ICPOut, ICPUpdate, RecalculateResult
from app.services import icp_service
from app.services.icp_config import CRITERIA, CRITERIA_LABELS

router = APIRouter(tags=["icp"])


@router.get("/icp", response_model=ICPOut)
def get_icp(_: User = CurrentUser, db: Session = Depends(get_db)):
    return icp_service.get_active(db)


@router.get("/icp/criteria")
def criteria(_: User = CurrentUser) -> dict:
    return {"criteria": [{"name": c, "label": CRITERIA_LABELS[c]} for c in CRITERIA]}


@router.get("/icp/versions", response_model=list[ICPOut])
def versions(_: User = CurrentUser, db: Session = Depends(get_db)):
    return repo.list_versions(db)


@router.put("/icp", response_model=ICPOut)
def update_icp(body: ICPUpdate, admin: User = AdminUser, db: Session = Depends(get_db)):
    """Creates a NEW immutable version and makes it active. Past evaluations keep the version they used."""
    return icp_service.update(db, config=body.config, name=body.name, actor_id=admin.id)


@router.post("/icp/recalculate", response_model=RecalculateResult)
def recalculate(admin: User = AdminUser, db: Session = Depends(get_db)):
    version, n = icp_service.recalculate_all(db, actor_id=admin.id)
    return RecalculateResult(icp_version=version, recalculated=n)
