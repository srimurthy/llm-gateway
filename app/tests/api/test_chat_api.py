import json

import httpx
import pytest

from llm_gateway.core.errors import ProviderThrottledError, ProviderUnavailableError
from llm_gateway.core.models import Usage
from tests.conftest import TENANT_HEADERS
from tests.fakes import Fail, FailMidStream, ScriptedProvider, Succeed

pytestmark = pytest.mark.usefixtures("client")


def chat_body(**overrides: object) -> dict[str, object]:
    return {"model": "fast", "messages": [{"role": "user", "content": "hi"}], **overrides}


def sse_events(text: str) -> list[str]:
    return [line.removeprefix("data: ") for line in text.split("\n\n") if line]


async def test_completion_returns_openai_shape(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/chat/completions", json=chat_body(), headers=TENANT_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "fast"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "hello world"}
    assert body["usage"] == {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    assert response.headers["x-llmgw-provider"] == "primary"
    assert int(response.headers["x-ratelimit-remaining-tokens"]) < 100_000
    assert response.headers["x-request-id"]


async def test_fallback_is_invisible_to_the_client(
    client: httpx.AsyncClient, primary: ScriptedProvider
) -> None:
    primary._behaviors = [Fail(ProviderThrottledError("primary", "429"))]

    response = await client.post("/v1/chat/completions", json=chat_body(), headers=TENANT_HEADERS)

    assert response.status_code == 200
    assert response.headers["x-llmgw-provider"] == "secondary"


async def test_all_providers_down_returns_503_with_retry_after(
    client: httpx.AsyncClient, primary: ScriptedProvider, secondary: ScriptedProvider
) -> None:
    primary._behaviors = [Fail(ProviderUnavailableError("primary", "500"))]
    secondary._behaviors = [Fail(ProviderUnavailableError("secondary", "500"))]

    response = await client.post("/v1/chat/completions", json=chat_body(), headers=TENANT_HEADERS)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "providers_unavailable"
    assert response.headers["retry-after"]


async def test_streaming_emits_sse_and_done(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=chat_body(stream=True, stream_options={"include_usage": True}),
        headers=TENANT_HEADERS,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.text)
    assert events[-1] == "[DONE]"
    chunks = [json.loads(e) for e in events[:-1]]
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"])
    assert text == "hello world "
    assert chunks[-1]["usage"]["total_tokens"] == 12


async def test_stream_failure_before_first_token_returns_error_status(
    client: httpx.AsyncClient, primary: ScriptedProvider, secondary: ScriptedProvider
) -> None:
    primary._behaviors = [Fail(ProviderThrottledError("primary", "429"))]
    secondary._behaviors = [Fail(ProviderThrottledError("secondary", "429"))]

    response = await client.post(
        "/v1/chat/completions", json=chat_body(stream=True), headers=TENANT_HEADERS
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "providers_throttled"


async def test_stream_failure_mid_stream_sends_error_event(
    client: httpx.AsyncClient, primary: ScriptedProvider
) -> None:
    primary._behaviors = [FailMidStream(["partial "], ProviderUnavailableError("primary", "reset"))]

    response = await client.post(
        "/v1/chat/completions", json=chat_body(stream=True), headers=TENANT_HEADERS
    )

    events = sse_events(response.text)
    assert response.status_code == 200
    assert "[DONE]" not in events
    assert json.loads(events[-1])["error"]["code"] == "stream_interrupted"


async def test_missing_tenant_is_401(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/chat/completions", json=chat_body())

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"


async def test_malformed_tenant_is_401(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=chat_body(), headers={"x-tenant-id": "a:b/../c"}
    )

    assert response.status_code == 401


async def test_alias_not_allowed_is_403(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=chat_body(model="smart"),
        headers={"x-tenant-id": "team-restricted"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_not_allowed"


async def test_unknown_alias_is_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=chat_body(model="gpt-9"), headers=TENANT_HEADERS
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"


async def test_unsupported_fields_are_400(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=chat_body(tools=[{"type": "function"}]),
        headers=TENANT_HEADERS,
    )

    assert response.status_code == 400
    assert "tools" in response.json()["error"]["message"]


async def test_max_tokens_above_alias_limit_is_400(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=chat_body(max_tokens=5000), headers=TENANT_HEADERS
    )

    assert response.status_code == 400
    assert "at most 1024" in response.json()["error"]["message"]


async def test_budget_exhaustion_is_429_with_headers(
    client: httpx.AsyncClient, primary: ScriptedProvider
) -> None:
    # team-tiny has 1,100 tokens per minute; each request reserves prompt + 1,000.
    primary._behaviors = [Succeed(usage=Usage(10, 1000))]
    headers = {"x-tenant-id": "team-tiny"}
    body = chat_body(max_tokens=1000)

    first = await client.post("/v1/chat/completions", json=body, headers=headers)
    second = await client.post("/v1/chat/completions", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "tokens_per_minute_exceeded"
    assert second.headers["x-ratelimit-limit-tokens"] == "1100"
    assert int(second.headers["retry-after"]) >= 1


async def test_models_lists_only_allowed_aliases(client: httpx.AsyncClient) -> None:
    everything = await client.get("/v1/models", headers=TENANT_HEADERS)
    restricted = await client.get("/v1/models", headers={"x-tenant-id": "team-restricted"})

    assert [m["id"] for m in everything.json()["data"]] == ["fast", "smart"]
    assert [m["id"] for m in restricted.json()["data"]] == ["fast"]


async def test_health_endpoints(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get("/readyz")).json() == {"status": "ready"}
