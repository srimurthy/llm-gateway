"""Per-provider circuit breaker.

State is per pod, by design: no shared store sits on the failure path, and each pod
learns about a failing provider within ``failure_threshold`` requests of its own.

CLOSED --(threshold consecutive failures)--> OPEN --(reset timeout)--> HALF_OPEN
HALF_OPEN lets one trial request through: success closes, failure reopens. A trial that
never reports back (its caller was cancelled) expires after ``reset_timeout_s``, so the
breaker cannot get stuck half-open.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum

import structlog

from llm_gateway.config.routing import CircuitBreakerSettings
from llm_gateway.observability import metrics

log = structlog.get_logger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        settings: CircuitBreakerSettings,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._name = name
        self._settings = settings
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._trial_started_at: float | None = None
        metrics.CIRCUIT_OPEN.labels(provider=name).set(0)

    @property
    def state(self) -> CircuitState:
        return self._state

    def allow_request(self) -> bool:
        if self._state is CircuitState.CLOSED:
            return True
        now = self._clock()
        if self._state is CircuitState.OPEN:
            if now - self._opened_at < self._settings.reset_timeout_s:
                return False
            self._transition(CircuitState.HALF_OPEN)
        trial_running = (
            self._trial_started_at is not None
            and now - self._trial_started_at < self._settings.reset_timeout_s
        )
        if trial_running:
            return False
        self._trial_started_at = now
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._trial_started_at = None
        if self._state is not CircuitState.CLOSED:
            self._transition(CircuitState.CLOSED)

    def record_failure(self) -> None:
        self._failures += 1
        self._trial_started_at = None
        if (
            self._state is CircuitState.HALF_OPEN
            or self._failures >= self._settings.failure_threshold
        ):
            self._opened_at = self._clock()
            if self._state is not CircuitState.OPEN:
                self._transition(CircuitState.OPEN)

    def _transition(self, state: CircuitState) -> None:
        log.warning("circuit_state_changed", provider=self._name, old=self._state, new=state)
        self._state = state
        metrics.CIRCUIT_OPEN.labels(provider=self._name).set(1 if state is CircuitState.OPEN else 0)
