# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml ./
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/python -c "import tomllib,subprocess;d=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies'];subprocess.check_call(['/opt/venv/bin/pip','install',*d])"

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
RUN useradd --system --uid 10001 --create-home app
WORKDIR /srv/app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini pyproject.toml ./
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app data ./data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status==200 else 1)"
# Single worker: login rate limiting is in-memory (see docs/SECURITY.md). Run migrations first (see compose.yaml).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
