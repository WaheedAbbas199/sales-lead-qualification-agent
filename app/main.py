"""FastAPI application factory."""

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dependencies import Container
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger, request_id_var
from app.core.security import LoginRateLimiter
from app.db.base import Base
from app.db.session import make_engine, make_session_factory
from app.integrations.gemini.client import build_llm
from app.integrations.web_search.provider import build_research
from app.services import icp_service
from app.workers.runner import WorkflowRunner

log = get_logger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)


def build_container(settings: Settings, *, llm=None, research=None, create_tables: bool = False) -> Container:
    engine = make_engine(settings)
    if create_tables:  # tests / quick local runs only; real deployments use `alembic upgrade head`
        import app.models  # noqa: F401

        Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    llm = llm or build_llm(settings)
    research = research or build_research(settings)
    runner = WorkflowRunner(factory, settings, llm, research)
    limiter = LoginRateLimiter(settings.login_max_attempts, settings.login_window_seconds)
    return Container(settings, engine, factory, llm, research, runner, limiter)


def create_app(settings: Settings | None = None, *, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with container.session_factory() as s:
            icp_service.ensure_default(s)
        recovered = container.runner.recover_stale()
        log.info(
            "startup complete (env=%s, ai=%s, research=%s, recovered_stale=%s)",
            settings.app_env,
            container.llm.name,
            container.research.name,
            recovered,
        )
        yield

    docs = "/api/v1/docs" if settings.enable_docs else None
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url=docs,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json" if settings.enable_docs else None,
    )
    app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if not request.url.path.startswith("/api/v1/docs"):
            response.headers["Content-Security-Policy"] = CSP
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    def envelope(status: int, code: str, message: str, details=None) -> JSONResponse:
        return JSONResponse(
            status_code=status, content={"error": {"code": code, "message": message, "details": details, "request_id": request_id_var.get()}}
        )

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return envelope(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
        return envelope(422, "validation_failed", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return envelope(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error: %s", type(exc).__name__)
        return envelope(500, "internal_error", "An unexpected error occurred")  # no internals leaked

    app.include_router(api_router, prefix="/api/v1")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


def app_factory() -> FastAPI:  # `uvicorn app.main:app_factory --factory`
    return create_app()


def __getattr__(name: str):
    """Lazy module-level `app` so importing app.main (tests, Alembic) never needs a full environment."""
    if name == "app":
        return create_app()
    raise AttributeError(name)
