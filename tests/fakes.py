"""In-memory stand-ins for the LLM provider, the search client and the call sink."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from typing import Any

from db.repositories.llm_calls import LlmCallRecord
from models.base import LLMProvider, LLMResponse, StreamChunk

STREAM_CHUNK_CHARS = 8


# Replays a script: each call takes the next item, a string answer or an exception to raise
class FakeProvider(LLMProvider):
    def __init__(self, script: Sequence[str | Exception], model_id: str = "fake/model") -> None:
        super().__init__(model_id, {})
        self._script = list(script)
        self.calls: list[tuple[list[dict[str, Any]], str]] = []

    # Record the call and take the next scripted item
    def _next(self, messages: Sequence[Mapping[str, Any]], system_prompt: str) -> str:
        self.calls.append(([dict(m) for m in messages], system_prompt))
        if not self._script:
            raise AssertionError("FakeProvider script is exhausted")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    # Return the next scripted answer with fixed token counts
    def invoke(
        self,
        messages: Sequence[Mapping[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        answer = self._next(messages, system_prompt)
        return LLMResponse(answer=answer, input_tokens=10, output_tokens=5)

    # Yield the next scripted answer in chunks; an exception is raised before the first chunk
    def invoke_stream(  # type: ignore[override]
        self,
        messages: Sequence[Mapping[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamChunk]:
        answer = self._next(messages, system_prompt)
        for start in range(0, len(answer), STREAM_CHUNK_CHARS):
            yield StreamChunk(delta=answer[start : start + STREAM_CHUNK_CHARS])


# Search double: query -> results (or an exception to raise); records every query
class FakeSearch:
    def __init__(
        self,
        results: Mapping[str, Sequence[Any] | Exception] | None = None,
        default: Sequence[Any] = (),
    ) -> None:
        self._results = dict(results or {})
        self._default = list(default)
        self.calls: list[str] = []
        self.tasks: list[str] = []

    # Return the results scripted for the query, else the default
    def __call__(self, query: str, task: str) -> list[Any]:
        self.calls.append(query)
        self.tasks.append(task)
        value = self._results.get(query, self._default)
        if isinstance(value, Exception):
            raise value
        return list(value)


# CallSink double that keeps log records and quota blocks in memory
class FakeSink:
    def __init__(self) -> None:
        self.logs: list[LlmCallRecord] = []
        self.blocks: dict[str, tuple[datetime, str]] = {}

    # Keep one call record
    def log(self, record: LlmCallRecord) -> None:
        self.logs.append(record)

    # Remember the block, replacing an earlier one for the service
    def block(self, service: str, until: datetime, reason: str) -> None:
        self.blocks[service] = (until, reason)

    # When the service is blocked until, or None
    def blocked_until(self, service: str) -> datetime | None:
        entry = self.blocks.get(service)
        return None if entry is None else entry[0]
