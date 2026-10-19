"""Provider-neutral chat types shared by the API, the router and every provider."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ChatPrompt:
    """What the caller asked for, before the gateway applies the alias's limits."""

    messages: tuple[ChatMessage, ...]
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: tuple[str, ...] = ()

    def to_request(self, max_tokens: int) -> ChatRequest:
        return ChatRequest(
            messages=self.messages,
            max_tokens=max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            stop=self.stop,
        )


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """A fully resolved request, ready to send to a provider."""

    messages: tuple[ChatMessage, ...]
    max_tokens: int
    temperature: float | None = None
    top_p: float | None = None
    stop: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    finish_reason: FinishReason
    usage: Usage | None


@dataclass(frozen=True, slots=True)
class ChatChunk:
    """One streamed increment. A chunk can carry text, a finish reason, usage, or a mix."""

    text: str = ""
    finish_reason: FinishReason | None = None
    usage: Usage | None = None
