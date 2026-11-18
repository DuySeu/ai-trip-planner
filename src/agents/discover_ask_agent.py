"""Discover ask agent: one short follow-up question for a visitor who does not know where to go.

One LLM call (purpose ``discover``), no search. The caller renders the context; this agent
only builds the prompt and returns the validated reply."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from core.prompts import discovery_ask_prompt
from domain.discovery import HIDDEN_FIELDS, DiscoveryReply, discovery_content
from models.model_router import CallContext, ModelRouter, call_json, compact_schema


class DiscoverAskAgent:
    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    # Ask the next question and note what the chat already tells about the trip
    # conversation is the rendered <conversation> block, "" when there is none
    def run(
        self,
        draft: Mapping[str, Any],
        today: date,
        conversation: str,
        message: str,
        ctx: CallContext,
    ) -> DiscoveryReply:
        system = discovery_ask_prompt.format(schema=compact_schema(DiscoveryReply, HIDDEN_FIELDS))
        content = discovery_content(today, draft, conversation, message)
        return call_json(
            self.router,
            "discover",
            system,
            [{"role": "user", "content": content}],
            DiscoveryReply,
            None,
            ctx,
        ).value
