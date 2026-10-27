from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import Container, get_container, get_db

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    """Liveness only: no dependencies touched, nothing sensitive returned."""
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db), c: Container = Depends(get_container)) -> dict:
    """Readiness: DB reachable + honest status of optional providers (no secrets, no hostnames)."""
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    llm, research = c.llm.status(), c.research.status()
    body = {
        "status": "ready" if db_ok else "degraded",
        "database": "ok" if db_ok else "unavailable",
        "ai": {"provider": llm["provider"], "configured": llm["configured"]},
        "research": {"provider": research["provider"], "configured": research["configured"]},
        "email_sending": "disabled (drafts only)",
    }
    if not db_ok:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content=body)  # type: ignore[return-value]
    return body
