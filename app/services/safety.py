"""Untrusted-content handling: injection heuristics, sanitising and prompt delimiting.

The heuristics are a *signal* (flag + force human review), not a security boundary. The real controls are:
schema validation, no tools given to the model, deterministic scoring, and approval gates.
"""

import re
import secrets

_INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier|system) (instructions|rules|prompts?)",
    r"disregard (all |any |the )?(previous|prior|above|earlier|system)",
    r"forget (everything|all|your) (instructions|rules|above)?",
    r"you are now\b",
    r"\bnew instructions?\b",
    r"system prompt",
    r"reveal (your|the) (prompt|instructions|api key|secret)",
    r"(send|email|forward) (an? )?(email|message)s? to (every|all|everyone)",
    r"\b(mark|set) (this|the) lead (as )?(qualified|high priority)",
    r"\bscore (this )?(lead )?(as )?100\b",
    r"approve (this|the) (lead|qualification) automatically",
    r"<\s*/?\s*(system|assistant|untrusted)[^>]*>",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def detect_injection(*texts: str | None) -> list[str]:
    """Return the list of heuristic patterns that matched anywhere in the given texts."""
    hits: list[str] = []
    for text in texts:
        if not text:
            continue
        for rx in _COMPILED:
            if rx.search(text) and rx.pattern not in hits:
                hits.append(rx.pattern)
    return hits


def truncate(text: str | None, limit: int) -> str:
    return (text or "")[:limit]


def wrap_untrusted(label: str, content: str | None, *, limit: int) -> tuple[str, str]:
    """Wrap untrusted text in a randomly-named delimiter the content cannot predict.

    Returns (wrapped_block, delimiter_name). Any occurrence of the delimiter inside the content is neutralised.
    """
    delimiter = f"UNTRUSTED_{secrets.token_hex(6).upper()}"
    safe = truncate(content, limit).replace(delimiter, "[removed]")
    safe = re.sub(r"<\s*/?\s*(system|assistant|user|untrusted)[^>]*>", "[tag removed]", safe, flags=re.IGNORECASE)
    return f'<{delimiter} field="{label}">\n{safe}\n</{delimiter}>', delimiter
