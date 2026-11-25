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
# The guards a typed message goes through, top to bottom, cheap first. The llm_judge has no model,
# so the router uses the "guard" purpose chain (CLASSIFIER_MODELS): its calls are logged in
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
# The turns the judge sees before the message, enough for a short reply to read in context
GUARD_HISTORY_MESSAGES = 4
# The reply to a blocked message, as (English, Vietnamese)
OFF_TOPIC = (
    "I can only help with travel: where to go, trip plans, hotels, tickets, weather, food and "
    "travel tips. Where would you like to go?",
    "Mình chỉ hỗ trợ các câu hỏi về du lịch: đi đâu, lịch trình, khách sạn, vé, thời tiết, ăn "
    "uống và kinh nghiệm đi lại. Bạn muốn đi đâu nào?",
)


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
    guardrail = load_guardrail(config, router=router, ctx=ctx)
    turns = "\n".join(
        f"{m.role}: {data_text(message_for_model(m))}" for m in history[-GUARD_HISTORY_MESSAGES:]
    )

    return asyncio.run(guardrail.check_input(message, conversation=turns or None))
