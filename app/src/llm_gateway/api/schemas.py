"""Request and response bodies, compatible with the OpenAI Chat Completions API.

Unknown request fields are rejected rather than ignored: silently dropping ``tools`` or
``response_format`` would return an answer the caller did not ask for.
"""

from __future__ import annotations

from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_gateway.core.models import ChatMessage, ChatPrompt, Role

MAX_PROMPT_CHARS: Final = 2_000_000


class TextContentPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    text: str


class ChatMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "developer", "user", "assistant"]
    content: str | list[TextContentPart]
    name: str | None = Field(default=None, max_length=64)

    @property
    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "".join(part.text for part in self.content)

    def to_message(self) -> ChatMessage:
        role = Role.SYSTEM if self.role == "developer" else Role(self.role)
        return ChatMessage(role=role, content=self.text)


class StreamOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_usage: bool = False


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=128, description="A model alias.")
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=1024)
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    stop: str | list[str] | None = None
    stream: bool = False
    stream_options: StreamOptions | None = None
    n: Literal[1] = 1
    user: str | None = Field(
        default=None, max_length=256, description="Accepted for compatibility; not used."
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if (
            self.max_tokens is not None
            and self.max_completion_tokens is not None
            and self.max_tokens != self.max_completion_tokens
        ):
            raise ValueError("max_tokens and max_completion_tokens disagree; send one of them")
        if isinstance(self.stop, list) and len(self.stop) > 4:  # noqa: PLR2004 - OpenAI's limit
            raise ValueError("stop accepts at most 4 sequences")
        if sum(len(m.text) for m in self.messages) > MAX_PROMPT_CHARS:
            raise ValueError(f"messages exceed {MAX_PROMPT_CHARS} characters in total")
        return self

    @property
    def include_usage(self) -> bool:
        return bool(self.stream_options and self.stream_options.include_usage)

    def to_prompt(self) -> ChatPrompt:
        stop = (self.stop,) if isinstance(self.stop, str) else tuple(self.stop or ())
        return ChatPrompt(
            messages=tuple(m.to_message() for m in self.messages),
            max_tokens=self.max_completion_tokens or self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            stop=stop,
        )


class UsageOut(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class AssistantMessageOut(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChoiceOut(BaseModel):
    index: int = 0
    message: AssistantMessageOut
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChoiceOut]
    usage: UsageOut | None = None


class DeltaOut(BaseModel):
    role: Literal["assistant"] | None = None
    content: str | None = None


class ChunkChoiceOut(BaseModel):
    index: int = 0
    delta: DeltaOut
    finish_reason: str | None = None


class ChatCompletionChunkOut(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoiceOut]
    usage: UsageOut | None = None


class ModelOut(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "llm-gateway"
    description: str = ""


class ModelListOut(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelOut]


class JobAcceptedOut(BaseModel):
    id: str
    object: Literal["chat.completion.job"] = "chat.completion.job"
    status: str
    status_url: str


class JobErrorOut(BaseModel):
    code: str
    message: str


class JobOut(BaseModel):
    id: str
    object: Literal["chat.completion.job"] = "chat.completion.job"
    status: str
    model: str
    created_at: str
    result: ChatCompletionResponse | None = None
    error: JobErrorOut | None = None
