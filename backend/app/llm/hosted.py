"""Conservative hosted-provider admission, shared by deployment roles and keys.

No credential rotation, cross-model fallback or implicit inference retries. The
provider remains authoritative for organization quotas across other processes.
Only numeric allowlisted quota information is retained in the coordinator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re
from threading import Condition, local
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .ollama import OllamaResponseError, OllamaTransportError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class HostedRateLimitError(OllamaTransportError):
    """Retryable by an owning task, never by rotating credentials."""
    code = "MODEL_RATE_LIMITED"
    safe_message = "The provider is rate limited. Retry after its cooldown."

    def __init__(self, message, *, retry_after_seconds=60):
        self.retry_after_seconds = max(0, retry_after_seconds)
        super().__init__(message)


class HostedQuotaError(OllamaResponseError):
    code = "MODEL_QUOTA_EXHAUSTED"
    safe_message = "The provider quota is exhausted. Wait for reset before retrying."


class HostedCapacityError(OllamaTransportError):
    code = "MODEL_CAPACITY_TIMEOUT"
    safe_message = "Provider admission exceeded this request's time budget."

    def __init__(self, message, *, retry_after_seconds=0):
        self.retry_after_seconds = max(0, retry_after_seconds)
        super().__init__(message)


def duration(value):
    if not isinstance(value, str):
        return 0.0
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        result = float(value)
    else:
        parts = re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", value)
        if not parts or "".join(n + u for n, u in parts) != value:
            return 0.0
        result = sum(float(n) * {"ms": .001, "s": 1, "m": 60, "h": 3600}[u] for n, u in parts)
    return result if math.isfinite(result) else 0.0


def retry_after(value):
    seconds = duration(value)
    if seconds or not isinstance(value, str):
        return seconds
    try:
        when = parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0, (when - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 0.0


def safe_headers(headers):
    headers = {str(k).lower(): v for k, v in headers.items()}
    safe = {}
    for name in ("x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
                 "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens",
                 "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"):
        value = headers.get(name)
        if isinstance(value, str) and len(value) <= 20 and re.fullmatch(r"\d+", value):
            safe[name] = int(value)
    for name in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        seconds = duration(headers.get(name))
        if seconds:
            safe[name] = seconds
    seconds = retry_after(headers.get("retry-after"))
    if seconds:
        safe["retry-after"] = seconds
    return safe


@dataclass
class ProviderState:
    active: bool = False
    next_request: float = 0
    cooldown: float = 0
    token_reset: float = 0
    request_reset: float = 0
    remaining_tokens: int | None = None
    remaining_requests: int | None = None
    headers: dict = field(default_factory=dict)
    token_limit: int | None = None
    last_started: float = 0
    last_estimate: int = 0


class HostedAdmission:
    def __init__(self, *, intervals=None, clock=time.monotonic):
        self.intervals = intervals if intervals is not None else {"groq": 2.1, "openrouter": 3.2}
        self.clock = clock
        self.condition = Condition()
        self.states = {}

    def acquire(self, provider, payload, timeout):
        deadline = self.clock() + timeout
        base_provider = provider.partition(":")[0]
        # Approximate admission cost, including the reserved completion. Three
        # UTF-8 bytes/token deliberately overestimates ordinary English input;
        # numeric provider headers and 429 cooldowns remain authoritative.
        estimate = math.ceil(len(json.dumps(payload, ensure_ascii=False).encode()) / 3) + int(
            payload.get("max_completion_tokens", payload.get("max_tokens", 0)))
        with self.condition:
            state = self.states.setdefault(provider, ProviderState())
            while True:
                now = self.clock()
                if state.remaining_requests == 0 and state.request_reset > now:
                    raise HostedQuotaError("Provider daily request quota is exhausted")
                if state.request_reset and now >= state.request_reset:
                    state.remaining_requests, state.request_reset = None, 0
                if state.token_reset and now >= state.token_reset:
                    state.remaining_tokens, state.token_reset = None, 0
                until = max(state.next_request, state.cooldown)
                if state.remaining_tokens is not None and state.remaining_tokens < estimate:
                    until = max(until, state.token_reset)
                remaining = deadline - now
                wait = max(0, until - now)
                if remaining <= 0 or wait >= remaining:
                    raise HostedCapacityError("Provider admission exceeded the request timeout", retry_after_seconds=wait)
                if not state.active and wait == 0:
                    state.active = True
                    state.last_started, state.last_estimate = now, estimate
                    # Smooth sustained Groq traffic at the advertised TPM rather
                    # than repeatedly bursting at the nominal request interval.
                    interval = self.intervals.get(base_provider, 0)
                    if base_provider == "groq" and state.token_limit:
                        interval = max(interval, 60 * estimate / state.token_limit)
                    state.next_request = now + interval
                    if state.remaining_tokens is not None:
                        state.remaining_tokens = max(0, state.remaining_tokens - estimate)
                    return remaining
                self.condition.wait(timeout=min(remaining, wait if wait else .25))

    def release(self, provider, *, status=None, headers=None):
        with self.condition:
            state = self.states[provider]
            now = self.clock()
            safe = safe_headers(headers or {})
            state.headers = safe
            if provider.partition(":")[0] == "groq" and safe.get("x-ratelimit-limit-tokens", 0) > 0:
                state.token_limit = safe["x-ratelimit-limit-tokens"]
                state.next_request = max(state.next_request,
                    state.last_started + 60 * state.last_estimate / state.token_limit)
            if "x-ratelimit-remaining-tokens" in safe:
                state.remaining_tokens = safe["x-ratelimit-remaining-tokens"]
                state.token_reset = now + safe.get("x-ratelimit-reset-tokens", 60)
            if "x-ratelimit-remaining-requests" in safe:
                state.remaining_requests = safe["x-ratelimit-remaining-requests"]
                state.request_reset = now + safe.get("x-ratelimit-reset-requests", 86400)
            if status == 429:
                state.cooldown = max(state.cooldown, now + safe.get("retry-after", 60))
                # OpenRouter reset headers describe the particular limit hit.
                reset = safe.get("x-ratelimit-reset")
                if reset:
                    # OpenRouter uses epoch milliseconds; tolerate epoch seconds
                    # as well, without turning a minute into a millennia wait.
                    reset_seconds = reset / 1000 if reset > 10**11 else reset
                    state.cooldown = max(state.cooldown, now + max(0, reset_seconds - time.time()))
            state.active = False
            self.condition.notify_all()


class DeploymentHostedAdmission(HostedAdmission):
    """Default transport gate; local state is numeric telemetry only."""
    def __init__(self):
        super().__init__()
        self.reservations = local()

    def _coordinator(self):
        from ..db.session import session_factory
        from .capacity import DatabaseAdmission
        return DatabaseAdmission(session_factory)

    def acquire(self, provider, payload, timeout):
        coordinator = self._coordinator()
        owner, remaining = coordinator.acquire(provider, payload, timeout)
        self.reservations.current = (coordinator, provider, owner)
        with self.condition:
            self.states.setdefault(provider, ProviderState()).active = True
        return remaining

    def release(self, provider, *, status=None, headers=None):
        reservation = getattr(self.reservations, "current", None)
        try:
            if reservation is not None:
                coordinator, scope, owner = reservation
                if not coordinator.release(scope, owner, status=status, headers=headers):
                    raise HostedCapacityError("Shared provider reservation is no longer valid")
        finally:
            self.reservations.current = None
            super().release(provider, status=status, headers=headers)


ADMISSION = DeploymentHostedAdmission()


def raise_for_status(provider, status, *, scope=None):
    if status == 429:
        with ADMISSION.condition:
            state = ADMISSION.states.get(scope or provider)
            wait = max(0, state.cooldown - ADMISSION.clock()) if state else 60
        raise HostedRateLimitError(f"{provider} rate limit reached", retry_after_seconds=wait)
    if status >= 400:
        raise OllamaResponseError(f"{provider} request failed ({status})")


def _read_response(response, deadline):
    """Bound both decoded JSON size and total body-read time, including trickles."""
    chunks, size = [], 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Provider response exceeded its request deadline")
        # urllib's HTTPResponse supports read1 and the underlying socket. Set
        # the remaining budget for each read rather than renewing a full timeout
        # whenever a slow server sends another byte.
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            sock.settimeout(remaining)
        read1 = getattr(response, "read1", None)
        chunk = read1(min(65536, MAX_RESPONSE_BYTES + 1 - size)) if read1 else response.read(MAX_RESPONSE_BYTES + 1)
        if time.monotonic() >= deadline:
            raise TimeoutError("Provider response exceeded its request deadline")
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise OllamaResponseError("Provider response exceeds its size limit")
        chunks.append(chunk)
        if not chunk or read1 is None:
            return b"".join(chunks)


def request(provider, method, url, payload, timeout, headers, *, capacity_scope=None):
    from .metrics import record_provider_request
    started = time.monotonic()
    admitted_at = None
    status, response_headers = None, {}
    if capacity_scope is not None:
        from .account_scopes import SCOPES
        if provider != "groq" or capacity_scope not in SCOPES:
            raise HostedCapacityError("Unverified hosted capacity scope")
    scope = capacity_scope or provider
    try:
        remaining = ADMISSION.acquire(scope, payload, timeout)
        admitted_at = time.monotonic()
        try:
            outgoing = Request(url, data=json.dumps(payload).encode(), method=method,
                headers={"Content-Type": "application/json", "User-Agent": "site-progress-agent/0.1", **headers})
            try:
                with urlopen(outgoing, timeout=remaining) as response:
                    status, response_headers = response.status, response.headers
                    raw = _read_response(response, started + timeout)
                    return status, json.loads(raw)
            except HTTPError as error:
                status, response_headers = error.code, error.headers
                error.close()  # Error bodies may echo private input; never read them.
                return status, {}
        finally:
            transport_finished = time.monotonic()
            ADMISSION.release(scope, status=status, headers=response_headers)
    finally:
        finished = time.monotonic()
        record_provider_request(provider,
            admission_ms=1000 * ((admitted_at if admitted_at is not None else finished) - started),
            transport_ms=1000 * (transport_finished - admitted_at) if admitted_at is not None else 0,
            admitted=admitted_at is not None, status=status)
