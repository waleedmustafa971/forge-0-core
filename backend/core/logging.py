"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s\"']+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
    re.compile(r"\b(sk|gho|ghp|github_pat)_[A-Za-z0-9_]{8,}\b"),
]


def redact(text: str) -> str:
    """Masks credentials that may appear in log lines or captured output."""
    for pattern in _SECRET_PATTERNS:
        replacement = (lambda m: f"{m.group(1)}***") if pattern.groups else "***"
        text = pattern.sub(replacement, text)
    return text


_known_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Registers a literal secret so it is masked wherever it appears."""
    if value and len(value) >= 6:
        _known_secrets.add(value)


def redact_known(text: str) -> str:
    for secret in _known_secrets:
        text = text.replace(secret, "***")
    return redact(text)


class JsonFormatter(logging.Formatter):
    _RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_known(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = redact_known(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_known(super().format(record))


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if fmt == "json" else TextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
