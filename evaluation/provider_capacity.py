"""Bounded synthetic capacity probe using production adapters and admission.

No key rotation, paid OpenRouter fallback, production data or setting changes.
Submitted concurrency is measured separately from actual network concurrency.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock, local
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.llm import hosted
from app.llm.groq import GroqChatAdapter
from app.llm.openrouter import OpenRouterChatAdapter
from app.settings import get_settings

PLANNER = "nvidia/nemotron-3.5-super-vl:free"
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def read_json(url, token=None):
    headers = {"User-Agent": "site-progress-agent/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=headers), timeout=20) as response:
            return response.status, json.loads(response.read(2 * 1024 * 1024))
    except HTTPError as error:
        status = error.code
        error.close()
        return status, {}
    except (OSError, TimeoutError, ValueError):
        return 0, {}


def preflight(settings, request_budget):
    result = {"groq_key_slots": {}}
    for slot in (0, 1, 2):
        key = getattr(settings, "groq_api_key" if slot == 0 else f"groq_api_key_{slot}")
        if not key:
            result["groq_key_slots"][str(slot)] = {"configured": False}
            continue
        status, body = read_json("https://api.groq.com/openai/v1/models", key.get_secret_value())
        result["groq_key_slots"][str(slot)] = {"configured": True, "http_status": status,
            "baseline_model_listed": any(m.get("id") == settings.groq_model for m in body.get("data", []))}
    result["groq_ready"] = result["groq_key_slots"].get("0", {}).get("http_status") == 200
    key = settings.openrouter_api_key
    if not key:
        result["openrouter_ready"] = False
        return result
    status, body = read_json("https://openrouter.ai/api/v1/key", key.get_secret_value())
    data = body.get("data", {})
    quota = {k: v for k, v in data.get("free_model_daily_requests", {}).items()
             if k in {"used", "limit", "remaining"} and type(v) is int and v >= 0}
    result["openrouter_key"] = {"http_status": status, "free_model_daily_requests": quota}
    status, body = read_json("https://openrouter.ai/api/v1/models")
    model = next((m for m in body.get("data", []) if m.get("id") == PLANNER), None)
    prices = (model or {}).get("pricing", {})
    zero = bool(model) and all(str(prices.get(k, "-1")) in {"0", "0.0"}
                              for k in ("prompt", "completion")) and str(prices.get("request", "0")) in {"0", "0.0"}
    result["openrouter_catalog"] = {"http_status": status, "model": PLANNER,
                                    "listed": bool(model), "zero_price": zero}
    result["openrouter_ready"] = (result["openrouter_key"]["http_status"] == 200 and zero and
                                   quota.get("remaining", request_budget) >= request_budget)
    return result


def run_probe(settings, output, *, count=8, wave_seconds=20, timeout=30, providers=("groq", "openrouter")):
    if output.exists():
        raise ValueError("Use a new output directory; captures must not be overwritten")
    output.mkdir(parents=True)
    started = time.monotonic()
    config = {"started_at": datetime.now(timezone.utc).isoformat(),
        "requests_per_provider": count, "providers": list(providers), "submitted_concurrency_per_provider": 2,
        "wave_seconds": wave_seconds, "timeout_seconds": timeout,
        "groq_model": settings.groq_model, "groq_inference_key_slot": 0,
        "openrouter_model": PLANNER, "max_output_tokens": 256,
        "transport_retries": 0, "cross_provider_fallback": False,
        "admission_scope": "postgresql_deployment_all_roles_and_keys", "synthetic_only": True}
    (output / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    check = preflight(settings, count)
    (output / "preflight.json").write_text(json.dumps(check, indent=2) + "\n")
    started = time.monotonic()
    lock, thread_state = Lock(), local()
    network_active, network_max = {}, {}
    submitted_active, submitted_max = {}, {}
    real_open = hosted.urlopen
    def tracked_open(request, **kwargs):
        row = thread_state.row
        provider = row["provider"]
        with lock:
            network_active[provider] = network_active.get(provider, 0) + 1
            network_max[provider] = max(network_max.get(provider, 0), network_active[provider])
        row["network_started_ms"] = round((time.monotonic() - started) * 1000)
        def finish():
            row["network_finished_ms"] = round((time.monotonic() - started) * 1000)
            with lock:
                network_active[provider] -= 1
        try:
            response = real_open(request, **kwargs)
            row["http_status"] = response.status
            row["quota_headers"] = hosted.safe_headers(response.headers)
            class ObservedResponse:
                status, headers = response.status, response.headers
                def __enter__(self):
                    response.__enter__()
                    return self
                def __exit__(self, *args):
                    try:
                        return response.__exit__(*args)
                    finally:
                        finish()
                def read(self, *args):
                    return response.read(*args)
            return ObservedResponse()
        except HTTPError as error:
            row["http_status"] = error.code
            row["quota_headers"] = hosted.safe_headers(error.headers)
            finish()
            raise
        except BaseException:
            finish()
            raise
    hosted.urlopen = tracked_open
    rows = []
    def one(provider, ordinal):
        due = started + (ordinal // 2) * wave_seconds
        while time.monotonic() < due:
            time.sleep(min(.25, due - time.monotonic()))
        row = {"provider": provider, "ordinal": ordinal, "ok": False,
               "submitted_ms": round((time.monotonic() - started) * 1000)}
        thread_state.row = row
        with lock:
            submitted_active[provider] = submitted_active.get(provider, 0) + 1
            submitted_max[provider] = max(submitted_max.get(provider, 0), submitted_active[provider])
        try:
            if provider == "groq":
                adapter = GroqChatAdapter(settings.groq_model,
                    bearer_token=settings.groq_api_key.get_secret_value(), timeout=timeout)
            else:
                adapter = OpenRouterChatAdapter(PLANNER,
                    bearer_token=settings.openrouter_api_key.get_secret_value(), timeout=timeout)
            value = adapter.chat(system="Return only JSON: {\"ok\":true}. This is a synthetic health check.",
                user="Synthetic capacity check.", schema=SCHEMA, settings={"num_predict": 256})
            row["ok"] = value.value == {"ok": True}
            row["actual_model"] = value.model
        except Exception as error:
            row["error_type"] = type(error).__name__
            row["error_code"] = getattr(error, "code", "PROBE_FAILED")
        finally:
            row["finished_ms"] = round((time.monotonic() - started) * 1000)
            row["elapsed_ms"] = row["finished_ms"] - row["submitted_ms"]
            with lock:
                submitted_active[provider] -= 1
                with (output / "requests.jsonl").open("a") as stream:
                    stream.write(json.dumps(row) + "\n")
            print(json.dumps({k: row[k] for k in ("provider", "ordinal", "ok", "elapsed_ms", "http_status", "error_type") if k in row}), flush=True)
        return row
    try:
        # One two-thread executor per provider preserves the requested burst
        # concurrency even while the other provider has slow responses.
        with ThreadPoolExecutor(max_workers=2) as groq_pool, ThreadPoolExecutor(max_workers=2) as router_pool:
            jobs = []
            for name, pool in (("groq", groq_pool), ("openrouter", router_pool)):
                if name in providers and check.get(f"{name}_ready"):
                    jobs.extend(pool.submit(one, name, i) for i in range(count))
            for future in as_completed(jobs):
                rows.append(future.result())
    finally:
        hosted.urlopen = real_open
    summary = {"scope": "bounded synthetic probe, not production saturation certification", "providers": {}}
    for provider in ("groq", "openrouter"):
        group = [r for r in rows if r["provider"] == provider]
        summary["providers"][provider] = {"requests": len(group), "successes": sum(r["ok"] for r in group),
            "submitted_concurrency_max": submitted_max.get(provider, 0),
            "network_concurrency_max": network_max.get(provider, 0),
            "network_requests": sum("network_started_ms" in r for r in group),
            "errors": sorted({r["error_type"] for r in group if r.get("error_type")}),
            "elapsed_span_ms": max((r["finished_ms"] for r in group), default=0) - min((r["submitted_ms"] for r in group), default=0)}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--providers", nargs="+", choices=("groq", "openrouter"), default=["groq", "openrouter"])
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--wave-seconds", type=float, default=20)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if not 2 <= args.requests <= 8 or not 15 <= args.wave_seconds <= 60 or not 5 <= args.timeout <= 60:
        parser.error("Probe bounds: 2–8 requests/provider, 15–60 seconds/wave, 5–60 seconds timeout")
    run_probe(get_settings(), args.output_dir, count=args.requests,
              wave_seconds=args.wave_seconds, timeout=args.timeout, providers=args.providers)


if __name__ == "__main__":
    main()
