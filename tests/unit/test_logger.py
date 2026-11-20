from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from uuid import UUID

import pytest

from core.logger import ColorFormatter, fmt, log_context, setup_logging


@pytest.fixture
def root_logger(monkeypatch: pytest.MonkeyPatch) -> Iterator[logging.Logger]:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    yield root
    root.handlers, root.level = saved_handlers, saved_level


def lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().err.strip().splitlines()


def test_line_shows_time_file_level_and_message(root_logger, capsys):
    setup_logging()
    logging.getLogger("jobs.worker").info("started %s", "w1")
    (line,) = lines(capsys)
    assert re.fullmatch(r"\d\d:\d\d:\d\d \| tests/unit/test_logger\.py \| INFO \| started w1", line)


def test_log_context_appends_fields_inside_block_and_drops_them_after(root_logger, capsys):
    setup_logging()
    log = logging.getLogger("t")
    trip_id = UUID("11111111-1111-1111-1111-111111111111")
    with log_context(trip_id=trip_id, job_id="j1"):
        log.info("inside")
    log.info("outside")
    inside, outside = lines(capsys)
    assert inside.endswith(f"| inside | trip_id={trip_id} job_id=j1")
    assert outside.endswith("| outside")


def test_nested_log_context_merges_and_restores_outer_fields(root_logger, capsys):
    setup_logging()
    log = logging.getLogger("t")
    with log_context(request_id="r1"):
        with log_context(model_id="m1"):
            log.info("both")
        log.info("outer only")
    both, outer = lines(capsys)
    assert both.endswith("| both | request_id=r1 model_id=m1")
    assert outer.endswith("| outer only | request_id=r1")


def test_setup_logging_twice_keeps_one_handler_and_reads_level_from_env(
    root_logger, capsys, monkeypatch
):
    setup_logging()
    monkeypatch.setenv("LOG_LEVEL", "warning")
    setup_logging()
    logging.getLogger("t").info("hidden")
    logging.getLogger("t").warning("shown")
    assert [line.split(" | ")[-1] for line in lines(capsys)] == ["shown"]


def test_unknown_log_level_falls_back_to_info(root_logger, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "LOUD")
    setup_logging()
    assert root_logger.level == logging.INFO


def test_exception_text_follows_the_line_with_context_on_the_first_line(root_logger, capsys):
    setup_logging()
    with log_context(request_id="r1"):
        try:
            raise ValueError("boom")
        except ValueError:
            logging.getLogger("t").exception("failed")
    out = lines(capsys)
    assert out[0].endswith("| failed | request_id=r1")
    assert out[-1] == "ValueError: boom"


def test_color_wraps_the_line_in_the_level_color():
    formatter = ColorFormatter(use_color=True)
    record = logging.LogRecord("t", logging.WARNING, __file__, 1, "careful", None, None)
    assert formatter.format(record).startswith("\033[33m")
    assert formatter.format(record).endswith("\033[0m")


def test_uvicorn_lines_go_through_the_same_format_named_by_logger(root_logger, capsys):
    loggers = [logging.getLogger(name) for name in ("uvicorn", "uvicorn.access")]
    saved = [(lg.handlers, lg.propagate) for lg in loggers]
    for lg in loggers:
        lg.handlers, lg.propagate = [logging.StreamHandler()], False
    try:
        setup_logging()
        access = logging.getLogger("uvicorn.access")
        record = access.makeRecord(
            "uvicorn.access",
            logging.INFO,
            "/elsewhere/uvicorn/h11_impl.py",
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:1", "GET", "/trips/x", "1.1", 200),
            None,
        )
        access.handle(record)
        (line,) = lines(capsys)
    finally:
        for lg, (handlers, propagate) in zip(loggers, saved, strict=True):
            lg.handlers, lg.propagate = handlers, propagate
    assert re.fullmatch(
        r'\d\d:\d\d:\d\d \| uvicorn\.access \| INFO \| 127\.0\.0\.1:1 - "GET /trips/x HTTP/1\.1" 200',
        line,
    )


def test_fmt_renders_collections_as_json_and_others_as_text():
    assert fmt({"city": "Huế", "days": 3}) == '{"city": "Huế", "days": 3}'
    assert fmt([1, 2], pretty=True) == "[\n  1,\n  2\n]"
    assert fmt(42) == "42"
