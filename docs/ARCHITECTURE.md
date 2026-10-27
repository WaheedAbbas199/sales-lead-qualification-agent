# Architecture

## 1. Problem & MVP
Sales teams waste time on poor-fit leads and cannot explain why a lead is "hot". This app gives every lead a reproducible,
explainable score + BANT picture, adds an AI *proposal* layer, and forces a human decision before consequential actions.

**MVP (built):** lead intake, normalisation/dedup, versioned ICP, deterministic scoring, BANT, Gemini proposal, LangGraph workflow,
approval queue, draft outreach, dashboard, audit trail, tests, Docker.
**Later:** email sending (with suppression list + idempotency), CRM sync, queue/worker, multi-tenancy, SSO, embeddings (only if measured value).

## 2. System diagram
```mermaid
flowchart LR
  B[Browser SPA<br/>vanilla JS] -->|HTTPS + Bearer JWT| API[FastAPI /api/v1]
  API --> SVC[Services<br/>lead · scoring · bant · icp · approval · outreach]
  SVC --> REPO[Repositories] --> DB[(PostgreSQL / SQLite)]
  API -->|queue job| RUN[WorkflowRunner]
  RUN --> G[LangGraph graph]
  G --> SVC
  G -->|proposal only| LLM[Gemini adapter]
  G -->|search API only| RS[Brave adapter]
  REV[Reviewer] -->|decision| API
```

## 3. Data flow (qualification)
`POST /leads/{id}/qualify` → execution row `queued` (partial unique index = max one active per lead) → background run →
nodes persist state/trace after every step → **`human_review` creates a pending Approval and parks the run** →
reviewer `POST /approvals/{id}/decision` (atomic compare-and-set) → `resume()` re-enters the graph at `check_approval`
which **re-reads the decision from the DB** → `finalize_*` → approval-gated draft tool → END.

## 4. LangGraph design
State (`app/agents/state.py`) holds ids and small facts only; ORM objects live in a per-run scratch dict.
```mermaid
flowchart TD
  S((START)) -->|new run| load_lead --> validate_lead --> normalize_lead --> check_duplicates --> load_icp_profile
  load_icp_profile --> collect_authorized_research --> assess_bant --> calculate_lead_score --> ai_analysis
  ai_analysis --> validate_result --> save_evaluation --> human_review --> E1((END: awaiting approval))
  S -->|resume| check_approval
  check_approval -->|approved| finalize_approved --> prepare_outreach_draft --> E2((END))
  check_approval -->|rejected| finalize_rejected --> E2
  check_approval -->|revision| finalize_revision --> E2
  check_approval -->|pending| pending_guard --> E2
  validate_lead -. error .-> fail
  ai_analysis -. "LLM errors do NOT fail the run" .-> validate_result
```
* Deterministic nodes (validate, normalise, dedupe, BANT, score) are plain Python. Only `ai_analysis` calls an LLM.
* Bounded: step budget (30), `recursion_limit`, LLM retries ≤ `LLM_MAX_RETRIES`, timeouts on every external call.
* Failure → `fail` node closes the execution and returns the lead to `new`. Stale `running` rows are recovered at startup.
* Why not LangGraph `interrupt`/checkpointer? Persisting our own `WorkflowExecution.state` keeps one storage engine (SQLite or Postgres),
  makes the pause visible/queryable in SQL, and lets approval be a *separate authenticated HTTP action*.

## 5. Entities
```mermaid
erDiagram
  USER ||--o{ AUDIT_EVENT : acts
  LEAD_SOURCE ||--o{ LEAD : provides
  LEAD ||--o{ EVALUATION : has
  ICP_PROFILE ||--o{ EVALUATION : "version used"
  EVALUATION ||--o{ BANT_ASSESSMENT : contains
  EVALUATION ||--o{ EVIDENCE : cites
  LEAD ||--o{ WORKFLOW_EXECUTION : runs
  WORKFLOW_EXECUTION ||--|| APPROVAL : needs
  EVALUATION ||--o{ APPROVAL : "bound by hash"
  LEAD ||--o{ OUTREACH_DRAFT : has
  LEAD ||--o{ ACTIVITY : logs
```
Evaluations are **immutable**; recalculation adds rows. ICP edits create a **new version** (old rows untouched).
Each approval stores the evaluation `payload_hash`; if the result changes after review was requested, the decision fails closed.

## 6. Scoring rules (engine `scoring-v1`)
| Criterion | Full | Partial | Not matched | Unknown (0 pts) |
|---|---|---|---|---|
| Industry | in target list | – | other industry | blank |
| Company | size in range *and* location targeted | near range (±50%) / one of two | outside | both blank |
| Need | ≥2 keyword hits | 1 hit (0.6) | text but no hit | no text |
| Decision maker | flag=yes or relevant title | unknown title (0.3) | flag=no | none |
| Budget | ≥ minimum | 50–99% (0.5) | <50% | blank |
| Timeline | immediate / ≤3 mo | 6 mo (0.6), exploring (0.2) | – | blank |
| Evidence quality | ≥85% | scaled | – | no fields |

Weights are normalised to 100. Disqualification needs **explicit** data (opt-out, excluded industry/country, budget below hard minimum).
Defaults 80/50 are configurable starting points, **not** benchmarks and **not** conversion probabilities.

## 7. API (all under `/api/v1`)
`GET /health` · `GET /ready` · `POST /auth/login|logout` · `GET /auth/me` · `GET|POST /users` (admin) ·
`GET|POST /leads` · `GET|PATCH /leads/{id}` · `GET /leads/{id}/detail` · `POST /leads/{id}/archive|restore|merge` ·
`POST /leads/import` · `GET /leads/import/template` · `POST /leads/{id}/score` · `GET /leads/{id}/evaluations` ·
`POST /leads/{id}/qualify` (202) · `GET /workflows/{id}` · `GET /leads/{id}/workflows` ·
`GET /approvals` · `POST /approvals/{id}/decision` · `GET|PUT /icp` · `GET /icp/versions|criteria` · `POST /icp/recalculate` ·
`POST /leads/{id}/drafts` · `GET /drafts` · `PATCH /drafts/{id}` · `POST /drafts/{id}/mark-sent` ·
`GET /dashboard/stats|reports`. Errors use one envelope: `{"error":{"code","message","details","request_id"}}`.

## 8. Folder structure
```
app/ api/ (dependencies, v1/endpoints)  core/ (config, security, logging, exceptions)  db/  models/  schemas/
     repositories/  services/ (pure domain logic + orchestration)  agents/ (state, graph, nodes, prompts, tools)
     integrations/ (gemini, web_search)  workers/ (runner)  static/ (css, js, pages)
alembic/  tests/ (unit, api, integration, security, workflows)  scripts/  docs/  data/
```
Not created because not implemented: `integrations/email`, `integrations/crm` (no empty placeholders by design).

## 9. Decisions (ADR summary)
| Decision | Why | Trade-off |
|---|---|---|
| Deterministic scoring, LLM proposes | explainable, reproducible, injection cannot move the score | less "magic" |
| Own persisted state instead of LangGraph checkpointer | single DB, SQL-visible pause | manual resume code |
| Partial unique index per lead | race-safe duplicate protection in the DB | needs index support (SQLite/Postgres both OK) |
| Bearer JWT, role read from DB each request | revocation/demotion immediate | one DB read per request |
| Draft-only outreach | no legal/deliverability risk in v1 | manual send |
| BackgroundTasks | zero infra | not durable; see limitations |
