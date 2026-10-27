"""Persist immutable evaluations (score + BANT + evidence) and update the lead's denormalised summary."""

import hashlib
import json

from sqlalchemy.orm import Session

from app.models import BantAssessment, Evaluation, Evidence, ICPProfile, Lead
from app.models.enums import LeadStatus
from app.repositories import qualification_repository as qrepo
from app.services.bant_service import BantItem, assess_bant
from app.services.icp_config import ICPConfig
from app.services.scoring_service import LeadFacts, ScoreResult, score_lead


def compute_payload_hash(score: ScoreResult, bant: list[BantItem], ai_report: dict | None) -> str:
    canonical = {
        "score": score.total,
        "priority": score.priority.value,
        "breakdown": score.breakdown(),
        "disqualified": score.disqualified,
        "reasons": score.disqualification_reasons,
        "bant": [(b.dimension.value, b.status.value, b.origin) for b in bant],
        "ai": ai_report,
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode()).hexdigest()


def persist_evaluation(
    session: Session,
    *,
    lead: Lead,
    icp_row: ICPProfile,
    score: ScoreResult,
    bant: list[BantItem],
    kind: str,
    workflow_id: str | None = None,
    ai_status: str = "not_run",
    ai_report: dict | None = None,
    evidence_rows: list[dict] | None = None,
    requires_human_review: bool = True,
    update_lead_summary: bool = True,
) -> Evaluation:
    ev = Evaluation(
        lead_id=lead.id,
        workflow_id=workflow_id,
        icp_id=icp_row.id,
        icp_version=icp_row.version,
        engine_version=score.engine_version,
        kind=kind,
        total_score=score.total,
        priority=score.priority,
        breakdown=score.breakdown(),
        missing_information=score.missing_information,
        disqualified=score.disqualified,
        disqualification_reasons=score.disqualification_reasons,
        ai_status=ai_status,
        ai_report=ai_report,
        requires_human_review=requires_human_review,
        payload_hash=compute_payload_hash(score, bant, ai_report),
    )
    for b in bant:
        ev.bant.append(
            BantAssessment(
                dimension=b.dimension,
                status=b.status,
                origin=b.origin,
                evidence_text=b.evidence_text,
                provenance=b.provenance,
                rationale=b.rationale,
                clarification_needed=b.clarification_needed,
            )
        )
    for e in evidence_rows or []:
        ev.evidence.append(
            Evidence(
                lead_id=lead.id,
                statement=e["statement"],
                provenance=e["provenance"],
                source_url=e.get("source_url"),
                retrieved_at=e.get("retrieved_at"),
                confidence=e.get("confidence"),
            )
        )
    session.add(ev)
    session.flush()
    if update_lead_summary:
        lead.latest_score = score.total
        lead.priority = score.priority
        lead.latest_evaluation_id = ev.id
    return ev


def score_only(session: Session, lead: Lead, icp_row: ICPProfile) -> Evaluation:
    """Deterministic scoring + rules-based BANT. No LLM, no network. Safe to call at any time."""
    icp = ICPConfig.model_validate(icp_row.config)
    facts = LeadFacts.from_lead(lead, has_verified_evidence=qrepo.has_verified_evidence(session, lead.id))
    score = score_lead(facts, icp)
    bant = assess_bant(facts, icp)
    ev = persist_evaluation(session, lead=lead, icp_row=icp_row, score=score, bant=bant, kind="score_only")
    if lead.status == LeadStatus.NEW and score.disqualified:
        pass  # status transitions only happen through the approval workflow
    return ev
