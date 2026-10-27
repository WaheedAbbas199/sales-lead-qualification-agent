"""Human approval boundary. Decisions are atomic, role-checked and bound to the exact evaluation payload."""

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, PermissionDenied, ValidationFailed
from app.db.base import utcnow
from app.models import Approval, Evaluation, Lead, User, WorkflowExecution
from app.models.enums import ApprovalStatus, Role
from app.services.audit_service import activity, audit

REVIEW_ROLES = {Role.ADMIN, Role.REVIEWER}


def get_approval(session: Session, approval_id: str) -> Approval:
    a = session.get(Approval, approval_id)
    if not a:
        raise NotFoundError("Approval not found")
    return a


def decide(session: Session, approval_id: str, *, reviewer: User, decision: ApprovalStatus, comment: str | None) -> Approval:
    if reviewer.role not in REVIEW_ROLES:  # defence in depth: also enforced at the API layer
        raise PermissionDenied("Only reviewers and admins can decide approvals")
    if decision == ApprovalStatus.PENDING:
        raise ValidationFailed("Decision must be approved, rejected or revision_requested")
    if decision != ApprovalStatus.APPROVED and not (comment and comment.strip()):
        raise ValidationFailed("A comment is required when rejecting or requesting a revision")
    approval = get_approval(session, approval_id)
    evaluation = session.get(Evaluation, approval.evaluation_id)
    wf = session.get(WorkflowExecution, approval.workflow_id)
    if evaluation is None or wf is None:
        raise ConflictError("Approval references missing data")
    if evaluation.payload_hash != approval.payload_hash:  # result changed after review was requested => fail closed
        raise ConflictError("The evaluation changed after this approval was requested; re-run qualification")
    # Atomic compare-and-set: two reviewers clicking at once cannot both win.
    res = session.execute(
        update(Approval)
        .where(Approval.id == approval_id, Approval.status == ApprovalStatus.PENDING)
        .values(status=decision, reviewer_id=reviewer.id, comment=(comment or None), decided_at=utcnow())
    )
    if res.rowcount != 1:
        session.rollback()
        raise ConflictError("This approval has already been decided")
    lead = session.get(Lead, approval.lead_id)
    audit(
        session,
        actor_id=reviewer.id,
        action=f"approval.{decision.value}",
        entity_type="approval",
        entity_id=approval_id,
        details={"workflow_id": approval.workflow_id, "lead_id": approval.lead_id, "evaluation_id": approval.evaluation_id},
    )
    if lead:
        activity(
            session,
            lead_id=lead.id,
            actor_id=reviewer.id,
            kind="review",
            message=f"Review decision: {decision.value}" + (f" - {comment.strip()[:300]}" if comment else ""),
        )
    session.commit()
    session.refresh(approval)
    return approval
