import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

_STD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_SENSITIVE_KEY = re.compile(
    r"(password|secret|authorization|api[_-]?key|cookie|credential|jwt|bearer|access_token|refresh_token|^token$|database_url)",
    re.I,
)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_KV = re.compile(r"(?i)((?:password|secret|token|api[_-]?key|authorization)\s*[=:]\s*)[^\s,;&\"']+")
_URL_CRED = re.compile(r"(://[^:/\s]+:)[^@\s]+@")
REDACTED = "***"


def scrub_text(text: str) -> str:
    text = _BEARER.sub(r"\1" + REDACTED, text)
    text = _KV.sub(r"\1" + REDACTED, text)
    return _URL_CRED.sub(r"\1" + REDACTED + "@", text)


def redact(value: Any, key: str = "") -> Any:
    if key and _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub_text(record.getMessage()),
        }
        for k, v in record.__dict__.items():
            if k not in _STD_ATTRS and not k.startswith("_"):
                payload[k] = redact(v, k)
        if record.exc_info:
            payload["exception"] = scrub_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    access = logging.getLogger("uvicorn.access")  # replaced by our timing middleware
    access.handlers = []
    access.propagate = False
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
