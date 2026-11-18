from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from domain.currency import Currencies, local_currency_for, to_vnd

THB = Currencies(local="THB", local_to_home_rate=Decimal("720.5"), rate_date=date(2026, 11, 16))


def test_local_currency_none_for_vietnam_and_thb_for_thailand():
    assert local_currency_for("VN") is None and local_currency_for("TH") == "THB"


def test_local_currency_rejects_unknown_country():
    with pytest.raises(ValueError):
        local_currency_for("ZZ")


def test_to_vnd_converts_local_with_stored_rate():
    assert to_vnd(Decimal("10"), "THB", THB) == Decimal("7205.0")
    assert to_vnd(Decimal("10"), "VND", THB) == Decimal("10")


def test_to_vnd_rejects_third_currency():
    with pytest.raises(ValueError):
        to_vnd(Decimal("10"), "USD", THB)
    with pytest.raises(ValueError):
        to_vnd(Decimal("10"), "THB", Currencies())


def test_currencies_need_local_rate_and_date_together():
    with pytest.raises(ValidationError):
        Currencies(local="THB")
    with pytest.raises(ValidationError):
        Currencies(local_to_home_rate=Decimal("1"), rate_date=date(2026, 11, 16))
