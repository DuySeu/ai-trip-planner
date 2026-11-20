"""Central logging setup: one colored text line per record, with per-request, per-job fields.

Usage in code:
    from core.logger import setup_logging
    setup_logging()

    import logging
    logger = logging.getLogger(__name__)
    logger.info("reading input")

Terminal output (one colored line per record):
    17:23:31 | src/chat/chat_service.py | INFO | reading input | request_id=f02c3056
    <time> | <file path from the working directory> | <LEVEL> | <message> | <log_context fields>
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any

LOG_FORMAT = "%(asctime)s | %(relpath)s | %(levelname)s | %(message)s"
DATE_FORMAT = "%H:%M:%S"

_RESET = "\033[0m"
_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}

# Fields added to every line logged inside log_context (request_id, trip_id, job_id, model_id)
_context: ContextVar[Mapping[str, str]] = ContextVar("log_context", default=MappingProxyType({}))


# Shows the source file relative to `root`, appends the log_context fields to the first line
# and wraps the whole record in an ANSI color for its level
class ColorFormatter(logging.Formatter):
    def __init__(
        self,
        fmt: str = LOG_FORMAT,
        datefmt: str | None = DATE_FORMAT,
        use_color: bool = True,
        root: str | None = None,
    ) -> None:
        super().__init__(fmt, datefmt)
        self.use_color = use_color
        self.root = root or os.getcwd()

    # Render the record, colored when use_color is set
    def format(self, record: logging.LogRecord) -> str:
        try:
            relpath = os.path.relpath(record.pathname, self.root)
        except ValueError:  # e.g. different drive on Windows
            relpath = record.pathname
        # A library file (uvicorn in the venv) is named by its logger, not by a "../" path
        record.relpath = record.name if relpath.startswith("..") else relpath
        line = super().format(record)
        if not self.use_color:
            return line
        color = _LEVEL_COLORS.get(record.levelno, "")
        return f"{color}{line}{_RESET}" if color else line

    # The first line of the record, before any exception text, with the context fields
    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802
        line = super().formatMessage(record)
        fields = _context.get()
        if not fields:
            return line
        return line + " | " + " ".join(f"{k}={v}" for k, v in fields.items())


# Send every record to stderr through one ColorFormatter handler; level from LOG_LEVEL (default
# INFO, unknown names fall back to INFO). Safe to call again: it replaces its own handler only.
def setup_logging(fmt: str = LOG_FORMAT, datefmt: str = DATE_FORMAT) -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    for old in [h for h in root.handlers if isinstance(h.formatter, ColorFormatter)]:
        root.removeHandler(old)

    handler = logging.StreamHandler()
    use_color = handler.stream.isatty() and os.environ.get("NO_COLOR") is None
    handler.setFormatter(ColorFormatter(fmt, datefmt, use_color=use_color, root=os.getcwd()))
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own handlers on these loggers; send their records to root instead
    for name in ("uvicorn", "uvicorn.access"):
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True


# Add fields to every log line written inside the block, on top of any outer block's fields
@contextmanager
def log_context(**fields: object) -> Iterator[None]:
    token = _context.set({**_context.get(), **{k: str(v) for k, v in fields.items()}})
    try:
        yield
    finally:
        _context.reset(token)


# Render a value for a log message:
# dict / list / tuple -> JSON (compact, or indented when pretty=True);
# anything with .to_string() (pandas DataFrame / Series) -> text table on new lines;
# everything else -> str(obj).
#     logger.info("input: %s", fmt(payload))
#     logger.info("frame:%s", fmt(df, pretty=True))
def fmt(obj: Any, *, pretty: bool = False) -> str:
    if isinstance(obj, (dict, list, tuple)):
        return json.dumps(obj, ensure_ascii=False, default=str, indent=2 if pretty else None)
    to_string = getattr(obj, "to_string", None)
    if callable(to_string):
        return "\n" + str(to_string())
    return str(obj)
