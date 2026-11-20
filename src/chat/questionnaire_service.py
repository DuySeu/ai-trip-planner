"""Save one answer of a questionnaire card: no router, no model call."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any
from uuid import UUID

from psycopg import Connection

from core.exceptions import Conflict, InvalidInput, NotFound
from db.repositories import conversations, messages
from db.repositories.messages import MessageRow
from domain.discovery import RequestDraft
from domain.questionnaire import answer_for

# Styles the budget step adds; answering the styles step again keeps them
BUDGET_STYLES = ("budget", "luxury")


# Turn the answer into draft fields, then write them into the card and the conversation's draft.
# step only grows, so answering an earlier step again leaves it where it was
def answer_questionnaire(
    conn: Connection[Any],
    conversation_id: UUID,
    message_id: UUID,
    step: int,
    choice: str | list[str] | None,
    typed: Mapping[str, Any],
    today: date,
) -> MessageRow:
    # Locked so two answers sent at once cannot both start from the same card and draft
    card = messages.get_message(conn, message_id, lock=True)
    if card.conversation_id != conversation_id:
        raise NotFound(f"message {message_id}")
    meta = card.metadata or {}
    if card.intent != "discover" or meta.get("kind") != "questionnaire":
        raise Conflict(f"message {message_id} is not a questionnaire")
    if meta.get("status") != "open":
        raise Conflict(f"questionnaire {message_id} is already closed")
    try:
        fields = answer_for(step, choice, typed, today)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc

    draft = conversations.get_conversation(conn, conversation_id).request_draft or {}
    old_styles = draft.get("travel_styles") or []
    if "travel_styles" in fields or (step == 3 and fields):
        styles = _styles(old_styles, fields, step)
        if "travel_styles" in fields or styles != old_styles:
            fields["travel_styles"] = styles
    answers = RequestDraft.model_validate(fields).model_dump(mode="json", include=set(fields))
    metadata = {
        **meta,
        "step": max(int(meta.get("step", 0)), step),
        "answers": {**meta.get("answers", {}), **answers},
        "choices": {**meta.get("choices", {}), str(step): choice},
    }
    saved = messages.update_open_metadata(conn, message_id, {"status": "open"}, metadata)
    if saved is None:
        raise Conflict(f"questionnaire {message_id} is already closed")
    conversations.save_draft(conn, conversation_id, {**draft, **answers})
    return saved


# The styles step replaces the chosen styles but keeps a budget style; the budget step swaps the
# budget style for its own (or none)
def _styles(old: list[str], fields: Mapping[str, Any], step: int) -> list[str]:
    new = list(fields.get("travel_styles", []))
    if step == 1:
        return [*new, *(s for s in old if s in BUDGET_STYLES and s not in new)]
    kept = [s for s in old if s not in BUDGET_STYLES]
    return list(dict.fromkeys([*kept, *new]))
