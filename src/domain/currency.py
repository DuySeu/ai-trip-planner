"""Currencies of a trip and conversion to VND with a stored rate."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, PlainSerializer, model_validator

from core.constants import COUNTRY_CURRENCY

HOME_CURRENCY = "VND"

# A rate is a JSON number (720.5), as the frontend reads it, not a Decimal string
Rate = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


# The plan's currencies: VND, plus the local one and its rate for a trip abroad
class Currencies(BaseModel):
    model_config = ConfigDict(frozen=True)

    home: Literal["VND"] = "VND"
    local: str | None = None
    local_to_home_rate: Rate | None = None
    rate_date: date | None = None

    # A local currency always comes with its rate and the rate's date, and never without
    @model_validator(mode="after")
    def _local_and_rate_together(self) -> Self:
        if len({self.local is None, self.local_to_home_rate is None, self.rate_date is None}) > 1:
            raise ValueError("local, local_to_home_rate and rate_date must be set together")
        if self.local_to_home_rate is not None and self.local_to_home_rate <= 0:
            raise ValueError("local_to_home_rate must be positive")
        return self


# The local currency for a destination country; None inside Vietnam
def local_currency_for(country_code: str) -> str | None:
    currency = COUNTRY_CURRENCY.get(country_code.upper())
    if currency is None:
        raise ValueError(f"no currency known for country {country_code!r}")
    return None if currency == HOME_CURRENCY else currency


# Convert an amount in the home or local currency to VND with the plan's stored rate
def to_vnd(amount: Decimal, currency: str, currencies: Currencies) -> Decimal:
    if currency == HOME_CURRENCY:
        return amount
    if currency == currencies.local and currencies.local_to_home_rate is not None:
        return amount * currencies.local_to_home_rate
    raise ValueError(f"currency {currency!r} is neither VND nor this trip's local currency")
