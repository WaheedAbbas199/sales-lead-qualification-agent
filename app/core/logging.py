"""Structured logging with request/workflow correlation ids and secret redaction."""

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
workflow_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("workflow_id", default="-")

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization|api[_-]?key|token|password|secret)([\"'\s:=]+)((?:bearer\s+)?[^\s\"',}]+)"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
]


def redact(text: str) -> str:
    out = text
    out = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
    out = _SECRET_PATTERNS[1].sub("[REDACTED]", out)
    return out


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "request_id": request_id_var.get(),
            "workflow_id": workflow_id_var.get(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update({k: redact(str(v)) for k, v in extra.items()})
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        return redact(f"{base} [req={request_id_var.get()} wf={workflow_id_var.get()}]")


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else PlainFormatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, msg: str, **fields) -> None:
    logger.info(msg, extra={"extra_fields": fields})
