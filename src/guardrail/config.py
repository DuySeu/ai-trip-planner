from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .types import GuardrailConfigError, Stage


# Check a config mapping ({"input": [...], "output": [...]}) into {stage: [raw guard params]} with
# names filled in and checked
def parse_config(raw: Mapping[str, Any]) -> dict[Stage, list[dict[str, Any]]]:
    if not isinstance(raw, Mapping):
        raise GuardrailConfigError("config top level must be a mapping")

    unknown = set(raw) - {s.value for s in Stage}
    if unknown:
        raise GuardrailConfigError(f"unknown top-level keys: {sorted(unknown)}")

    stages: dict[Stage, list[dict[str, Any]]] = {}
    for stage in Stage:
        entries = raw.get(stage.value) or []
        if not isinstance(entries, list):
            raise GuardrailConfigError(f"'{stage}' must be a list of guards")

        # Every entry needs a type; names default to the type and must be unique per stage
        seen: set[str] = set()
        guards = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping) or not isinstance(entry.get("type"), str):
                raise GuardrailConfigError(f"{stage}[{index}] must be a mapping with a 'type'")
            name = entry.get("name") or entry["type"]
            if name in seen:
                raise GuardrailConfigError(f"duplicate guard name '{name}' in '{stage}'")
            seen.add(name)
            guards.append({**entry, "name": name})
        stages[stage] = guards
    return stages
