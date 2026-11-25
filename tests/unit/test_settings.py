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


WITHOUT_OPENROUTER_KEY = {k: v for k, v in MIN_ENV.items() if k != "OPENROUTER_API_KEY"}


def test_llm_provider_defaults_to_openrouter_with_4096_output_tokens():
    s = load_settings(MIN_ENV)
    assert (s.llm_provider, s.max_output_tokens) == ("openrouter", 4096)


@pytest.mark.parametrize("value", ["anthropic", "OpenAI"])
def test_load_settings_rejects_unknown_llm_provider(value):
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        load_settings({**MIN_ENV, "LLM_PROVIDER": value})


def test_load_settings_needs_the_key_of_the_chosen_provider():
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        load_settings(WITHOUT_OPENROUTER_KEY)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        load_settings({**WITHOUT_OPENROUTER_KEY, "LLM_PROVIDER": "openai"})
    openai_env = {**WITHOUT_OPENROUTER_KEY, "LLM_PROVIDER": "openai", "OPENAI_API_KEY": "k"}
    assert load_settings(openai_env).llm_provider == "openai"


def test_bedrock_needs_no_key():
    env = {**WITHOUT_OPENROUTER_KEY, "LLM_PROVIDER": "bedrock"}
    assert load_settings(env).llm_provider == "bedrock"


def test_provider_problem_is_reported_with_the_other_problems():
    env = {k: v for k, v in WITHOUT_OPENROUTER_KEY.items() if k != "TAVILY_API_KEY"}
    with pytest.raises(ValueError) as e:
        load_settings(env)
    assert "TAVILY_API_KEY" in str(e.value) and "OPENROUTER_API_KEY" in str(e.value)


def test_embedding_models_are_optional_and_parsed_like_the_other_chains():
    assert load_settings(MIN_ENV).embedding_models == ()
    env = {**MIN_ENV, "EMBEDDING_MODELS": "e/one:free, e/two:free"}
    assert load_settings(env).embedding_models == ("e/one:free", "e/two:free")
