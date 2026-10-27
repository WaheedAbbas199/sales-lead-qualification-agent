"""LLM abstraction + Gemini implementation (google-genai SDK).

* Credentials/model come from settings; nothing is hard-coded.
* Bounded retries with backoff for transient errors (429/5xx/timeouts) only.
* Output is validated with Pydantic; malformed output raises LLMMalformedOutput (never saved).
* The model is given NO tools: it can only return text/JSON.
"""

import json
import time
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.exceptions import LLMMalformedOutput, LLMNotConfigured, LLMUnavailable
from app.core.logging import get_logger
from app.integrations.gemini.schemas import AIEmailDraft, AIQualificationReport

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    name: str

    def status(self) -> dict: ...
    def qualify(self, system: str, prompt: str) -> AIQualificationReport: ...
    def draft_email(self, system: str, prompt: str) -> AIEmailDraft: ...


class DisabledLLM:
    """Used when no provider is configured. Raises a clear error instead of pretending to work."""

    name = "disabled"

    def status(self) -> dict:
        return {"provider": "disabled", "configured": False, "message": "AI provider not configured (LLM_PROVIDER=disabled or missing key)."}

    def qualify(self, system: str, prompt: str) -> AIQualificationReport:
        raise LLMNotConfigured("AI provider is not configured")

    def draft_email(self, system: str, prompt: str) -> AIEmailDraft:
        raise LLMNotConfigured("AI provider is not configured")


class GeminiLLM:
    name = "gemini"

    def __init__(self, settings: Settings):
        if not settings.gemini_api_key:
            raise LLMNotConfigured("GEMINI_API_KEY is not set")
        from google import genai
        from google.genai import types

        self._types = types
        self._model = settings.gemini_model
        self._retries = settings.llm_max_retries
        self._client = genai.Client(api_key=settings.gemini_api_key, http_options=types.HttpOptions(timeout=settings.llm_timeout_seconds * 1000))

    def status(self) -> dict:
        # Configuration check only: a real call would cost money on every health probe.
        return {"provider": "gemini", "configured": True, "model": self._model}

    def _generate(self, system: str, prompt: str, schema: type[T]) -> T:
        from google.genai import errors

        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=self._types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=0.2,
                        max_output_tokens=2000,
                    ),
                )
                parsed = getattr(resp, "parsed", None)
                if isinstance(parsed, schema):
                    return parsed
                text = (resp.text or "").strip()
                if not text:
                    raise LLMMalformedOutput("Model returned an empty response")
                return schema.model_validate(json.loads(text))
            except (json.JSONDecodeError, ValidationError) as exc:
                # Malformed output: one more try is allowed, but never "repaired" silently.
                last = LLMMalformedOutput(f"Model output failed schema validation: {type(exc).__name__}")
            except LLMMalformedOutput as exc:
                last = exc
            except errors.APIError as exc:
                code = getattr(exc, "code", 0) or 0
                if code in (400, 401, 403, 404):
                    raise LLMUnavailable(f"Gemini rejected the request (HTTP {code}); check API key / model name") from exc
                last = LLMUnavailable(f"Gemini transient error (HTTP {code})")
            except Exception as exc:  # network/timeouts from the HTTP layer
                last = LLMUnavailable(f"Gemini request failed: {type(exc).__name__}")
            log.warning("LLM attempt %s/%s failed: %s", attempt + 1, self._retries + 1, last)
            if attempt < self._retries:
                time.sleep(min(2**attempt, 8))
        assert last is not None
        raise last

    def qualify(self, system: str, prompt: str) -> AIQualificationReport:
        return self._generate(system, prompt, AIQualificationReport)

    def draft_email(self, system: str, prompt: str) -> AIEmailDraft:
        return self._generate(system, prompt, AIEmailDraft)


def build_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "gemini" and settings.gemini_api_key:
        return GeminiLLM(settings)
    return DisabledLLM()
