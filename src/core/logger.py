"""JSON-lines logging with per-request, per-job context fields."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

# Fields added to every line logged inside log_context (request_id, trip_id, job_id, model_id)
_context: ContextVar[Mapping[str, str]] = ContextVar("log_context", default=MappingProxyType({}))


# The handler configure_logging installs; the type lets a second call find and replace it
class JsonHandler(logging.StreamHandler):  # type: ignore[type-arg]
    pass


# One JSON object per log record
class JsonFormatter(logging.Formatter):
    # Render the record with its context fields
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_context.get(),
        }
        if record.exc_info:
            line["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False)


# Send every log record to stderr as one JSON line; safe to call again with another level
def configure_logging(level: str) -> None:
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, JsonHandler)]:
        root.removeHandler(handler)

    handler = JsonHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())


# Add fields to every log line written inside the block, on top of any outer block's fields
@contextmanager
def log_context(**fields: object) -> Iterator[None]:
    token = _context.set({**_context.get(), **{k: str(v) for k, v in fields.items()}})
    try:
        yield
    finally:
        _context.reset(token)
