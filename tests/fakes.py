"""In-memory stand-ins for the LLM provider, the search client and the call sink."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from datetime import datetime
from typing import Any

from db.repositories.llm_calls import LlmCallRecord
from models.llm_factory import Embedder, EmbeddingResponse, LLMProvider, LLMResponse, StreamChunk

STREAM_CHUNK_CHARS = 8


# Replays one script shared by every model: each call takes the next item, a string answer, the
# vectors of an embed call, or an exception to raise; known limits the model ids it accepts (None
# accepts all)
class FakeProvider(LLMProvider, Embedder):
    name = "openrouter"

    def __init__(
        self,
        script: Sequence[str | list[list[float]] | Exception],
        name: str = "openrouter",
        known: AbstractSet[str] | None = None,
    ) -> None:
        self.name = name  # type: ignore[misc]
        self._known = known
        self._script = list(script)
        self.calls: list[tuple[list[dict[str, Any]], str]] = []
        # The model id, timeout and response_format of each call, in order (formats: invoke only)
        self.models: list[str] = []
        self.timeouts: list[float | None] = []
        self.formats: list[Mapping[str, Any] | None] = []
        # The texts of each embed call, in order
        self.embedded: list[list[str]] = []

    def accepts(self, model_id: str) -> bool:
        return self._known is None or model_id in self._known

    # Record the call and take the next scripted item
    def _next(
        self,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        system_prompt: str,
        timeout_s: float | None,
    ) -> str:
        self.calls.append(([dict(m) for m in messages], system_prompt))
        item = self._take(model_id, timeout_s)
        assert isinstance(item, str), "FakeProvider: a chat call got scripted vectors"
        return item

    # Note the model and timeout, then take the next item; an exception is raised
    def _take(self, model_id: str, timeout_s: float | None) -> str | list[list[float]]:
        self.models.append(model_id)
        self.timeouts.append(timeout_s)
        if not self._script:
            raise AssertionError("FakeProvider script is exhausted")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    # Return the next scripted vectors; one input token per text
    def embed(
        self, model_id: str, texts: Sequence[str], *, timeout_s: float | None = None
    ) -> EmbeddingResponse:
        self.embedded.append(list(texts))
        item = self._take(model_id, timeout_s)
        assert isinstance(item, list), "FakeProvider: an embed call got a scripted answer"
        return EmbeddingResponse(vectors=item, input_tokens=len(texts))

    # Return the next scripted answer with fixed token counts
    def invoke(
        self,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        system_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> LLMResponse:
        self.formats.append(response_format)
        answer = self._next(model_id, messages, system_prompt, timeout_s)
        return LLMResponse(answer=answer, input_tokens=10, output_tokens=5)

    # Yield the next scripted answer in chunks; an exception is raised before the first chunk
    def invoke_stream(
        self,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        system_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout_s: float | None = None,
    ) -> Iterator[StreamChunk]:
        answer = self._next(model_id, messages, system_prompt, timeout_s)
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
        self.countries: list[str | None] = []

    # Return the results scripted for the query, else the default
    def __call__(self, query: str, task: str, country_code: str | None = None) -> list[Any]:
        self.calls.append(query)
        self.tasks.append(task)
        self.countries.append(country_code)
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
