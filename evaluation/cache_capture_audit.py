"""Measure explicit cache telemetry from sealed calls; missing never means zero."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


def usage_cache(usage):
    if not isinstance(usage, dict):
        return dict(status="missing", prompt_tokens=None, cached_tokens=None)
    details = usage.get("prompt_tokens_details")
    if not isinstance(details, dict) or "cached_tokens" not in details:
        return dict(status="missing", prompt_tokens=usage.get("prompt_tokens"), cached_tokens=None)
    prompt, cached = usage.get("prompt_tokens"), details["cached_tokens"]
    if type(prompt) is not int or type(cached) is not int or not 0 <= cached <= prompt:
        return dict(status="invalid", prompt_tokens=None, cached_tokens=None)
    return dict(status="hit" if cached else "explicit_zero", prompt_tokens=prompt, cached_tokens=cached)


def audit(capture):
    capture = Path(capture).resolve()
    manifest_path = capture / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if not {"requests.jsonl", "calls.jsonl", "config.json"} <= set(manifest):
        raise ValueError("Sealed raw request/call evidence required")
    for name, expected in manifest.items():
        path = capture / name
        if (Path(name).name != name or path.resolve().parent != capture
                or sha256(path.read_bytes()).hexdigest() != expected):
            raise ValueError("Original capture seal mismatch")
    config = json.loads((capture / "config.json").read_text())
    if config.get("execution_mode") != "live_groq":
        raise ValueError("Actual live capture required")

    def index(name):
        result = {}
        for line in (capture / name).read_text().splitlines():
            row = json.loads(line)
            if row["id"] in result:
                raise ValueError("Duplicate raw request/call identity")
            result[row["id"]] = row
        return result

    requests, calls = index("requests.jsonl"), index("calls.jsonl")
    rows = []
    for identity, call in calls.items():
        if identity not in requests:
            raise ValueError("Captured call lacks its original request")
        payload = requests[identity]["payload"]
        messages = payload["messages"]
        stable = []
        for message in messages:
            if message["role"] != "system":
                break
            stable.append(message)
        prefix = sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
        telemetry = usage_cache(call.get("usage"))
        if telemetry["status"] in {"hit", "explicit_zero"} and (
            call.get("status") != 200 or call.get("returned_model") != payload["model"]
        ):
            telemetry = dict(status="unverified_response", prompt_tokens=None, cached_tokens=None)
        rows.append(dict(
            call_id=identity, model=payload["model"], stable_prefix_sha256=prefix,
            stable_system_before_variable=bool(stable), http_status=call.get("status"),
            **telemetry,
        ))
    explicit = [r for r in rows if r["status"] in {"hit", "explicit_zero"}]
    groups = Counter((r["model"], r["stable_prefix_sha256"]) for r in rows
                     if r["stable_system_before_variable"])
    return dict(
        capture=str(capture), manifest_sha256=sha256(manifest_path.read_bytes()).hexdigest(),
        calls=len(rows), telemetry_counts=dict(Counter(r["status"] for r in rows)),
        explicit_cache_telemetry_calls=len(explicit),
        prompt_tokens_with_telemetry=sum(r["prompt_tokens"] for r in explicit),
        cached_tokens=sum(r["cached_tokens"] for r in explicit),
        repeated_stable_prefix_groups=sum(n > 1 for n in groups.values()),
        rows=rows, new_provider_calls=0, release_accepted=False,
        limitations=[
            "Missing telemetry is unknown, not an explicit zero or miss.",
            "Explicit cache counts do not establish a cohort-wide hit rate.",
            "A shared system-prefix hash does not establish which provider tokens were cached.",
            "No cache savings are applied to historical billing or cold reservations.",
            "Historical calls do not establish independently cold parallel starts.",
        ],
    )
