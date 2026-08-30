"""Shared HTTP plumbing for the real providers (spec section 25).

Three things every external call needs, kept here so no provider has to remember them:

* **Rate limiting.** arXiv asks for no more than one request every three seconds, and
  spec section 27 lists 同一ソースへの過剰APIアクセス as a guardrail. The limiter is a
  minimum-interval gate, not a token bucket, because that is what the published limit
  actually says.
* **A circuit breaker.** Spec section 25: Providerごとのサーキットブレーカー. After a run
  of failures the breaker opens and calls fail immediately instead of piling more load
  onto something already struggling — and, just as importantly, the caller learns fast
  enough to fall back to cache rather than waiting out a timeout on every card.
* **Honest health.** ``GET /health`` reports each provider separately (spec section 24),
  and an open breaker is a specific, reportable state rather than a generic failure.

The transport is injected. Every test in this repository drives these providers through a
recorded response, which is why none of them need the network.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from papermatch_api.providers.base import ProviderUnavailable


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        import json

        return json.loads(self.text)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class Transport(Protocol):
    """Minimal HTTP surface, so tests can supply recorded responses."""

    def get(
        self, url: str, *, params: Mapping[str, Any], headers: Mapping[str, str]
    ) -> HttpResponse: ...


class HttpxTransport:
    """The real thing."""

    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self._timeout = timeout_seconds

    def get(
        self, url: str, *, params: Mapping[str, Any], headers: Mapping[str, str]
    ) -> HttpResponse:
        try:
            response = httpx.get(
                url, params=dict(params), headers=dict(headers), timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc
        return HttpResponse(
            status_code=response.status_code,
            text=response.text,
            headers=dict(response.headers),
        )


class RateLimiter:
    """Enforces a minimum gap between requests.

    Thread-safe because ingestion may run several providers at once, and the published
    limit is per source, not per worker.
    """

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.min_interval = min_interval_seconds
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._last_call: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Block until the next call is allowed. Returns how long it waited."""
        with self._lock:
            now = self._clock()
            if self._last_call is None:
                self._last_call = now
                return 0.0
            elapsed = now - self._last_call
            remaining = self.min_interval - elapsed
            if remaining <= 0:
                self._last_call = now
                return 0.0
            self._sleep(remaining)
            self._last_call = self._clock()
            return remaining


class CircuitBreaker:
    """Opens after consecutive failures and closes again after a cool-down.

    Deliberately simple: no half-open probe counting, just one trial call once the
    cool-down elapses. A more elaborate policy would need production traffic to tune
    against, and guessing at one now would be a fiction.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 4,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock or time.monotonic
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._is_open_locked()

    def _is_open_locked(self) -> bool:
        if self._opened_at is None:
            return False
        if self._clock() - self._opened_at >= self.cooldown_seconds:
            # Cool-down elapsed: allow one trial call through.
            self._opened_at = None
            self._failures = self.failure_threshold - 1
            return False
        return True

    def before_call(self) -> None:
        if self.is_open:
            raise ProviderUnavailable("circuit breaker is open")

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = self._clock()

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._failures


class HttpProviderClient:
    """A transport wrapped in a rate limiter and a circuit breaker."""

    def __init__(
        self,
        *,
        transport: Transport,
        rate_limiter: RateLimiter,
        breaker: CircuitBreaker,
        user_agent: str,
    ) -> None:
        self._transport = transport
        self._rate_limiter = rate_limiter
        self._breaker = breaker
        self._user_agent = user_agent

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    def get(self, url: str, params: Mapping[str, Any] | None = None) -> HttpResponse:
        self._breaker.before_call()
        self._rate_limiter.wait()
        headers = {"User-Agent": self._user_agent, "Accept": "*/*"}
        try:
            response = self._transport.get(url, params=params or {}, headers=headers)
        except ProviderUnavailable:
            self._breaker.record_failure()
            raise
        except Exception as exc:  # any transport error trips the breaker
            self._breaker.record_failure()
            raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc

        # 429 and 5xx mean the source is unhappy with us; 4xx otherwise is our own bug and
        # must not open the breaker, or one malformed query would disable the provider.
        if response.status_code == 429 or response.status_code >= 500:
            self._breaker.record_failure()
            raise ProviderUnavailable(f"HTTP {response.status_code} from {url}")

        self._breaker.record_success()
        return response


#: Sent on every request. Spec section 21 asks that provider terms and acknowledgements be
#: respected, and arXiv in particular asks callers to identify themselves.
DEFAULT_USER_AGENT = (
    "PaperMatch/0.1 (+https://github.com/buzzwole11/nonchan2; research reading app)"
)


__all__ = [
    "DEFAULT_USER_AGENT",
    "CircuitBreaker",
    "HttpProviderClient",
    "HttpResponse",
    "HttpxTransport",
    "RateLimiter",
    "Transport",
]
