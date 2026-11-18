"""Discover answer agent: answers a general question about places, seasons, costs or visas.

One LLM call (purpose ``discover``), no search. The caller renders the context; this agent
only builds the prompt and returns the validated reply."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from core.prompts import discovery_answer_prompt
from domain.discovery import HIDDEN_FIELDS, DiscoveryReply, discovery_content
from models.model_router import CallContext, ModelRouter, call_json, compact_schema


class DiscoverAnswerAgent:
    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    # Answer the question and note what the chat tells about the trip
    # conversation is the rendered <conversation> block, "" when there is none
    def run(
        self,
        draft: Mapping[str, Any],
        today: date,
        conversation: str,
        message: str,
        ctx: CallContext,
    ) -> DiscoveryReply:
        system = discovery_answer_prompt.format(
            schema=compact_schema(DiscoveryReply, HIDDEN_FIELDS)
        )
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
