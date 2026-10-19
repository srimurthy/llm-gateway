"""Amazon Bedrock through the Converse API, which gives one request shape for every model family.

The pure functions at the top translate requests, responses and errors. They hold all of
the mapping logic and are unit-tested without AWS; ``BedrockProvider`` only does I/O.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from botocore.exceptions import BotoCoreError, ClientError

from llm_gateway.core.errors import (
    ProviderError,
    ProviderRequestError,
    ProviderThrottledError,
    ProviderUnavailableError,
)
from llm_gateway.core.models import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResult,
    FinishReason,
    Role,
    Usage,
)

if TYPE_CHECKING:
    from types_aiobotocore_bedrock_runtime import BedrockRuntimeClient

_THROTTLING_CODES: Final = frozenset(
    {"ThrottlingException", "ServiceQuotaExceededException", "TooManyRequestsException"}
)
_REQUEST_ERROR_CODES: Final = frozenset({"ValidationException"})

_STOP_REASONS: Final[Mapping[str, FinishReason]] = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "max_tokens": FinishReason.LENGTH,
    "content_filtered": FinishReason.CONTENT_FILTER,
    "guardrail_intervened": FinishReason.CONTENT_FILTER,
}

# Errors that arrive as events inside an open ConverseStream response.
_STREAM_ERROR_EVENTS: Final[Mapping[str, type[ProviderError]]] = {
    "throttlingException": ProviderThrottledError,
    "serviceUnavailableException": ProviderUnavailableError,
    "internalServerException": ProviderUnavailableError,
    "modelStreamErrorException": ProviderUnavailableError,
    "validationException": ProviderRequestError,
}


def build_converse_kwargs(model_id: str, request: ChatRequest) -> dict[str, Any]:
    system = [{"text": m.content} for m in request.messages if m.role is Role.SYSTEM]
    turns = merge_consecutive_turns([m for m in request.messages if m.role is not Role.SYSTEM])

    inference: dict[str, Any] = {"maxTokens": request.max_tokens}
    if request.temperature is not None:
        inference["temperature"] = request.temperature
    if request.top_p is not None:
        inference["topP"] = request.top_p
    if request.stop:
        inference["stopSequences"] = list(request.stop)

    kwargs: dict[str, Any] = {
        "modelId": model_id,
        "messages": [{"role": m.role.value, "content": [{"text": m.content}]} for m in turns],
        "inferenceConfig": inference,
    }
    if system:
        kwargs["system"] = system
    return kwargs


def merge_consecutive_turns(messages: Sequence[ChatMessage]) -> list[ChatMessage]:
    """Join back-to-back turns from the same role.

    Converse rejects two user (or assistant) turns in a row; OpenAI-style callers send them.
    """
    merged: list[ChatMessage] = []
    for message in messages:
        if merged and merged[-1].role is message.role:
            previous = merged[-1]
            merged[-1] = ChatMessage(
                role=message.role, content=f"{previous.content}\n\n{message.content}"
            )
        else:
            merged.append(message)
    return merged


def map_stop_reason(reason: str | None) -> FinishReason:
    return _STOP_REASONS.get(reason or "", FinishReason.STOP)


def map_usage(raw: Mapping[str, Any] | None) -> Usage | None:
    if not raw:
        return None
    return Usage(
        prompt_tokens=int(raw.get("inputTokens", 0)),
        completion_tokens=int(raw.get("outputTokens", 0)),
    )


def map_client_error(provider: str, error: ClientError) -> ProviderError:
    details = error.response.get("Error", {})
    code = str(details.get("Code", ""))
    if code in _THROTTLING_CODES:
        return ProviderThrottledError(provider, code)
    if code in _REQUEST_ERROR_CODES:
        return ProviderRequestError(provider, str(details.get("Message", code))[:500])
    # AccessDenied, ResourceNotFound and friends are deployment mistakes. Falling back to
    # the next provider keeps the service up while the alarm on this metric gets fixed.
    return ProviderUnavailableError(provider, code or "client_error")


def parse_stream_event(provider: str, event: Mapping[str, Any]) -> ChatChunk | None:
    if delta := event.get("contentBlockDelta"):
        text = delta.get("delta", {}).get("text")
        return ChatChunk(text=text) if text else None
    if stop := event.get("messageStop"):
        return ChatChunk(finish_reason=map_stop_reason(stop.get("stopReason")))
    if metadata := event.get("metadata"):
        usage = map_usage(metadata.get("usage"))
        return ChatChunk(usage=usage) if usage else None
    for key, error_type in _STREAM_ERROR_EVENTS.items():
        if key in event:
            raise error_type(provider, key)
    return None


class BedrockProvider:
    def __init__(self, name: str, *, model_id: str, client: BedrockRuntimeClient) -> None:
        self._name = name
        self._model_id = model_id
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    async def complete(self, request: ChatRequest) -> ChatResult:
        try:
            response = await self._client.converse(**build_converse_kwargs(self._model_id, request))
        except ClientError as exc:
            raise map_client_error(self._name, exc) from exc
        except BotoCoreError as exc:
            raise ProviderUnavailableError(self._name, type(exc).__name__) from exc

        content = response["output"].get("message", {}).get("content", [])
        return ChatResult(
            text="".join(block.get("text", "") for block in content),
            finish_reason=map_stop_reason(response.get("stopReason")),
            usage=map_usage(response.get("usage")),
        )

    async def stream(self, request: ChatRequest) -> AsyncGenerator[ChatChunk]:
        try:
            response = await self._client.converse_stream(
                **build_converse_kwargs(self._model_id, request)
            )
            async for event in response["stream"]:
                if chunk := parse_stream_event(self._name, event):
                    yield chunk
        except ClientError as exc:
            raise map_client_error(self._name, exc) from exc
        except BotoCoreError as exc:
            raise ProviderUnavailableError(self._name, type(exc).__name__) from exc
