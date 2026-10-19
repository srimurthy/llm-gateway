"""Token estimates used to reserve budget before a provider call.

The provider's reported usage settles the difference afterwards, so these only need to
be roughly right, cheap, and the same for every provider. A real tokenizer would differ
per model family anyway.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Final

from llm_gateway.core.models import ChatMessage, Usage

CHARS_PER_TOKEN: Final = 4
MESSAGE_OVERHEAD_TOKENS: Final = 4
REPLY_PRIMING_TOKENS: Final = 3


def estimate_text_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def estimate_prompt_tokens(messages: Iterable[ChatMessage]) -> int:
    return REPLY_PRIMING_TOKENS + sum(
        MESSAGE_OVERHEAD_TOKENS + estimate_text_tokens(message.content) for message in messages
    )


def estimate_usage(*, prompt_tokens: int, output_text: str) -> Usage:
    """Usage to bill when a provider did not report it (for example, a client disconnect)."""
    return Usage(prompt_tokens=prompt_tokens, completion_tokens=estimate_text_tokens(output_text))
