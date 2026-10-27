from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import Container, CurrentUser, ReviewerUser, SalesUser, get_container, get_db
from app.core.exceptions import NotFoundError
from app.models import Approval, Evaluation, Lead, User, WorkflowExecution
from app.models.enums import ApprovalStatus
from app.repositories import icp_repository
from app.repositories import qualification_repository as qrepo
from app.schemas.qualification import ApprovalDecision, ApprovalOut, EvaluationOut, WorkflowOut
from app.services import approval_service, evaluation_service, lead_service
from app.services.audit_service import audit

router = APIRouter(tags=["qualification"])


@router.post("/leads/{lead_id}/score", response_model=EvaluationOut, status_code=201)
def score_lead(lead_id: str, user: User = SalesUser, db: Session = Depends(get_db)):
    """Deterministic scoring only (no AI, no approval needed, no status change). Creates a new history row."""
    lead = lead_service.get_lead(db, lead_id)
    icp_row = icp_repository.get_active(db)
    if icp_row is None:
        raise NotFoundError("No active ICP profile")
    ev = evaluation_service.score_only(db, lead, icp_row)
    audit(db, actor_id=user.id, action="lead.score", entity_type="lead", entity_id=lead.id, details={"evaluation_id": ev.id})
    db.commit()
    return ev


@router.get("/leads/{lead_id}/evaluations", response_model=list[EvaluationOut])
def evaluations(lead_id: str, _: User = CurrentUser, db: Session = Depends(get_db)):
    lead_service.get_lead(db, lead_id)
    return qrepo.list_evaluations(db, lead_id)


@router.post("/leads/{lead_id}/qualify", response_model=WorkflowOut, status_code=202)
def qualify(lead_id: str, background: BackgroundTasks, user: User = SalesUser, db: Session = Depends(get_db), c: Container = Depends(get_container)):
    """Start the full LangGraph qualification workflow (runs in the background; poll /workflows/{id})."""
    wf = c.runner.create_execution(db, lead_id=lead_id, actor_id=user.id)
    if c.settings.workflow_inline:
        c.runner.run(wf.id)
        db.refresh(wf)
    else:
        background.add_task(c.runner.run, wf.id)
    return wf


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(workflow_id: str, _: User = CurrentUser, db: Session = Depends(get_db)):
    wf = db.get(WorkflowExecution, workflow_id)
    if not wf:
        raise NotFoundError("Workflow not found")
    db.refresh(wf)
    return wf


@router.get("/leads/{lead_id}/workflows", response_model=list[WorkflowOut])
def lead_workflows(lead_id: str, _: User = CurrentUser, db: Session = Depends(get_db)):
    lead_service.get_lead(db, lead_id)
    return qrepo.list_workflows(db, lead_id)


# ------------------------------- review queue -------------------------------
def _approval_out(db: Session, a: Approval) -> ApprovalOut:
    lead, ev = db.get(Lead, a.lead_id), db.get(Evaluation, a.evaluation_id)
    return ApprovalOut(
        id=a.id,
        workflow_id=a.workflow_id,
        lead_id=a.lead_id,
        lead_name=lead.full_name if lead else None,
        company_name=lead.company_name if lead else None,
        evaluation_id=a.evaluation_id,
        status=a.status,
        reviewer_id=a.reviewer_id,
        comment=a.comment,
        created_at=a.created_at,
        decided_at=a.decided_at,
        score=ev.total_score if ev else None,
        priority=ev.priority if ev else None,
        requires_human_review=ev.requires_human_review if ev else None,
        suspicious_content=bool(lead and lead.suspicious_content),
        missing_information=(ev.missing_information if ev else []),
        ai_summary=((ev.ai_report or {}).get("summary") if ev else None),
    )


@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(status: ApprovalStatus | None = Query(None), _: User = CurrentUser, db: Session = Depends(get_db)):
    return [_approval_out(db, a) for a in qrepo.list_approvals(db, status)]


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalOut)
def decide(
    approval_id: str,
    body: ApprovalDecision,
    background: BackgroundTasks,
    reviewer: User = ReviewerUser,
    db: Session = Depends(get_db),
    c: Container = Depends(get_container),
):
    approval = approval_service.decide(db, approval_id, reviewer=reviewer, decision=body.decision, comment=body.comment)
    # The workflow resumes ONLY after the decision is committed; the first node re-reads it from the DB.
    if c.settings.workflow_inline:
        c.runner.resume(approval.workflow_id)
        db.refresh(approval)
    else:
        background.add_task(c.runner.resume, approval.workflow_id)
    return _approval_out(db, approval)
