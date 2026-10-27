import pytest
from pydantic import ValidationError

from app.models.enums import Consent, CriterionStatus, Priority, Timeline
from app.services.icp_config import CRITERIA, ICPConfig, Thresholds, default_hvac_icp
from app.services.scoring_service import LeadFacts, priority_for, score_lead

ICP = default_hvac_icp()
FULL = LeadFacts(
    industry="hvac",
    company_size=25,
    country="United States",
    job_title="Owner",
    requirements="We miss calls after hours and need follow-up automation",
    budget_usd=5000,
    timeline=Timeline.WITHIN_3_MONTHS,
    website="https://x.com",
    email="a@x.com",
)


def by_name(result, name):
    return next(c for c in result.criteria if c.name == name)


def test_strong_lead_is_high_priority_and_deterministic():
    a, b = score_lead(FULL, ICP), score_lead(FULL, ICP)
    assert a.total == b.total >= 80 and a.priority == Priority.HIGH
    assert a.breakdown() == b.breakdown()


def test_breakdown_points_sum_to_total_and_max_is_100():
    r = score_lead(FULL, ICP)
    assert round(sum(c.points for c in r.criteria), 2) == r.total
    assert round(sum(c.max_points for c in r.criteria), 2) == 100.0
    assert [c.name for c in r.criteria] == CRITERIA


def test_empty_lead_scores_zero_and_everything_is_unknown_not_negative():
    r = score_lead(LeadFacts(), ICP)
    assert r.total == 0
    assert all(c.status == CriterionStatus.UNKNOWN for c in r.criteria)
    assert not r.disqualified and len(r.missing_information) >= 6


def test_missing_budget_is_unknown_but_low_budget_is_not_matched():
    assert by_name(score_lead(LeadFacts(), ICP), "budget_fit").status == CriterionStatus.UNKNOWN
    low = score_lead(LeadFacts(budget_usd=500), ICP)
    assert by_name(low, "budget_fit").status == CriterionStatus.NOT_MATCHED


def test_absence_of_data_never_earns_points():
    sparse = score_lead(LeadFacts(industry="hvac"), ICP)
    others = [c for c in sparse.criteria if c.name not in ("industry_fit", "evidence_quality")]
    assert all(c.points == 0 and c.status == CriterionStatus.UNKNOWN for c in others)
    assert by_name(sparse, "evidence_quality").fraction < 0.1  # one known field out of nine


@pytest.mark.parametrize(
    "score,prio", [(80, Priority.HIGH), (79.99, Priority.MEDIUM), (50, Priority.MEDIUM), (49.99, Priority.LOW), (0, Priority.LOW)]
)
def test_threshold_boundaries(score, prio):
    assert priority_for(score, ICP) == prio


def test_weights_are_normalised_so_any_positive_scale_works():
    cfg = default_hvac_icp().model_copy(update={"weights": {k: 1 for k in CRITERIA}})
    r = score_lead(FULL, cfg)
    assert round(sum(c.max_points for c in r.criteria), 2) == 100.0


def test_invalid_weights_rejected():
    base = default_hvac_icp().model_dump()
    with pytest.raises(ValidationError):
        ICPConfig(**{**base, "weights": {"industry_fit": 1}})
    with pytest.raises(ValidationError):
        ICPConfig(**{**base, "weights": {k: 0 for k in CRITERIA}})
    with pytest.raises(ValidationError):
        ICPConfig(**{**base, "weights": {**{k: 1 for k in CRITERIA}, "bogus": 1}})
    with pytest.raises(ValidationError):
        Thresholds(high_min=50, medium_min=60)
    with pytest.raises(ValidationError):
        ICPConfig(**{**base, "required_fields": ["nonsense"]})


def test_disqualification_requires_explicit_data():
    assert not score_lead(LeadFacts(), ICP).disqualified
    opted = score_lead(LeadFacts(consent=Consent.OPTED_OUT), ICP)
    assert opted.disqualified and opted.priority == Priority.LOW
    tiny = score_lead(LeadFacts(budget_usd=100), ICP)
    assert tiny.disqualified and "hard minimum" in tiny.disqualification_reasons[0]
    assert not score_lead(LeadFacts(budget_usd=None), ICP).disqualified


def test_excluded_industry_and_country():
    cfg = default_hvac_icp()
    cfg.disqualification.excluded_industries = ["retail"]
    cfg.disqualification.excluded_countries = ["Canada"]
    assert score_lead(LeadFacts(industry="retail"), cfg).disqualified
    assert score_lead(LeadFacts(country="Canada"), cfg).disqualified


def test_decision_maker_flag_false_vs_unknown_title():
    assert by_name(score_lead(LeadFacts(is_decision_maker=False), ICP), "decision_maker").status == CriterionStatus.NOT_MATCHED
    assert by_name(score_lead(LeadFacts(job_title="Technician"), ICP), "decision_maker").status == CriterionStatus.PARTIAL
    assert by_name(score_lead(LeadFacts(job_title="Founder"), ICP), "decision_maker").status == CriterionStatus.MATCHED


def test_need_matching_uses_word_boundaries():
    r = score_lead(LeadFacts(requirements="our leadership is great"), ICP)
    assert by_name(r, "business_need").status == CriterionStatus.NOT_MATCHED


def test_required_fields_listed_as_missing():
    r = score_lead(LeadFacts(industry="hvac"), ICP)
    assert any("requirements" in m for m in r.missing_information) and any("job_title" in m for m in r.missing_information)


def test_verified_evidence_raises_evidence_quality_only():
    base = score_lead(FULL, ICP)
    from dataclasses import replace

    verified = score_lead(replace(FULL, has_verified_evidence=True), ICP)
    assert verified.total > base.total
    assert [c.points for c in verified.criteria if c.name != "evidence_quality"] == [c.points for c in base.criteria if c.name != "evidence_quality"]
