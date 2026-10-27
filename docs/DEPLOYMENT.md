# Deployment & operations

## Local (Windows PowerShell)
```powershell
cd sales-lead-qualification-agent
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env          # edit SECRET_KEY; keep DATABASE_URL=sqlite:///./data/app.db
alembic upgrade head
python -m scripts.create_admin --email admin@example.com --name "Admin"
python -m scripts.seed_demo
uvicorn app.main:app --reload
pytest ; ruff check .
```
Expected: `Created admin user …`, `Seeded 6 synthetic leads`, server on http://127.0.0.1:8000.
Common errors: *"SECRET_KEY must be…"* (only in `APP_ENV=production`); *Activate.ps1 blocked* → `Set-ExecutionPolicy -Scope Process RemoteSigned`;
*"no such table"* → run `alembic upgrade head`; *AI shows "not configured"* → set `LLM_PROVIDER=gemini` + key and restart.

## Docker Compose (PostgreSQL)
1. Create `.env` beside `compose.yaml`: `POSTGRES_PASSWORD`, `SECRET_KEY` (≥32 random chars), `ALLOWED_ORIGINS=https://your.domain`, optional Gemini/Brave keys.
2. `docker compose up -d db`
3. `docker compose --profile tools run --rm migrate`
4. `docker compose up -d app`
5. `docker compose run --rm app python -m scripts.create_admin --email you@example.com --name "You"`

PostgreSQL is on a private network (no published port). The app binds to `127.0.0.1:8000`; a container is **not** a security boundary by itself.

## HTTPS / reverse proxy (Caddy example)
```
leads.example.com {
    reverse_proxy 127.0.0.1:8000
}
```
Caddy obtains certificates automatically. The app runs uvicorn with `--proxy-headers`; restrict who can reach port 8000 (firewall) so clients cannot spoof `X-Forwarded-For`.

## Backup / restore (PostgreSQL)
```bash
docker compose exec -T db pg_dump -U sla -Fc sla > backup_$(date +%F).dump
docker compose exec -T db pg_restore -U sla -d sla --clean --if-exists < backup_2026-10-26.dump
```
Test restores regularly; store backups encrypted and off-host.

## Migrations & rollback
Run `alembic upgrade head` **before** starting a new version. Rollback: `alembic downgrade -1` (verified for `0001` on SQLite; test on a Postgres copy first).
Take a backup before every migration. Destructive migrations should be expand/contract across two releases.

## Operations
* Logs: JSON to stdout with `request_id` and `workflow_id`; secrets are redacted.
* Probes: `/api/v1/health` (liveness), `/api/v1/ready` (DB + provider configuration, no secrets).
* Stuck runs: executions left `running` are failed with `interrupted` at startup; start qualification again.
* Retention: nothing is auto-deleted. Define a policy for leads, audit events and workflow traces.
