from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from uuid import UUID

import pytest

from core.logger import configure_logging, log_context


@pytest.fixture
def root_logger() -> Iterator[logging.Logger]:
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    yield root
    root.handlers, root.level = saved_handlers, saved_level


def last_line(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    return json.loads(capsys.readouterr().err.strip().splitlines()[-1])


def test_log_line_is_json_with_time_level_logger_message(root_logger, capsys):
    configure_logging("INFO")
    logging.getLogger("jobs.worker").info("started %s", "w1")
    line = last_line(capsys)
    assert (line["level"], line["logger"], line["message"]) == ("INFO", "jobs.worker", "started w1")
    assert str(line["time"]).endswith("+00:00")


def test_log_context_adds_fields_inside_block_and_removes_them_after(root_logger, capsys):
    configure_logging("INFO")
    log = logging.getLogger("t")
    trip_id = UUID("11111111-1111-1111-1111-111111111111")
    with log_context(trip_id=trip_id, job_id="j1"):
        log.info("inside")
        inside = last_line(capsys)
    log.info("outside")
    outside = last_line(capsys)
    assert (inside["trip_id"], inside["job_id"]) == (str(trip_id), "j1")
    assert "trip_id" not in outside and "job_id" not in outside


def test_nested_log_context_merges_and_restores_outer_fields(root_logger, capsys):
    configure_logging("INFO")
    log = logging.getLogger("t")
    with log_context(request_id="r1"):
        with log_context(model_id="m1"):
            log.info("both")
            both = last_line(capsys)
        log.info("outer only")
        outer = last_line(capsys)
    assert (both["request_id"], both["model_id"]) == ("r1", "m1")
    assert outer["request_id"] == "r1" and "model_id" not in outer


def test_configure_logging_twice_keeps_one_handler_and_respects_level(root_logger, capsys):
    configure_logging("INFO")
    configure_logging("WARNING")
    logging.getLogger("t").info("hidden")
    logging.getLogger("t").warning("shown")
    lines = capsys.readouterr().err.strip().splitlines()
    assert [json.loads(line)["message"] for line in lines] == ["shown"]


def test_exception_text_is_included_in_the_line(root_logger, capsys):
    configure_logging("INFO")
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("t").exception("failed")
    assert "ValueError: boom" in str(last_line(capsys)["exc_info"])


def test_configure_logging_rejects_unknown_level(root_logger):
    with pytest.raises(ValueError):
        configure_logging("LOUD")
