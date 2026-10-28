import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SECRET_KEYS = re.compile(
    r"(token|secret|password|authorization|cookie|api_?key|email|phone)|^(code|auth_code|link_code)$",
    re.IGNORECASE,
)
_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"), "Bearer ***"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "***@***"),
    (re.compile(r"(?<!\d)(\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"), "+7***"),
    (re.compile(r"((?:access|refresh)_token|client_secret|code)=([^&\s]+)"), r"\1=***"),
]


def redact_text(value: str) -> str:
    for pattern, repl in _PATTERNS:
        value = pattern.sub(repl, value)
    return value


def redact(value: Any, key: str | None = None) -> Any:
    """Recursively mask secrets and personal data before they reach a log sink."""
    if key is not None and _SECRET_KEYS.search(key):
        return "***"
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class JsonFormatter(logging.Formatter):
    _RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        extra = {k: v for k, v in record.__dict__.items() if k not in self._RESERVED}
        if extra:
            payload.update(redact(extra))
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
