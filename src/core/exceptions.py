"""Domain exceptions shared by services, the worker and the API error mapping."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime


# A row the caller asked for does not exist
class NotFound(Exception):
    pass


# The request clashes with the current state (for example an active job)
class Conflict(Exception):
    pass


# A value the visitor sent breaks a rule a request schema cannot express (dates in the past, an
# unknown button id); the message says which
class InvalidInput(Exception):
    pass


# The plan changed since the client read it
class PlanConflict(Conflict):
    pass


# A per-user, per-IP or global usage limit was reached
class LimitExceeded(Exception):
    pass


# A provider's daily or monthly free quota is used up until blocked_until
class QuotaExhausted(Exception):
    # Keep the reset time for the 429 body
    def __init__(self, blocked_until: datetime) -> None:
        super().__init__(f"quota exhausted until {blocked_until.isoformat()}")
        self.blocked_until = blocked_until


# Every model in the chain failed with a transient error
class LLMUnavailable(Exception):
    pass


# A job used all the LLM calls it may make
class LLMBudgetExceeded(Exception):
    pass


# The model's structured output stayed invalid after repair
class InvalidLLMOutput(Exception):
    # Keep the validation errors for logs and the repair prompt
    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = list(errors)


# A plan edit cannot be applied to the plan
class EditRejected(Exception):
    # Keep the reasons to show the visitor
    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = list(errors)


# Research failed in a way that leaves nothing to plan from
class ResearchFailed(Exception):
    pass
