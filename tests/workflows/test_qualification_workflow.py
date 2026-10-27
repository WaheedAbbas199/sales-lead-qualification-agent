import pytest
from sqlalchemy import select

from app.agents.tools.registry import Tier, ToolRegistry
from app.core.exceptions import PermissionDenied
from app.models import Approval, AuditEvent, Evaluation, Lead, OutreachDraft, WorkflowExecution
from app.models.enums import ApprovalStatus, LeadStatus, WorkflowStatus
from tests.conftest import FakeLLM, FakeResearch, make_lead

API = "/api/v1"


def qualify(client, headers, lead_id):
    return client.post(f"{API}/leads/{lead_id}/qualify", headers=headers)


def pending(client, headers):
    return client.get(f"{API}/approvals?status=pending", headers=headers).json()


def decide(client, headers, approval_id, decision, comment=None):
    return client.post(f"{API}/approvals/{approval_id}/decision", json={"decision": decision, "comment": comment}, headers=headers)


def drafts_for(container, lead_id):
    with container.session_factory() as s:
        return list(s.scalars(select(OutreachDraft).where(OutreachDraft.lead_id == lead_id)))


def test_success_path_stops_at_human_review_with_no_side_effects(client, sales, container):
    lead = make_lead(client, sales)
    r = qualify(client, sales, lead["id"])
    assert r.status_code == 202 and r.json()["status"] == "awaiting_approval"
    assert [t["node"] for t in r.json()["trace"]] == [
        "load_lead",
        "validate_lead",
        "normalize_lead",
        "check_duplicates",
        "load_icp_profile",
        "collect_authorized_research",
        "assess_bant",
        "calculate_lead_score",
        "ai_analysis",
        "validate_result",
        "save_evaluation",
        "human_review",
    ]
    cur = client.get(f"{API}/leads/{lead['id']}", headers=sales).json()
    assert cur["status"] == "pending_review" and cur["latest_score"] >= 80
    assert drafts_for(container, lead["id"]) == []  # nothing consequential happened before approval
    assert len(pending(client, sales)) == 1


def test_approval_resumes_and_creates_gated_draft(client, sales, reviewer, container):
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    ap = pending(client, reviewer)[0]
    r = decide(client, reviewer, ap["id"], "approved")
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["reviewer_id"] and r.json()["decided_at"]
    assert client.get(f"{API}/leads/{lead['id']}", headers=sales).json()["status"] == "qualified"
    drafts = drafts_for(container, lead["id"])
    assert len(drafts) == 1 and drafts[0].draft_type.value == "discovery_meeting"
    wf = client.get(f"{API}/leads/{lead['id']}/workflows", headers=sales).json()[0]
    assert wf["status"] == "completed" and wf["trace"][-1]["node"] == "prepare_outreach_draft"


def test_llm_draft_references_must_be_grounded(client, sales, reviewer, container):
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    decide(client, reviewer, pending(client, reviewer)[0]["id"], "approved")
    d = drafts_for(container, lead["id"])[0]
    assert d.generated_by == "llm" and d.evidence_references == []  # fake LLM cited a phrase the lead never wrote


def test_reject_and_revision_paths(client, sales, reviewer, container):
    a, b = make_lead(client, sales), make_lead(client, sales, email="b@x.example.com", first_name="Bee", company_name="Bee Co")
    qualify(client, sales, a["id"])
    qualify(client, sales, b["id"])
    aps = {p["lead_id"]: p for p in pending(client, reviewer)}
    assert decide(client, reviewer, aps[a["id"]]["id"], "rejected").status_code == 422  # comment required
    assert decide(client, reviewer, aps[a["id"]]["id"], "rejected", "Not a fit").status_code == 200
    assert decide(client, reviewer, aps[b["id"]]["id"], "revision_requested", "Need budget").status_code == 200
    assert client.get(f"{API}/leads/{a['id']}", headers=sales).json()["status"] == "new"
    assert client.get(f"{API}/leads/{b['id']}", headers=sales).json()["status"] == "needs_revision"
    assert drafts_for(container, a["id"]) == [] and drafts_for(container, b["id"]) == []
    assert qualify(client, sales, a["id"]).status_code == 202  # can be re-run after a decision


def test_sales_cannot_approve_and_double_decision_conflicts(client, sales, reviewer):
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    ap = pending(client, sales)[0]
    assert decide(client, sales, ap["id"], "approved").status_code == 403
    assert decide(client, reviewer, ap["id"], "approved").status_code == 200
    assert decide(client, reviewer, ap["id"], "rejected", "changed my mind").status_code == 409


def test_unauthenticated_cannot_decide(client, sales):
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    assert client.post(f"{API}/approvals/{pending(client, sales)[0]['id']}/decision", json={"decision": "approved"}).status_code == 401


def test_duplicate_execution_is_rejected_then_allowed_after_completion(client, sales, reviewer):
    lead = make_lead(client, sales)
    assert qualify(client, sales, lead["id"]).status_code == 202
    again = qualify(client, sales, lead["id"])
    assert again.status_code == 409 and "workflow_id" in again.json()["error"]["details"]
    decide(client, reviewer, pending(client, reviewer)[0]["id"], "approved")
    assert qualify(client, sales, lead["id"]).status_code == 202


def test_db_unique_index_blocks_two_active_executions(container, client, sales):
    lead = make_lead(client, sales)
    with container.session_factory() as s:
        s.add(WorkflowExecution(lead_id=lead["id"], status=WorkflowStatus.RUNNING, state={}, trace=[]))
        s.commit()
        s.add(WorkflowExecution(lead_id=lead["id"], status=WorkflowStatus.QUEUED, state={}, trace=[]))
        with pytest.raises(Exception):
            s.commit()


def test_resume_twice_is_a_noop(client, sales, reviewer, container):
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    decide(client, reviewer, pending(client, reviewer)[0]["id"], "approved")
    wf_id = client.get(f"{API}/leads/{lead['id']}/workflows", headers=sales).json()[0]["id"]
    assert container.runner.resume(wf_id) is False
    assert len(drafts_for(container, lead["id"])) == 1


def test_resume_while_pending_parks_without_side_effects(client, sales, container):
    lead = make_lead(client, sales)
    wf_id = qualify(client, sales, lead["id"]).json()["id"]
    assert container.runner.resume(wf_id) is True  # accidental resume before any decision
    with container.session_factory() as s:
        wf = s.get(WorkflowExecution, wf_id)
        assert wf.status == WorkflowStatus.AWAITING_APPROVAL and s.get(Lead, lead["id"]).status == LeadStatus.PENDING_REVIEW
    assert drafts_for(container, lead["id"]) == []


def test_tool_registry_fails_closed_without_approval(client, sales, container):
    lead = make_lead(client, sales)
    wf_id = qualify(client, sales, lead["id"]).json()["id"]
    with container.session_factory() as s:
        reg = ToolRegistry(s)
        reg.register("danger", Tier.EXTERNAL, lambda: "sent")
        with pytest.raises(PermissionDenied):
            reg.call("danger", workflow_id=wf_id)  # approval still pending
        with pytest.raises(PermissionDenied):
            reg.call("not_registered", workflow_id=wf_id)  # allow-list only
        approval = s.query(Approval).filter_by(workflow_id=wf_id).one()
        approval.status = ApprovalStatus.APPROVED  # approved but NO reviewer identity => still refused
        s.commit()
        with pytest.raises(PermissionDenied):
            reg.call("danger", workflow_id=wf_id)


def test_payload_tamper_after_review_request_fails_closed(client, sales, reviewer, container):
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    ap = pending(client, reviewer)[0]
    with container.session_factory() as s:
        s.get(Evaluation, ap["evaluation_id"]).payload_hash = "tampered"
        s.commit()
    assert decide(client, reviewer, ap["id"], "approved").status_code == 409


def test_invalid_lead_fails_cleanly(client, sales):
    lead = make_lead(client, sales, email=None, website=None, requirements=None)
    r = qualify(client, sales, lead["id"]).json()
    assert r["status"] == "failed" and "at least an email" in r["error"]
    assert client.get(f"{API}/leads/{lead['id']}", headers=sales).json()["status"] == "new"


def test_missing_data_lead_gets_low_score_and_missing_info(client, sales, reviewer):
    lead = make_lead(
        client,
        sales,
        industry=None,
        company_size=None,
        country=None,
        job_title=None,
        budget_usd=None,
        timeline="unknown",
        is_decision_maker=None,
        website=None,
    )
    qualify(client, sales, lead["id"])
    ap = pending(client, reviewer)[0]
    assert ap["score"] < 50 and ap["missing_information"]
    decide(client, reviewer, ap["id"], "approved")
    assert client.get(f"{API}/leads/{lead['id']}", headers=sales).json()["status"] == "nurture"


@pytest.mark.parametrize("mode,status", [("timeout", "unavailable"), ("malformed", "malformed")])
def test_llm_failures_degrade_gracefully(client, sales, llm, mode, status):
    llm.mode = mode
    lead = make_lead(client, sales)
    r = qualify(client, sales, lead["id"]).json()
    assert r["status"] == "awaiting_approval"  # deterministic score still produced, still needs a human
    ev = client.get(f"{API}/leads/{lead['id']}/detail", headers=sales).json()["evaluation"]
    assert ev["ai_status"] == status and ev["ai_report"] is None and ev["total_score"] >= 80 and ev["requires_human_review"]


def test_llm_not_configured_is_reported_honestly(client, sales, container):
    from app.integrations.gemini.client import DisabledLLM

    container.runner.llm = DisabledLLM()
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    ev = client.get(f"{API}/leads/{lead['id']}/detail", headers=sales).json()["evaluation"]
    assert ev["ai_status"] == "not_configured" and ev["ai_report"] is None


def test_hallucinated_evidence_is_dropped(client, sales, llm):
    llm.mode = "hallucinate"
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    ev = client.get(f"{API}/leads/{lead['id']}/detail", headers=sales).json()["evaluation"]
    texts = " ".join(e["statement"] for e in ev["evidence"])
    assert "500 employees" not in texts and "miss calls" in texts
    assert ev["ai_report"]["requires_human_review"] is True  # model said False; grounding failure forces review


def test_ai_cannot_change_score_or_priority(client, sales):
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    ev = client.get(f"{API}/leads/{lead['id']}/detail", headers=sales).json()["evaluation"]
    assert "score" not in str(ev["ai_report"].keys()) and ev["engine_version"] == "scoring-v1"
    det = client.post(f"{API}/leads/{lead['id']}/score", headers=sales).json()
    assert det["total_score"] == ev["total_score"]


def test_research_ok_stores_provenance_and_failure_never_fabricates(client, sales, container):
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    ev = client.get(f"{API}/leads/{lead['id']}/detail", headers=sales).json()["evaluation"]
    prov = {e["provenance"]: e for e in ev["evidence"]}
    assert prov["verified_source"]["source_url"].startswith("https://whitfield-air") and prov["verified_source"]["retrieved_at"]
    assert prov["search_snippet"]["statement"].startswith("Search snippet (not proof)")

    container.runner.research = FakeResearch("fail")
    other = make_lead(client, sales, email="o@x.example.com", first_name="Oh", company_name="Other Co")
    r = qualify(client, sales, other["id"]).json()
    assert r["status"] == "awaiting_approval"
    ev2 = client.get(f"{API}/leads/{other['id']}/detail", headers=sales).json()["evaluation"]
    assert not [e for e in ev2["evidence"] if e["provenance"] in ("verified_source", "search_snippet")]


def test_disabled_research_makes_no_calls(client, sales, research):
    from app.integrations.web_search.provider import DisabledResearch

    client.app.state.container.runner.research = DisabledResearch()
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    assert research.calls == 0
    ev = client.get(f"{API}/leads/{lead['id']}/detail", headers=sales).json()["evaluation"]
    assert ev["evidence"] == [] or all(e["provenance"] == "ai_inferred" for e in ev["evidence"])


def test_stale_execution_recovery(client, sales, container):
    from datetime import timedelta
    from app.db.base import utcnow

    lead = make_lead(client, sales)
    with container.session_factory() as s:
        wf = WorkflowExecution(lead_id=lead["id"], status=WorkflowStatus.RUNNING, state={}, trace=[])
        s.add(wf)
        s.get(Lead, lead["id"]).status = LeadStatus.QUALIFYING
        s.commit()
        wf.updated_at = utcnow() - timedelta(hours=2)
        s.commit()
    assert container.runner.recover_stale() == 1
    assert qualify(client, sales, lead["id"]).status_code == 202
    assert client.get(f"{API}/leads/{lead['id']}/workflows", headers=sales).json()[-1]["error_category"] == "interrupted"


def test_audit_trail_records_workflow_and_decision(client, sales, reviewer, container):
    lead = make_lead(client, sales)
    qualify(client, sales, lead["id"])
    decide(client, reviewer, pending(client, reviewer)[0]["id"], "approved")
    with container.session_factory() as s:
        actions = {a.action for a in s.scalars(select(AuditEvent))}
    assert {"workflow.started", "workflow.awaiting_approval", "approval.approved", "workflow.completed", "lead.create"} <= actions


def test_opted_out_lead_is_disqualified_after_approval_and_no_draft(client, sales, reviewer, container):
    lead = make_lead(client, sales, consent="opted_out")
    qualify(client, sales, lead["id"])
    ap = pending(client, reviewer)[0]
    decide(client, reviewer, ap["id"], "approved")
    assert client.get(f"{API}/leads/{lead['id']}", headers=sales).json()["status"] == "disqualified"
    assert drafts_for(container, lead["id"]) == []


def test_fake_llm_default_unused_import():
    assert FakeLLM().mode == "ok"
