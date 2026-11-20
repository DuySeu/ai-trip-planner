"""How a message reads to the model: cards and forms hold their data in metadata, so history shows a
short line for them."""

from __future__ import annotations

from typing import Any

from db.repositories.messages import MessageRow


# The text the model sees for a message; a trip form or a questionnaire card becomes one line
def message_for_model(message: MessageRow) -> str:
    meta = message.metadata or {}
    if message.intent == "create_trip":
        return _trip_form_line(meta)
    if message.intent == "discover" and meta.get("kind") == "questionnaire" and not message.content:
        answers = meta.get("answers")
        known = ", ".join(sorted(answers)) if isinstance(answers, dict) and answers else "nothing"
        return f"[questionnaire: {meta.get('status', '?')}, answered {known}]"
    return message.content


# "[trip form: place, when, status]"; a draft that is not an object gives a bare marker
def _trip_form_line(meta: dict[str, Any]) -> str:
    form = meta.get("draft")
    if not isinstance(form, dict):
        return "[trip form]"
    destination = form.get("destination")
    place = destination.get("name") if isinstance(destination, dict) else None
    if form.get("start_date") and form.get("end_date"):
        when = f"{form['start_date']} to {form['end_date']}"
    elif form.get("length_days"):
        when = f"{form['length_days']} days"
    else:
        when = "no dates"
    return f"[trip form: {place or '?'}, {when}, {meta.get('status', '?')}]"
