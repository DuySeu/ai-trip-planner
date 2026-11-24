"""Typed settings loaded once from the environment at startup."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import MISSING, dataclass, fields
from typing import Any

from psycopg.conninfo import make_conninfo

BOOL_VALUES = {
    "1": True,
    "true": True,
    "yes": True,
    "on": True,
    "0": False,
    "false": False,
    "no": False,
    "off": False,
}

PARSERS: dict[str, Callable[[str], Any]] = {
    "str": str,
    "int": int,
    "bool": lambda raw: BOOL_VALUES[raw.lower()],
    "tuple[str, ...]": lambda raw: tuple(part.strip() for part in raw.split(",") if part.strip()),
}


# Postgres connection, read from DB_* variables
@dataclass(frozen=True)
class DbSettings:
    user: str
    password: str
    name: str
    host: str = "localhost"
    port: int = 5432
    sslmode: str = "prefer"

    # libpq connection string, optionally for another database on the same server
    def conninfo(self, dbname: str | None = None) -> str:
        return make_conninfo(
            "",
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=dbname or self.name,
            sslmode=self.sslmode,
        )


# Every setting the backend reads; .env.example says what each one means
@dataclass(frozen=True)
class Settings:
    db: DbSettings
    openrouter_api_key: str
    tavily_api_key: str
    planner_models: tuple[str, ...]
    chat_models: tuple[str, ...]
    classifier_models: tuple[str, ...]
    daily_llm_ceiling_new_trips: int
    daily_llm_ceiling_chat: int
    daily_tavily_ceiling: int
    llm_calls_per_job: int = 6
    planner_timeout_s: int = 90
    chat_timeout_s: int = 30
    quota_reset_hour_utc: int = 0
    openrouter_daily_cap_pattern: str = "free-models-per-day"
    tavily_quota_pattern: str = "usage limit"
    user_inactive_days: int = 90
    trust_proxy_headers: bool = False
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    ip_requests_per_minute: int = 30
    ip_chat_per_minute: int = 10
    ip_trips_per_day: int = 10
    ip_chat_per_day: int = 200
    user_trips_per_day: int = 5
    user_chat_per_day: int = 100
    template_path: str = "data/trip-template.xlsx"


# Read only the DB_* variables (for migrations and tests, which need no API keys)
def load_db_settings(env: Mapping[str, str]) -> DbSettings:
    values, problems = _read_fields(DbSettings, env, prefix="DB_")
    if problems:
        raise ValueError(f"Invalid settings: {'; '.join(problems)}")
    return DbSettings(**values)


# Build Settings from an environment mapping, reporting every problem at once
def load_settings(env: Mapping[str, str]) -> Settings:
    db_values, db_problems = _read_fields(DbSettings, env, prefix="DB_")
    values, problems = _read_fields(Settings, env, prefix="", skip={"db"})
    problems = db_problems + problems
    if problems:
        raise ValueError(f"Invalid settings: {'; '.join(problems)}")

    settings = Settings(db=DbSettings(**db_values), **values)
    if settings.daily_llm_ceiling_chat <= settings.daily_llm_ceiling_new_trips:
        raise ValueError(
            "Invalid settings: DAILY_LLM_CEILING_CHAT must be greater than "
            "DAILY_LLM_CEILING_NEW_TRIPS"
        )
    return settings


# Parse a dataclass's fields from env as PREFIX + FIELD_NAME; return values and problems
def _read_fields(
    cls: type, env: Mapping[str, str], prefix: str, skip: frozenset[str] | set[str] = frozenset()
) -> tuple[dict[str, Any], list[str]]:
    values: dict[str, Any] = {}
    missing: list[str] = []
    invalid: list[str] = []

    for field in fields(cls):
        if field.name in skip:
            continue
        name = f"{prefix}{field.name}".upper()
        raw = env.get(name, "").strip()

        # Keep the default, or record a missing required variable
        if not raw:
            if field.default is MISSING:
                missing.append(name)
            continue

        # Parse by the field's declared type
        try:
            values[field.name] = PARSERS[str(field.type)](raw)
        except (ValueError, KeyError):
            invalid.append(f"{name}={raw!r} is not a valid {field.type}")

    return values, ([f"missing {', '.join(missing)}"] if missing else []) + invalid
