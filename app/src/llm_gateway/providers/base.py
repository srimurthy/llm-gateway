"""The contract every model backend implements."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Protocol

from llm_gateway.core.models import ChatChunk, ChatRequest, ChatResult


class ChatProvider(Protocol):
    """A model backend.

    Implementations raise only ``ProviderError`` subclasses, so the router can decide
    between falling back and failing the request without knowing any SDK.
    """

    @property
    def name(self) -> str: ...

    async def complete(self, request: ChatRequest) -> ChatResult: ...

    def stream(self, request: ChatRequest) -> AsyncGenerator[ChatChunk]: ...
