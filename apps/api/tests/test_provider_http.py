"""Rate limiting and circuit breaking (spec sections 25, 27, 30)."""

from __future__ import annotations

import pytest

from papermatch_api.providers.base import ProviderUnavailable
from papermatch_api.providers.http import (
    CircuitBreaker,
    HttpProviderClient,
    HttpResponse,
    RateLimiter,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingTransport:
    def __init__(self, responses: list[HttpResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url: str, *, params, headers) -> HttpResponse:  # type: ignore[no-untyped-def]
        self.calls.append((url, dict(params), dict(headers)))
        nxt = self._responses.pop(0) if self._responses else HttpResponse(200, "ok")
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


# ------------------------------------------------------------------------ rate limit


def test_the_first_call_is_not_delayed() -> None:
    clock = FakeClock()
    limiter = RateLimiter(3.0, clock=clock, sleep=clock.advance)
    assert limiter.wait() == 0.0


def test_a_second_call_waits_out_the_remaining_interval() -> None:
    """arXiv asks for one request every three seconds; we honour the published number."""
    clock = FakeClock()
    limiter = RateLimiter(3.0, clock=clock, sleep=clock.advance)
    limiter.wait()
    clock.advance(1.0)
    assert limiter.wait() == pytest.approx(2.0)


def test_a_call_after_the_interval_does_not_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(3.0, clock=clock, sleep=clock.advance)
    limiter.wait()
    clock.advance(10.0)
    assert limiter.wait() == 0.0


# --------------------------------------------------------------------------- breaker


def test_the_breaker_stays_closed_below_the_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=3, clock=FakeClock())
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open is False


def test_the_breaker_opens_on_a_run_of_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=3, clock=FakeClock())
    for _ in range(3):
        breaker.record_failure()
    assert breaker.is_open is True
    with pytest.raises(ProviderUnavailable, match="circuit breaker is open"):
        breaker.before_call()


def test_a_success_resets_the_count() -> None:
    breaker = CircuitBreaker(failure_threshold=3, clock=FakeClock())
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.is_open is False


def test_the_breaker_lets_one_call_through_after_the_cool_down() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60.0, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open is True

    clock.advance(61.0)
    assert breaker.is_open is False, "the cool-down should allow a trial call"

    # And a single further failure re-opens it, rather than needing the whole run again.
    breaker.record_failure()
    assert breaker.is_open is True


# ---------------------------------------------------------------------------- client


def _client(transport: RecordingTransport, clock: FakeClock) -> HttpProviderClient:
    return HttpProviderClient(
        transport=transport,
        rate_limiter=RateLimiter(0.0, clock=clock, sleep=clock.advance),
        breaker=CircuitBreaker(failure_threshold=2, clock=clock),
        user_agent="PaperMatch/test",
    )


def test_every_request_identifies_the_caller() -> None:
    """Spec section 21: provider terms and acknowledgements are respected."""
    transport = RecordingTransport([HttpResponse(200, "ok")])
    clock = FakeClock()
    _client(transport, clock).get("http://example.test/api")
    assert transport.calls[0][2]["User-Agent"] == "PaperMatch/test"


def test_a_transport_error_becomes_provider_unavailable_and_counts_as_a_failure() -> None:
    transport = RecordingTransport([RuntimeError("socket exploded")])
    clock = FakeClock()
    client = _client(transport, clock)

    with pytest.raises(ProviderUnavailable):
        client.get("http://example.test/api")
    assert client.breaker.consecutive_failures == 1


def test_a_429_or_5xx_trips_the_breaker() -> None:
    for status in (429, 500, 503):
        transport = RecordingTransport([HttpResponse(status, "")])
        client = _client(transport, FakeClock())
        with pytest.raises(ProviderUnavailable):
            client.get("http://example.test/api")
        assert client.breaker.consecutive_failures == 1, f"HTTP {status} should count"


def test_a_4xx_that_is_our_own_fault_does_not_trip_the_breaker() -> None:
    """A malformed query must not disable the provider for everyone else."""
    transport = RecordingTransport([HttpResponse(400, "bad query")])
    client = _client(transport, FakeClock())

    response = client.get("http://example.test/api")
    assert response.status_code == 400
    assert client.breaker.consecutive_failures == 0


def test_an_open_breaker_fails_fast_without_touching_the_transport() -> None:
    """The point of the breaker: stop piling load on something already struggling, and let
    the caller fall back to cache instead of waiting out another timeout."""
    transport = RecordingTransport([HttpResponse(500, ""), HttpResponse(500, "")])
    client = _client(transport, FakeClock())

    for _ in range(2):
        with pytest.raises(ProviderUnavailable):
            client.get("http://example.test/api")
    calls_before = len(transport.calls)

    with pytest.raises(ProviderUnavailable, match="circuit breaker is open"):
        client.get("http://example.test/api")
    assert len(transport.calls) == calls_before, "no request should have been attempted"
