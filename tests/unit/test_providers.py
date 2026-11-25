from __future__ import annotations

import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
import urllib3
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from openrouter import errors

from core.constants import ModelId
from models.llm_factory import ProviderCallError
from models.provider import (
    BedrockProvider,
    OpenAIProvider,
    OpenRouterProvider,
    alternate_turns,
    role_credentials,
)

MODEL_A = ModelId.GEMMA_4_31B_IT
MODEL_B = ModelId.NEMOTRON_3_SUPER_120B_A12B
MESSAGES = [{"role": "user", "content": "hi"}]
PATTERN = "free-models-per-day"


# An SDK 429 built the way the SDK builds it from a JSON body
def rate_limit(message: str = "Rate limit exceeded") -> errors.TooManyRequestsResponseError:
    body = json.dumps({"error": {"code": 429, "message": message}})
    response = httpx.Response(429, text=body, headers={"content-type": "application/json"})
    data = errors.TooManyRequestsResponseErrorData.model_validate_json(body)
    return errors.TooManyRequestsResponseError(data, response, body)


# The SDK's 404 when no endpoint of the model supports the request's parameters
def no_endpoints() -> errors.NotFoundResponseError:
    message = "No endpoints found that can handle the requested parameters."
    body = json.dumps({"error": {"code": 404, "message": message}})
    response = httpx.Response(404, text=body, headers={"content-type": "application/json"})
    data = errors.NotFoundResponseErrorData.model_validate_json(body)
    return errors.NotFoundResponseError(data, response, body)


# The SDK's generic error for a status without a specific class
def http_error(status: int) -> errors.OpenRouterDefaultError:
    return errors.OpenRouterDefaultError("API error occurred", httpx.Response(status, text="oops"))


# Stands in for client.chat: records the keyword arguments of every send, answers like the SDK
# (an object with choices and usage, or an iterator of events when streaming), or raises
class RecordingChat:
    def __init__(self, error: Exception | None = None, stream_error: Exception | None = None):
        self.calls: list[dict[str, Any]] = []
        self.error = error
        self.stream_error = stream_error

    @property
    def kwargs(self) -> dict[str, Any]:
        return self.calls[-1]

    def send(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if kwargs.get("stream"):
            return self._events()
        message = SimpleNamespace(content="{}", tool_calls=None)
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    def _events(self) -> Iterator[Any]:
        delta = SimpleNamespace(content="part ", tool_calls=None)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
        if self.stream_error is not None:
            raise self.stream_error


def openrouter_with(chat: RecordingChat) -> OpenRouterProvider:
    provider = OpenRouterProvider("key", PATTERN)
    provider.client = SimpleNamespace(chat=chat)  # type: ignore[assignment]
    return provider


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (rate_limit(), "rate_limited"),
        (rate_limit("Rate limit: free-models-per-day"), "quota_exhausted"),
        (http_error(502), "provider_error"),
        (http_error(408), "timeout"),
        (no_endpoints(), "provider_error"),
        (errors.NoResponseError(), "provider_error"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("down"), "provider_error"),
    ],
)
def test_openrouter_maps_sdk_errors_to_outcomes(error: Exception, outcome: str):
    with pytest.raises(ProviderCallError) as raised:
        openrouter_with(RecordingChat(error=error)).invoke(MODEL_A, MESSAGES, "sys")
    assert raised.value.outcome == outcome
    assert str(raised.value).startswith(f"{type(error).__name__}: ")


def test_openrouter_uses_one_client_and_sends_model_and_timeout_per_call():
    chat = RecordingChat()
    provider = openrouter_with(chat)
    client = provider.client
    provider.invoke(MODEL_A, MESSAGES, "sys", timeout_s=30.0)
    provider.invoke(MODEL_B, MESSAGES, "sys")
    assert [c["model"] for c in chat.calls] == [MODEL_A, MODEL_B]
    assert chat.calls[0]["timeout_ms"] == 30000
    assert "timeout_ms" not in chat.calls[1]
    assert chat.calls[0]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]
    assert provider.client is client


def test_openrouter_stream_sends_timeout_and_yields_deltas():
    chat = RecordingChat()
    chunks = list(openrouter_with(chat).invoke_stream(MODEL_A, MESSAGES, "sys", timeout_s=90.0))
    assert [c.delta for c in chunks] == ["part "]
    assert (chat.kwargs["stream"], chat.kwargs["timeout_ms"]) == (True, 90000)


def test_openrouter_stream_error_after_first_chunk_is_a_provider_call_error():
    chat = RecordingChat(stream_error=httpx.ReadTimeout("slow"))
    seen: list[str | None] = []
    with pytest.raises(ProviderCallError) as raised:
        for chunk in openrouter_with(chat).invoke_stream(MODEL_A, MESSAGES, "sys"):
            seen.append(chunk.delta)
    assert seen == ["part "]
    assert raised.value.outcome == "timeout"


def test_openrouter_accepts_only_known_model_ids():
    provider = OpenRouterProvider("key", PATTERN)
    assert provider.accepts(MODEL_A)
    assert not provider.accepts("made/up:free")


def test_openrouter_json_request_requires_support_and_heals_the_reply():
    chat = RecordingChat()
    openrouter_with(chat).invoke(MODEL_A, MESSAGES, "sys", response_format={"type": "json_object"})
    assert chat.kwargs["response_format"] == {"type": "json_object"}
    assert chat.kwargs["provider"] == {"require_parameters": True}
    assert chat.kwargs["plugins"] == [{"id": "response-healing"}]


def test_openrouter_text_request_sends_no_json_options():
    chat = RecordingChat()
    openrouter_with(chat).invoke(MODEL_A, MESSAGES, "sys")
    assert not {"response_format", "provider", "plugins"} & chat.kwargs.keys()


REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def openai_rate_limit(code: str) -> openai.RateLimitError:
    response = httpx.Response(429, request=REQUEST)
    return openai.RateLimitError("limited", response=response, body={"code": code, "message": "m"})


def openai_status(status: int) -> openai.APIStatusError:
    return openai.APIStatusError(
        "failed", response=httpx.Response(status, request=REQUEST), body=None
    )


# Stands in for client.chat.completions: records every create call, answers like the SDK, or raises
class RecordingCompletions:
    def __init__(self, error: Exception | None = None, stream_error: Exception | None = None):
        self.calls: list[dict[str, Any]] = []
        self.error = error
        self.stream_error = stream_error

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if kwargs.get("stream"):
            return self._events()
        message = SimpleNamespace(content="{}", tool_calls=None)
        usage = SimpleNamespace(prompt_tokens=4, completion_tokens=2)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    def _events(self) -> Iterator[Any]:
        delta = SimpleNamespace(content="part ", tool_calls=None)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
        if self.stream_error is not None:
            raise self.stream_error


def openai_with(completions: RecordingCompletions) -> OpenAIProvider:
    provider = OpenAIProvider("key")
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]
    return provider


def test_openai_uses_one_client_and_sends_model_timeout_and_format_per_call():
    completions = RecordingCompletions()
    provider = openai_with(completions)
    client = provider.client
    json_object = {"type": "json_object"}
    response = provider.invoke(
        "gpt-a", MESSAGES, "sys", response_format=json_object, timeout_s=30.0
    )
    provider.invoke("gpt-b", MESSAGES, "sys")
    first, second = completions.calls
    assert (first["model"], second["model"]) == ("gpt-a", "gpt-b")
    assert first["timeout"] == 30.0 and "timeout" not in second
    assert first["response_format"] == json_object and "response_format" not in second
    assert not {"provider", "plugins"} & first.keys()
    assert first["messages"][0] == {"role": "system", "content": "sys"}
    assert (response.answer, response.input_tokens, response.output_tokens) == ("{}", 4, 2)
    assert provider.client is client


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (openai_rate_limit("insufficient_quota"), "quota_exhausted"),
        (openai_rate_limit("rate_limit_exceeded"), "rate_limited"),
        (openai.APITimeoutError(request=REQUEST), "timeout"),
        (openai_status(504), "timeout"),
        (openai_status(408), "timeout"),
        (openai_status(500), "provider_error"),
        (openai.APIConnectionError(request=REQUEST), "provider_error"),
    ],
)
def test_openai_maps_sdk_errors_to_outcomes(error: Exception, outcome: str):
    with pytest.raises(ProviderCallError) as raised:
        openai_with(RecordingCompletions(error=error)).invoke("gpt-a", MESSAGES, "sys")
    assert raised.value.outcome == outcome


def test_openai_unknown_model_id_is_a_provider_error_not_a_crash():
    # A model id left over from OpenRouter in CHAT_MODELS: OpenAI answers 404
    provider = openai_with(RecordingCompletions(error=openai_status(404)))
    assert provider.accepts(MODEL_A)
    with pytest.raises(ProviderCallError) as raised:
        provider.invoke(MODEL_A, MESSAGES, "sys")
    assert raised.value.outcome == "provider_error"


def test_openai_stream_error_after_first_chunk_is_a_provider_call_error():
    completions = RecordingCompletions(stream_error=openai.APIConnectionError(request=REQUEST))
    seen: list[str | None] = []
    with pytest.raises(ProviderCallError):
        for chunk in openai_with(completions).invoke_stream(
            "gpt-a", MESSAGES, "sys", timeout_s=9.0
        ):
            seen.append(chunk.delta)
    assert seen == ["part "]
    assert completions.calls[0]["timeout"] == 9.0


CLAUDE = "anthropic.claude-3-haiku-20240307-v1:0"
ANTHROPIC_REPLY = {
    "content": [{"type": "text", "text": "hi"}],
    "usage": {"input_tokens": 7, "output_tokens": 3},
}


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "m"}}, "InvokeModel")


# Stands in for the bedrock-runtime client: records every call, answers with the shapes boto3
# returns (a streaming body to read, or an event stream of chunks), or raises
class RecordingBedrock:
    def __init__(self, error: Exception | None = None, stream_error: Exception | None = None):
        self.calls: list[dict[str, Any]] = []
        self.error = error
        self.stream_error = stream_error

    @property
    def body(self) -> dict[str, Any]:
        return json.loads(self.calls[-1]["body"])

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"body": io.BytesIO(json.dumps(ANTHROPIC_REPLY).encode())}

    def invoke_model_with_response_stream(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"body": self._events()}

    def _events(self) -> Iterator[dict[str, Any]]:
        event = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "part "}}
        yield {"chunk": {"bytes": json.dumps(event).encode()}}
        if self.stream_error is not None:
            raise self.stream_error


def bedrock_with(client: RecordingBedrock) -> BedrockProvider:
    provider = BedrockProvider("ap-southeast-1", "", "", "", read_timeout_s=90, max_tokens=4096)
    provider.client = client
    return provider


def test_bedrock_sends_model_and_max_tokens_and_reads_usage():
    client = RecordingBedrock()
    response = bedrock_with(client).invoke(CLAUDE, MESSAGES, "sys", timeout_s=5.0)
    assert client.calls[0]["modelId"] == CLAUDE
    assert client.body["max_tokens"] == 4096 and client.body["system"] == "sys"
    assert client.body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    ]
    assert (response.answer, response.input_tokens, response.output_tokens) == ("hi", 7, 3)


def test_bedrock_ignores_response_format():
    client = RecordingBedrock()
    bedrock_with(client).invoke(CLAUDE, MESSAGES, "sys", response_format={"type": "json_object"})
    assert "response_format" not in client.body


def test_bedrock_sends_alternating_turns():
    client = RecordingBedrock()
    turns = [
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
    ]
    bedrock_with(client).invoke(CLAUDE, turns, "sys")
    assert client.body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "a\n\nb"}]}
    ]


def test_alternate_turns_merges_same_role_and_starts_with_user():
    turns = [
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "c"},
        {"role": "assistant", "content": [{"type": "text", "text": "d"}]},
    ]
    assert alternate_turns(turns) == [
        {"role": "user", "content": "a\n\nb"},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "c"}, {"type": "text", "text": "d"}],
        },
    ]


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (client_error("ThrottlingException"), "rate_limited"),
        (client_error("TooManyRequestsException"), "rate_limited"),
        (client_error("ServiceQuotaExceededException"), "rate_limited"),
        (client_error("ModelTimeoutException"), "timeout"),
        (client_error("ValidationException"), "provider_error"),
        (ReadTimeoutError(endpoint_url="https://bedrock"), "timeout"),
        (ConnectTimeoutError(endpoint_url="https://bedrock"), "timeout"),
        (EndpointConnectionError(endpoint_url="https://bedrock"), "provider_error"),
    ],
)
def test_bedrock_maps_errors_to_outcomes(error: Exception, outcome: str):
    with pytest.raises(ProviderCallError) as raised:
        bedrock_with(RecordingBedrock(error=error)).invoke(CLAUDE, MESSAGES, "sys")
    assert raised.value.outcome == outcome


def test_bedrock_stream_error_after_first_chunk_is_a_provider_call_error():
    # boto3 raises a throttling event from the stream with a lower-case code
    client = RecordingBedrock(stream_error=client_error("throttlingException"))
    seen: list[str | None] = []
    with pytest.raises(ProviderCallError) as raised:
        for chunk in bedrock_with(client).invoke_stream(CLAUDE, MESSAGES, "sys"):
            seen.append(chunk.delta)
    assert seen == ["part "]
    assert raised.value.outcome == "rate_limited"
    assert client.body["max_tokens"] == 4096


def test_role_credentials_come_from_assume_role_in_refreshable_form():
    expiry = datetime(2026, 11, 25, 16, 0, tzinfo=UTC)
    creds = {"AccessKeyId": "a", "SecretAccessKey": "s", "SessionToken": "t", "Expiration": expiry}
    calls: list[dict[str, Any]] = []

    def assume_role(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"Credentials": creds}

    sts = SimpleNamespace(assume_role=assume_role)
    assert role_credentials(sts, "arn:aws:iam::1:role/r") == {
        "access_key": "a",
        "secret_key": "s",
        "token": "t",
        "expiry_time": expiry.isoformat(),
    }
    assert calls[0]["RoleArn"] == "arn:aws:iam::1:role/r"


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (urllib3.exceptions.ReadTimeoutError(None, "https://bedrock", "read timed out"), "timeout"),
        (urllib3.exceptions.ProtocolError("connection reset"), "provider_error"),
    ],
)
def test_bedrock_stream_network_error_from_the_raw_body_is_a_provider_call_error(error, outcome):
    # The event stream reads the raw urllib3 response, so its errors are not botocore's
    client = RecordingBedrock(stream_error=error)
    with pytest.raises(ProviderCallError) as raised:
        list(bedrock_with(client).invoke_stream(CLAUDE, MESSAGES, "sys"))
    assert raised.value.outcome == outcome


def test_sdk_retries_are_off_so_the_router_owns_fallback():
    assert OpenAIProvider("key").client.max_retries == 0
    provider = BedrockProvider("ap-southeast-1", "", "", "", read_timeout_s=90, max_tokens=4096)
    assert provider.client.meta.config.retries["total_max_attempts"] == 1


# Stands in for client.embeddings: records every call and answers like the SDKs (data[i].embedding,
# usage.prompt_tokens), or raises
class RecordingEmbeddings:
    def __init__(self, error: Exception | None = None):
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def _answer(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        data = [SimpleNamespace(embedding=[float(i), 1.0]) for i, _ in enumerate(kwargs["input"])]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=6))

    generate = _answer  # OpenRouter
    create = _answer  # OpenAI


EMBED_MODEL = ModelId.NEMOTRON_3_EMBED_1B


def test_openrouter_embeds_with_the_same_client_model_and_timeout_per_call():
    embeddings = RecordingEmbeddings()
    provider = OpenRouterProvider("key", PATTERN)
    provider.client = SimpleNamespace(chat=RecordingChat(), embeddings=embeddings)  # type: ignore[assignment]
    response = provider.embed(EMBED_MODEL, ["a", "b"], timeout_s=30.0)
    assert response.vectors == [[0.0, 1.0], [1.0, 1.0]] and response.input_tokens == 6
    assert embeddings.calls[0] == {"model": EMBED_MODEL, "input": ["a", "b"], "timeout_ms": 30000}
    assert provider.accepts(EMBED_MODEL)


def test_openrouter_embed_maps_sdk_errors():
    provider = OpenRouterProvider("key", PATTERN)
    embeddings = RecordingEmbeddings(error=rate_limit("free-models-per-day"))
    provider.client = SimpleNamespace(embeddings=embeddings)  # type: ignore[assignment]
    with pytest.raises(ProviderCallError) as raised:
        provider.embed(EMBED_MODEL, ["a"])
    assert raised.value.outcome == "quota_exhausted"


def test_openai_embeds_with_model_and_timeout_per_call():
    embeddings = RecordingEmbeddings()
    provider = OpenAIProvider("key")
    provider.client = SimpleNamespace(embeddings=embeddings)  # type: ignore[assignment]
    response = provider.embed("text-embedding-3-small", ["a"], timeout_s=9.0)
    assert response.vectors == [[0.0, 1.0]] and response.input_tokens == 6
    assert embeddings.calls[0] == {
        "model": "text-embedding-3-small",
        "input": ["a"],
        "timeout": 9.0,
    }


def test_openai_embed_maps_sdk_errors():
    provider = OpenAIProvider("key")
    embeddings = RecordingEmbeddings(error=openai_rate_limit("rate_limit_exceeded"))
    provider.client = SimpleNamespace(embeddings=embeddings)  # type: ignore[assignment]
    with pytest.raises(ProviderCallError) as raised:
        provider.embed("text-embedding-3-small", ["a"])
    assert raised.value.outcome == "rate_limited"


# Stands in for bedrock-runtime invoke_model with an embedding model's reply
class EmbeddingBedrock(RecordingBedrock):
    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        request = json.loads(kwargs["body"])
        if kwargs["modelId"].startswith("amazon.titan-embed"):
            reply = {"embedding": [float(len(request["inputText"]))], "inputTextTokenCount": 2}
        else:
            reply = {"embeddings": [[float(len(t))] for t in request["texts"]]}
        return {"body": io.BytesIO(json.dumps(reply).encode())}


def test_bedrock_titan_embeds_one_text_per_call_and_counts_tokens():
    client = EmbeddingBedrock()
    response = bedrock_with(client).embed("amazon.titan-embed-text-v2:0", ["ab", "abc"])
    assert response.vectors == [[2.0], [3.0]] and response.input_tokens == 4
    assert [json.loads(c["body"]) for c in client.calls] == [
        {"inputText": "ab"},
        {"inputText": "abc"},
    ]


def test_bedrock_cohere_embeds_the_batch_in_one_call():
    client = EmbeddingBedrock()
    response = bedrock_with(client).embed("cohere.embed-multilingual-v3", ["ab", "abc"])
    assert response.vectors == [[2.0], [3.0]] and response.input_tokens == 0
    assert json.loads(client.calls[0]["body"]) == {
        "texts": ["ab", "abc"],
        "input_type": "search_document",
    }


def test_bedrock_unknown_embedding_family_is_a_provider_error_without_a_call():
    client = EmbeddingBedrock()
    with pytest.raises(ProviderCallError) as raised:
        bedrock_with(client).embed(CLAUDE, ["a"])
    assert raised.value.outcome == "provider_error" and client.calls == []


def test_bedrock_embed_maps_client_errors():
    client = EmbeddingBedrock(error=client_error("ThrottlingException"))
    with pytest.raises(ProviderCallError) as raised:
        bedrock_with(client).embed("amazon.titan-embed-text-v2:0", ["a"])
    assert raised.value.outcome == "rate_limited"
