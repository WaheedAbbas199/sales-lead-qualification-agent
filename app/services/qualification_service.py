"""AI analysis step (proposal only) + grounding checks. Deterministic code owns scores and statuses."""

from dataclasses import dataclass, field

from app.agents.prompts.qualification import QUALIFY_SYSTEM, build_qualify_prompt
from app.core.config import Settings
from app.core.exceptions import LLMMalformedOutput, LLMNotConfigured, LLMUnavailable
from app.integrations.gemini.client import LLMClient
from app.integrations.gemini.schemas import AIQualificationReport
from app.models import Lead
from app.models.enums import Provenance
from app.services.icp_config import ICPConfig


@dataclass
class AIOutcome:
    status: str  # ok | unavailable | malformed | not_configured
    report: dict | None = None
    evidence: list[dict] = field(default_factory=list)
    dropped_ungrounded: int = 0
    message: str | None = None


def lead_prompt_view(lead: Lead) -> dict:
    return {
        "name": lead.full_name,
        "company": lead.company_name,
        "job_title": lead.job_title,
        "industry": lead.industry,
        "company_size_employees": lead.company_size,
        "country": lead.country,
        "region": lead.region,
        "website": lead.website,
        "stated_budget_usd": str(lead.budget_usd) if lead.budget_usd is not None else None,
        "stated_timeline": lead.timeline.value if lead.timeline.value != "unknown" else None,
        "decision_maker_flag": lead.is_decision_maker,
        "business_requirements": lead.requirements,
    }


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def ground_report(report: AIQualificationReport, corpus: str) -> tuple[AIQualificationReport, int]:
    """Drop any evidence/BANT quote that is not literally present in the supplied data (anti-hallucination)."""
    hay = _norm(corpus)
    dropped = 0
    good_evidence = []
    for e in report.evidence:
        if _norm(e.quote) and _norm(e.quote) in hay:
            good_evidence.append(e)
        else:
            dropped += 1
    for b in report.bant_assessment:
        if b.evidence_quote and _norm(b.evidence_quote) not in hay:
            b.evidence_quote = None
            dropped += 1
    report.evidence = good_evidence
    return report, dropped


def run_ai_analysis(*, llm: LLMClient, lead: Lead, snippets: list[dict], icp: ICPConfig, settings: Settings) -> AIOutcome:
    prompt = build_qualify_prompt(lead=lead_prompt_view(lead), snippets=snippets, icp=icp, limit=settings.llm_max_input_chars)
    try:
        report = llm.qualify(QUALIFY_SYSTEM, prompt)
    except LLMNotConfigured as exc:
        return AIOutcome("not_configured", message=exc.message)
    except LLMMalformedOutput as exc:
        return AIOutcome("malformed", message=exc.message)
    except LLMUnavailable as exc:
        return AIOutcome("unavailable", message=exc.message)
    corpus = "\n".join([*(str(v) for v in lead_prompt_view(lead).values() if v is not None), *(f"{s['title']} {s['snippet']}" for s in snippets)])
    report, dropped = ground_report(report, corpus)
    evidence = [
        {
            "statement": f"{e.statement} (quote: \u201c{e.quote}\u201d)",
            "provenance": Provenance.SEARCH_SNIPPET if e.source_field == "research_snippet" else Provenance.AI_INFERRED,
            "confidence": None,
        }
        for e in report.evidence
    ]
    data = report.model_dump(mode="json")
    if dropped or report.suspected_prompt_injection:
        data["requires_human_review"] = True
    return AIOutcome("ok", report=data, evidence=evidence, dropped_ungrounded=dropped)
