from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from typing import ClassVar, Literal

from pydantic import Field

from ..registry import CommonParams, GuardDeps, register_guard, require_router
from ..types import Action, GuardContext, GuardrailConfigError, GuardResult


class EmbeddingParams(CommonParams):
    mode: Literal["deny", "allow"]
    examples: list[str] = Field(min_length=1)
    # None: the router's embed chain (EMBEDDING_MODELS) with fallback; a model id calls only it
    model: str | None = None
    threshold: float = Field(ge=0, le=1)


@register_guard("embedding")
class EmbeddingGuard:
    Params = EmbeddingParams
    requires: ClassVar[frozenset[str]] = frozenset({"router"})

    def __init__(self, params: EmbeddingParams, deps: GuardDeps) -> None:
        self.params = params
        self.name = params.name
        self.router = require_router(deps, params.name)
        self.ctx = deps.ctx
        self.examples = [e.strip() for e in params.examples if e.strip()]
        if not self.examples:
            raise GuardrailConfigError(f"guard '{self.name}': examples list is empty")
        self.vectors: list[list[float]] | None = None
        self.lock = asyncio.Lock()

    # Embed the example set once, even under concurrent first calls
    async def warmup(self) -> None:
        async with self.lock:
            if self.vectors is None:
                self.vectors = await self._embed(self.examples)

    # The router is sync, so it runs in a thread and the guard's timeout still applies
    async def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.router.embed, texts, self.ctx, self.params.model)

    # Score text by its closest example; deny scores similarity, allow scores distance
    async def check(self, text: str, context: GuardContext) -> GuardResult:
        await self.warmup()
        [vector] = await self._embed([text])

        # ponytail: linear scan in pure Python, fine for a few hundred examples, use numpy past that
        best = max(_cosine(vector, example) for example in self.vectors)
        score = best if self.params.mode == "deny" else 1.0 - best
        blocked = score >= self.params.threshold
        return GuardResult(
            guard=self.name,
            action=Action.BLOCK if blocked else Action.ALLOW,
            text=text,
            score=score,
            category=self.params.category or self.name,
            reason=f"{self.params.mode} similarity {best:.3f}",
        )


# Cosine similarity clamped to 0..1; zero vectors score 0
def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    norm = math.hypot(*a) * math.hypot(*b)
    if norm == 0:
        return 0.0
    return max(0.0, min(1.0, sum(x * y for x, y in zip(a, b, strict=True)) / norm))
