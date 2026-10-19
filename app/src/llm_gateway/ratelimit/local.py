"""In-pod token buckets, used only while Valkey is unreachable.

Each pod gets a fraction of the real budget, so the fleet as a whole stays near the
tenant's limit without any coordination. The event loop is single-threaded and these
methods never await, so no lock is needed.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

_MS_PER_MINUTE = 60_000


@dataclass(frozen=True, slots=True)
class LocalDecision:
    allowed: bool
    remaining: int
    retry_after_ms: int


class LocalTokenBuckets:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}

    def take(self, key: str, *, capacity: float, tokens: int) -> LocalDecision:
        level = self._refill(key, capacity)
        if level >= tokens:
            level -= tokens
            self._buckets[key] = (level, self._now_ms())
            return LocalDecision(allowed=True, remaining=math.floor(level), retry_after_ms=0)
        retry_after_ms = math.ceil((tokens - level) / (capacity / _MS_PER_MINUTE))
        return LocalDecision(
            allowed=False, remaining=math.floor(level), retry_after_ms=retry_after_ms
        )

    def adjust(self, key: str, *, capacity: float, delta: int) -> None:
        level = self._refill(key, capacity)
        self._buckets[key] = (min(capacity, level + delta), self._now_ms())

    def _refill(self, key: str, capacity: float) -> float:
        now = self._now_ms()
        level, updated = self._buckets.get(key, (capacity, now))
        return min(capacity, level + (now - updated) * capacity / _MS_PER_MINUTE)

    def _now_ms(self) -> float:
        return self._clock() * 1000
