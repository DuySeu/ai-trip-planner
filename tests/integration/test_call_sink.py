from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.call_sink import DbCallSink
from db.repositories.llm_calls import LlmCallRecord, count_today


def test_log_call_persists_outcome(db_pool, db_conn):
    record = LlmCallRecord(
        purpose="generate",
        model_id="vendor/model:free",
        outcome="rate_limited",
        input_tokens=120,
        output_tokens=0,
        latency_ms=850,
        error="429",
    )
    DbCallSink(db_pool).log(record)
    row = db_conn.execute(
        "SELECT purpose, model_id, outcome, input_tokens, output_tokens, latency_ms, error "
        "FROM llm_calls"
    ).fetchall()
    assert row == [("generate", "vendor/model:free", "rate_limited", 120, 0, 850, "429")]
    assert count_today(db_conn) == 1


def test_block_then_blocked_until_returns_time(db_pool):
    sink = DbCallSink(db_pool)
    until = datetime.now(UTC) + timedelta(hours=3)
    sink.block("openrouter", until, "free-models-per-day")
    assert sink.blocked_until("openrouter") == until
    assert sink.blocked_until("tavily") is None


def test_expired_block_returns_none(db_pool):
    sink = DbCallSink(db_pool)
    sink.block("openrouter", datetime.now(UTC) - timedelta(minutes=1), "old")
    assert sink.blocked_until("openrouter") is None


def test_a_second_block_replaces_the_first(db_pool):
    sink = DbCallSink(db_pool)
    later = datetime.now(UTC) + timedelta(hours=9)
    sink.block("openrouter", datetime.now(UTC) + timedelta(hours=1), "first")
    sink.block("openrouter", later, "second")
    assert sink.blocked_until("openrouter") == later
