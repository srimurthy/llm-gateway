"""Job records and the queue message that carries a job to the worker."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from llm_gateway.core.models import ChatMessage, ChatPrompt, Role

JOB_ID_PATTERN = r"^job-[0-9a-f]{32}$"


class JobStatus(StrEnum):
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class JobError:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    tenant: str
    alias: str
    status: JobStatus
    created_at: datetime
    result: dict[str, Any] | None = None
    error: JobError | None = None


def new_job_id() -> str:
    return f"job-{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class JobMessage:
    job_id: str
    tenant: str
    alias: str
    prompt: ChatPrompt

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "tenant": self.tenant,
                "alias": self.alias,
                "prompt": {
                    "messages": [
                        {"role": m.role.value, "content": m.content} for m in self.prompt.messages
                    ],
                    "max_tokens": self.prompt.max_tokens,
                    "temperature": self.prompt.temperature,
                    "top_p": self.prompt.top_p,
                    "stop": list(self.prompt.stop),
                },
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, body: str) -> JobMessage:
        """Parse a queue message. Raises ``ValueError`` for anything malformed."""
        try:
            data = json.loads(body)
            prompt = data["prompt"]
            return cls(
                job_id=str(data["job_id"]),
                tenant=str(data["tenant"]),
                alias=str(data["alias"]),
                prompt=ChatPrompt(
                    messages=tuple(
                        ChatMessage(role=Role(m["role"]), content=str(m["content"]))
                        for m in prompt["messages"]
                    ),
                    max_tokens=prompt.get("max_tokens"),
                    temperature=prompt.get("temperature"),
                    top_p=prompt.get("top_p"),
                    stop=tuple(prompt.get("stop") or ()),
                ),
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"malformed job message: {exc}") from exc
