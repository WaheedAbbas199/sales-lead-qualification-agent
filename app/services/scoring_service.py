"""Deterministic, transparent 0-100 lead scoring. Pure functions: no DB, no LLM, no network.

Design rules (see docs/ARCHITECTURE.md):
* Missing information is `unknown` and earns 0 points - it is never rewarded, and never treated as a "no".
* `not_matched` means we HAVE data and it does not fit.
* Disqualification requires explicit data that violates a rule (never absence of data).
* The LLM can never change this score.
"""

import re
from dataclasses import dataclass, field

from app.models.enums import Consent, CriterionStatus, Priority, Timeline
from app.services.icp_config import CRITERIA, CRITERIA_LABELS, ENGINE_VERSION, LEAD_FIELDS, ICPConfig
from app.services.normalization import normalize_country


@dataclass(frozen=True)
class LeadFacts:
    industry: str | None = None  # normalised
    company_size: int | None = None
    country: str | None = None  # normalised
    region: str | None = None
    job_title: str | None = None
    is_decision_maker: bool | None = None
    requirements: str | None = None
    budget_usd: float | None = None
    timeline: Timeline = Timeline.UNKNOWN
    website: str | None = None
    email: str | None = None
    consent: Consent = Consent.UNKNOWN
    has_verified_evidence: bool = False  # at least one evidence row from an authorised, URL-backed source

    @classmethod
    def from_lead(cls, lead, *, has_verified_evidence: bool = False) -> "LeadFacts":
        return cls(
            industry=lead.industry_normalized,
            company_size=lead.company_size,
            country=normalize_country(lead.country),
            region=(lead.region or None),
            job_title=lead.job_title,
            is_decision_maker=lead.is_decision_maker,
            requirements=lead.requirements,
            budget_usd=float(lead.budget_usd) if lead.budget_usd is not None else None,
            timeline=lead.timeline,
            website=lead.website,
            email=lead.email_normalized,
            consent=lead.consent,
            has_verified_evidence=has_verified_evidence,
        )


@dataclass
class CriterionResult:
    name: str
    label: str
    weight_pct: float
    status: CriterionStatus
    fraction: float
    points: float
    max_points: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "weight_pct": self.weight_pct,
            "status": self.status.value,
            "fraction": round(self.fraction, 4),
            "points": round(self.points, 2),
            "max_points": round(self.max_points, 2),
            "reason": self.reason,
        }


@dataclass
class ScoreResult:
    total: float
    priority: Priority
    criteria: list[CriterionResult]
    missing_information: list[str]
    disqualified: bool
    disqualification_reasons: list[str]
    meets_minimum: bool
    engine_version: str = ENGINE_VERSION
    matched_services: list[str] = field(default_factory=list)

    def breakdown(self) -> list[dict]:
        return [c.to_dict() for c in self.criteria]


def _kw_hits(text: str | None, keywords: list[str]) -> list[str]:
    if not text:
        return []
    low = text.lower()
    hits = []
    for kw in keywords:
        if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", low) and kw not in hits:
            hits.append(kw)
    return hits


def matched_services(facts: LeadFacts, icp: ICPConfig) -> list[str]:
    return [s.name for s in icp.services if _kw_hits(facts.requirements, s.keywords)]


def _result(name, weight, status, fraction, reason) -> CriterionResult:
    return CriterionResult(name, CRITERIA_LABELS[name], weight, status, fraction, weight * fraction, weight, reason)


def _industry(f: LeadFacts, icp: ICPConfig, w: float) -> CriterionResult:
    if not f.industry:
        return _result("industry_fit", w, CriterionStatus.UNKNOWN, 0, "Industry not provided")
    if not icp.target_industries:
        return _result("industry_fit", w, CriterionStatus.UNKNOWN, 0, "ICP has no target industries configured")
    if f.industry in icp.target_industries:
        return _result("industry_fit", w, CriterionStatus.MATCHED, 1, f"'{f.industry}' is a target industry")
    return _result("industry_fit", w, CriterionStatus.NOT_MATCHED, 0, f"'{f.industry}' is not in the target industries")


def _company(f: LeadFacts, icp: ICPConfig, w: float) -> CriterionResult:
    parts: list[tuple[float, str]] = []
    if f.company_size is not None and (icp.company_size_min is not None or icp.company_size_max is not None):
        lo = icp.company_size_min if icp.company_size_min is not None else 0
        hi = icp.company_size_max if icp.company_size_max is not None else 10**9
        if lo <= f.company_size <= hi:
            parts.append((1.0, f"size {f.company_size} within {lo}-{hi}"))
        elif (lo * 0.5) <= f.company_size <= (hi * 1.5):
            parts.append((0.5, f"size {f.company_size} near target range {lo}-{hi}"))
        else:
            parts.append((0.0, f"size {f.company_size} outside {lo}-{hi}"))
    if f.country and icp.target_countries:
        if f.country in icp.target_countries:
            parts.append((1.0, f"location '{f.country}' is targeted"))
        else:
            parts.append((0.0, f"location '{f.country}' is not targeted"))
    if not parts:
        return _result("company_fit", w, CriterionStatus.UNKNOWN, 0, "Company size and location not provided (or not configured)")
    frac = sum(p[0] for p in parts) / len(parts)
    status = CriterionStatus.MATCHED if frac == 1 else CriterionStatus.NOT_MATCHED if frac == 0 else CriterionStatus.PARTIAL
    return _result("company_fit", w, status, frac, "; ".join(p[1] for p in parts))


def _need(f: LeadFacts, icp: ICPConfig, w: float) -> CriterionResult:
    if not f.requirements:
        return _result("business_need", w, CriterionStatus.UNKNOWN, 0, "No business requirements provided")
    keywords = list(dict.fromkeys(icp.supported_problems + [k for s in icp.services for k in s.keywords]))
    hits = _kw_hits(f.requirements, keywords)
    if len(hits) >= 2:
        return _result("business_need", w, CriterionStatus.MATCHED, 1, f"Stated need matches supported problems: {', '.join(hits[:5])}")
    if len(hits) == 1:
        return _result("business_need", w, CriterionStatus.PARTIAL, 0.6, f"One supported problem mentioned: {hits[0]}")
    return _result("business_need", w, CriterionStatus.NOT_MATCHED, 0, "Stated requirements do not match any configured service or problem")


def _authority(f: LeadFacts, icp: ICPConfig, w: float) -> CriterionResult:
    title_hit = bool(f.job_title and any(t in f.job_title.lower() for t in icp.relevant_titles))
    if f.is_decision_maker is True:
        return _result("decision_maker", w, CriterionStatus.MATCHED, 1, "Contact is flagged as a decision-maker")
    if title_hit:
        return _result("decision_maker", w, CriterionStatus.MATCHED, 1, f"Job title '{f.job_title}' is a relevant decision-making role")
    if f.is_decision_maker is False:
        return _result("decision_maker", w, CriterionStatus.NOT_MATCHED, 0, "Contact is flagged as NOT a decision-maker")
    if f.job_title:
        return _result("decision_maker", w, CriterionStatus.PARTIAL, 0.3, f"Title '{f.job_title}' is not a known decision role (possible influencer)")
    return _result("decision_maker", w, CriterionStatus.UNKNOWN, 0, "Job title and decision role not provided")


def _budget(f: LeadFacts, icp: ICPConfig, w: float) -> CriterionResult:
    if f.budget_usd is None:
        return _result("budget_fit", w, CriterionStatus.UNKNOWN, 0, "Budget not provided")
    floor = icp.min_budget_usd
    if floor is None:
        return _result("budget_fit", w, CriterionStatus.UNKNOWN, 0, "ICP has no minimum budget configured")
    if f.budget_usd >= floor:
        return _result("budget_fit", w, CriterionStatus.MATCHED, 1, f"Budget ${f.budget_usd:,.0f} >= ${floor:,.0f}")
    if f.budget_usd >= floor * 0.5:
        return _result("budget_fit", w, CriterionStatus.PARTIAL, 0.5, f"Budget ${f.budget_usd:,.0f} is 50-99% of ${floor:,.0f}")
    return _result("budget_fit", w, CriterionStatus.NOT_MATCHED, 0, f"Budget ${f.budget_usd:,.0f} is below 50% of ${floor:,.0f}")


_TIMELINE_FRACTION = {Timeline.IMMEDIATE: 1.0, Timeline.WITHIN_3_MONTHS: 1.0, Timeline.WITHIN_6_MONTHS: 0.6, Timeline.EXPLORING: 0.2}


def _timeline(f: LeadFacts, icp: ICPConfig, w: float) -> CriterionResult:
    if f.timeline == Timeline.UNKNOWN:
        return _result("timeline", w, CriterionStatus.UNKNOWN, 0, "Purchase timeline not provided")
    frac = _TIMELINE_FRACTION[f.timeline]
    status = CriterionStatus.MATCHED if frac == 1 else CriterionStatus.PARTIAL
    return _result("timeline", w, status, frac, f"Stated timeline: {f.timeline.value.replace('_', ' ')}")


def _evidence(f: LeadFacts, icp: ICPConfig, w: float) -> CriterionResult:
    present = {
        "industry": bool(f.industry),
        "company_size": f.company_size is not None,
        "country": bool(f.country),
        "job_title": bool(f.job_title),
        "requirements": bool(f.requirements),
        "budget_usd": f.budget_usd is not None,
        "timeline": f.timeline != Timeline.UNKNOWN,
        "website": bool(f.website),
        "email": bool(f.email),
    }
    known = sum(present.values())
    frac = (known / len(LEAD_FIELDS)) * 0.7 + (0.3 if f.has_verified_evidence else 0.0)
    if known == 0 and not f.has_verified_evidence:
        return _result("evidence_quality", w, CriterionStatus.UNKNOWN, 0, "No qualification fields provided")
    status = CriterionStatus.MATCHED if frac >= 0.85 else CriterionStatus.PARTIAL if frac > 0 else CriterionStatus.NOT_MATCHED
    ver = "with" if f.has_verified_evidence else "without"
    return _result("evidence_quality", w, status, min(frac, 1.0), f"{known}/{len(LEAD_FIELDS)} key fields provided, {ver} verified external evidence")


def _missing(f: LeadFacts, icp: ICPConfig, criteria: list[CriterionResult]) -> list[str]:
    missing = [f"{c.label}: {c.reason}" for c in criteria if c.status == CriterionStatus.UNKNOWN and c.name != "evidence_quality"]
    # required fields from the ICP always surface, even if the related criterion has zero weight
    present = {
        "requirements": bool(f.requirements),
        "job_title": bool(f.job_title),
        "industry": bool(f.industry),
        "company_size": f.company_size is not None,
        "country": bool(f.country),
        "budget_usd": f.budget_usd is not None,
        "timeline": f.timeline != Timeline.UNKNOWN,
        "website": bool(f.website),
        "email": bool(f.email),
    }
    for fld in icp.required_fields:
        msg = f"Required field missing: {fld}"
        if not present.get(fld) and msg not in missing:
            missing.append(msg)
    return missing


def _disqualification(f: LeadFacts, icp: ICPConfig) -> list[str]:
    d = icp.disqualification
    reasons: list[str] = []
    if d.disqualify_on_opt_out and f.consent == Consent.OPTED_OUT:
        reasons.append("Contact has opted out of communication")
    if f.industry and f.industry in d.excluded_industries:
        reasons.append(f"Industry '{f.industry}' is excluded")
    if f.country and f.country in d.excluded_countries:
        reasons.append(f"Country '{f.country}' is excluded")
    if d.hard_min_budget_usd is not None and f.budget_usd is not None and f.budget_usd < d.hard_min_budget_usd:
        reasons.append(f"Stated budget ${f.budget_usd:,.0f} is below the hard minimum ${d.hard_min_budget_usd:,.0f}")
    return reasons


def priority_for(score: float, icp: ICPConfig) -> Priority:
    if score >= icp.thresholds.high_min:
        return Priority.HIGH
    if score >= icp.thresholds.medium_min:
        return Priority.MEDIUM
    return Priority.LOW


def score_lead(facts: LeadFacts, icp: ICPConfig) -> ScoreResult:
    weights = icp.normalized_weights()
    fns = {
        "industry_fit": _industry,
        "company_fit": _company,
        "business_need": _need,
        "decision_maker": _authority,
        "budget_fit": _budget,
        "timeline": _timeline,
        "evidence_quality": _evidence,
    }
    criteria = [fns[name](facts, icp, weights[name]) for name in CRITERIA]
    total = round(min(100.0, max(0.0, sum(c.points for c in criteria))), 2)
    reasons = _disqualification(facts, icp)
    disq = bool(reasons)
    prio = Priority.LOW if disq else priority_for(total, icp)
    return ScoreResult(
        total=total,
        priority=prio,
        criteria=criteria,
        missing_information=_missing(facts, icp, criteria),
        disqualified=disq,
        disqualification_reasons=reasons,
        meets_minimum=(not disq and total >= icp.min_qualifying_score),
        matched_services=matched_services(facts, icp),
    )
