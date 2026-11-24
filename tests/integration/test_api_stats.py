from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from db.repositories import jobs, quota, trips, users
from tests.fixtures.builders import DALAT_FIELDS
from tests.integration.test_api_foundation import ENV
from tests.integration.test_api_trips import make_client


@pytest.fixture
def client(db_pool: ConnectionPool) -> TestClient:
    return make_client(db_pool)


def test_health_returns_ceilings_from_settings(client):
    response = client.get("/stats/health")

    assert response.status_code == 200
    today = response.json()["data"]["llm_today"]
    assert (today["ceiling_new_trips"], today["ceiling_chat"]) == (
        int(ENV["DAILY_LLM_CEILING_NEW_TRIPS"]),
        int(ENV["DAILY_LLM_CEILING_CHAT"]),
    )


def test_usage_defaults_to_30_days(client):
    data = client.get("/stats/usage").json()["data"]

    assert data["days"] == 30 and len(data["daily"]) == 30


def test_usage_accepts_7_days(client):
    assert len(client.get("/stats/usage?days=7").json()["data"]["daily"]) == 7


@pytest.mark.parametrize("days", ["0", "31", "abc"])
def test_usage_rejects_other_days(client, days):
    response = client.get(f"/stats/usage?days={days}")

    assert response.status_code == 422 and response.json()["success"] is False


def test_stats_never_return_user_content(client, db_conn):
    user = users.claim_user(db_conn, "Linh Secret")
    trip = trips.create_trip(db_conn, user.id, {**DALAT_FIELDS, "notes": "note-secret"}, None)
    job = jobs.enqueue(db_conn, trip.id)
    jobs.finish(db_conn, job.id, "failed", "error-secret")
    trips.set_status(db_conn, trip.id, "failed", "generation_failed")
    quota.block(db_conn, "openrouter", datetime.now(UTC) + timedelta(hours=1), "reason-secret")

    body = client.get("/stats/health").text + client.get("/stats/usage?days=7").text

    assert "generation_failed" in body and "Đà Lạt" in body
    for secret in (
        "Linh Secret",
        "note-secret",
        "error-secret",
        "reason-secret",
        str(user.id),
        str(trip.id),
    ):
        assert secret not in body
