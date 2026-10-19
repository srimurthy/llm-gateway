"""Echo provider for local development and tests. Never route a production alias here."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator

from llm_gateway.core.models import ChatChunk, ChatRequest, ChatResult, FinishReason, Role, Usage
from llm_gateway.core.tokens import estimate_prompt_tokens, estimate_text_tokens

_WORD = re.compile(r"\S+\s*")


class MockProvider:
    def __init__(self, name: str, *, chunk_delay_s: float = 0.0) -> None:
        self._name = name
        self._chunk_delay_s = chunk_delay_s

    @property
    def name(self) -> str:
        return self._name

    async def complete(self, request: ChatRequest) -> ChatResult:
        text = self._reply(request)
        return ChatResult(text=text, finish_reason=FinishReason.STOP, usage=_usage(request, text))

    async def stream(self, request: ChatRequest) -> AsyncGenerator[ChatChunk]:
        text = self._reply(request)
        for word in _WORD.findall(text):
            if self._chunk_delay_s:
                await asyncio.sleep(self._chunk_delay_s)
            yield ChatChunk(text=word)
        yield ChatChunk(finish_reason=FinishReason.STOP, usage=_usage(request, text))

    @staticmethod
    def _reply(request: ChatRequest) -> str:
        last_user = next((m.content for m in reversed(request.messages) if m.role is Role.USER), "")
        words = _WORD.findall(f"echo: {last_user}")
        return "".join(words[: request.max_tokens]).rstrip()


def _usage(request: ChatRequest, text: str) -> Usage:
    return Usage(
        prompt_tokens=estimate_prompt_tokens(request.messages),
        completion_tokens=estimate_text_tokens(text),
    )
