"""Synthetic planner smoke checks for explicitly requested free OpenRouter models.

Never retains credentials, raw completions, prompts or provider error bodies.
Run from repository root; no application configuration or domain writes occur.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
from urllib.request import urlopen

from app.agent.hierarchy import validated_decision
from app.llm.openrouter import OpenRouterChatAdapter
from app.settings import get_settings

MODELS = (
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3.5-super-vl:free",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--phases", type=int, choices=(1, 3), default=1)
    args = parser.parse_args()
    token = get_settings().openrouter_api_key
    if token is None or not token.get_secret_value().strip():
        raise SystemExit("OpenRouter credential is missing")
    with urlopen("https://openrouter.ai/api/v1/models", timeout=20) as response:
        catalog = {row["id"]: row for row in json.loads(response.read())["data"]}
    result = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "source": "https://openrouter.ai/api/v1/models", "timeout_seconds": args.timeout,
              "max_output_tokens": 1536, "transport_retries": 0, "models": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for model_id in MODELS:
        metadata = catalog.get(model_id)
        row = {"model": model_id, "catalog_present": metadata is not None, "trials": []}
        if metadata:
            row.update(pricing={key: metadata.get("pricing", {}).get(key) for key in ("prompt", "completion")},
                       supported_parameters=metadata.get("supported_parameters", []),
                       reasoning=metadata.get("reasoning", {}))
        if not metadata or any(float(metadata.get("pricing", {}).get(key, "-1")) != 0
                               for key in ("prompt", "completion")):
            row["skipped"] = "missing_or_nonzero_catalog_price"
        else:
            for action in ("intake", "analysis", "review")[:args.phases]:
                trial = {"expected_action": action}
                def transport(method, url, payload, timeout, headers):
                    status, body = OpenRouterChatAdapter._http_transport(method, url, payload, timeout, headers)
                    trial["http_status"] = status
                    if isinstance(body, dict):
                        usage = body.get("usage", {})
                        trial["tokens"] = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                                           if isinstance(usage.get(key), int)}
                        choices = body.get("choices", [])
                        if choices and isinstance(choices[0], dict):
                            finish = choices[0].get("finish_reason")
                            trial["finish_reason"] = finish if finish in ("stop", "length", "error", "tool_calls", "content_filter") else "other"
                    return status, body
                adapter = OpenRouterChatAdapter(model_id, bearer_token=token.get_secret_value(),
                    timeout=args.timeout, max_retries=0, transport=transport)
                started = perf_counter()
                try:
                    trial["action"] = validated_decision(adapter.chat, action)
                    trial["passed"] = True
                except Exception as error:
                    trial["passed"] = False
                    trial["error_type"] = type(error).__name__
                    if getattr(error, "code", None) in ("AGENT_PLANNER_INVALID", "AGENT_PLANNER_FAILED"):
                        trial["error_code"] = error.code
                trial["elapsed_ms"] = round((perf_counter() - started) * 1000)
                row["trials"].append(trial)
                print(json.dumps({"model": model_id, **trial}), flush=True)
                if trial.get("http_status") in (401, 402, 403, 429):
                    break
        result["models"].append(row)
        args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
