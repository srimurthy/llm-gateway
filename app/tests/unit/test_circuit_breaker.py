from llm_gateway.config.routing import CircuitBreakerSettings
from llm_gateway.routing.circuit_breaker import CircuitBreaker, CircuitState
from tests.fakes import FakeClock


def make_breaker(clock: FakeClock) -> CircuitBreaker:
    return CircuitBreaker(
        "p", CircuitBreakerSettings(failure_threshold=3, reset_timeout_s=10), clock=clock
    )


def test_opens_after_consecutive_failures() -> None:
    breaker = make_breaker(FakeClock())
    for _ in range(2):
        breaker.record_failure()
    assert breaker.allow_request()

    breaker.record_failure()

    assert breaker.state is CircuitState.OPEN
    assert not breaker.allow_request()


def test_success_resets_failure_count() -> None:
    breaker = make_breaker(FakeClock())
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state is CircuitState.CLOSED


def test_half_open_allows_one_trial_then_closes_on_success() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure()

    clock.advance(10)

    assert breaker.allow_request()
    assert breaker.state is CircuitState.HALF_OPEN
    assert not breaker.allow_request(), "only one trial at a time"

    breaker.record_success()

    assert breaker.state is CircuitState.CLOSED
    assert breaker.allow_request()


def test_failed_trial_reopens() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance(10)
    assert breaker.allow_request()

    breaker.record_failure()

    assert breaker.state is CircuitState.OPEN
    assert not breaker.allow_request()


def test_abandoned_trial_expires() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance(10)
    assert breaker.allow_request()  # trial starts and its caller is cancelled: no report

    clock.advance(10)

    assert breaker.allow_request(), "a new trial is allowed once the old one has expired"
