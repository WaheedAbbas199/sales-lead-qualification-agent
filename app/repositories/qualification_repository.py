from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Approval, Evaluation, Evidence, WorkflowExecution
from app.models.enums import ACTIVE_WORKFLOW_STATUSES, ApprovalStatus, Provenance


def latest_evaluation(session: Session, lead_id: str) -> Evaluation | None:
    return session.scalar(select(Evaluation).where(Evaluation.lead_id == lead_id).order_by(Evaluation.created_at.desc(), Evaluation.id.desc()))


def list_evaluations(session: Session, lead_id: str) -> list[Evaluation]:
    return list(session.scalars(select(Evaluation).where(Evaluation.lead_id == lead_id).order_by(Evaluation.created_at.desc(), Evaluation.id.desc())))


def has_verified_evidence(session: Session, lead_id: str) -> bool:
    return bool(
        session.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.lead_id == lead_id, Evidence.provenance == Provenance.VERIFIED_SOURCE)
        )
    )


def active_workflow(session: Session, lead_id: str) -> WorkflowExecution | None:
    return session.scalar(
        select(WorkflowExecution).where(WorkflowExecution.lead_id == lead_id, WorkflowExecution.status.in_(ACTIVE_WORKFLOW_STATUSES))
    )


def list_workflows(session: Session, lead_id: str) -> list[WorkflowExecution]:
    return list(session.scalars(select(WorkflowExecution).where(WorkflowExecution.lead_id == lead_id).order_by(WorkflowExecution.created_at.desc())))


def list_approvals(session: Session, status: ApprovalStatus | None, limit: int = 200) -> list[Approval]:
    stmt = select(Approval).order_by(Approval.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Approval.status == status)
    return list(session.scalars(stmt))
