"""Executes / resumes qualification workflows. Used by API (BackgroundTasks or inline) and by tests."""

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.agents.graph import RECURSION_LIMIT, build_graph
from app.agents.nodes.qualification_nodes import Deps, QualificationNodes
from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger, request_id_var, workflow_id_var
from app.db.base import utcnow
from app.integrations.gemini.client import LLMClient
from app.integrations.web_search.provider import ResearchProvider
from app.models import Lead, WorkflowExecution
from app.models.enums import ACTIVE_WORKFLOW_STATUSES, LeadStatus, WorkflowStatus
from app.repositories import qualification_repository as qrepo
from app.services.audit_service import audit

log = get_logger(__name__)


@dataclass
class WorkflowRunner:
    session_factory: sessionmaker[Session]
    settings: Settings
    llm: LLMClient
    research: ResearchProvider

    # ---------------------------------------------------------------- start
    def create_execution(self, session: Session, *, lead_id: str, actor_id: str | None) -> WorkflowExecution:
        """Idempotent start: at most one active execution per lead (also enforced by a partial unique index)."""
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise NotFoundError("Lead not found")
        if lead.status == LeadStatus.ARCHIVED:
            raise ConflictError("Archived leads cannot be qualified")
        active = qrepo.active_workflow(session, lead_id)
        if active:
            raise ConflictError(
                "A qualification workflow is already active for this lead", details={"workflow_id": active.id, "status": active.status.value}
            )
        prior = len(qrepo.list_workflows(session, lead_id))
        wf = WorkflowExecution(
            lead_id=lead_id, status=WorkflowStatus.QUEUED, started_by=actor_id, request_id=request_id_var.get(), attempt=prior + 1, state={}, trace=[]
        )
        session.add(wf)
        try:
            session.flush()
        except Exception as exc:  # unique index lost a race with a concurrent request
            session.rollback()
            raise ConflictError("A qualification workflow is already active for this lead") from exc
        audit(session, actor_id=actor_id, action="workflow.started", entity_type="workflow", entity_id=wf.id, details={"lead_id": lead_id})
        session.commit()
        return wf

    # ---------------------------------------------------------------- run
    def _invoke(self, workflow_id: str, *, resume: bool) -> None:
        workflow_id_var.set(workflow_id)
        with self.session_factory() as session:
            wf = session.get(WorkflowExecution, workflow_id)
            if wf is None:
                return
            deps = Deps(session=session, settings=self.settings, llm=self.llm, research=self.research, actor_id=wf.started_by)
            state = {**(wf.state or {}), "workflow_id": wf.id, "lead_id": wf.lead_id, "steps": 0, "errors": []}
            if resume:
                state["resume"] = True
                deps.snapshot.update({k: v for k, v in (wf.state or {}).items() if k not in ("steps", "resume")})
            graph = build_graph(QualificationNodes(deps))
            try:
                graph.invoke(state, {"recursion_limit": RECURSION_LIMIT})
            except Exception as exc:  # noqa: BLE001 - never leave an execution stuck in 'running'
                log.exception("Workflow crashed: %s", type(exc).__name__)
                session.rollback()
                wf = session.get(WorkflowExecution, workflow_id)
                wf.status, wf.error, wf.error_category, wf.finished_at = WorkflowStatus.FAILED, f"crash: {type(exc).__name__}", "crash", utcnow()
                lead = session.get(Lead, wf.lead_id)
                if lead and lead.status in (LeadStatus.QUALIFYING, LeadStatus.PENDING_REVIEW):
                    lead.status = LeadStatus.NEW
                session.commit()

    def run(self, workflow_id: str) -> None:
        """Run a QUEUED execution once. Re-entrancy safe: only the caller that flips queued->running proceeds."""
        with self.session_factory() as session:
            res = session.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == workflow_id, WorkflowExecution.status == WorkflowStatus.QUEUED)
                .values(status=WorkflowStatus.RUNNING)
            )
            session.commit()
            if res.rowcount != 1:
                return
        self._invoke(workflow_id, resume=False)

    def resume(self, workflow_id: str) -> bool:
        """Continue after a human decision. Compare-and-set on status makes double-resume a no-op."""
        with self.session_factory() as session:
            res = session.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == workflow_id, WorkflowExecution.status == WorkflowStatus.AWAITING_APPROVAL)
                .values(status=WorkflowStatus.RUNNING)
            )
            session.commit()
            if res.rowcount != 1:
                return False
        self._invoke(workflow_id, resume=True)
        return True

    # ---------------------------------------------------------------- recovery
    def recover_stale(self) -> int:
        """Executions left 'running'/'queued' by a crash are failed (so they can be started again safely)."""
        from datetime import timedelta

        cutoff = utcnow() - timedelta(minutes=self.settings.workflow_stale_minutes)
        n = 0
        with self.session_factory() as session:
            stale = session.scalars(
                select(WorkflowExecution).where(
                    WorkflowExecution.status.in_([WorkflowStatus.RUNNING, WorkflowStatus.QUEUED]), WorkflowExecution.updated_at < cutoff
                )
            )
            for wf in stale:
                wf.status, wf.error, wf.error_category, wf.finished_at = (
                    WorkflowStatus.FAILED,
                    "interrupted (stale execution recovered)",
                    "interrupted",
                    utcnow(),
                )
                lead = session.get(Lead, wf.lead_id)
                if lead and lead.status in (LeadStatus.QUALIFYING,):
                    lead.status = LeadStatus.NEW
                n += 1
            session.commit()
        return n


__all__ = ["WorkflowRunner", "ACTIVE_WORKFLOW_STATUSES"]
