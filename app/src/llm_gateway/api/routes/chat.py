"""POST /v1/chat/completions."""

from __future__ import annotations

import time
from typing import Final

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response, StreamingResponse

from llm_gateway.api.dependencies import ChatServiceDep, TenantDep
from llm_gateway.api.openai_format import build_completion, new_completion_id, sse_stream
from llm_gateway.api.schemas import ChatCompletionRequest, ChatCompletionResponse
from llm_gateway.ratelimit.token_budget import Reservation

router = APIRouter(prefix="/v1", tags=["chat"])

PROVIDER_HEADER: Final = "x-llmgw-provider"
_STREAM_HEADERS: Final = {"cache-control": "no-cache", "x-accel-buffering": "no"}


def _response_headers(reservation: Reservation, provider: str) -> dict[str, str]:
    return {
        "x-ratelimit-limit-tokens": str(reservation.capacity),
        "x-ratelimit-remaining-tokens": str(max(reservation.remaining, 0)),
        PROVIDER_HEADER: provider,
    }


@router.post(
    "/chat/completions",
    response_model=ChatCompletionResponse,
    summary="Create a chat completion (OpenAI-compatible).",
)
async def create_chat_completion(
    body: ChatCompletionRequest, tenant: TenantDep, chat: ChatServiceDep
) -> Response:
    prompt = body.to_prompt()

    if body.stream:
        stream = await chat.stream(tenant=tenant, alias=body.model, prompt=prompt)
        return StreamingResponse(
            sse_stream(stream.chunks, alias=body.model, include_usage=body.include_usage),
            media_type="text/event-stream",
            headers={**_STREAM_HEADERS, **_response_headers(stream.reservation, stream.provider)},
        )

    outcome = await chat.complete(tenant=tenant, alias=body.model, prompt=prompt)
    completion = build_completion(
        completion_id=new_completion_id(),
        alias=body.model,
        created=int(time.time()),
        result=outcome.result,
    )
    return JSONResponse(
        completion.model_dump(mode="json", exclude_none=True),
        headers=_response_headers(outcome.reservation, outcome.provider),
    )
