"""Manual smoke run against the real stack (real LLM, Tavily, Open-Meteo); not part of the suite.

PYTHONPATH=src uv run python scripts/smoke.py            # API on http://localhost:8000
API_URL=http://host:8000 PYTHONPATH=src uv run python scripts/smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import date, timedelta
from typing import Any

import httpx
import psycopg
from dotenv import load_dotenv

from core.settings import load_db_settings

API_URL = os.environ.get("API_URL", "http://localhost:8000")
POLL_SECONDS = 3
TIMEOUT_SECONDS = 300
FINAL_STATUSES = {"ready", "failed"}


# Print one step's result
def report(step: str, detail: str) -> None:
    print(f"[{step}] {detail}", flush=True)


# Read the data field of an envelope response, failing loudly with the error body
def data_of(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        raise SystemExit(f"HTTP {response.status_code} on {response.request.url}: {response.text}")
    return response.json()["data"]


# Send one chat message and return (events, text) from the SSE stream
def chat(
    client: httpx.Client, conversation_id: str, content: str, trip_id: str, revision: int
) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    events: list[tuple[str, dict[str, Any]]] = []
    body = {
        "conversation_id": conversation_id,
        "content": content,
        "trip_id": trip_id,
        "plan_revision": revision,
    }
    with client.stream("POST", "/chat", json=body) as stream:
        if stream.status_code >= 400:
            stream.read()
            raise SystemExit(f"HTTP {stream.status_code} on chat: {stream.text}")
        name = ""
        for line in stream.iter_lines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                events.append((name, json.loads(line.removeprefix("data: "))))
    text = "".join(data["text"] for kind, data in events if kind == "token")
    return events, text


def main() -> int:
    load_dotenv()
    with httpx.Client(base_url=API_URL, timeout=120) as client:
        user = data_of(client.post("/users", json={"name": f"smoke-{uuid.uuid4().hex[:8]}"}))
        report("user", f"claimed {user['name']}")

        places = data_of(client.get("/places", params={"q": "Da Lat"}))
        if not places:
            raise SystemExit("no place found for 'Da Lat'")
        place = places[0]
        report("places", f"{len(places)} result(s), using {place['name']} {place['country_code']}")

        start = date.today() + timedelta(days=7)
        trip_body = {
            "user_id": user["id"],
            "destination": {k: place[k] for k in ("name", "country_code", "lat", "lon")},
            "origin": "Ho Chi Minh City",
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=2)).isoformat(),
            "travelers": 2,
            "travel_styles": ["relax", "food"],
            "budget_amount": "6000000",
            "budget_scope": "total",
            "language": "en",
        }
        trip = data_of(client.post("/trips", json=trip_body))
        report("create", f"trip {trip['id']} status {trip['status']}")

        deadline = time.monotonic() + TIMEOUT_SECONDS
        current: dict[str, Any] = {}
        while time.monotonic() < deadline:
            current = data_of(client.get(f"/trips/{trip['id']}"))
            report("poll", f"{current['status']} stage={current['stage']}")
            if current["status"] in FINAL_STATUSES:
                break
            time.sleep(POLL_SECONDS)
        if current.get("status") != "ready":
            report("result", f"not ready: {current.get('status')} {current.get('failure_reason')}")
            return 1
        report(
            "result",
            f"ready, total {current['total_cost_vnd']} VND, over_budget={current['over_budget']}",
        )

        conversation = data_of(client.post("/conversations", json={"user_id": user["id"]}))
        trip_id, revision = trip["id"], current["plan_revision"]
        events, text = chat(
            client, conversation["id"], "What is the plan for day 1?", trip_id, revision
        )
        report("question", f"{[kind for kind, _ in events]} -> {text[:200]!r}")

        events, text = chat(
            client, conversation["id"], "Remove the last item of day 2.", trip_id, revision
        )
        report("edit", f"{[kind for kind, _ in events]} -> {text[:200]!r}")

        export = client.get(f"/trips/{trip_id}/export.xlsx")
        report("export", f"HTTP {export.status_code}, {len(export.content)} bytes")

    db = load_db_settings(os.environ)
    with psycopg.connect(db.conninfo()) as conn:
        trip_uuid = uuid.UUID(trip_id)
        llm = conn.execute(
            "SELECT purpose, model_id, outcome, count(*) FROM llm_calls WHERE trip_id = %s "
            "GROUP BY 1, 2, 3 ORDER BY 1",
            (trip_uuid,),
        ).fetchall()
        tavily = conn.execute(
            "SELECT count(*) FROM search_cache WHERE provider = 'tavily' AND created_at > now() - interval '1 hour'"
        ).fetchone()
    report("llm_calls", json.dumps([list(row) for row in llm]))
    report("tavily_calls", f"{tavily[0] if tavily else 0} cached in the last hour")
    return 0


if __name__ == "__main__":
    sys.exit(main())
