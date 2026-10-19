"""Turn neutral results into OpenAI-format JSON and server-sent events."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog

from llm_gateway.api.schemas import (
    AssistantMessageOut,
    ChatCompletionChunkOut,
    ChatCompletionResponse,
    ChoiceOut,
    ChunkChoiceOut,
    DeltaOut,
    UsageOut,
)
from llm_gateway.core.errors import ProviderError
from llm_gateway.core.models import ChatChunk, ChatResult, Usage
from llm_gateway.observability import metrics

log = structlog.get_logger(__name__)


def new_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex}"


def usage_out(usage: Usage | None) -> UsageOut | None:
    if usage is None:
        return None
    return UsageOut(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def error_body(message: str, *, error_type: str, code: str) -> dict[str, Any]:
    return {"error": {"message": message, "type": error_type, "code": code}}


def build_completion(
    *, completion_id: str, alias: str, created: int, result: ChatResult
) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=alias,
        choices=[
            ChoiceOut(
                message=AssistantMessageOut(content=result.text),
                finish_reason=result.finish_reason.value,
            )
        ],
        usage=usage_out(result.usage),
    )


async def sse_stream(
    chunks: AsyncIterator[ChatChunk], *, alias: str, include_usage: bool
) -> AsyncIterator[str]:
    completion_id = new_completion_id()
    created = int(time.time())

    def frame(choices: list[ChunkChoiceOut], usage: UsageOut | None = None) -> str:
        payload = ChatCompletionChunkOut(
            id=completion_id, created=created, model=alias, choices=choices, usage=usage
        )
        return f"data: {payload.model_dump_json(exclude_none=True)}\n\n"

    usage: Usage | None = None
    metrics.ACTIVE_STREAMS.inc()
    try:
        yield frame([ChunkChoiceOut(delta=DeltaOut(role="assistant", content=""))])
        try:
            async for chunk in chunks:
                if chunk.usage is not None:
                    usage = chunk.usage
                if chunk.text or chunk.finish_reason is not None:
                    finish = chunk.finish_reason.value if chunk.finish_reason else None
                    yield frame(
                        [
                            ChunkChoiceOut(
                                delta=DeltaOut(content=chunk.text or None), finish_reason=finish
                            )
                        ]
                    )
        except ProviderError:
            # Headers are already sent, so the status cannot change. Send an error event,
            # the way OpenAI does, and end the stream without [DONE].
            body = error_body(
                "The model provider failed mid-stream. Retry the request.",
                error_type="server_error",
                code="stream_interrupted",
            )
            yield f"data: {json.dumps(body)}\n\n"
            return
        if include_usage and usage is not None:
            yield frame([], usage=usage_out(usage))
        yield "data: [DONE]\n\n"
    finally:
        metrics.ACTIVE_STREAMS.dec()
