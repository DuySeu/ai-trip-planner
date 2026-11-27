"""Routing contract: the decision the orchestrator returns, its semantic checks, and the parser
that turns the orchestrator LLM's raw text into a validated LLMRoutingOutput.

Pydantic holds only per-field constraints. Every cross-field rule lives in
``check_semantics`` so the code-built fallback ``RoutingDecision`` (no steps,
no architecture) is never rejected by a validator.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Architecture = Literal["router", "sequential", "parallel"]


# One agent the caller offers for routing; frozen so a validated name cannot be blanked later
class AgentSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: NonEmptyStr
    description: NonEmptyStr


# One unit of work for one agent
class RoutingStep(BaseModel):
    id: NonEmptyStr
    agent: NonEmptyStr
    task: NonEmptyStr


# How parallel results are merged
class Aggregation(BaseModel):
    strategy: Literal["concat", "synthesize"]
    agent: NonEmptyStr | None


# What the LLM is asked to produce (no meta, no fallback status)
class LLMRoutingOutput(BaseModel):
    status: Literal["routed", "needs_clarification"]
    architecture: Architecture | None
    steps: list[RoutingStep]
    aggregation: Aggregation | None
    clarification: NonEmptyStr | None
    reasoning: NonEmptyStr


# Filled by code, never by the LLM
class RoutingMeta(BaseModel):
    model_id: str
    attempts: int
    input_tokens: int
    output_tokens: int
    error: str | None


# The public decision consumed by the dispatching system
class RoutingDecision(BaseModel):
    status: Literal["routed", "needs_clarification", "fallback"]
    architecture: Architecture | None
    steps: list[RoutingStep]
    aggregation: Aggregation | None
    clarification: str | None
    reasoning: str
    meta: RoutingMeta


# Check cross-field rules; return a copy with agent names canonicalized plus the errors
def check_semantics(
    output: LLMRoutingOutput, catalog: Sequence[AgentSpec]
) -> tuple[LLMRoutingOutput, list[str]]:
    canonical = {spec.name.casefold(): spec.name for spec in catalog}
    valid_names = ", ".join(spec.name for spec in catalog)
    errors: list[str] = []

    # Map each agent name to its catalog spelling, or record an error
    def resolve(name: str, path: str) -> str:
        match = canonical.get(name.strip().casefold())
        if match is None:
            errors.append(f"{path}: {name!r} is not in the catalog; use one of: {valid_names}")
            return name
        return match

    steps = [
        step.model_copy(update={"agent": resolve(step.agent, f"steps[{i}].agent")})
        for i, step in enumerate(output.steps)
    ]
    aggregation = output.aggregation
    if aggregation is not None and aggregation.agent is not None:
        aggregation = aggregation.model_copy(
            update={"agent": resolve(aggregation.agent, "aggregation.agent")}
        )

    # Step ids must be unique
    ids = [step.id for step in steps]
    duplicates = sorted({step_id for step_id in ids if ids.count(step_id) > 1})
    if duplicates:
        errors.append(f"steps: duplicate step id(s) {duplicates}; each id must be unique")

    # Status-specific shape
    if output.status == "routed":
        if output.architecture is None:
            errors.append("architecture: must be router, sequential or parallel when status is routed")
        elif output.architecture == "router" and len(steps) != 1:
            errors.append(f"steps: router needs exactly 1 step, got {len(steps)}")
        elif output.architecture in ("sequential", "parallel") and len(steps) < 2:
            errors.append(f"steps: {output.architecture} needs at least 2 steps, got {len(steps)}")

        if output.architecture == "parallel" and aggregation is None:
            errors.append("aggregation: required when architecture is parallel")
        elif output.architecture in ("router", "sequential") and aggregation is not None:
            errors.append(f"aggregation: must be null when architecture is {output.architecture}")

        if output.clarification is not None:
            errors.append("clarification: must be null when status is routed")
    else:
        if output.clarification is None:
            errors.append("clarification: required when status is needs_clarification")
        if output.architecture is not None:
            errors.append("architecture: must be null when status is needs_clarification")
        if aggregation is not None:
            errors.append("aggregation: must be null when status is needs_clarification")
        if steps:
            errors.append("steps: must be empty when status is needs_clarification")

    # Strategy decides whether an aggregating agent is set
    if aggregation is not None:
        if aggregation.strategy == "synthesize" and aggregation.agent is None:
            errors.append("aggregation.agent: required when strategy is synthesize")
        elif aggregation.strategy == "concat" and aggregation.agent is not None:
            errors.append("aggregation.agent: must be null when strategy is concat")

    normalized = output.model_copy(update={"steps": steps, "aggregation": aggregation})
    return normalized, errors


# Extract, validate and semantically check one LLM answer; stop at the first failing layer
def parse_output(
    text: str | None, catalog: Sequence[AgentSpec]
) -> tuple[LLMRoutingOutput | None, list[str]]:
    # Layer 1: extract the first JSON value starting at the first "{"
    if not text or not text.strip():
        return None, ["response: empty, expected one JSON object"]
    start = text.find("{")
    if start == -1:
        return None, ["response: no JSON object found"]
    try:
        data, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as e:
        return None, [f"response: invalid or truncated JSON ({e.msg} at char {e.pos})"]
    if not isinstance(data, dict):
        return None, [f"response: expected a JSON object, got {type(data).__name__}"]

    # Layer 2: per-field format
    try:
        output = LLMRoutingOutput.model_validate(data)
    except ValidationError as e:
        return None, [
            f"{'.'.join(str(part) for part in err['loc']) or '(root)'}: {err['msg']}"
            for err in e.errors()
        ]

    # Layer 3: cross-field logic and agent names
    normalized, errors = check_semantics(output, catalog)
    if errors:
        return None, errors
    return normalized, []
