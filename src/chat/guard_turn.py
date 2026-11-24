"""The guardrail in front of the chat router: a typed message that is not about travel stops here."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from chat.handlers import data_text
from chat.history import message_for_model
from db.repositories.messages import MessageRow
from guardrail import Decision, load_guardrail
from models.model_router import CallContext, ModelRouter

# Text files of the guards, read once at import so a missing file fails at startup
PROMPT_DIR = Path(__file__).resolve().parents[1] / "guardrail" / "prompt"
# System prompt of the travel_only judge; {categories}, {output_note} and {context_note} are filled
# by the guard, literal braces are doubled
TOPIC_PROMPT = (PROMPT_DIR / "topic_prompt.txt").read_text(encoding="utf-8")
# One phrase per line, blocked without a model call (whole-word, any case)
DENYLIST = [
    line.strip()
    for line in (PROMPT_DIR / "denylist.txt").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
# The guards a typed message goes through, top to bottom, cheap first. The llm_judge has no model:
# RouterChatClient uses the "guard" purpose chain (CLASSIFIER_MODELS), so its calls are logged in
# llm_calls and count toward the chat ceiling. No max_length guard: SendMessageBody already caps a
# message at 4000 characters.
GUARDRAIL_CONFIG: Mapping[str, Any] = {
    "input": [
        {"type": "keyword", "name": "denylist", "words": DENYLIST, "action": "block"},
        {
            "type": "llm_judge",
            "name": "travel_only",
            "prompt": TOPIC_PROMPT,
            "categories": ["off_topic", "prompt_injection", "harmful"],
            "threshold": 0.7,
            "timeout_s": 30,
            # A failed check lets the message through: the handler after it reports an outage
            "on_error": "allow",
        },
    ]
}
# JSON mode: the judge's verdict has no schema the router knows, only that it is one object
JSON_OBJECT = {"type": "json_object"}
# The turns the judge sees before the message, enough for a short reply to read in context
GUARD_HISTORY_MESSAGES = 4
# The reply to a blocked message, as (English, Vietnamese)
OFF_TOPIC = (
    "I can only help with travel: where to go, trip plans, hotels, tickets, weather, food and "
    "travel tips. Where would you like to go?",
    "Mình chỉ hỗ trợ các câu hỏi về du lịch: đi đâu, lịch trình, khách sạn, vé, thời tiết, ăn "
    "uống và kinh nghiệm đi lại. Bạn muốn đi đâu nào?",
)


# The model router as the guardrail's chat client: no model means the "guard" fallback chain, and
# every call is logged against this turn
class RouterChatClient:
    def __init__(self, router: ModelRouter, ctx: CallContext) -> None:
        self.router = router
        self.ctx = ctx

    # The router is sync, so it runs in a thread and the guard's timeout still applies. Every guard
    # that calls a model expects a JSON verdict, so JSON mode is always on.
    # ponytail: temperature is ignored, the provider's own setting is used
    async def complete(
        self, model: str | None, messages: Sequence[dict[str, str]], temperature: float = 0.0
    ) -> str:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [m for m in messages if m["role"] != "system"]
        if model is None:
            response = await asyncio.to_thread(
                self.router.invoke, "guard", rest, system, self.ctx, JSON_OBJECT
            )
        else:
            response = await asyncio.to_thread(
                self.router.invoke_model, model, "guard", rest, system, self.ctx, JSON_OBJECT
            )
        return response.answer


# Run the input guards on a typed message, with the last turns as context. The chat flow is sync,
# so the async pipeline runs on its own event loop in the streaming thread.
# ponytail: the guards are built per turn (cheap without files); an embedding guard would embed its
# examples every turn, so build once at startup and share a loop before adding one
def check_message(
    config: Mapping[str, Any],
    router: ModelRouter,
    ctx: CallContext,
    message: str,
    history: Sequence[MessageRow],
) -> Decision:
    guardrail = load_guardrail(config, chat_client=RouterChatClient(router, ctx))
    turns = "\n".join(
        f"{m.role}: {data_text(message_for_model(m))}" for m in history[-GUARD_HISTORY_MESSAGES:]
    )

    return asyncio.run(guardrail.check_input(message, conversation=turns or None))
