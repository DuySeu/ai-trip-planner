from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


# model None lets the client pick its own model (a fallback chain, for example). The app passes
# chat.guard_turn.RouterChatClient, which goes through the ModelRouter (logging, quota, ceiling)
class ChatClient(Protocol):
    async def complete(
        self, model: str | None, messages: Sequence[dict[str, str]], temperature: float = 0.0
    ) -> str: ...


class Embedder(Protocol):
    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]: ...
