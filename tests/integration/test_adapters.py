import json

import httpx
import pytest

from app.core.exceptions import LLMMalformedOutput, LLMNotConfigured, LLMUnavailable, ResearchUnavailable
from app.integrations.gemini.client import DisabledLLM, GeminiLLM, build_llm
from app.integrations.gemini.schemas import AIQualificationReport
from app.integrations.web_search.provider import BraveResearch, DisabledResearch, build_research
from tests.conftest import make_settings


def test_disabled_providers_fail_loudly_not_silently():
    llm = DisabledLLM()
    assert llm.status()["configured"] is False
    with pytest.raises(LLMNotConfigured):
        llm.qualify("s", "p")
    with pytest.raises(ResearchUnavailable):
        DisabledResearch().search("Acme", None)


def test_build_helpers_respect_configuration():
    assert build_llm(make_settings(llm_provider="disabled")).name == "disabled"
    assert build_llm(make_settings(llm_provider="gemini", gemini_api_key="")).name == "disabled"
    assert build_llm(make_settings()).name == "gemini"
    assert build_research(make_settings(research_enabled=True, brave_api_key="")).name == "disabled"
    assert build_research(make_settings(research_enabled=True, brave_api_key="k")).name == "brave"


class _Resp:
    def __init__(self, text=None, parsed=None):
        self.text, self.parsed = text, parsed


class _Models:
    def __init__(self, behaviours):
        self.behaviours, self.calls = list(behaviours), 0

    def generate_content(self, **kwargs):
        self.calls += 1
        b = self.behaviours.pop(0)
        if isinstance(b, Exception):
            raise b
        return b


class _Client:
    def __init__(self, behaviours):
        self.models = _Models(behaviours)


GOOD = json.dumps({"summary": "s", "recommended_next_action": "human_review", "confidence": 0.4})


def gemini(behaviours, retries=2, monkeypatch=None):
    g = GeminiLLM(make_settings(llm_max_retries=retries))
    g._client = _Client(behaviours)
    return g


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("app.integrations.gemini.client.time.sleep", lambda s: None)


def test_gemini_parses_valid_json():
    g = gemini([_Resp(text=GOOD)])
    assert isinstance(g.qualify("s", "p"), AIQualificationReport)


def test_gemini_retries_transient_then_succeeds():
    g = gemini([RuntimeError("503"), RuntimeError("timeout"), _Resp(text=GOOD)])
    assert g.qualify("s", "p").confidence == 0.4 and g._client.models.calls == 3


def test_gemini_gives_up_after_bounded_retries():
    g = gemini([RuntimeError("x")] * 5, retries=2)
    with pytest.raises(LLMUnavailable):
        g.qualify("s", "p")
    assert g._client.models.calls == 3


def test_gemini_malformed_output_never_accepted():
    g = gemini([_Resp(text="not json")] * 3)
    with pytest.raises(LLMMalformedOutput):
        g.qualify("s", "p")
    g2 = gemini([_Resp(text=json.dumps({"summary": "s", "recommended_next_action": "send_all_emails", "confidence": 5}))] * 3)
    with pytest.raises(LLMMalformedOutput):
        g2.qualify("s", "p")
    g3 = gemini([_Resp(text="")] * 3)
    with pytest.raises(LLMMalformedOutput):
        g3.qualify("s", "p")


def test_gemini_auth_errors_are_not_retried():
    from google.genai import errors

    err = errors.ClientError(403, {"error": {"message": "denied", "status": "PERMISSION_DENIED"}})
    g = gemini([err, _Resp(text=GOOD)])
    with pytest.raises(LLMUnavailable):
        g.qualify("s", "p")
    assert g._client.models.calls == 1


def test_gemini_requires_key():
    with pytest.raises(LLMNotConfigured):
        GeminiLLM(make_settings(gemini_api_key=""))


def brave(handler):
    return BraveResearch(make_settings(research_enabled=True, brave_api_key="brave-key"), transport=httpx.MockTransport(handler))


def test_brave_maps_results_and_sends_key_header_only():
    seen = {}

    def handler(request: httpx.Request):
        seen["key"], seen["q"] = request.headers["X-Subscription-Token"], request.url.params["q"]
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"title": "Acme", "url": "https://acme.example.com/", "description": "HVAC pros"},
                        {"title": "Bad", "url": "javascript:alert(1)", "description": "x"},
                    ]
                }
            },
        )

    hits = brave(handler).search("Acme", "acme.example.com")
    assert [h.url for h in hits] == ["https://acme.example.com/"] and hits[0].host == "acme.example.com" and hits[0].retrieved_at
    assert seen["key"] == "brave-key" and "Acme" in seen["q"]


@pytest.mark.parametrize(
    "handler",
    [lambda r: httpx.Response(429), lambda r: httpx.Response(200, text="not json"), lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))],
)
def test_brave_failures_become_research_unavailable(handler):
    with pytest.raises(ResearchUnavailable):
        brave(handler).search("Acme", None)
