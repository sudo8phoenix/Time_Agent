"""Resumable, live role matrix for Qwen, GPT-OSS 120B/20B and DeepSeek V4 Flash.

Use one frozen report and schedule. Run from the repo root with .venv/bin/python.
This is a role-contract comparison, not a PostgreSQL-backed graph execution.
"""
# ruff: noqa: E402
from __future__ import annotations

import csv
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.hierarchy import validated_decision
from app.agent.planner import create_planner
from app.agent.schedule_decision import candidate_for_activity, select_activity
from app.llm import hosted
from app.llm.extract import BatchInput, FragmentInput, extract_batch
from app.llm.provider import create_adapter
from app.schemas.observation import Observation
from app.settings import get_settings

HERE = Path(__file__).parent
OUTPUT = HERE / "four-model-matrix.json"
SOURCE = (HERE / "input.txt").read_text().rstrip()
SCHEDULE = ROOT / "data/review/gt10-five-entry/schedule.csv"
MODELS = {
    "qwen": ("groq", "qwen/qwen3.8-27b"),
    "gpt120": ("groq", "openai/gpt-oss-120b"),
    "gpt20": ("groq", "openai/gpt-oss-20b"),
    "deepseek": ("gonka", "deepseek-ai/DeepSeek-V4-Flash-0731"),
}
STAGES = ("intake", "analysis", "review")


def save(record):
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, default=str) + "\n")
    temporary.replace(OUTPUT)


def model_settings(settings, name, role):
    provider, model = MODELS[name]
    return settings.model_copy(update={
        f"{role}_provider": provider,
        f"{role}_model": model,
        f"{role}_key_slot": 1 if role == "orchestrator" else 2,
        "groq_account_scopes_enabled": False,
    })


def candidates():
    with SCHEDULE.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = []
    for row in rows:
        row["id"] = str(uuid5(NAMESPACE_URL, f"four-model-matrix/{row['activity_id']}"))
        row["external_id"] = row["activity_id"]
        row["name"] = row["activity_name"]
        row["is_leaf"] = row["is_leaf"].lower() == "true"
        result.append(candidate_for_activity(row))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--retest-deepseek-planner', action='store_true')
    parser.add_argument('--retry-transport-failures', action='store_true')
    args = parser.parse_args()
    settings = get_settings()
    if not settings.groq_api_key_1 or not settings.groq_api_key_2 or not settings.gonka_broker_llm:
        raise RuntimeError("The configured Groq planner/worker and Gonka keys are required")
    hosted.ADMISSION = hosted.HostedAdmission(intervals={"groq": 2.1, "gonka": 10.5})
    record = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {
        "input": "artifacts/gonka-model-comparison/input.txt",
        "schedule": str(SCHEDULE.relative_to(ROOT)),
        "models": {key: list(value) for key, value in MODELS.items()},
        "planner": {}, "extraction": {}, "selection": {},
        "calls": [],
    }
    if record["models"] != {key: list(value) for key, value in MODELS.items()}:
        raise RuntimeError("Existing matrix uses different model assignments")
    for entry in record["calls"]:
        if "ok" not in entry:
            entry["ok"] = False
            entry["error"] = "Interrupted before transport"
    save(record)
    if args.retry_transport_failures:
        for key, results in record['selection'].items():
            retry = [row for row in results if 'TransportError' in (row.get('error') or '')]
            if retry:
                record.setdefault('selection_transport_failures', {}).setdefault(key, []).extend(retry)
                record['selection'][key] = [row for row in results if row not in retry]
        save(record)
    if record["calls"]:
        last_gonka = next((entry for entry in reversed(record["calls"])
                           if entry["provider"] == "gonka"), None)
        if last_gonka:
            elapsed = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(last_gonka["started_at"])).total_seconds()
            if elapsed < 61:
                time.sleep(61 - elapsed)

    def invoke(name, role, label, callback):
        provider, model = MODELS[name]
        entry = {"provider": provider, "model": model, "role": role, "label": label,
                 "started_at": datetime.now(timezone.utc).isoformat(), "attempts": []}
        adapter = callback[0]
        original = adapter._transport

        def observed_transport(*args):
            status, body = original(*args)
            usage = body.get("usage") if isinstance(body, dict) else None
            choice = (body.get("choices") or [None])[0] if isinstance(body, dict) else None
            content = (choice.get("message") or {}).get("content") if isinstance(choice, dict) else None
            entry["attempts"].append({"http_status": status,
                "finish_reason": choice.get("finish_reason") if isinstance(choice, dict) else None,
                "content_shape": ("fenced" if content.lstrip().startswith("```") else
                                  "object" if content.lstrip().startswith("{") else "other")
                    if isinstance(content, str) else "absent",
                "content_length": len(content) if isinstance(content, str) else None,
                "usage": {key: usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
                    if isinstance(usage, dict) else None})
            return status, body

        adapter._transport = observed_transport
        start = time.monotonic()
        try:
            value = callback[1]()
            entry["ok"] = True
            return value
        except Exception as exc:
            entry["ok"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"
            return None
        except KeyboardInterrupt:
            entry["ok"] = False
            entry["error"] = "Interrupted"
            raise
        finally:
            adapter._transport = original
            entry["elapsed_seconds"] = round(time.monotonic() - start, 3)
            record["calls"].append(entry)
            save(record)
            print(json.dumps({key: entry[key] for key in (
                "role", "model", "label", "ok", "elapsed_seconds")}), flush=True)

    # Planner decisions are independent of report content in the bounded graph.
    planner_results = (record.setdefault('planner_retest_fenced_json_v1', {})
                       if args.retest_deepseek_planner else record['planner'])
    for stage in STAGES:
        for name in MODELS:
            if args.retest_deepseek_planner and name != 'deepseek':
                continue
            if stage in planner_results.get(name, {}):
                continue
            assigned = model_settings(settings, name, "orchestrator")
            adapter = create_adapter(assigned, timeout=300, role="orchestrator")
            try:
                create_planner(assigned, timeout=300, adapter_factory=lambda *_args, **_kwargs: adapter)
            except Exception as exc:
                planner_results.setdefault(name, {})[stage] = {"error": str(exc)}
                save(record)
                continue
            action = invoke(name, "orchestrator", stage,
                (adapter, lambda adapter=adapter, stage=stage: validated_decision(adapter.chat, stage)))
            entry = record["calls"][-1]
            record['calls'][-1]['trial'] = ('fenced_json_v1' if args.retest_deepseek_planner else 'initial')
            planner_results.setdefault(name, {})[stage] = (
                {"action": action, "elapsed_seconds": entry["elapsed_seconds"]} if action
                else {"error": entry.get("error"), "elapsed_seconds": entry["elapsed_seconds"]})
            save(record)

    batch = BatchInput("four-model-site-update",
                       (FragmentInput("f1", "user:site-update", SOURCE),))
    for name in MODELS:
        if "observations" in record["extraction"].get(name, {}):
            continue
        assigned = model_settings(settings, name, "extraction")
        adapter = create_adapter(assigned, timeout=300, role="extraction")
        result = invoke(name, "extraction", "full site update", (adapter,
            lambda adapter=adapter, name=name: extract_batch(batch, adapter.chat,
                model=MODELS[name][1], runtime=MODELS[name][0],
                settings={"temperature": 0.0, "num_predict": 4096})))
        entry = record["calls"][-1]
        record["extraction"][name] = (
            {"observations": [item.model_dump(mode="json") for item in result.observations],
             "validation_errors": list(result.errors),
             "elapsed_seconds": entry["elapsed_seconds"]} if result else
            {"error": entry.get("error"), "elapsed_seconds": entry["elapsed_seconds"]})
        save(record)

    pool = candidates()
    for extractor in MODELS:
        extracted = record["extraction"].get(extractor, {})
        if "observations" not in extracted:
            continue
        observations = [Observation.model_validate(row) for row in extracted["observations"]]
        for selector in MODELS:
            key = f"{extractor}::{selector}"
            results = record["selection"].setdefault(key, [])
            assigned = model_settings(settings, selector, "selection")
            adapter = create_adapter(assigned, timeout=300, role="selection")
            for index, observation in enumerate(observations, 1):
                if any(item["observation"] == index for item in results):
                    continue
                proposal = invoke(selector, "selection", f"{extractor} observation {index}",
                    (adapter, lambda observation=observation, adapter=adapter:
                     select_activity(observation, pool, {"f1": SOURCE},
                                     model_call=adapter.chat, compact_context=True,
                                     short_ids=True)))
                entry = record["calls"][-1]
                match = (next((row.external_id for row in pool
                               if row.candidate_id == proposal.candidate_id), None)
                         if proposal else None)
                results.append({"observation": index,
                    "event_type": observation.event_type.value,
                    "quantity": str(observation.quantity) if observation.quantity is not None else None,
                    "unit": observation.unit.value if observation.unit else None,
                    "activity": match,
                    "mapping_state": proposal.mapping_state.value if proposal else None,
                    "error": entry.get("error"),
                    "elapsed_seconds": entry["elapsed_seconds"]})
                save(record)


if __name__ == "__main__":
    main()
