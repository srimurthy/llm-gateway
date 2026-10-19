import json

import httpx2 as httpx
import pytest
from botocore.exceptions import ClientError
from openai import AsyncOpenAI

from llm_gateway.core.errors import (
    ProviderRequestError,
    ProviderThrottledError,
    ProviderUnavailableError,
)
from llm_gateway.core.models import ChatMessage, ChatRequest, FinishReason, Role, Usage
from llm_gateway.providers.bedrock import (
    build_converse_kwargs,
    map_client_error,
    parse_stream_event,
)
from llm_gateway.providers.mock import MockProvider
from llm_gateway.providers.openai_compatible import OpenAICompatibleProvider

REQUEST = ChatRequest(
    messages=(
        ChatMessage(Role.SYSTEM, "be brief"),
        ChatMessage(Role.USER, "first"),
        ChatMessage(Role.USER, "second"),
        ChatMessage(Role.ASSISTANT, "ok"),
        ChatMessage(Role.USER, "third"),
    ),
    max_tokens=64,
    temperature=0.2,
    stop=("END",),
)


class TestBedrockMapping:
    def test_builds_converse_request(self) -> None:
        kwargs = build_converse_kwargs("model-x", REQUEST)

        assert kwargs["modelId"] == "model-x"
        assert kwargs["system"] == [{"text": "be brief"}]
        assert kwargs["inferenceConfig"] == {
            "maxTokens": 64,
            "temperature": 0.2,
            "stopSequences": ["END"],
        }
        roles = [m["role"] for m in kwargs["messages"]]
        assert roles == ["user", "assistant", "user"], "consecutive user turns are merged"
        assert kwargs["messages"][0]["content"] == [{"text": "first\n\nsecond"}]

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("ThrottlingException", ProviderThrottledError),
            ("ValidationException", ProviderRequestError),
            ("ModelNotReadyException", ProviderUnavailableError),
            ("AccessDeniedException", ProviderUnavailableError),
        ],
    )
    def test_maps_client_errors(self, code: str, expected: type) -> None:
        error = ClientError({"Error": {"Code": code, "Message": "m"}}, "Converse")

        assert isinstance(map_client_error("bedrock", error), expected)

    def test_parses_stream_events(self) -> None:
        assert parse_stream_event("b", {"contentBlockDelta": {"delta": {"text": "hi"}}}) is not None
        stop = parse_stream_event("b", {"messageStop": {"stopReason": "max_tokens"}})
        assert stop is not None
        assert stop.finish_reason is FinishReason.LENGTH
        meta = parse_stream_event(
            "b", {"metadata": {"usage": {"inputTokens": 5, "outputTokens": 7}}}
        )
        assert meta is not None
        assert meta.usage == Usage(5, 7)
        assert parse_stream_event("b", {"contentBlockStart": {}}) is None

    def test_stream_error_events_raise(self) -> None:
        with pytest.raises(ProviderThrottledError):
            parse_stream_event("b", {"throttlingException": {"message": "slow down"}})


def openai_provider(handler: httpx.MockTransport) -> OpenAICompatibleProvider:
    client = AsyncOpenAI(
        base_url="http://vllm.test/v1",
        api_key="k",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=handler),
    )
    return OpenAICompatibleProvider("vllm", client=client, model="m")


class TestOpenAICompatible:
    async def test_complete_maps_response(self) -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["max_tokens"] == 64
            assert body["stop"] == ["END"]
            return httpx.Response(
                200,
                json={
                    "id": "x",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "m",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "hello"},
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
                },
            )

        result = await openai_provider(httpx.MockTransport(handle)).complete(REQUEST)

        assert result.text == "hello"
        assert result.finish_reason is FinishReason.LENGTH
        assert result.usage == Usage(3, 1)

    async def test_stream_maps_chunks_and_usage(self) -> None:
        events = [
            {"choices": []},
            {"choices": [{"index": 0, "delta": {"content": "he"}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {"content": "llo"}, "finish_reason": "stop"}]},
            {
                "choices": [],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        ]
        envelope = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": "m"}
        frames = [f"data: {json.dumps({**envelope, **event})}\n\n" for event in events]
        body = "".join(frames) + "data: [DONE]\n\n"

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

        chunks = [c async for c in openai_provider(httpx.MockTransport(handle)).stream(REQUEST)]

        assert "".join(c.text for c in chunks) == "hello"
        assert chunks[-1].usage == Usage(3, 2)
        assert any(c.finish_reason is FinishReason.STOP for c in chunks)

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (429, ProviderThrottledError),
            (500, ProviderUnavailableError),
            (401, ProviderUnavailableError),
            (400, ProviderRequestError),
        ],
    )
    async def test_maps_http_errors(self, status: int, expected: type) -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"error": {"message": "nope"}})

        with pytest.raises(expected):
            await openai_provider(httpx.MockTransport(handle)).complete(REQUEST)


async def test_mock_provider_echoes_last_user_message() -> None:
    provider = MockProvider("mock")

    result = await provider.complete(REQUEST)
    streamed = "".join([c.text async for c in provider.stream(REQUEST)])

    assert result.text == "echo: third"
    assert streamed == "echo: third"
