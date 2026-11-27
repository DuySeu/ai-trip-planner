"""Orchestrator agent.

Reads a conversation plus the caller's agent catalog and returns a
``RoutingDecision``. It only decides; it never runs an agent. Stateless: the
same ``messages`` and ``catalog`` always produce the same LLM input.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from agents.base_agent import BaseAgent
from core.prompts import orchestrator_prompt, orchestrator_repair_prompt
from models.model_router import CallContext
from orchestration.routing_schema import (
    AgentSpec,
    LLMRoutingOutput,
    RoutingDecision,
    RoutingMeta,
    parse_output,
)


class OrchestratorAgent(BaseAgent):
    # Decide which agents handle the last user message and how they are arranged; each call goes
    # through the router's classify chain. The parser and repair stay here: errors depend on catalog
    def route(
        self, messages: Sequence[Mapping[str, Any]], catalog: Sequence[AgentSpec], ctx: CallContext
    ) -> RoutingDecision:
        # Validate the catalog: non-empty, names unique ignoring case
        if not catalog:
            raise ValueError("catalog is empty")
        folded = [spec.name.casefold() for spec in catalog]
        duplicates = sorted({name for name in folded if folded.count(name) > 1})
        if duplicates:
            raise ValueError(f"catalog has duplicate agent names (case-insensitive): {duplicates}")

        # The request is the last original message; filtering applies to history only
        if not messages:
            raise ValueError("messages is empty")
        last = messages[-1]
        if last.get("role") != "user":
            raise ValueError("the last message must have role 'user'")
        request = _message_text(last.get("content"))
        if not request:
            raise ValueError("the last message has no text")
        history = [
            (message["role"], text)
            for message in messages[:-1]
            if message.get("role") in ("user", "assistant")
            and (text := _message_text(message.get("content")))
        ]

        # Build the system prompt and the single wrapped user message
        system_prompt = orchestrator_prompt.format(
            catalog="\n".join(f"- {spec.name}: {spec.description}" for spec in catalog),
            schema=json.dumps(LLMRoutingOutput.model_json_schema()),
        )
        conversation = ""
        if history:
            lines = "\n".join(f"{role}: {text}" for role, text in history)
            conversation = f"<conversation>\n{lines}\n</conversation>\n"
        user_payload = {
            "role": "user",
            "content": f"{conversation}<request>\n{request}\n</request>",
        }

        # Attempt 1
        response, model_id = self.router.invoke_with_model(
            "classify", [user_payload], system_prompt, ctx
        )
        input_tokens, output_tokens = response.input_tokens, response.output_tokens
        output, errors = parse_output(response.answer, catalog)
        attempts = 1

        # Attempt 2: show the model its own answer and the errors
        if errors:
            repair_messages = [
                user_payload,
                {"role": "assistant", "content": response.answer or "(empty)"},
                {
                    "role": "user",
                    "content": orchestrator_repair_prompt.format(errors="\n".join(errors)),
                },
            ]
            response, model_id = self.router.invoke_with_model(
                "classify", repair_messages, system_prompt, ctx
            )
            input_tokens += response.input_tokens
            output_tokens += response.output_tokens
            output, errors = parse_output(response.answer, catalog)
            attempts = 2

        meta = RoutingMeta(
            model_id=model_id,
            attempts=attempts,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error="; ".join(errors) if errors else None,
        )
        if output is None:
            return RoutingDecision(
                status="fallback",
                architecture=None,
                steps=[],
                aggregation=None,
                clarification=None,
                reasoning="",
                meta=meta,
            )
        return RoutingDecision(**output.model_dump(), meta=meta)


# Extract stripped text from a message content: a string, or the text blocks of a block list
def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        return "\n".join(texts).strip()
    return ""
