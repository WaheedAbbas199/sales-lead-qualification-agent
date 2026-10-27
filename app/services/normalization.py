"""Pure normalisation helpers (no I/O) - easy to unit-test."""

import re
from urllib.parse import urlparse

from email_validator import EmailNotValidError, validate_email

_WS = re.compile(r"\s+")
# strip control chars (keeps \n and \t handled by whitespace collapse in single-line fields)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

INDUSTRY_ALIASES: dict[str, str] = {
    "hvac": "hvac",
    "hvac contractor": "hvac",
    "hvac contractors": "hvac",
    "heating and cooling": "hvac",
    "heating & cooling": "hvac",
    "heating, ventilation and air conditioning": "hvac",
    "heating ventilation air conditioning": "hvac",
    "air conditioning": "hvac",
    "ac repair": "hvac",
    "plumbing": "plumbing",
    "plumber": "plumbing",
    "electrical": "electrical",
    "electrician": "electrical",
    "roofing": "roofing",
    "saas": "software",
    "software": "software",
    "software as a service": "software",
    "it services": "it services",
    "information technology": "it services",
    "real estate": "real estate",
    "healthcare": "healthcare",
    "health care": "healthcare",
    "retail": "retail",
    "e-commerce": "ecommerce",
    "ecommerce": "ecommerce",
    "construction": "construction",
    "home services": "home services",
}

COUNTRY_ALIASES: dict[str, str] = {
    "us": "United States",
    "usa": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "united states": "United States",
    "united states of america": "United States",
    "america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "united kingdom": "United Kingdom",
    "gb": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "ca": "Canada",
    "canada": "Canada",
    "au": "Australia",
    "australia": "Australia",
    "de": "Germany",
    "germany": "Germany",
    "pk": "Pakistan",
    "pakistan": "Pakistan",
    "in": "India",
    "india": "India",
    "ae": "United Arab Emirates",
    "uae": "United Arab Emirates",
}


def clean_text(value: str | None, *, max_len: int = 500) -> str | None:
    """Collapse whitespace, strip control chars, cap length. Returns None for blank."""
    if value is None:
        return None
    text = _WS.sub(" ", _CTRL.sub("", str(value))).strip()
    if not text:
        return None
    return text[:max_len]


def clean_multiline(value: str | None, *, max_len: int = 5000) -> str | None:
    if value is None:
        return None
    text = _CTRL.sub("", str(value)).replace("\r\n", "\n").strip()
    return text[:max_len] or None


def normalize_email(value: str | None) -> str | None:
    text = clean_text(value, max_len=320)
    if not text:
        return None
    try:
        # check_deliverability=False -> no DNS lookups (deterministic, offline-safe)
        return validate_email(text, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError(f"Invalid email address: {exc}") from exc


def normalize_url(value: str | None) -> tuple[str | None, str | None]:
    """Return (normalised_url, domain). Only http(s) is accepted; everything else is rejected."""
    text = clean_text(value, max_len=500)
    if not text:
        return None, None
    candidate = text if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text) else f"https://{text}"
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Website must use http or https")
    host = (parsed.hostname or "").lower()
    if not host or "." not in host or " " in host:
        raise ValueError("Website is not a valid domain")
    if host.startswith("www."):
        host = host[4:]
    return f"{parsed.scheme}://{host}", host


def normalize_industry(value: str | None) -> str | None:
    text = clean_text(value, max_len=120)
    if not text:
        return None
    key = text.lower()
    return INDUSTRY_ALIASES.get(key, key)


def normalize_country(value: str | None) -> str | None:
    text = clean_text(value, max_len=80)
    if not text:
        return None
    return COUNTRY_ALIASES.get(text.lower(), text.title() if text.islower() else text)


_BOOL_TRUE = {"true", "yes", "y", "1", "decision maker", "decision-maker"}
_BOOL_FALSE = {"false", "no", "n", "0"}


def parse_optional_bool(value) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text or text in {"unknown", "?", "n/a"}:
        return None
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    raise ValueError("Expected yes/no/unknown")


def parse_budget(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        number = float(value)
    else:
        text = str(value).strip().lower().replace(",", "").replace("$", "").replace("usd", "").strip()
        if not text or text in {"unknown", "n/a", "?"}:
            return None
        mult = 1.0
        if text.endswith("k"):
            mult, text = 1000.0, text[:-1]
        try:
            number = float(text) * mult
        except ValueError as exc:
            raise ValueError("Budget must be a number such as 5000 or 5k") from exc
    if number < 0 or number > 1_000_000_000:
        raise ValueError("Budget is out of range")
    return round(number, 2)
