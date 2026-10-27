from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, get_db
from app.models import User
from app.services import dashboard_service

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/stats")
def stats(_: User = CurrentUser, db: Session = Depends(get_db)) -> dict:
    return dashboard_service.stats(db)


@router.get("/dashboard/reports")
def reports(_: User = CurrentUser, db: Session = Depends(get_db)) -> dict:
    return dashboard_service.reports(db)
