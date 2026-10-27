import io

from tests.conftest import GOOD_LEAD, PASSWORD, login, make_lead

API = "/api/v1"


def test_health_and_ready_leak_nothing(client):
    assert client.get(f"{API}/health").json() == {"status": "ok"}
    body = client.get(f"{API}/ready").json()
    assert body["status"] == "ready" and "test-key" not in str(body) and "sqlite" not in str(body)


def test_login_success_and_me(client):
    r = client.post(f"{API}/auth/login", json={"email": "sales@example.com", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["role"] == "sales"
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["email"] == "sales@example.com" and "password" not in me.text


def test_login_failure_is_generic_and_rate_limited(client):
    for _ in range(5):
        r = client.post(f"{API}/auth/login", json={"email": "sales@example.com", "password": "wrong-password"})
        assert r.status_code == 401 and r.json()["error"]["message"] == "Invalid email or password"
    assert client.post(f"{API}/auth/login", json={"email": "sales@example.com", "password": PASSWORD}).status_code == 429


def test_unknown_user_same_error_as_wrong_password(client):
    r = client.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"})
    assert r.status_code == 401 and r.json()["error"]["message"] == "Invalid email or password"


def test_protected_routes_require_token(client):
    for method, path in [("get", "/leads"), ("post", "/leads"), ("get", "/dashboard/stats"), ("get", "/icp"), ("get", "/approvals")]:
        assert getattr(client, method)(f"{API}{path}").status_code == 401
    assert client.get(f"{API}/leads", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_error_envelope_has_request_id(client):
    r = client.get(f"{API}/leads", headers={"X-Request-ID": "abc123"})
    assert r.status_code == 401 and r.json()["error"]["request_id"] == "abc123" and r.headers["X-Request-ID"] == "abc123"


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_lead_crud_and_normalisation(client, sales):
    lead = make_lead(client, sales)
    assert lead["country"] == "United States" and lead["website"] == "https://whitfield-air.example.com"
    got = client.get(f"{API}/leads/{lead['id']}", headers=sales).json()
    assert got["source_name"] == "Website form"
    r = client.patch(f"{API}/leads/{lead['id']}", json={"job_title": "General Manager", "budget_usd": 7000}, headers=sales)
    assert r.status_code == 200 and r.json()["job_title"] == "General Manager" and float(r.json()["budget_usd"]) == 7000
    assert client.patch(f"{API}/leads/{lead['id']}", json={}, headers=sales).status_code == 422


def test_validation_errors_are_actionable(client, sales):
    r = client.post(
        f"{API}/leads", json={"first_name": "", "company_name": "X", "email": "bad", "website": "ftp://x.com", "budget_usd": -1}, headers=sales
    )
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"first_name", "email", "website", "budget_usd"} <= fields


def test_duplicate_email_conflict(client, sales):
    make_lead(client, sales)
    r = client.post(f"{API}/leads", json={**GOOD_LEAD, "first_name": "Other", "email": "DANA@whitfield-air.example.com"}, headers=sales)
    assert r.status_code == 409 and "existing_lead_id" in r.json()["error"]["details"]


def test_possible_duplicate_reported_not_blocked(client, sales):
    make_lead(client, sales)
    r = client.post(f"{API}/leads", json={**GOOD_LEAD, "email": "dana2@whitfield-air.example.com"}, headers=sales)
    assert r.status_code == 201 and r.json()["possible_duplicates"]


def test_merge_fills_empty_never_overwrites_and_audits(client, sales, container):
    a = make_lead(client, sales, email=None, job_title=None, requirements="primary text")
    b = make_lead(client, sales, email="b@whitfield-air.example.com", job_title="Owner", requirements="different text")
    merged = client.post(f"{API}/leads/{a['id']}/merge", json={"duplicate_id": b["id"]}, headers=sales).json()
    assert merged["job_title"] == "Owner" and merged["email"] == "b@whitfield-air.example.com" and merged["requirements"] == "primary text"
    assert client.get(f"{API}/leads/{b['id']}", headers=sales).json()["status"] == "archived"
    from sqlalchemy import select
    from app.models import AuditEvent

    with container.session_factory() as s:
        ev = s.scalar(select(AuditEvent).where(AuditEvent.action == "lead.merge"))
        assert "requirements" in ev.details["conflicts"]
    assert client.post(f"{API}/leads/{a['id']}/merge", json={"duplicate_id": a["id"]}, headers=sales).status_code == 422


def test_archive_restore_and_filtering_pagination(client, sales):
    ids = [make_lead(client, sales, email=f"l{i}@e.example.com", first_name=f"N{i}", company_name=f"Co{i}")["id"] for i in range(5)]
    r = client.get(f"{API}/leads?page=1&page_size=2&sort=company_name&order=asc", headers=sales).json()
    assert r["total"] == 5 and len(r["items"]) == 2 and r["items"][0]["company_name"] == "Co0"
    client.post(f"{API}/leads/{ids[0]}/archive", headers=sales)
    assert client.get(f"{API}/leads", headers=sales).json()["total"] == 4
    assert client.get(f"{API}/leads?include_archived=true", headers=sales).json()["total"] == 5
    assert client.get(f"{API}/leads?q=co3", headers=sales).json()["total"] == 1
    assert client.post(f"{API}/leads/{ids[0]}/restore", headers=sales).json()["status"] == "new"
    assert client.get(f"{API}/leads?page_size=1000", headers=sales).status_code == 422
    assert client.get(f"{API}/leads?sort=password", headers=sales).status_code == 422


def test_score_endpoint_deterministic_and_historical(client, sales):
    lead = make_lead(client, sales)
    e1 = client.post(f"{API}/leads/{lead['id']}/score", headers=sales).json()
    e2 = client.post(f"{API}/leads/{lead['id']}/score", headers=sales).json()
    assert e1["total_score"] == e2["total_score"] >= 80 and e1["id"] != e2["id"]
    assert e1["engine_version"] == "scoring-v1" and e1["icp_version"] == 1 and len(e1["breakdown"]) == 7
    assert len(e1["bant"]) == 4 and e1["ai_status"] == "not_run"
    assert len(client.get(f"{API}/leads/{lead['id']}/evaluations", headers=sales).json()) == 2


def test_icp_versioning_and_recalculation_preserve_history(client, sales, admin):
    lead = make_lead(client, sales)
    first = client.post(f"{API}/leads/{lead['id']}/score", headers=sales).json()
    cfg = client.get(f"{API}/icp", headers=sales).json()["config"]
    cfg["target_industries"] = ["plumbing"]
    assert client.put(f"{API}/icp", json={"config": cfg}, headers=sales).status_code == 403
    v2 = client.put(f"{API}/icp", json={"config": cfg}, headers=admin).json()
    assert v2["version"] == 2 and v2["is_active"]
    assert client.post(f"{API}/icp/recalculate", headers=admin).json() == {"icp_version": 2, "recalculated": 1}
    hist = client.get(f"{API}/leads/{lead['id']}/evaluations", headers=sales).json()
    assert len(hist) == 2 and hist[0]["icp_version"] == 2 and hist[1]["icp_version"] == 1
    assert hist[0]["total_score"] < first["total_score"] and hist[1]["total_score"] == first["total_score"]
    bad = {**cfg, "weights": {"industry_fit": 1}}
    assert client.put(f"{API}/icp", json={"config": bad}, headers=admin).status_code == 422


def test_csv_template_and_import_happy_path(client, sales):
    tpl = client.get(f"{API}/leads/import/template", headers=sales)
    assert tpl.status_code == 200 and tpl.text.startswith("first_name,")
    r = client.post(f"{API}/leads/import", files={"file": ("leads.csv", tpl.content, "text/csv")}, headers=sales)
    assert r.status_code == 200 and r.json()["created"] == 1 and r.json()["rejected"] == 0
    again = client.post(f"{API}/leads/import", files={"file": ("leads.csv", tpl.content, "text/csv")}, headers=sales).json()
    assert again["created"] == 0 and again["skipped_duplicates"] == 1


CSV = """first_name,last_name,company_name,email,company_size,budget_usd,timeline,extra
Ann,Lee,Acme HVAC,ann@acme.example.com,10,5k,within 3 months,x
,Nobody,NoFirst,nofirst@acme.example.com,5,100,immediate,x
Bob,Ray,Bob Co,not-an-email,5,100,immediate,x
Cy,Fox,Fox Co,cy@fox.example.com,abc,100,immediate,x
Di,Poe,Poe Co,di@poe.example.com,5,lots,immediate,x
Ed,Roe,Roe Co,ann@acme.example.com,5,100,immediate,x
Fay,Zed,=HYPERLINK("http://evil"),fay@zed.example.com,5,100,immediate,x
"""


def test_csv_import_reports_row_errors_and_neutralises_formulas(client, sales):
    r = client.post(f"{API}/leads/import", files={"file": ("l.csv", CSV.encode(), "text/csv")}, headers=sales).json()
    assert r["created"] == 2 and r["skipped_duplicates"] == 1 and r["rejected"] == 4 and r["ignored_columns"] == ["extra"]
    assert {e["row"] for e in r["errors"]} == {3, 4, 5, 6}
    assert "row,errors" in r["error_report_csv"]
    assert not any(line.startswith("=") for line in r["error_report_csv"].splitlines())
    leads = client.get(f"{API}/leads?q=hyperlink", headers=sales).json()["items"]
    assert leads and leads[0]["company_name"].startswith("=HYPERLINK")  # stored inert; UI renders via textContent


def test_csv_rejects_bad_files(client, sales):
    post = lambda name, data: client.post(f"{API}/leads/import", files={"file": (name, data, "text/csv")}, headers=sales)  # noqa: E731
    assert post("x.xlsx", b"a,b").status_code == 422
    assert post("x.csv", b"foo,bar\n1,2\n").status_code == 422
    assert post("x.csv", b"first_name,company_name\n\x00\x01").status_code == 422
    assert post("x.csv", b"\xff\xfe\x00bad").status_code == 422
    big = b"first_name,company_name\n" + b"a,b\n" * 600_000
    assert post("x.csv", big).status_code == 422


def test_dashboard_and_reports_shape(client, sales):
    make_lead(client, sales)
    s = client.get(f"{API}/dashboard/stats", headers=sales).json()
    assert s["total_leads"] == 1 and {"qualified_leads", "high_priority_leads", "awaiting_review", "follow_ups_due", "recent_activity"} <= set(s)
    rep = client.get(f"{API}/dashboard/reports", headers=sales).json()
    assert "NOT conversion rates" in rep["note"] and rep["lead_sources"] == {"Website form": 1}


def test_drafts_template_fallback_is_evidence_safe(client, sales):
    lead = make_lead(client, sales, requirements=None)
    d = client.post(f"{API}/leads/{lead['id']}/drafts", json={"draft_type": "introduction"}, headers=sales).json()
    assert "You mentioned" not in d["body"] and d["evidence_references"] == []


def test_draft_lifecycle_and_opt_out_block(client, sales):
    lead = make_lead(client, sales)
    d = client.post(f"{API}/leads/{lead['id']}/drafts", json={"draft_type": "follow_up"}, headers=sales).json()
    assert d["status"] == "draft"
    e = client.patch(f"{API}/drafts/{d['id']}", json={"body": "Edited body text here.", "follow_up_date": "2030-01-01"}, headers=sales).json()
    assert e["generated_by"] == "human" and e["follow_up_date"] == "2030-01-01"
    sent = client.post(f"{API}/drafts/{d['id']}/mark-sent", headers=sales).json()
    assert sent["status"] == "sent_manually" and sent["sent_manually_at"]
    assert client.patch(f"{API}/drafts/{d['id']}", json={"body": "later edit text"}, headers=sales).status_code == 409
    out = make_lead(client, sales, email="o@x.example.com", first_name="Opt", consent="opted_out")
    assert client.post(f"{API}/leads/{out['id']}/drafts", json={"draft_type": "introduction"}, headers=sales).status_code == 422


def test_login_helper_roles(client):
    assert login(client, "admin") and login(client, "reviewer")
    _ = io
