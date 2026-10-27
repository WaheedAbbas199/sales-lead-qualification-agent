# Security model

## Trust boundaries
Browser (untrusted) → API (authN/Z enforced here, never in the UI) → DB (trusted, private network) →
Gemini / Brave (external, untrusted *outputs*) . Lead text, CSV cells, search snippets and LLM output are **untrusted data**.

## Controls implemented (and where tested)
| Threat | Control | Test |
|---|---|---|
| Prompt injection in lead/search text | random-delimited data blocks, system rules separate, no tools for the model, schema-validated output, injection heuristic → flag + audit + forced review, deterministic score | `tests/security` |
| Fabricated AI evidence | every quote must literally appear in supplied data, else dropped | `test_hallucinated_evidence_is_dropped` |
| Approval bypass | tool registry re-reads approval + reviewer id from DB; resume re-reads decision; atomic decision CAS; payload-hash binding; resume-while-pending parks | `tests/workflows` |
| Broken access control | role per route + service; role/active flag read from DB per request | `tests/security` |
| Brute force | per (ip,email) sliding window limiter, generic error, constant-time-ish unknown-user path | `test_login_failure…` |
| CSV attacks | `.csv` only, size/row caps, UTF-8, NUL check, never evaluated; error report neutralises `= + - @` | `test_csv_*` |
| XSS | no `innerHTML` anywhere; strict CSP (`script-src 'self'`, no inline) | `test_stored_xss…`, CSP header test |
| SQL injection | SQLAlchemy parameters, allow-listed sort columns | `test_sql_injection…` |
| Secret leakage | log redaction, audit detail filter, `/ready` exposes no hostnames/keys, 500s are generic | tests |
| SSRF | research uses one fixed provider host; lead URLs are never fetched | design |
| Weak config in prod | startup refuses default/short `SECRET_KEY` or `*` CORS | `test_production_rejects_weak_config` |

## Known gaps — do before real customer data
* No TLS in the app: terminate HTTPS at a reverse proxy (see DEPLOYMENT.md).
* No MFA/SSO, password reset or account lockout beyond the rate limit.
* Token in `sessionStorage` (see README). No refresh tokens; 60-minute expiry.
* Rate limiter and workflow runner are per-process.
* No dependency vulnerability scan in CI yet (`pip-audit` recommended).
* Personal data (names, emails) is stored in plaintext; define retention/deletion policy and DPIA/GDPR/CAN-SPAM review **with counsel**. This repo is not legal compliance.
