from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from models.model_router import CallContext, ModelRouter

from .types import GuardContext, GuardrailConfigError, GuardResult

_REGISTRY: dict[str, type[Guard]] = {}


# What guards that call a model use: the app's router (fallback, call log, quota, budget) and the
# context its calls are logged and budgeted against
@dataclass(frozen=True)
class GuardDeps:
    router: ModelRouter | None = None
    ctx: CallContext = CallContext()


# The router of deps, or a config error naming the guard that needs it
def require_router(deps: GuardDeps, guard: str) -> ModelRouter:
    if deps.router is None:
        raise GuardrailConfigError(f"guard '{guard}' needs a router")
    return deps.router


# Parameters every guard accepts; each guard's Params subclasses this
class CommonParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    name: str = ""
    category: str | None = None
    timeout_s: float | None = Field(default=None, gt=0)
    on_error: Literal["block", "allow"] = "block"


class Guard(Protocol):
    Params: ClassVar[type[CommonParams]]
    requires: ClassVar[frozenset[str]]
    name: str
    params: CommonParams

    def __init__(self, params: Any, deps: GuardDeps) -> None: ...

    async def check(self, text: str, context: GuardContext) -> GuardResult: ...


# Register a guard class under the config `type` name
def register_guard(type_name: str) -> Callable[[type[Guard]], type[Guard]]:
    def decorator(cls: type[Guard]) -> type[Guard]:
        _REGISTRY[type_name] = cls
        return cls

    return decorator


# Look up the class registered for a config `type`
def guard_class(type_name: str) -> type[Guard]:
    if type_name not in _REGISTRY:
        raise GuardrailConfigError(f"unknown guard type '{type_name}'")
    return _REGISTRY[type_name]


# Validate raw config params and build the guard
def build_guard(type_name: str, raw_params: Mapping[str, Any], deps: GuardDeps) -> Guard:
    cls = guard_class(type_name)
    label = raw_params.get("name") or type_name
    try:
        params = cls.Params.model_validate({**raw_params, "type": type_name, "name": label})
    except ValidationError as exc:
        raise GuardrailConfigError(f"guard '{label}': {exc}") from exc
    return cls(params, deps)
