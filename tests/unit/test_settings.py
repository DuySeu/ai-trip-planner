from __future__ import annotations

import pytest

from core.settings import load_db_settings, load_settings

MIN_ENV = {
    "DB_USER": "postgres",
    "DB_PASSWORD": "secret",
    "DB_NAME": "trip",
    "OPENROUTER_API_KEY": "or-key",
    "TAVILY_API_KEY": "tv-key",
    "PLANNER_MODELS": "a/b:free, c/d:free",
    "CHAT_MODELS": "a/b:free",
    "CLASSIFIER_MODELS": "a/b:free",
    "DAILY_LLM_CEILING_NEW_TRIPS": "800",
    "DAILY_LLM_CEILING_CHAT": "950",
    "DAILY_TAVILY_CEILING": "30",
}


def test_load_settings_reads_required_and_defaults():
    s = load_settings(MIN_ENV)
    assert s.planner_models == ("a/b:free", "c/d:free")
    assert s.llm_calls_per_job == 6
    assert s.trust_proxy_headers is False
    assert s.retention_days == 30
    assert s.cors_origins == ("http://localhost:5173",)
    assert (s.db.host, s.db.port, s.db.sslmode) == ("localhost", 5432, "prefer")


def test_load_settings_names_every_missing_variable():
    with pytest.raises(ValueError) as e:
        load_settings({})
    assert "DB_PASSWORD" in str(e.value)
    assert "TAVILY_API_KEY" in str(e.value)


def test_load_settings_rejects_chat_ceiling_below_trip_ceiling():
    with pytest.raises(ValueError):
        load_settings(
            {**MIN_ENV, "DAILY_LLM_CEILING_CHAT": "10", "DAILY_LLM_CEILING_NEW_TRIPS": "20"}
        )


def test_load_settings_rejects_non_integer_value():
    with pytest.raises(ValueError) as e:
        load_settings({**MIN_ENV, "DB_PORT": "abc"})
    assert "DB_PORT" in str(e.value)


def test_load_settings_parses_boolean_flag():
    assert load_settings({**MIN_ENV, "TRUST_PROXY_HEADERS": "true"}).trust_proxy_headers is True


def test_db_conninfo_uses_every_db_variable_and_can_switch_database():
    db = load_db_settings(
        {
            "DB_HOST": "db.local",
            "DB_PORT": "55435",
            "DB_USER": "postgres",
            "DB_PASSWORD": "p w'd",
            "DB_NAME": "vcbdev",
            "DB_SSLMODE": "disable",
        }
    )
    assert db.conninfo() == (
        "host=db.local port=55435 user=postgres password='p w\\'d' dbname=vcbdev sslmode=disable"
    )
    assert "dbname=vcbdev_test" in db.conninfo("vcbdev_test")


def test_load_db_settings_needs_only_db_variables():
    db = load_db_settings({"DB_USER": "u", "DB_PASSWORD": "p", "DB_NAME": "n"})
    assert db.name == "n"
