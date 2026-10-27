"""LangGraph nodes. Deterministic tasks use plain Python; only `ai_analysis` talks to the LLM.

Every node is wrapped by `traced`, which: enforces the step budget, records a trace event, persists the
serialisable state, and converts exceptions into an explicit `failed` state (never a silent crash).
"""

import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.state import QualificationState
from app.agents.tools.registry import Tier, ToolRegistry
from app.core.config import Settings
from app.core.exceptions import AppError, ResearchUnavailable
from app.core.logging import get_logger
from app.db.base import utcnow
from app.integrations.gemini.client import LLMClient
from app.integrations.web_search.provider import ResearchProvider
from app.models import Approval, Evaluation, Lead, OutreachDraft, WorkflowExecution
from app.models.enums import (
    ApprovalStatus,
    BantDimension,
    BantStatus,
    DraftType,
    LeadStatus,
    Provenance,
    WorkflowStatus,
)
from app.repositories import icp_repository, qualification_repository
from app.services import evaluation_service, outreach_service
from app.services import normalization as norm
from app.services.audit_service import activity, audit
from app.services.bant_service import BantItem, assess_bant
from app.services.icp_config import ICPConfig
from app.services.qualification_service import run_ai_analysis
from app.services.safety import detect_injection
from app.services.scoring_service import LeadFacts, score_lead

log = get_logger(__name__)
MAX_STEPS = 30


@dataclass
class Deps:
    session: Session
    settings: Settings
    llm: LLMClient
    research: ResearchProvider
    actor_id: str | None = None
    scratch: dict[str, Any] = field(default_factory=dict)  # non-serialisable intermediates (ORM objects, results)
    snapshot: dict[str, Any] = field(default_factory=dict)


def traced(name: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(self: "QualificationNodes", state: QualificationState) -> dict:
            d = self.deps
            t0 = time.perf_counter()
            steps = state.get("steps", 0) + 1
            update: dict[str, Any]
            outcome = "ok"
            try:
                if steps > MAX_STEPS:
                    raise AppError("Workflow step budget exceeded")
                update = fn(self, state) or {}
            except (AppError, ValidationError, ValueError) as exc:
                d.session.rollback()
                outcome, update = (
                    "error",
                    {"status": "failed", "errors": [*state.get("errors", []), f"{name}: {getattr(exc, 'message', str(exc))}"[:500]]},
                )
                update["_category"] = getattr(exc, "code", type(exc).__name__)
            except Exception as exc:  # noqa: BLE001 - last-resort guard so the execution is always closed out
                d.session.rollback()
                log.exception("Unexpected failure in node %s", name)
                outcome, update = (
                    "error",
                    {"status": "failed", "errors": [*state.get("errors", []), f"{name}: unexpected {type(exc).__name__}"], "_category": "unexpected"},
                )
            category = update.pop("_category", None)
            update["steps"] = steps
            d.snapshot.update({k: v for k, v in update.items()})
            wf = d.session.get(WorkflowExecution, state["workflow_id"])
            if wf is not None:
                wf.current_node = name
                wf.trace = [*wf.trace, {"node": name, "outcome": outcome, "ms": int((time.perf_counter() - t0) * 1000), "at": utcnow().isoformat()}]
                wf.state = _json_safe({**d.snapshot, "workflow_id": state["workflow_id"], "lead_id": state["lead_id"]})
                if category:
                    wf.error_category = category
                d.session.commit()
            return update

        return wrapper

    return deco


def _json_safe(data: dict) -> dict:
    import json

    return json.loads(json.dumps(data, default=str))


class QualificationNodes:
    def __init__(self, deps: Deps):
        self.deps = deps
        self.tools = ToolRegistry(deps.session)
        self.tools.register("save_outreach_draft", Tier.DRAFT, self._save_draft_tool)  # approval-gated

    # ------------------------------------------------------------------ helpers
    def _lead(self, state) -> Lead:
        lead = self.deps.session.get(Lead, state["lead_id"])
        if lead is None:
            raise AppError("Lead no longer exists")
        return lead

    def _wf(self, state) -> WorkflowExecution:
        return self.deps.session.get(WorkflowExecution, state["workflow_id"])

    # ------------------------------------------------------------------ phase 1: analysis
    @traced("load_lead")
    def load_lead(self, state):
        lead = self._lead(state)
        if lead.status == LeadStatus.ARCHIVED:
            raise AppError("Archived leads cannot be qualified")
        lead.status = LeadStatus.QUALIFYING
        wf = self._wf(state)
        wf.status = WorkflowStatus.RUNNING
        self.deps.session.commit()
        return {"status": "running"}

    @traced("validate_lead")
    def validate_lead(self, state):
        lead = self._lead(state)
        problems = []
        if not lead.first_name or not lead.company_name:
            problems.append("first_name and company_name are required")
        if lead.email_normalized is None and lead.website is None and not lead.requirements:
            problems.append("lead needs at least an email, a website or business requirements to qualify")
        if problems:
            return {"validation_errors": problems, "status": "failed", "errors": problems}
        return {"validation_errors": []}

    @traced("normalize_lead")
    def normalize_lead(self, state):
        lead = self._lead(state)
        lead.company_name = norm.clean_text(lead.company_name, max_len=200) or lead.company_name
        lead.industry_normalized = norm.normalize_industry(lead.industry)
        lead.country = norm.normalize_country(lead.country)
        hits = detect_injection(lead.requirements, lead.job_title, lead.company_name, lead.first_name, lead.last_name)
        lead.suspicious_content = bool(hits)
        if hits:
            audit(
                self.deps.session,
                actor_id=self.deps.actor_id,
                action="security.prompt_injection_suspected",
                entity_type="lead",
                entity_id=lead.id,
                details={"patterns": len(hits), "workflow_id": state["workflow_id"]},
            )
        return {"injection_hits": hits}

    @traced("check_duplicates")
    def check_duplicates(self, state):
        from app.repositories import lead_repository as lrepo

        lead = self._lead(state)
        dups = lrepo.find_possible_duplicates(
            self.deps.session,
            first_name=lead.first_name,
            last_name=lead.last_name,
            company_name=lead.company_name,
            website_domain=lead.website_domain,
            exclude_id=lead.id,
        )
        return {"duplicate_ids": [d.id for d, _ in dups]}

    @traced("load_icp_profile")
    def load_icp_profile(self, state):
        row = icp_repository.get_active(self.deps.session)
        if row is None:
            raise AppError("No active ICP profile configured")
        self.deps.scratch["icp_row"] = row
        self.deps.scratch["icp"] = ICPConfig.model_validate(row.config)
        return {"icp_id": row.id, "icp_version": row.version}

    @traced("collect_authorized_research")
    def collect_research(self, state):
        lead = self._lead(state)
        rows: list[dict] = []
        snippets: list[dict] = []
        if self.deps.research.name == "disabled":
            self.deps.scratch.update(research_rows=rows, snippets=snippets)
            return {"research_status": "disabled", "snippets": []}
        try:
            hits = self.deps.research.search(lead.company_name, lead.website_domain)
        except ResearchUnavailable:
            # Never fabricate a result: continue with the lead data we have.
            self.deps.scratch.update(research_rows=rows, snippets=snippets)
            return {"research_status": "unavailable", "snippets": []}
        extra_hits: list[str] = []
        for h in hits:
            extra_hits += detect_injection(h.title, h.snippet)
            snippets.append({"title": h.title, "url": h.url, "snippet": h.snippet})
            official = bool(lead.website_domain and h.host == lead.website_domain)
            if official:
                rows.append(
                    {
                        "statement": f"Search provider returned a page on the lead's official domain: {h.title}",
                        "provenance": Provenance.VERIFIED_SOURCE,
                        "source_url": h.url,
                        "retrieved_at": h.retrieved_at,
                    }
                )
            rows.append(
                {
                    "statement": f"Search snippet (not proof): {h.snippet[:300]}",
                    "provenance": Provenance.SEARCH_SNIPPET,
                    "source_url": h.url,
                    "retrieved_at": h.retrieved_at,
                }
            )
        self.deps.scratch.update(research_rows=rows, snippets=snippets)
        out: dict[str, Any] = {"research_status": "ok", "snippets": [{"url": s["url"], "title": s["title"]} for s in snippets]}
        if extra_hits:
            out["injection_hits"] = [*state.get("injection_hits", []), *extra_hits]
        return out

    @traced("assess_bant")
    def assess_bant(self, state):
        lead, icp = self._lead(state), self.deps.scratch["icp"]
        verified = any(r["provenance"] == Provenance.VERIFIED_SOURCE for r in self.deps.scratch.get("research_rows", []))
        facts = LeadFacts.from_lead(lead, has_verified_evidence=verified)
        self.deps.scratch["facts"] = facts
        self.deps.scratch["bant"] = assess_bant(facts, icp)
        return {}

    @traced("calculate_lead_score")
    def calculate_score(self, state):
        score = score_lead(self.deps.scratch["facts"], self.deps.scratch["icp"])
        self.deps.scratch["score"] = score
        return {"score_total": score.total, "score_priority": score.priority.value, "disqualified": score.disqualified}

    @traced("ai_analysis")
    def ai_analysis(self, state):
        lead, icp = self._lead(state), self.deps.scratch["icp"]
        outcome = run_ai_analysis(llm=self.deps.llm, lead=lead, snippets=self.deps.scratch.get("snippets", []), icp=icp, settings=self.deps.settings)
        self.deps.scratch["ai"] = outcome
        return {"ai_status": outcome.status}

    @traced("validate_result")
    def validate_result(self, state):
        score = self.deps.scratch["score"]
        if not (0 <= score.total <= 100):
            raise AppError("Score out of range")
        if len(self.deps.scratch["bant"]) != 4:
            raise AppError("Incomplete BANT assessment")
        return {}

    @traced("save_evaluation")
    def save_evaluation(self, state):
        s = self.deps.scratch
        lead = self._lead(state)
        bant: list[BantItem] = list(s["bant"])
        ai = s["ai"]
        ai_report = ai.report
        if ai_report:
            for item in ai_report.get("bant_assessment", []):
                bant.append(
                    BantItem(
                        BantDimension(item["dimension"]),
                        BantStatus(item["status"]),
                        item.get("evidence_quote"),
                        Provenance.AI_INFERRED,
                        item.get("rationale", ""),
                        None,
                        origin="ai",
                    )
                )
        evidence = [*s.get("research_rows", []), *ai.evidence]
        suspicious = bool(state.get("injection_hits")) or bool(ai_report and ai_report.get("suspected_prompt_injection"))
        if ai_report is not None:
            ai_report["suspicious_input_detected"] = suspicious
        ev = evaluation_service.persist_evaluation(
            self.deps.session,
            lead=lead,
            icp_row=s["icp_row"],
            score=s["score"],
            bant=bant,
            kind="full",
            workflow_id=state["workflow_id"],
            ai_status=ai.status,
            ai_report=ai_report,
            evidence_rows=evidence,
            requires_human_review=True,
        )  # v1 policy: every qualification is reviewed by a human
        activity(
            self.deps.session,
            lead_id=lead.id,
            actor_id=self.deps.actor_id,
            kind="qualification",
            message=f"Qualification computed: score {ev.total_score:.0f} ({ev.priority.value}), AI: {ai.status}",
        )
        self.deps.session.commit()
        return {"evaluation_id": ev.id}

    @traced("human_review")
    def human_review(self, state):
        """The workflow STOPS here. Nothing after this node runs until a reviewer decides (see resume entry)."""
        s = self.deps.session
        ev = qualification_repository.latest_evaluation(s, state["lead_id"])
        if ev is None or ev.id != state["evaluation_id"]:
            raise AppError("Evaluation missing for review")
        approval = Approval(
            workflow_id=state["workflow_id"],
            lead_id=state["lead_id"],
            evaluation_id=ev.id,
            payload_hash=ev.payload_hash or "",
            status=ApprovalStatus.PENDING,
        )
        s.add(approval)
        lead = self._lead(state)
        lead.status = LeadStatus.PENDING_REVIEW
        wf = self._wf(state)
        wf.status = WorkflowStatus.AWAITING_APPROVAL
        audit(
            s,
            actor_id=self.deps.actor_id,
            action="workflow.awaiting_approval",
            entity_type="workflow",
            entity_id=wf.id,
            details={"lead_id": lead.id, "evaluation_id": ev.id},
        )
        s.commit()
        return {"status": "awaiting_approval", "approval_id": approval.id}

    # ------------------------------------------------------------------ phase 2: after a human decision
    @traced("check_approval")
    def check_approval(self, state):
        """Fail closed: the decision is read from the DB, never trusted from graph state."""
        approval = self.deps.session.query(Approval).filter(Approval.workflow_id == state["workflow_id"]).one_or_none()
        if approval is None:
            raise AppError("No approval record exists for this workflow")
        if approval.status != ApprovalStatus.PENDING and approval.reviewer_id is None:
            raise AppError("Approval has no reviewer identity; refusing to continue")
        return {"approval_status": approval.status.value}

    @traced("prepare_outreach_draft")
    def prepare_outreach_draft(self, state):
        lead = self._lead(state)
        s = self.deps.session
        final = state.get("final_lead_status")
        ev = s.get(Evaluation, state["evaluation_id"])
        if final == LeadStatus.QUALIFIED.value:
            dtype = DraftType.DISCOVERY_MEETING
        elif final == LeadStatus.NURTURE.value and ev and ev.missing_information:
            dtype = DraftType.MISSING_INFO
        else:
            return {}  # disqualified / nothing useful to draft
        existing = s.query(OutreachDraft).filter(OutreachDraft.evaluation_id == state["evaluation_id"], OutreachDraft.draft_type == dtype).first()
        if existing:  # idempotent on resume/retry
            return {"draft_id": existing.id}
        try:
            draft = self.tools.call(
                "save_outreach_draft", workflow_id=state["workflow_id"], lead=lead, draft_type=dtype, evaluation_id=state["evaluation_id"]
            )
        except AppError as exc:  # a draft problem must not undo an approved qualification
            s.rollback()
            return {"errors": [*state.get("errors", []), f"draft: {exc.message}"[:300]]}
        s.commit()
        return {"draft_id": draft.id}

    def _save_draft_tool(self, *, lead: Lead, draft_type: DraftType, evaluation_id: str):
        return outreach_service.generate_draft(
            self.deps.session,
            lead=lead,
            draft_type=draft_type,
            cta=None,
            actor_id=self.deps.actor_id,
            llm=self.deps.llm,
            settings=self.deps.settings,
            evaluation_id=evaluation_id,
        )

    @traced("finalize_approved")
    def finalize_approved(self, state):
        """Apply the consequential status change - only reachable on an APPROVED decision."""
        s, lead = self.deps.session, self._lead(state)
        ev = s.get(Evaluation, state["evaluation_id"])
        icp = ICPConfig.model_validate(icp_repository.get(s, ev.icp_id).config)
        if ev.disqualified:
            final = LeadStatus.DISQUALIFIED
        elif ev.total_score >= icp.min_qualifying_score:
            final = LeadStatus.QUALIFIED
        else:
            final = LeadStatus.NURTURE
        lead.status = final
        wf = self._wf(state)
        wf.status, wf.finished_at = WorkflowStatus.COMPLETED, utcnow()
        activity(s, lead_id=lead.id, actor_id=self.deps.actor_id, kind="status", message=f"Status set to {final.value} after approval")
        audit(
            s,
            actor_id=self.deps.actor_id,
            action="workflow.completed",
            entity_type="workflow",
            entity_id=wf.id,
            details={"final_status": final.value},
        )
        s.commit()
        return {"status": "completed", "final_lead_status": final.value}

    @traced("finalize_rejected")
    def finalize_rejected(self, state):
        s, lead = self.deps.session, self._lead(state)
        lead.status = LeadStatus.NEW
        wf = self._wf(state)
        wf.status, wf.finished_at = WorkflowStatus.REJECTED, utcnow()
        audit(s, actor_id=self.deps.actor_id, action="workflow.rejected", entity_type="workflow", entity_id=wf.id)
        s.commit()
        return {"status": "rejected", "final_lead_status": LeadStatus.NEW.value}

    @traced("finalize_revision")
    def finalize_revision(self, state):
        s, lead = self.deps.session, self._lead(state)
        lead.status = LeadStatus.NEEDS_REVISION
        wf = self._wf(state)
        wf.status, wf.finished_at = WorkflowStatus.REVISION_REQUESTED, utcnow()
        audit(s, actor_id=self.deps.actor_id, action="workflow.revision_requested", entity_type="workflow", entity_id=wf.id)
        s.commit()
        return {"status": "revision_requested", "final_lead_status": LeadStatus.NEEDS_REVISION.value}

    @traced("pending_guard")
    def pending_guard(self, state):
        """Resume attempted while the approval is still pending => stay parked (no side effects)."""
        wf = self._wf(state)
        wf.status = WorkflowStatus.AWAITING_APPROVAL
        self.deps.session.commit()
        return {"status": "awaiting_approval"}

    @traced("fail")
    def fail(self, state):
        s = self.deps.session
        wf = self._wf(state)
        wf.status, wf.finished_at = WorkflowStatus.FAILED, utcnow()
        wf.error = "; ".join(state.get("errors", []))[:1000] or "unknown error"
        lead = s.get(Lead, state["lead_id"])
        if lead and lead.status in (LeadStatus.QUALIFYING, LeadStatus.PENDING_REVIEW):
            lead.status = LeadStatus.NEW
        audit(
            s, actor_id=self.deps.actor_id, action="workflow.failed", entity_type="workflow", entity_id=wf.id, details={"category": wf.error_category}
        )
        s.commit()
        return {"status": "failed"}
