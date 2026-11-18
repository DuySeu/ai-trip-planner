"""Builders shared by the API and the worker, so both route LLM calls the same way."""

from __future__ import annotations

import functools
from collections.abc import Callable
from datetime import datetime

from psycopg_pool import ConnectionPool

from core.settings import Settings
from db.call_sink import DbCallSink
from models.model_router import ModelRouter, Purpose
from models.provider import OpenRouterProvider


# The model router: fallback chains from settings, calls and quota blocks kept in the database
def build_router(
    settings: Settings, pool: ConnectionPool, now: Callable[[], datetime]
) -> ModelRouter:
    # A model of the planner chain gets the planner timeout, any other the chat timeout
    @functools.cache
    def provider_for(model_id: str) -> OpenRouterProvider:
        timeout = (
            settings.planner_timeout_s
            if model_id in settings.planner_models
            else settings.chat_timeout_s
        )
        return OpenRouterProvider(model_id, {}, timeout_s=timeout)

    models: dict[Purpose, tuple[str, ...]] = {
        "generate": settings.planner_models,
        "repair": settings.planner_models,
        "edit": settings.planner_models,
        "classify": settings.classifier_models,
        "answer": settings.chat_models,
        "discover": settings.chat_models,
        "suggest": settings.chat_models,
    }
    return ModelRouter(
        provider_for=provider_for,
        models=models,
        sink=DbCallSink(pool),
        daily_cap_pattern=settings.openrouter_daily_cap_pattern,
        reset_hour_utc=settings.quota_reset_hour_utc,
        now=now,
    )
