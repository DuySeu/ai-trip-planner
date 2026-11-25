"""Base of every agent: one stateless object per request, every LLM call through the ModelRouter
(fallback chain, call log, quota blocks, budget, repair)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from collections.abc import Set as AbstractSet

from pydantic import BaseModel

from models.model_router import CallContext, ModelRouter, Purpose, call_json, compact_schema


class BaseAgent:
    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    # One structured call: the prompt gets the schema without the drop fields, content is the
    # single user message; the reply is validated, and repaired once when it fails or check fails
    def ask_json[T: BaseModel](
        self,
        purpose: Purpose,
        prompt: str,
        schema: type[T],
        content: str,
        ctx: CallContext,
        check: Callable[[T], list[str]] | None = None,
        drop: Mapping[str, AbstractSet[str]] | None = None,
    ) -> T:
        system = prompt.format(schema=compact_schema(schema, drop or {}))
        messages = [{"role": "user", "content": content}]
        return call_json(self.router, purpose, system, messages, schema, check, ctx, drop).value
