"""Outreach DRAFTS only. Nothing is ever sent by this application (v1)."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.prompts.qualification import DRAFT_SYSTEM, build_draft_prompt
from app.core.config import Settings
from app.core.exceptions import ConflictError, LLMError, NotFoundError, ValidationFailed
from app.db.base import utcnow
from app.integrations.gemini.client import LLMClient
from app.models import Lead, OutreachDraft
from app.models.enums import Consent, DraftStatus, DraftType, LeadStatus
from app.repositories import icp_repository, qualification_repository
from app.services.audit_service import activity, audit
from app.services.icp_config import ICPConfig
from app.services.qualification_service import lead_prompt_view
from app.services.scoring_service import LeadFacts, matched_services

DEFAULT_CTA = {
    DraftType.INTRODUCTION: "a short 15-minute intro call",
    DraftType.DISCOVERY_MEETING: "a 30-minute discovery meeting",
    DraftType.FOLLOW_UP: "a quick reply with a good time to talk",
    DraftType.MISSING_INFO: "replying to the questions below",
}


def _snippet(lead: Lead, limit: int = 160) -> str | None:
    if not lead.requirements:
        return None
    text = " ".join(lead.requirements.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def template_draft(lead: Lead, draft_type: DraftType, cta: str, services: list[str], questions: list[str]) -> tuple[str, str, list[str]]:
    """Deterministic, evidence-safe fallback. It only repeats what the lead themself wrote."""
    first = lead.first_name
    stated = _snippet(lead)
    refs = [stated] if stated else []
    svc = f" Based on that, {services[0]} may be relevant." if services and stated else ""
    if draft_type == DraftType.INTRODUCTION:
        subject = f"Quick question for {lead.company_name}"
        body = (
            f"Hi {first},\n\n"
            + (f'You mentioned: "{stated}".{svc} ' if stated else "I'm reaching out because we help businesses like yours with AI automation. ")
            + f"Would you be open to {cta}?\n\nBest regards"
        )
    elif draft_type == DraftType.DISCOVERY_MEETING:
        subject = f"Next step for {lead.company_name}"
        body = (
            f"Hi {first},\n\nThanks for the context so far."
            + (f' You noted: "{stated}".' if stated else "")
            + f" I'd suggest we set up {cta} to understand your goals and see whether we are a fit.\n\nBest regards"
        )
    elif draft_type == DraftType.FOLLOW_UP:
        subject = f"Following up - {lead.company_name}"
        body = (
            f"Hi {first},\n\nJust following up on my earlier note. Would you be open to {cta}? "
            "If the timing is not right, tell me and I will check back later.\n\nBest regards"
        )
    else:
        qs = questions or ["What is your approximate budget range?", "Who else is involved in the decision?", "When would you like to start?"]
        subject = f"A few quick questions - {lead.company_name}"
        body = (
            f"Hi {first},\n\nTo make sure I point you in the right direction, could you help with a few details?\n"
            + "\n".join(f"- {q}" for q in qs[:4])
            + f"\n\nThanks - this is all I need before suggesting {cta}.\n\nBest regards"
        )
    return subject, body, refs


def generate_draft(
    session: Session,
    *,
    lead: Lead,
    draft_type: DraftType,
    cta: str | None,
    actor_id: str | None,
    llm: LLMClient,
    settings: Settings,
    evaluation_id: str | None = None,
) -> OutreachDraft:
    if lead.consent == Consent.OPTED_OUT:
        raise ValidationFailed("This contact opted out of communication; no draft will be generated")
    if lead.status in (LeadStatus.ARCHIVED, LeadStatus.DISQUALIFIED):
        raise ValidationFailed(f"No outreach drafts for a lead with status '{lead.status.value}'")
    icp_row = icp_repository.get_active(session)
    icp = ICPConfig.model_validate(icp_row.config)
    services = matched_services(LeadFacts.from_lead(lead), icp)
    cta_text = (cta or DEFAULT_CTA[draft_type]).strip()
    latest = qualification_repository.latest_evaluation(session, lead.id)
    evaluation_id = evaluation_id or (latest.id if latest else None)
    questions = ((latest.ai_report or {}).get("recommended_questions") if latest else None) or []

    generated_by = "template"
    subject = body = ""
    refs: list[str] = []
    if settings.llm_provider == "gemini" and llm.name != "disabled":
        try:
            ai = llm.draft_email(
                DRAFT_SYSTEM,
                build_draft_prompt(
                    lead=lead_prompt_view(lead), draft_type=draft_type.value, cta=cta_text, services=services, limit=settings.llm_max_input_chars
                ),
            )
            hay = " ".join((lead.requirements or "").lower().split())
            refs = [r for r in ai.evidence_references if " ".join(r.lower().split()) in hay]
            subject, body, generated_by = ai.subject.strip(), ai.body.strip(), "llm"
        except LLMError:
            generated_by = "template"
    if generated_by == "template":
        subject, body, refs = template_draft(lead, draft_type, cta_text, services, questions)

    draft = OutreachDraft(
        lead_id=lead.id,
        evaluation_id=evaluation_id,
        draft_type=draft_type,
        subject=subject[:300],
        body=body,
        generated_by=generated_by,
        evidence_references=refs,
        created_by=actor_id,
    )
    session.add(draft)
    session.flush()
    audit(
        session,
        actor_id=actor_id,
        action="outreach.draft_created",
        entity_type="outreach_draft",
        entity_id=draft.id,
        details={"lead_id": lead.id, "type": draft_type.value, "generated_by": generated_by},
    )
    activity(session, lead_id=lead.id, actor_id=actor_id, kind="draft", message=f"{draft_type.value} draft created ({generated_by})")
    return draft


def get_draft(session: Session, draft_id: str) -> OutreachDraft:
    d = session.get(OutreachDraft, draft_id)
    if not d:
        raise NotFoundError("Draft not found")
    return d


def update_draft(
    session: Session, draft_id: str, *, subject: str | None, body: str | None, follow_up: date | None, actor_id: str, set_follow_up: bool
) -> OutreachDraft:
    d = get_draft(session, draft_id)
    if d.status != DraftStatus.DRAFT:
        raise ConflictError("Only drafts that are still in 'draft' status can be edited")
    if subject is not None:
        d.subject = subject
    if body is not None:
        d.body = body
    if subject is not None or body is not None:
        d.generated_by = "human"
    if set_follow_up:
        d.follow_up_date = follow_up
        lead = session.get(Lead, d.lead_id)
        if lead:
            lead.follow_up_date = follow_up
    audit(session, actor_id=actor_id, action="outreach.draft_edited", entity_type="outreach_draft", entity_id=d.id)
    session.commit()
    return d


def mark_sent_manually(session: Session, draft_id: str, *, actor_id: str, follow_up: date | None) -> OutreachDraft:
    d = get_draft(session, draft_id)
    if d.status == DraftStatus.SENT_MANUALLY:
        return d  # idempotent
    if d.status != DraftStatus.DRAFT:
        raise ConflictError("Draft is not in 'draft' status")
    lead = session.get(Lead, d.lead_id)
    if lead and lead.consent == Consent.OPTED_OUT:
        raise ValidationFailed("Contact opted out; cannot record outreach")
    d.status = DraftStatus.SENT_MANUALLY
    d.sent_manually_at = utcnow()
    if follow_up:
        d.follow_up_date = follow_up
        if lead:
            lead.follow_up_date = follow_up
    audit(session, actor_id=actor_id, action="outreach.marked_sent", entity_type="outreach_draft", entity_id=d.id, details={"lead_id": d.lead_id})
    activity(session, lead_id=d.lead_id, actor_id=actor_id, kind="outreach_sent", message="Outreach marked as sent manually")
    session.commit()
    return d


def list_drafts(session: Session, *, status: DraftStatus | None, lead_id: str | None, limit: int = 200) -> list[OutreachDraft]:
    stmt = select(OutreachDraft).order_by(OutreachDraft.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(OutreachDraft.status == status)
    if lead_id:
        stmt = stmt.where(OutreachDraft.lead_id == lead_id)
    return list(session.scalars(stmt))
