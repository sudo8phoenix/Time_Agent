"""Single-credential pacing for synthetic evaluation, using safe response headers."""
from __future__ import annotations

import json
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def duration_seconds(value):
    if not isinstance(value, str):
        return 0.0
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return float(value)
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", value)
    if not parts or "".join(number + unit for number, unit in parts) != value:
        return 0.0
    return sum(float(number) * {"h": 3600, "m": 60, "s": 1, "ms": .001}[unit]
               for number, unit in parts)


class ProviderPacer:
    def __init__(self, *, clock=time.monotonic, sleep=time.sleep):
        self.clock, self.sleep = clock, sleep
        self.state = {}

    def wait_seconds(self, provider, payload):
        state = self.state.get(provider, {})
        now = self.clock()
        until = state.get("retry_until", 0)
        if provider == "openrouter":
            until = max(until, state.get("last_request", -100) + 3.2)
        if provider == "groq" and state.get("remaining_tokens") is not None:
            # Conservative estimate; upstream headers remain authoritative.
            estimate = len(json.dumps(payload, ensure_ascii=False)) / 2 + payload.get("max_completion_tokens", 0)
            if state["remaining_tokens"] < estimate:
                until = max(until, state.get("token_reset_at", now))
        return max(0.0, until - now)

    def observe(self, provider, headers, status):
        now = self.clock()
        state = self.state.setdefault(provider, {})
        state["last_request"] = now
        safe = {}
        for name in ("x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-remaining-requests"):
            value = headers.get(name)
            if isinstance(value, str) and re.fullmatch(r"\d+", value):
                safe[name] = int(value)
        if "x-ratelimit-remaining-tokens" in safe:
            state["remaining_tokens"] = safe["x-ratelimit-remaining-tokens"]
            reset = duration_seconds(headers.get("x-ratelimit-reset-tokens"))
            state["token_reset_at"] = now + min(reset or 60, 300)
        if status == 429:
            retry = duration_seconds(headers.get("retry-after")) or 60
            # Do not issue more traffic when a daily/excessive delay is indicated.
            if retry > 300 or safe.get("x-ratelimit-remaining-requests") == 0:
                state["exhausted"] = True
            state["retry_until"] = now + min(retry, 300)
        return safe

    def transport(self, method, url, payload, timeout, headers, *, call):
        provider = "groq" if url.startswith("https://api.groq.com/") else "openrouter"
        if self.state.get(provider, {}).get("exhausted"):
            raise RuntimeError("Evaluation provider quota exhausted")
        delay = self.wait_seconds(provider, payload)
        call["pacing_wait_ms"] = round(delay * 1000)
        if delay:
            print(json.dumps({"provider": provider, "pacing_seconds": round(delay, 2)}), flush=True)
            # Keep each wait interruptible and short; no credential pooling.
            until = self.clock() + delay
            while self.clock() < until:
                self.sleep(min(1, until - self.clock()))
        request = Request(url, data=json.dumps(payload).encode(), method=method,
                          headers={"Content-Type": "application/json", "User-Agent": "site-progress-agent/0.1", **headers})
        started = self.clock()
        try:
            with urlopen(request, timeout=timeout) as response:
                status = response.status
                body = json.loads(response.read())
                response_headers = response.headers
        except HTTPError as error:
            status, body, response_headers = error.code, {}, error.headers
            # Deliberately discard remote error bodies.
        call["network_ms"] = round((self.clock() - started) * 1000)
        call["quota_headers"] = self.observe(provider, response_headers, status)
        return status, body
