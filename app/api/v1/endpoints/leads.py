from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import Container, CurrentUser, SalesUser, get_container, get_db
from app.core.exceptions import ValidationFailed
from app.models import Activity, Lead, OutreachDraft, User
from app.models.enums import ApprovalStatus, LeadStatus, Priority
from app.repositories import lead_repository as repo
from app.repositories import qualification_repository as qrepo
from app.schemas.common import Page
from app.schemas.lead import ImportResult, LeadCreate, LeadCreateResult, LeadOut, LeadUpdate, MergeRequest
from app.schemas.qualification import ActivityOut, ApprovalOut, DraftOut, EvaluationOut, WorkflowOut
from app.services import lead_service
from app.services.audit_service import audit

router = APIRouter(tags=["leads"])


@router.get("/leads", response_model=Page[LeadOut])
def list_leads(
    db: Session = Depends(get_db),
    _: User = CurrentUser,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: LeadStatus | None = None,
    priority: Priority | None = None,
    source: Annotated[str | None, Query(max_length=120)] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    include_archived: bool = False,
    sort: Annotated[str, Query(pattern="^(created_at|updated_at|company_name|latest_score|status|priority|follow_up_date)$")] = "created_at",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = repo.search(
        db,
        q=q,
        status=status.value if status else None,
        priority=priority.value if priority else None,
        source=source,
        min_score=min_score,
        include_archived=include_archived,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )
    return Page[LeadOut](items=[LeadOut.model_validate(i) for i in items], total=total, page=page, page_size=page_size)


@router.post("/leads", response_model=LeadCreateResult, status_code=201)
def create_lead(body: LeadCreate, user: User = SalesUser, db: Session = Depends(get_db)):
    lead, dups = lead_service.create_lead(db, body, actor_id=user.id)
    return LeadCreateResult(lead=LeadOut.model_validate(lead), possible_duplicates=dups)


@router.get("/leads/import/template")
def import_template(_: User = CurrentUser):
    return Response(
        lead_service.csv_template(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="lead_import_template.csv"'}
    )


@router.post("/leads/import", response_model=ImportResult)
def import_leads(file: UploadFile = File(...), user: User = SalesUser, db: Session = Depends(get_db), c: Container = Depends(get_container)):
    limit = c.settings.csv_max_bytes
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise ValidationFailed(f"File too large (max {limit} bytes)")
    return lead_service.import_csv(db, content=content, filename=file.filename or "", settings=c.settings, actor_id=user.id)


@router.get("/leads/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: str, _: User = CurrentUser, db: Session = Depends(get_db)):
    return lead_service.get_lead(db, lead_id)


@router.patch("/leads/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: str, body: LeadUpdate, user: User = SalesUser, db: Session = Depends(get_db)):
    return lead_service.update_lead(db, lead_id, body, actor_id=user.id)


@router.post("/leads/{lead_id}/archive", response_model=LeadOut)
def archive(lead_id: str, user: User = SalesUser, db: Session = Depends(get_db)):
    return lead_service.archive_lead(db, lead_id, actor_id=user.id)


@router.post("/leads/{lead_id}/restore", response_model=LeadOut)
def restore(lead_id: str, user: User = SalesUser, db: Session = Depends(get_db)):
    return lead_service.restore_lead(db, lead_id, actor_id=user.id)


@router.post("/leads/{lead_id}/merge", response_model=LeadOut)
def merge(lead_id: str, body: MergeRequest, user: User = SalesUser, db: Session = Depends(get_db)):
    return lead_service.merge_leads(db, lead_id, body.duplicate_id, actor_id=user.id)


@router.get("/leads/{lead_id}/detail")
def lead_detail(lead_id: str, _: User = CurrentUser, db: Session = Depends(get_db)) -> dict:
    """Everything the Lead Details page needs in one round trip."""
    lead = lead_service.get_lead(db, lead_id)
    evals = qrepo.list_evaluations(db, lead_id)
    latest_full = next((e for e in evals if e.kind == "full"), None)
    shown = latest_full or (evals[0] if evals else None)
    acts = list(db.scalars(select(Activity).where(Activity.lead_id == lead_id).order_by(Activity.created_at.desc()).limit(50)))
    drafts = list(db.scalars(select(OutreachDraft).where(OutreachDraft.lead_id == lead_id).order_by(OutreachDraft.created_at.desc())))
    wfs = qrepo.list_workflows(db, lead_id)
    pending = next((a for a in qrepo.list_approvals(db, ApprovalStatus.PENDING) if a.lead_id == lead_id), None)
    return {
        "lead": LeadOut.model_validate(lead).model_dump(mode="json"),
        "evaluation": EvaluationOut.model_validate(shown).model_dump(mode="json") if shown else None,
        "history": [
            {
                "id": e.id,
                "kind": e.kind,
                "score": e.total_score,
                "priority": e.priority.value,
                "icp_version": e.icp_version,
                "engine_version": e.engine_version,
                "ai_status": e.ai_status,
                "created_at": e.created_at.isoformat(),
            }
            for e in evals
        ],
        "workflows": [WorkflowOut.model_validate(w).model_dump(mode="json") for w in wfs[:10]],
        "activities": [ActivityOut.model_validate(a).model_dump(mode="json") for a in acts],
        "drafts": [DraftOut.model_validate(d).model_dump(mode="json") for d in drafts],
        "pending_approval": ApprovalOut(
            id=pending.id,
            workflow_id=pending.workflow_id,
            lead_id=pending.lead_id,
            evaluation_id=pending.evaluation_id,
            status=pending.status,
            reviewer_id=None,
            comment=None,
            created_at=pending.created_at,
            decided_at=None,
        ).model_dump(mode="json")
        if pending
        else None,
    }


_ = (audit, Lead)
