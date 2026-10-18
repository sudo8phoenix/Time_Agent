"""Invocation-local numeric provider timing; never stores request/response text."""
from contextlib import contextmanager
from contextvars import ContextVar


_current = ContextVar("provider_metrics", default=None)


@contextmanager
def capture_provider_metrics():
    metrics = {}
    token = _current.set(metrics)
    try:
        yield metrics
    finally:
        _current.reset(token)


def record_provider_request(provider, *, admission_ms, transport_ms, admitted, status):
    metrics = _current.get()
    if metrics is None or provider not in {"groq", "openrouter"}:
        return
    row = metrics.setdefault(provider, {
        "calls": 0, "admitted": 0, "admission_ms": 0, "transport_ms": 0,
        "responses_2xx": 0, "responses_429": 0, "responses_other": 0,
        "no_response": 0,
    })
    row["calls"] += 1
    row["admitted"] += int(admitted)
    row["admission_ms"] += max(0, int(admission_ms))
    row["transport_ms"] += max(0, int(transport_ms))
    category = ("responses_2xx" if isinstance(status, int) and 200 <= status < 300 else
                "responses_429" if status == 429 else
                "no_response" if status is None else "responses_other")
    row[category] += 1
