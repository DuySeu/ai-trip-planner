from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from .config import parse_config
from .providers import ChatClient, Embedder
from .registry import Guard, GuardDeps, build_guard, guard_class
from .types import Action, Decision, GuardContext, GuardrailConfigError, GuardResult, Stage, decide

NETWORK_TIMEOUT_S = 10.0

logger = logging.getLogger(__name__)


# Ordered input and output guard pipelines built from one config
class Guardrail:
    def __init__(self, guards: Mapping[Stage, Sequence[Guard]]) -> None:
        self._guards = {stage: tuple(guards.get(stage, ())) for stage in Stage}

    async def check_input(self, text: str, conversation: str | None = None) -> Decision:
        return await self._run(text, GuardContext(stage=Stage.INPUT, conversation=conversation))

    async def check_output(self, text: str, user_input: str | None = None) -> Decision:
        return await self._run(text, GuardContext(stage=Stage.OUTPUT, user_input=user_input))

    # Prepare lazy resources (example embeddings) before the first request
    async def warmup(self) -> None:
        for guards in self._guards.values():
            for guard in guards:
                if hasattr(guard, "warmup"):
                    await guard.warmup()

    def guards(self, stage: Stage) -> tuple[Guard, ...]:
        return self._guards[stage]

    # A guardrail holding only one guard, sharing the same instance
    def only(self, stage: Stage, name: str) -> Guardrail:
        guard = next((g for g in self._guards[stage] if g.name == name), None)
        if guard is None:
            raise KeyError(f"no guard '{name}' in '{stage}'")
        return Guardrail({stage: [guard]})

    async def _run(self, text: str, context: GuardContext) -> Decision:
        results: list[GuardResult] = []
        current = text
        for guard in self._guards[context.stage]:
            result = await _run_guard(guard, current, context)
            results.append(result)
            current = result.text
            if result.action is Action.BLOCK:
                break
        return decide(current, results)


# Build a guardrail from a config mapping; a guard that needs a client the caller did not pass is a
# config error
def load_guardrail(
    config: Mapping[str, Any],
    chat_client: ChatClient | None = None,
    embedder: Embedder | None = None,
) -> Guardrail:
    stages = parse_config(config)

    needed = set().union(*(guard_class(e["type"]).requires for es in stages.values() for e in es))
    passed = {"chat": chat_client, "embedder": embedder}
    missing = sorted(kind for kind in needed if passed[kind] is None)
    if missing:
        raise GuardrailConfigError(f"config needs clients that were not passed: {missing}")

    deps = GuardDeps(chat_client=chat_client, embedder=embedder)
    guards = {
        stage: [build_guard(e["type"], e, deps) for e in entries] for stage, entries in stages.items()
    }
    return Guardrail(guards)


# Run one guard with its timeout, turning any failure into a result per on_error
async def _run_guard(guard: Guard, text: str, context: GuardContext) -> GuardResult:
    timeout = guard.params.timeout_s or (NETWORK_TIMEOUT_S if guard.requires else None)
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(guard.check(text, context), timeout)
    # Any guard failure must fail closed or open per config, so catch everything but cancellation
    except Exception as exc:  # noqa: BLE001
        logger.warning("guard %s failed: %s", guard.name, type(exc).__name__)
        action = Action.BLOCK if guard.params.on_error == "block" else Action.ALLOW
        result = GuardResult(
            guard=guard.name,
            action=action,
            text=text,
            score=None,
            error=f"{type(exc).__name__}: {exc}",
        )
    return replace(result, latency_ms=(time.perf_counter() - start) * 1000)
