"""How a message reads to the model: trip form messages hold JSON, so history shows a short line."""

from __future__ import annotations

import json

from db.repositories.messages import MessageRow

TRIP_FORM_STATES = {"trip_form": "open", "created_trip": "created", "canceled_trip": "canceled"}
TRIP_FORM_INTENTS = frozenset(TRIP_FORM_STATES)


# The text the model sees for a message; a trip form becomes one line, not its JSON
def message_for_model(message: MessageRow) -> str:
    state = TRIP_FORM_STATES.get(message.intent or "")
    if state is None:
        return message.content

    # A form that is not a JSON object (old or hand-edited data) is a bare marker
    try:
        form = json.loads(message.content)
    except json.JSONDecodeError:
        return "[trip form]"
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
    return f"[trip form: {place or '?'}, {when}, {state}]"
