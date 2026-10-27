"""Domain exceptions mapped to a consistent JSON error envelope."""


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str, *, details: dict | list | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class PermissionDenied(AppError):
    status_code = 403
    code = "forbidden"


class AuthenticationFailed(AppError):
    status_code = 401
    code = "unauthenticated"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


# --- AI / research provider errors (categorised so workflows can degrade gracefully) ---
class LLMError(AppError):
    status_code = 502
    code = "llm_error"


class LLMNotConfigured(LLMError):
    status_code = 503
    code = "llm_not_configured"


class LLMUnavailable(LLMError):
    code = "llm_unavailable"


class LLMMalformedOutput(LLMError):
    code = "llm_malformed_output"


class ResearchUnavailable(AppError):
    status_code = 503
    code = "research_unavailable"
