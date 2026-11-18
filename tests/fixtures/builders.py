"""Ready-made trip requests and plans for tests; the plans pass check_plan against their request."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from domain.plan import Plan
from domain.trip_request import TripRequest

FIXTURES_DIR = Path(__file__).parent
# Research ids the fixtures cite as sources
DALAT_SOURCE_IDS = frozenset({1, 2, 3})
BANGKOK_SOURCE_IDS = frozenset({1, 2})

DALAT_FIELDS: dict[str, Any] = {
    "destination": {"name": "Đà Lạt", "country_code": "VN", "lat": 11.9404, "lon": 108.4583},
    "origin": "Ho Chi Minh City",
    "start_date": "2026-12-20",
    "end_date": "2026-12-23",
    "travelers": 4,
    "travel_styles": ["nature", "food"],
    "budget_amount": "5000000",
    "budget_scope": "per_person",
    "language": "vi",
}
BANGKOK_FIELDS: dict[str, Any] = {
    "destination": {"name": "Bangkok", "country_code": "TH", "lat": 13.7563, "lon": 100.5018},
    "origin": "Ho Chi Minh City",
    "start_date": "2026-12-20",
    "end_date": "2026-12-24",
    "travelers": 2,
    "travel_styles": ["culture", "food"],
    "budget_amount": "20000000",
    "budget_scope": "per_person",
    "language": "en",
}


# The Da Lat request (4 days, 4 friends, VND); overrides replace form fields
def dalat_request(**overrides: Any) -> TripRequest:
    return TripRequest.model_validate({**DALAT_FIELDS, **overrides})


# The Bangkok request (5 days, 4 nights, 2 travelers, THB); overrides replace form fields
def bangkok_request(**overrides: Any) -> TripRequest:
    return TripRequest.model_validate({**BANGKOK_FIELDS, **overrides})


# Load a plan fixture such as "plan_domestic.json"
def load_plan(name: str) -> Plan:
    return Plan.model_validate_json((FIXTURES_DIR / name).read_text(encoding="utf-8"))


# The Da Lat plan, domestic, all prices in VND
def dalat_plan() -> Plan:
    return load_plan("plan_domestic.json")


# The Bangkok plan: THB on the ground, flights in VND, rate 720.5
def bangkok_plan() -> Plan:
    return load_plan("plan_abroad.json")
