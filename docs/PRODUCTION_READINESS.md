# Production readiness review (honest)

**Classification: Production Candidate.** **Score: 6.5 / 10.**

| Area | Status | Evidence / gap |
|---|---|---|
| Architecture | Good | layered, documented, ADR table |
| Correctness | Good | 117 automated tests passed locally (`pytest`), ruff clean |
| Security | Solid foundations, not audited | see SECURITY.md gaps (no MFA, no TLS in-app, no pen-test, no `pip-audit`) |
| Testing | Good backend, **no browser/UI tests**, no load tests, Postgres not exercised by tests (SQLite only) |
| Real integrations | **Unverified** | Gemini + Brave tested with mocks only; first live call may need small fixes (model name, quotas) |
| Scalability | Limited | BackgroundTasks, per-process limiter, no queue; fine for a small team |
| Observability | Basic | JSON logs + ids + health; no metrics/tracing yet (add Prometheus/OpenTelemetry) |
| Deployment | Provided, untested here | Dockerfile/compose written but **not built or run** in this environment |
| Compliance | Not assessed | GDPR/CAN-SPAM/consent policy requires legal review |

## Definition-of-done check
| Item | Verified how |
|---|---|
| Starts with documented commands | ran `alembic upgrade head`, `create_admin`, `seed_demo`, `uvicorn` and exercised login → qualify → approve → draft over HTTP |
| Migrations on fresh DB (+downgrade) | ran up/down/up on SQLite; Postgres **not** tested |
| Auth & RBAC enforced | tests |
| Create/import leads, validation, dedupe | tests |
| ICP + scoring configurable, deterministic | tests |
| BANT unknown vs confirmed | tests |
| Gemini structured output | **mock only** |
| LangGraph paths | tests (success, invalid, missing data, LLM timeout/malformed, research failure, duplicate run, reject, revision, resume twice) |
| Human approval blocks side effects | tests |
| Dashboard shows backend data | server serves it; **not browser-tested** |
| Secrets not committed | `.gitignore`, `.env.example` placeholders |

## Next steps (priority order)
1. Run against real Gemini with a few synthetic leads; adjust model name/prompt; add an optional live-integration test (skipped without a key).
2. Build & run the Docker stack on a clean machine; test migrations on PostgreSQL.
3. Add Playwright UI smoke tests.
4. Move background work to a queue; add Redis rate limiting.
5. Add `pip-audit`, metrics, and a data-retention job.
