from abc import ABC, abstractmethod
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any


@dataclass
class Message:
    role: str
    content: str | list[dict[str, Any]]


@dataclass
class LLMResponse:
    answer: str
    input_tokens: int
    output_tokens: int
    tool_calls: list[dict[str, Any]] | None = None
    original_response: Any = None


@dataclass
class StreamChunk:
    text: str | None = None
    tool_call: dict[str, Any] | None = None

    # Standard chunk:
    delta: str | None = None
    tool_call_chunk: dict[str, Any] | None = (
        None  # {index, name, arguments_delta, id}
    )


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, model_id: str, inference_config: dict):
        self.model_id = model_id
        self.inference_config = inference_config

    # response_format asks for JSON output: {"type": "json_object"} or {"type": "json_schema", ...}
    @abstractmethod
    def invoke(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any] | LLMResponse:
        pass

    @abstractmethod
    def invoke_stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict] | None = None,
    ) -> Generator:
        pass
