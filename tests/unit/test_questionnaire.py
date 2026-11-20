from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from domain.questionnaire import answer_for, first_missing_step, questionnaire_metadata

TODAY = date(2026, 11, 21)
FULL_DRAFT = {
    "travel_styles": ["food"],
    "travelers": 2,
    "budget_amount": "6000000",
    "origin": "Hà Nội",
    "month": "December",
    "length_days": 5,
}


def test_budget_choice_sets_amount_scope_and_style():
    assert answer_for(3, "premium", {}, TODAY) == {
        "budget_amount": Decimal("25000000"),
        "budget_scope": "per_person",
        "travel_styles": ["luxury"],
    }


def test_moderate_budget_adds_no_style():
    assert answer_for(3, "moderate", {}, TODAY) == {
        "budget_amount": Decimal("6000000"),
        "budget_scope": "per_person",
    }


def test_button_ids_map_to_their_values():
    assert answer_for(1, ["food", "nature", "food"], {}, TODAY) == {
        "travel_styles": ["food", "nature"]
    }
    assert answer_for(2, "3_4", {}, TODAY) == {"travelers": 4}
    assert answer_for(2, "5_plus", {}, TODAY) == {"travelers": 5}
    assert answer_for(4, "hcmc", {}, TODAY) == {"origin": "TP. Hồ Chí Minh"}
    assert answer_for(5, "this_month", {}, TODAY) == {"month": "November"}
    assert answer_for(5, "holiday_30_4", {}, TODAY) == {"month": "April"}
    assert answer_for(6, "week", {}, TODAY) == {"length_days": 7}


def test_next_month_in_december_is_january():
    assert answer_for(5, "next_month", {}, date(2026, 12, 3)) == {"month": "January"}


def test_typed_values_are_checked_like_the_draft():
    assert answer_for(2, None, {"travelers": 7}, TODAY) == {"travelers": 7}
    assert answer_for(3, None, {"budget_amount": "8000000"}, TODAY) == {
        "budget_amount": Decimal("8000000"),
        "budget_scope": "per_person",
    }
    assert answer_for(5, None, {"start_date": "2026-12-24"}, TODAY) == {
        "start_date": date(2026, 12, 24)
    }


def test_skipped_step_sets_nothing():
    assert answer_for(4, None, {}, TODAY) == {}


def test_typed_travelers_out_of_range_is_rejected():
    with pytest.raises(ValueError):
        answer_for(2, None, {"travelers": 0}, TODAY)


def test_typed_start_date_in_the_past_is_rejected():
    with pytest.raises(ValueError):
        answer_for(5, None, {"start_date": "2026-11-20"}, TODAY)


def test_typed_field_of_another_step_is_rejected():
    with pytest.raises(ValueError):
        answer_for(2, None, {"origin": "Huế"}, TODAY)


def test_unknown_choice_is_rejected():
    with pytest.raises(ValueError):
        answer_for(4, "paris", {}, TODAY)
    with pytest.raises(ValueError):
        answer_for(1, ["luxury"], {}, TODAY)
    with pytest.raises(ValueError):
        answer_for(7, "week", {}, TODAY)


def test_first_missing_step_skips_what_the_draft_has():
    assert first_missing_step({}) == 1
    assert first_missing_step({"travel_styles": ["food"], "travelers": 2}) == 3
    assert first_missing_step(FULL_DRAFT) is None


def test_start_and_end_date_answer_when_and_length():
    draft = {**FULL_DRAFT, "start_date": "2026-12-20", "end_date": "2026-12-23"}
    del draft["month"], draft["length_days"]
    assert first_missing_step(draft) is None


def test_questionnaire_metadata_starts_after_the_answered_steps():
    meta = questionnaire_metadata({"travel_styles": ["food"], "travelers": 2, "notes": "x"})
    assert meta == {
        "kind": "questionnaire",
        "status": "open",
        "step": 2,
        "answers": {"travel_styles": ["food"], "travelers": 2, "notes": "x"},
        "choices": {},
    }


def test_last_step_takes_notes_next_to_a_button():
    assert answer_for(6, "week", {"notes": "  no long drives "}, TODAY) == {
        "length_days": 7,
        "notes": "no long drives",
    }


def test_button_with_typed_values_of_another_step_is_rejected():
    with pytest.raises(ValueError):
        answer_for(2, "2", {"travelers": 3}, TODAY)
