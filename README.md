# Pilot Light --- Sales Lead Qualification Agent

An AI-assisted sales lead qualification application designed to help
sales teams organize leads, assess fit, understand business needs, and
prepare better follow-ups.

> **Project status:** Built as a practical AI engineering project.
> Verify the feature checklist against the current code before
> describing every capability as production-ready. AI output is
> assistive and must not be treated as verified business fact without
> supporting evidence.

## Overview

Sales teams often spend too much time reviewing incoming leads,
searching for company context, deciding who to contact first, and
preparing follow-up messages. **Pilot Light** brings lead management and
qualification workflows into one application, combining a Python API,
relational database, dashboard, and optional AI-assisted research.

The project is configured to use **PostgreSQL** for persistent storage,
**Google Gemini** for AI-assisted tasks, and **Tavily** for web research
when the relevant credentials and settings are configured.

## Key capabilities

-   **Lead management:** Store and review lead and company information
    through the application.
-   **Qualification workflow:** Organize lead evaluations and workflow
    execution records.
-   **Scoring and prioritization:** Help users identify leads that may
    deserve attention first. Scores are guidance, not calibrated
    probabilities of conversion.
-   **BANT and evidence-oriented assessment:** Support qualification
    around Budget, Authority, Need, and Timeline while distinguishing
    known information from gaps.
-   **AI-assisted analysis:** Gemini can support language-based analysis
    when configured. AI output should be reviewed and validated.
-   **Optional web research:** Tavily can be used as a configured search
    provider. Search results are evidence to inspect, not automatic
    proof that a claim is true.
-   **Human review:** The data model includes approval records to
    support review before consequential actions.
-   **Outreach drafts:** Prepare sales outreach drafts for a human to
    review and edit. The current project should not be represented as
    automatically sending email.
-   **Dashboard and reporting:** View lead-related metrics, activity,
    and qualification/reporting information.
-   **Authentication and user administration:** Login and current-user
    endpoints are present; user listing/creation is admin-protected.
-   **Database migrations and demo data:** SQLAlchemy/Alembic migrations
    have been run against PostgreSQL, and a seed script provides
    fictional demonstration leads.

### Important limitations

-   Demo companies and contacts are synthetic and must not be presented
    as real prospects.
-   AI-generated interpretations can be wrong. Review sources and
    evidence before relying on a qualification result.
-   Tavily research requires valid configuration and may be unavailable
    if the provider or network fails.
-   Email sending is not implemented as an automatic side effect;
    outreach should be treated as drafts.
-   Multi-tenant isolation, compliance certification, and production
    security have not been established by the information available for
    this README. Review and test these before a multi-organization or
    public production deployment.
-   A running application is not, by itself, evidence of production
    readiness.

## Technology

-   **Backend:** Python, FastAPI, Pydantic, SQLAlchemy
-   **Database:** PostgreSQL; SQLite support may be available for
    lightweight local use depending on configuration
-   **Migrations:** Alembic
-   **AI provider:** Google Gemini
-   **Web research:** Tavily
-   **Frontend:** HTML, CSS, vanilla JavaScript
-   **Testing and operations:** Use the test and deployment tooling
    included in the repository; confirm the current scripts and
    configuration before relying on them.

## Architecture

``` mermaid
flowchart TD
    U[Sales user] --> UI[Pilot Light web dashboard]
    UI --> API[FastAPI API]
    API --> AUTH[Authentication and authorization]
    API --> SVC[Lead and qualification services]
    SVC --> DB[(PostgreSQL)]
    SVC --> WF[Qualification workflow]
    WF --> SCORE[Deterministic scoring and rules]
    WF --> GEM[Gemini AI provider]
    WF --> TAV[Tavily research provider]
    WF --> REVIEW[Human review / approval]
    SVC --> REPORTS[Dashboard and reports]
    SVC --> DRAFTS[Outreach drafts]
```

### Typical data flow

1.  A user signs in and creates or imports lead information through
    supported application features.
2.  The API validates the request and persists application records in
    PostgreSQL.
3.  The qualification workflow uses available lead data and configured
    criteria.
4.  Deterministic rules handle business-critical scoring; AI-assisted
    analysis helps summarize unstructured information when configured.
5.  Optional research may retrieve public company context through
    Tavily.
6.  The application stores evaluation, evidence, workflow, activity,
    and/or review records supported by the current implementation.
7.  A user reviews the result and edits outreach drafts before using
    them.

The exact enabled workflow nodes depend on the code and environment
configuration. Do not assume that a provider has run successfully merely
because its API key is present.

## Repository layout

The current repository is the source of truth for the exact structure.
Main areas include:

``` text
sales-lead-qualification-agent/
├── app/
│   ├── api/                 # FastAPI endpoints and dependencies
│   ├── core/                # Application configuration and shared logic
│   ├── db/                  # Database session and base configuration
│   ├── models/              # SQLAlchemy database models
│   ├── schemas/             # Request/response validation schemas
│   ├── services/            # Business logic and reporting services
│   └── static/              # Browser UI (HTML/CSS/JavaScript)
├── alembic/                 # Database migrations
├── scripts/                 # Utility and demo-data scripts
├── tests/                   # Automated tests, if included in this checkout
├── .env.example             # Example configuration, if included
├── alembic.ini
└── pyproject.toml and/or requirements.txt
```

Some folders shown above may differ in the current checkout. Keep this
section aligned with the actual files before publishing.

## Requirements

-   Python 3.11 or newer, compatible with the project's pinned
    dependencies
-   PostgreSQL 16+ recommended; this project has been tested with
    PostgreSQL 18.6
-   Google Gemini API key for AI features
-   Tavily API key for web research
-   Git

You can run the application without optional AI/research integrations
only if the current configuration supports those features being
disabled.

## Local setup --- Windows PowerShell

Commands below assume you are in the repository root (the directory
containing `alembic.ini` and the `app` folder).

### 1. Clone the repository

Replace `YOUR_GITHUB_USERNAME` with your GitHub username after
publishing the repository.

``` powershell
git clone https://github.com/YOUR_GITHUB_USERNAME/sales-lead-qualification-agent.git
cd sales-lead-qualification-agent
```

If the project is nested inside another folder in your local workspace,
make sure you run commands from the inner repository root.

### 2. Create and activate a virtual environment

``` powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell blocks activation, use this for the current terminal only:

``` powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

Use the dependency file that actually exists in the repository:

``` powershell
# If requirements.txt exists:
pip install -r requirements.txt

# Otherwise, if pyproject.toml defines the project and dependencies:
pip install -e .
```

Install the PostgreSQL driver used by this project if it is not already
included in the dependency configuration:

``` powershell
pip install "psycopg[binary]"
```

Prefer keeping dependencies declared and pinned in the project's
dependency file rather than relying on manual installs.

### 4. Configure environment variables

Copy the example file if the repository includes one:

``` powershell
Copy-Item .env.example .env
```

Edit `.env` and set the database URL and provider credentials using the
exact variable names defined in `app/core/config.py` or the project's
settings module.

Example database URL for local PostgreSQL:

``` dotenv
DATABASE_URL=postgresql+psycopg://YOUR_DB_USER:YOUR_DB_PASSWORD@localhost:5432/sales_leads
```

This is an example only. The actual environment variable name may differ
in the current settings implementation. Use the variable name expected
by the code. Keep `.env` private; never commit API keys, passwords,
signing secrets, or real customer data.

Configure the Gemini and Tavily credentials using the variable names
defined by the project. Do not paste real secrets into README, source
code, screenshots, or GitHub issues.

### 5. Create the PostgreSQL database

If PostgreSQL is installed locally, create a database named
`sales_leads` using pgAdmin or `psql`. Example command (adjust the
PostgreSQL username as needed):

``` powershell
psql -U postgres -h localhost -p 5432 -c "CREATE DATABASE sales_leads;"
```

If the database already exists, do not run the create command again.
Make sure the database URL points to the correct database.

### 6. Run migrations

``` powershell
alembic upgrade head
```

This applies the schema migrations to the configured database. Never
point a migration command at a production database until you have a
backup and have reviewed the migration.

### 7. Seed fictional demo leads

``` powershell
python -m scripts.seed_demo
```

The seed script used during development reported six synthetic leads. It
may skip records already present, so the number inserted on a later run
can be zero. Verify the script's behavior in the current checkout before
relying on it.

### 8. Start the application

Use the launch command documented by the repository. A typical FastAPI
development command is:

``` powershell
uvicorn app.main:app --reload
```

Open the local address printed by Uvicorn. FastAPI's interactive API
documentation is commonly available at `/docs` if enabled by the
application.

### 9. Create the initial administrator

Use the initial-admin setup flow if it has been implemented in the
current version. If not, follow the repository's documented
administrator creation procedure. Do not publish default admin
credentials. The project previously used a `scripts.create_admin`
utility, but a client-facing first-run setup flow should be verified
before claiming that terminal-free setup is available.

## Configuration

Check the actual settings module and `.env.example` for authoritative
variable names. Typical configuration categories include:

  Category                  Purpose
  ------------------------- -------------------------------------------
  Application environment   Select development or production behavior
  Database URL              PostgreSQL connection string
  Gemini API key/model      Enable AI-assisted analysis
  Tavily API key            Enable web research
  Authentication secret     Protect token/session signing
  Allowed origins           Restrict browser origins where configured
  Logging level             Control application log verbosity

Do not commit `.env`. Keep `.env.example` limited to safe placeholder
values.

## API

The API is organized under `/api/v1` where configured. Authentication
routes known to exist include:

  -----------------------------------------------------------------------
  Method                  Path                    Purpose
  ----------------------- ----------------------- -----------------------
  `POST`                  `/api/v1/auth/login`    Authenticate a user

  `POST`                  `/api/v1/auth/logout`   Record logout and let
                                                  the client discard its
                                                  token

  `GET`                   `/api/v1/auth/me`       Return the current
                                                  authenticated user

  `GET`                   `/api/v1/users`         List users;
                                                  administrator access
                                                  required

  `POST`                  `/api/v1/users`         Create a user;
                                                  administrator access
                                                  required
  -----------------------------------------------------------------------

Confirm the exact API prefix in `app/api/v1/router.py` and
`app/main.py`; route prefixes can differ by configuration. Open `/docs`
while the application is running to see the live OpenAPI contract.

## Testing and quality checks

Run the commands supported by the repository. Typical commands are:

``` powershell
pytest
ruff check .
ruff format --check .
```

These commands only verify quality if the corresponding tools and tests
are installed and configured. Do not report a test suite as passing
unless you have actually run it and checked the exit code. Prefer mocked
AI and search-provider calls for repeatable tests.

## Security notes

-   Keep `.env` and credentials out of Git.
-   Use a unique, strong authentication secret in each environment.
-   Restrict database network access; do not expose PostgreSQL publicly
    by default.
-   Use HTTPS behind a correctly configured reverse proxy for public
    deployments.
-   Enforce authorization on the server, not only in the frontend.
-   Treat CSV fields, lead descriptions, and web search results as
    untrusted input.
-   Review AI outputs and source evidence before acting on them.
-   Keep human approval between AI recommendations and consequential
    external actions.
-   Configure rate limits, backups, retention, logging, and monitoring
    before production use.
-   Do not upload real customer data or secrets to a public repository.

## Roadmap

Potential next steps, depending on the current implementation:

-   First-run administrator setup through the UI
-   Stronger CSV import validation and downloadable rejected-row reports
-   Versioned ICP profiles and reproducible scoring-rule versions
-   More comprehensive workflow retries, resumability, and idempotency
    tests
-   Additional security and prompt-injection tests
-   Docker Compose deployment and health checks
-   CI checks with GitHub Actions
-   Optional CRM integrations
-   Email provider integration only with explicit authorization,
    suppression checks, and human approval
-   Measured outcome reporting tied to meetings held and deals won

## Contributing

1.  Open an issue describing the proposed change.
2.  Create a feature branch.
3.  Add or update tests.
4.  Run the relevant checks.
5.  Submit a pull request with a clear description and known
    limitations.

## License

No license has been specified in this README. Add a `LICENSE` file
before publishing if you want to explicitly grant others permission to
use, modify, and redistribute this project. Do not assume that public
visibility alone grants reuse rights.

## Author

**Waheed Abbas**\
AI Engineering \| Python \| FastAPI \| PostgreSQL \| Agentic AI

Add your LinkedIn profile and contact details here if you want them
public.
