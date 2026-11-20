from __future__ import annotations

import dataclasses
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook  # type: ignore[import-untyped]
from psycopg import Connection
from psycopg_pool import ConnectionPool

from api.routes.exports import ascii_file_name
from core.exceptions import Conflict
from core.settings import load_settings
from db.repositories import conversations, jobs, messages, quota, trips
from domain.trip_request import today_in_vietnam
from service.worker.generate_plan import run_generate_plan
from tests.fixtures.builders import (
    BANGKOK_FIELDS,
    DALAT_FIELDS,
    FIXTURES_DIR,
    bangkok_plan,
    dalat_plan,
)
from tests.integration.test_api_foundation import ENV, make_app
from tests.integration.test_generate_plan_job import NOW, make_rig
from tests.unit.test_plan_generator import answer

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# The Da Lat form body for a user, with dates ten days ahead so the start date rule holds
def trip_body(user_id: UUID | str, **overrides: Any) -> dict[str, Any]:
    start = today_in_vietnam(datetime.now(UTC)) + timedelta(days=10)
    fields = {
        **DALAT_FIELDS,
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=3)).isoformat(),
        "user_id": str(user_id),
    }
    return {**fields, **overrides}


# A client on an app over the test pool; env overrides change the settings
def make_client(pool: ConnectionPool, **env: str) -> TestClient:
    app = make_app(pool, load_settings({**ENV, **env}))
    return TestClient(app, raise_server_exceptions=False)


# A client plus a user who already claimed a name
@pytest.fixture
def client(db_pool: ConnectionPool) -> TestClient:
    return make_client(db_pool)


# The id of a user claimed through the API
def claim(client: TestClient, name: str = "Linh") -> str:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 200
    return str(response.json()["data"]["id"])


# A trip created through the API; returns its id
def create_trip(client: TestClient, user_id: str, **overrides: Any) -> str:
    response = client.post("/trips", json=trip_body(user_id, **overrides))
    assert response.status_code == 202, response.text
    return str(response.json()["data"]["id"])


# Give the trip the Da Lat plan and mark it ready, as a finished job would
def make_ready(conn: Connection[Any], trip_id: str) -> None:
    plan = dalat_plan().model_dump(mode="json")
    trips.save_plan(conn, UUID(trip_id), 0, plan, 1000, False, "fake/model")
    trips.set_status(conn, UUID(trip_id), "ready")


# An open trip form of the user in a new conversation; returns the conversation and message ids
def open_form(conn: Connection[Any], user_id: str, draft: dict[str, Any] | None = None):
    conversation = conversations.create_conversation(conn, UUID(user_id), draft)
    form = messages.add_message(conn, conversation.id, "assistant", "{}", "trip_form")
    return conversation, form


# --- users ---


def test_claim_user_twice_returns_same_id(client):
    first = client.post("/users", json={"name": "Linh"})
    second = client.post("/users", json={"name": "  linh "})
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["id"] == second.json()["data"]["id"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 51, "\x00\x01"])
def test_claim_user_with_invalid_name_returns_422(client, name):
    response = client.post("/users", json={"name": name})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_claim_user_stores_the_nfc_form_of_the_name(client):
    decomposed = "Lê"  # E + combining circumflex
    data = client.post("/users", json={"name": decomposed}).json()["data"]
    assert data["name"] == "Ê" or data["name"] == "Lê"


def test_get_user_returns_name_and_trip_count(client):
    user_id = claim(client)
    create_trip(client, user_id)
    data = client.get(f"/users/{user_id}").json()["data"]
    assert data["name"] == "Linh"
    assert data["trip_count"] == 1


def test_get_unknown_user_returns_404(client):
    response = client.get("/users/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_user_trips_are_newest_first_and_paged(client):
    user_id = claim(client)
    ids = [create_trip(client, user_id) for _ in range(3)]

    page = client.get(f"/users/{user_id}/trips", params={"limit": 2, "offset": 0}).json()
    assert [t["id"] for t in page["data"]] == [ids[2], ids[1]]
    assert page["meta"] == {"total": 3, "limit": 2, "offset": 0}
    rest = client.get(f"/users/{user_id}/trips", params={"limit": 2, "offset": 2}).json()
    assert [t["id"] for t in rest["data"]] == [ids[0]]
    assert "plan" not in rest["data"][0]


def test_user_trips_for_unknown_user_returns_404(client):
    assert client.get("/users/00000000-0000-0000-0000-000000000000/trips").status_code == 404


def test_user_trips_do_not_include_other_users_trips(client):
    mine, theirs = claim(client, "Mai"), claim(client, "Nam")
    create_trip(client, theirs)
    assert client.get(f"/users/{mine}/trips").json()["data"] == []


# --- places ---


# A client whose place search answers with the Da Lat fixture, or with an error
def places_client(pool: ConnectionPool, status: int = 200) -> TestClient:
    body = (FIXTURES_DIR / "geocoding_da_lat.json").read_text(encoding="utf-8")
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text=body))
    app = make_app(pool)
    app.state.deps = dataclasses.replace(app.state.deps, http=httpx.Client(transport=transport))
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("q", ["a", " a ", ""])
def test_places_requires_two_characters(db_pool, q):
    response = places_client(db_pool).get("/places", params={"q": q})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_places_without_q_returns_422(db_pool):
    assert places_client(db_pool).get("/places").status_code == 422


def test_places_returns_name_country_and_coordinates(db_pool):
    response = places_client(db_pool).get("/places", params={"q": "Da Lat"})
    assert response.status_code == 200
    first = response.json()["data"][0]
    assert first == {
        "name": "Da Lat",
        "admin1": "Lam Dong",
        "country_code": "VN",
        "lat": 11.94646,
        "lon": 108.44193,
    }


def test_places_returns_503_when_the_geocoder_is_down(db_pool):
    response = places_client(db_pool, status=500).get("/places", params={"q": "Da Lat"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"


# --- creating a trip ---


def test_create_trip_returns_202_and_queues_trip_and_job(client, db_conn):
    user_id = claim(client)
    response = client.post("/trips", json=trip_body(user_id))
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["status"] == "queued"

    trip = trips.get_trip(db_conn, UUID(data["id"]))
    assert trip.status == "queued"
    assert trip.destination_name == "Đà Lạt"
    job = jobs.active_job(db_conn, trip.id)
    assert job is not None and job.kind == "generate_plan"


def test_create_trip_derives_local_currency_from_country_not_from_client(client, db_conn):
    user_id = claim(client)
    domestic = create_trip(client, user_id, local_currency="USD")
    abroad_destination = {"name": "Bangkok", "country_code": "TH", "lat": 13.75, "lon": 100.5}
    abroad = create_trip(client, user_id, destination=abroad_destination, local_currency="USD")
    assert trips.get_trip(db_conn, UUID(domestic)).local_currency is None
    assert trips.get_trip(db_conn, UUID(abroad)).local_currency == "THB"


def test_create_trip_in_unsupported_country_returns_422(client):
    user_id = claim(client)
    nowhere = {"name": "Nowhere", "country_code": "ZZ", "lat": 1.0, "lon": 1.0}
    response = client.post("/trips", json=trip_body(user_id, destination=nowhere))
    assert response.status_code == 422
    assert "ZZ" in response.json()["error"]["message"]


def test_create_trip_starting_yesterday_returns_422(client, db_conn):
    user_id = claim(client)
    yesterday = today_in_vietnam(datetime.now(UTC)) - timedelta(days=1)
    body = trip_body(user_id, start_date=yesterday.isoformat(), end_date=yesterday.isoformat())
    response = client.post("/trips", json=body)
    assert response.status_code == 422
    assert "start_date" in response.json()["error"]["message"]
    assert db_conn.execute("SELECT count(*) FROM trips").fetchone()[0] == 0


def test_create_trip_over_thirty_days_returns_422(client):
    user_id = claim(client)
    start = today_in_vietnam(datetime.now(UTC)) + timedelta(days=1)
    body = trip_body(
        user_id, start_date=start.isoformat(), end_date=(start + timedelta(days=30)).isoformat()
    )
    assert client.post("/trips", json=body).status_code == 422


def test_create_trip_for_unknown_user_returns_404(client):
    response = client.post("/trips", json=trip_body("00000000-0000-0000-0000-000000000000"))
    assert response.status_code == 404


def test_sixth_trip_same_day_same_name_returns_429(db_pool):
    client = make_client(db_pool, IP_TRIPS_PER_DAY="50")
    user_id = claim(client)
    for _ in range(5):
        create_trip(client, user_id)
    response = client.post("/trips", json=trip_body(user_id))
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


def test_other_name_is_not_blocked_by_a_full_name(db_pool):
    client = make_client(db_pool, IP_TRIPS_PER_DAY="50")
    full = claim(client, "Full")
    for _ in range(5):
        create_trip(client, full)
    assert client.post("/trips", json=trip_body(claim(client, "Other"))).status_code == 202


def test_trip_over_the_per_ip_daily_cap_returns_429(db_pool):
    client = make_client(db_pool, IP_TRIPS_PER_DAY="2")
    user_id = claim(client)
    create_trip(client, user_id)
    create_trip(client, user_id)
    assert client.post("/trips", json=trip_body(user_id)).status_code == 429


def test_create_trip_while_quota_is_blocked_returns_429_and_makes_no_trip(client, db_conn):
    user_id = claim(client)
    until = datetime.now(UTC) + timedelta(hours=3)
    quota.block(db_conn, "tavily", until, "monthly cap")
    response = client.post("/trips", json=trip_body(user_id))
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "quota_exhausted"
    assert db_conn.execute("SELECT count(*) FROM trips").fetchone()[0] == 0


def test_create_trip_leaves_no_trip_when_queuing_the_job_fails(client, db_conn, monkeypatch):
    user_id = claim(client)

    def broken(*args: Any, **kwargs: Any) -> None:
        raise Conflict("boom")

    monkeypatch.setattr(jobs, "enqueue", broken)
    assert client.post("/trips", json=trip_body(user_id)).status_code == 409
    assert db_conn.execute("SELECT count(*) FROM trips").fetchone()[0] == 0


def test_create_trip_from_form_marks_message_created_with_trip_id(client, db_conn):
    user_id = claim(client)
    _, form = open_form(db_conn, user_id)
    body = trip_body(user_id, message_id=str(form.id))
    response = client.post("/trips", json=body)
    assert response.status_code == 202, response.text

    closed = messages.get_message(db_conn, form.id)
    content = json.loads(closed.content)
    assert closed.intent == "created_trip"
    assert content["trip_id"] == response.json()["data"]["id"]
    assert content["destination"] == DALAT_FIELDS["destination"]
    assert content["start_date"] == body["start_date"]


def test_create_trip_message_id_is_not_stored_in_the_request(client, db_conn):
    user_id = claim(client)
    _, form = open_form(db_conn, user_id)
    client.post("/trips", json=trip_body(user_id, message_id=str(form.id)))
    content = json.loads(messages.get_message(db_conn, form.id).content)
    assert "message_id" not in content and "user_id" not in content


def test_create_trip_from_form_clears_conversation_draft(client, db_conn):
    user_id = claim(client)
    conversation, form = open_form(db_conn, user_id, {"travelers": 4})
    client.post("/trips", json=trip_body(user_id, message_id=str(form.id)))
    assert conversations.get_conversation(db_conn, conversation.id).request_draft is None


def test_create_trip_twice_from_one_form_returns_409_and_keeps_one_trip(client, db_conn):
    user_id = claim(client)
    _, form = open_form(db_conn, user_id)
    body = trip_body(user_id, message_id=str(form.id))
    assert client.post("/trips", json=body).status_code == 202
    second = client.post("/trips", json=body)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"
    assert trips.count_trips_today(db_conn, UUID(user_id)) == 1
    assert db_conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


def test_create_trip_from_other_users_form_returns_404_and_creates_nothing(client, db_conn):
    owner = claim(client, "Owner")
    other = claim(client, "Other")
    _, form = open_form(db_conn, owner)
    response = client.post("/trips", json=trip_body(other, message_id=str(form.id)))
    assert response.status_code == 404
    assert db_conn.execute("SELECT count(*) FROM trips").fetchone()[0] == 0
    assert db_conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    assert messages.get_message(db_conn, form.id).intent == "trip_form"


def test_create_trip_from_unknown_form_returns_404_and_creates_nothing(client, db_conn):
    user_id = claim(client)
    response = client.post("/trips", json=trip_body(user_id, message_id=str(UUID(int=1))))
    assert response.status_code == 404
    assert db_conn.execute("SELECT count(*) FROM trips").fetchone()[0] == 0


# The job runner finishes the trip the API queued, and the API then serves its plan and export
def test_create_trip_returns_202_and_trip_becomes_ready_after_job(db_pool, db_conn):
    # The API clock stands on the day the Bangkok fixture plan was written for
    app = make_app(db_pool)
    app.state.deps = dataclasses.replace(app.state.deps, now=lambda: NOW)
    client = TestClient(app, raise_server_exceptions=False)
    user_id = claim(client)
    body = {**BANGKOK_FIELDS, "user_id": user_id}
    created = client.post("/trips", json=body)
    assert created.status_code == 202
    trip_id = created.json()["data"]["id"]

    job = jobs.lease_next(db_conn, "w1", 600)
    assert job is not None
    run_generate_plan(job, make_rig(db_pool, [answer(plan=bangkok_plan())]).deps)

    trip = client.get(f"/trips/{trip_id}").json()["data"]
    assert (trip["status"], trip["plan_revision"], trip["failure_reason"]) == ("ready", 1, None)
    assert trip["plan"]["currencies"]["local"] == "THB"
    assert trip["local_currency"] == "THB"
    export = client.get(f"/trips/{trip_id}/export.xlsx")
    assert export.status_code == 200
    assert load_workbook(io.BytesIO(export.content))["Itinerary"]["A1"].value == "Bangkok TRIP"


# --- reading, retrying, deleting ---


def test_get_trip_returns_status_stage_revision_and_plan(client, db_conn):
    user_id = claim(client)
    trip_id = create_trip(client, user_id)

    queued = client.get(f"/trips/{trip_id}").json()["data"]
    assert queued["status"] == "queued"
    assert queued["stage"] is None
    assert queued["plan"] is None
    assert queued["plan_revision"] == 0
    assert queued["destination"]["name"] == "Đà Lạt"

    job = jobs.active_job(db_conn, UUID(trip_id))
    assert job is not None
    jobs.set_stage(db_conn, job.id, "planning")
    assert client.get(f"/trips/{trip_id}").json()["data"]["stage"] == "planning"

    jobs.finish(db_conn, job.id, "succeeded")
    make_ready(db_conn, trip_id)
    ready = client.get(f"/trips/{trip_id}").json()["data"]
    assert ready["status"] == "ready"
    assert ready["stage"] is None
    assert ready["plan_revision"] == 1
    assert ready["plan"]["title"] == dalat_plan().title


def test_get_unknown_trip_returns_404(client):
    assert client.get("/trips/00000000-0000-0000-0000-000000000000").status_code == 404


def test_get_trip_with_malformed_id_returns_422(client):
    assert client.get("/trips/not-a-uuid").status_code == 422


def test_retry_when_job_active_returns_409(client):
    trip_id = create_trip(client, claim(client))
    response = client.post(f"/trips/{trip_id}/retry")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_retry_a_ready_trip_returns_409(client, db_conn):
    trip_id = create_trip(client, claim(client))
    job = jobs.active_job(db_conn, UUID(trip_id))
    assert job is not None
    jobs.finish(db_conn, job.id, "succeeded")
    make_ready(db_conn, trip_id)
    assert client.post(f"/trips/{trip_id}/retry").status_code == 409


def test_retry_a_failed_trip_queues_a_new_job(client, db_conn):
    trip_id = create_trip(client, claim(client))
    job = jobs.active_job(db_conn, UUID(trip_id))
    assert job is not None
    jobs.finish(db_conn, job.id, "failed", "boom")
    trips.set_status(db_conn, UUID(trip_id), "failed", "generation_failed")

    response = client.post(f"/trips/{trip_id}/retry")
    assert response.status_code == 202
    assert response.json()["data"] == {"id": trip_id, "status": "queued"}
    trip = trips.get_trip(db_conn, UUID(trip_id))
    assert trip.status == "queued" and trip.failure_reason is None
    assert jobs.active_job(db_conn, UUID(trip_id)) is not None


def test_retry_while_quota_is_blocked_returns_429(client, db_conn):
    trip_id = create_trip(client, claim(client))
    job = jobs.active_job(db_conn, UUID(trip_id))
    assert job is not None
    jobs.finish(db_conn, job.id, "failed", "quota")
    trips.set_status(db_conn, UUID(trip_id), "failed", "quota_exhausted")
    quota.block(db_conn, "openrouter", datetime.now(UTC) + timedelta(hours=1), "daily cap")

    response = client.post(f"/trips/{trip_id}/retry")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "quota_exhausted"


def test_retry_unknown_trip_returns_404(client):
    assert client.post("/trips/00000000-0000-0000-0000-000000000000/retry").status_code == 404


def test_delete_trip_returns_204_then_404(client, db_conn):
    trip_id = create_trip(client, claim(client))
    assert client.delete(f"/trips/{trip_id}").status_code == 204
    assert client.get(f"/trips/{trip_id}").status_code == 404
    assert client.delete(f"/trips/{trip_id}").status_code == 404
    assert db_conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


# --- export ---


def test_export_before_ready_returns_409(client):
    trip_id = create_trip(client, claim(client))
    response = client.get(f"/trips/{trip_id}/export.xlsx")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_export_unknown_trip_returns_404(client):
    assert client.get("/trips/00000000-0000-0000-0000-000000000000/export.xlsx").status_code == 404


def test_export_downloads_xlsx_of_current_plan(client, db_conn):
    trip_id = create_trip(client, claim(client))
    make_ready(db_conn, trip_id)

    response = client.get(f"/trips/{trip_id}/export.xlsx")
    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_TYPE
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="Da Lat.xlsx"')
    assert "filename*=UTF-8''%C4%90%C3%A0%20L%E1%BA%A1t.xlsx" in disposition
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook["Itinerary"]["A1"].value == "Đà Lạt TRIP"
    assert workbook["Itinerary"]["K8"].value == 4


def test_export_works_while_a_replan_runs_on_a_trip_that_has_a_plan(client, db_conn):
    trip_id = create_trip(client, claim(client))
    make_ready(db_conn, trip_id)
    trips.set_status(db_conn, UUID(trip_id), "planning")
    assert client.get(f"/trips/{trip_id}/export.xlsx").status_code == 200


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Đà Lạt", "Da Lat"),
        ("đồi Đông", "doi Dong"),
        ('Hà "Nội"\r\nX-Header: 1', "Ha _Noi___X-Header_ 1"),
        ("../../etc/passwd", "etc_passwd"),
        ("東京", "trip"),
        ("Saint-Étienne", "Saint-Etienne"),
    ],
)
def test_ascii_file_name_folds_accents_and_removes_unsafe_characters(name, expected):
    assert ascii_file_name(name) == expected


def test_export_header_has_no_quote_or_line_break_for_a_hostile_destination(client, db_conn):
    user_id = claim(client)
    hostile = {"name": 'Bad"\nname', "country_code": "VN", "lat": 1.0, "lon": 1.0}
    trip_id = create_trip(client, user_id, destination=hostile)
    make_ready(db_conn, trip_id)
    disposition = client.get(f"/trips/{trip_id}/export.xlsx").headers["content-disposition"]
    plain = disposition.split('filename="')[1].split('"')[0]
    assert plain == "Bad__name.xlsx"
    assert "\n" not in disposition


def test_template_path_default_exists():
    assert Path(load_settings(ENV).template_path).exists()
