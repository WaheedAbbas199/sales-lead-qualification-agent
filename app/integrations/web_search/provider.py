"""Optional company research via the official Brave Search API.

Disabled unless RESEARCH_ENABLED=true AND BRAVE_API_KEY is set. We only call the provider's API
(fixed host => no SSRF from lead-supplied URLs) and we never fetch lead websites directly.
Search snippets are *leads, not proof*; they are stored with SEARCH_SNIPPET provenance.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.exceptions import ResearchUnavailable
from app.core.logging import get_logger

log = get_logger(__name__)
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
TAVILY_URL = "https://api.tavily.com/search"


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    retrieved_at: datetime

    @property
    def host(self) -> str:
        host = (urlparse(self.url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host


class ResearchProvider(Protocol):
    name: str

    def status(self) -> dict: ...
    def search(self, company: str, domain: str | None) -> list[SearchHit]: ...


class DisabledResearch:
    name = "disabled"

    def status(self) -> dict:
        return {"provider": "disabled", "configured": False, "message": "Company research is disabled (set RESEARCH_ENABLED=true and BRAVE_API_KEY)."}

    def search(self, company: str, domain: str | None) -> list[SearchHit]:
        raise ResearchUnavailable("Research provider is not configured")


class BraveResearch:
    name = "brave"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._key = settings.brave_api_key
        self._client = httpx.Client(timeout=10.0, transport=transport)

    def status(self) -> dict:
        return {"provider": "brave", "configured": True}

    def search(self, company: str, domain: str | None) -> list[SearchHit]:
        query = f'"{company}" {domain or ""}'.strip()[:200]
        try:
            resp = self._client.get(
                BRAVE_URL, params={"q": query, "count": 5}, headers={"Accept": "application/json", "X-Subscription-Token": self._key}
            )
            resp.raise_for_status()
            results = resp.json().get("web", {}).get("results", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise ResearchUnavailable(f"Search provider failed: {type(exc).__name__}") from exc
        now = datetime.now(UTC)
        hits = []
        for r in results[:5]:
            url = str(r.get("url", ""))
            if not url.startswith(("http://", "https://")):
                continue
            hits.append(SearchHit(title=str(r.get("title", ""))[:200], url=url[:1000], snippet=str(r.get("description", ""))[:500], retrieved_at=now))
        return hits


class TavilyResearch:
    name = "tavily"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._key = settings.tavily_api_key
        self._client = httpx.Client(timeout=10.0, transport=transport)

    def status(self) -> dict:
        return {"provider": "tavily", "configured": True}

    def search(self, company: str, domain: str | None) -> list[SearchHit]:
        query = f'"{company}" {domain or ""}'.strip()[:200]

        try:
            resp = self._client.post(
                TAVILY_URL,
                json={
                    "api_key": self._key,
                    "query": query,
                    "max_results": 5,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise ResearchUnavailable(
                f"Search provider failed: {type(exc).__name__}"
            ) from exc

        now = datetime.now(UTC)
        hits = []

        for result in results[:5]:
            url = str(result.get("url", ""))
            if not url.startswith(("http://", "https://")):
                continue

            hits.append(
                SearchHit(
                    title=str(result.get("title", ""))[:200],
                    url=url[:1000],
                    snippet=str(result.get("content", ""))[:500],
                    retrieved_at=now,
                )
            )

        return hits


def build_research(settings: Settings) -> ResearchProvider:
    if not settings.research_configured:
        return DisabledResearch()

    if settings.search_provider == "tavily":
        return TavilyResearch(settings)

    if settings.search_provider == "brave":
        return BraveResearch(settings)

    return DisabledResearch()


