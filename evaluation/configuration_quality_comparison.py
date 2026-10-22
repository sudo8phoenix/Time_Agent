"""Build the cross-configuration scorecard from retained captures, without inference."""

import json
from hashlib import sha256
from pathlib import Path
from statistics import median

BASE = Path("evaluation/results/prompting-checklist-2026-10-20")
OUTPUT = BASE / "model-configuration-comparison-2026-10-22"


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    OUTPUT.mkdir(exist_ok=True)
    families = {
        "mixed": ["qwen-orchestrator-graph-2026-10-22", "qwen-orchestrator-graph-2026-10-22-rerun"],
        "all_qwen": ["qwen-all-roles-graph-2026-10-22", "qwen-all-roles-graph-2026-10-22-rerun"],
        "all_20b": ["gpt20-all-roles-graph-2026-10-22"],
    }
    reports, accounting, sources, prompts, app_sources = [], [], {}, {}, {}
    all_http = []
    prices = {
        "openai/gpt-oss-20b": [0.075, 0.30],
        "openai/gpt-oss-120b": [0.15, 0.60],
        "qwen/qwen3.8-27b": [0.8, 4],
    }
    inputs = {}
    for family, names in families.items():
        calls, windows = [], []
        for name in names:
            root = BASE / name
            plan = json.loads((root / "plan.json").read_text())
            app_sources[name] = {
                k: v for k, v in plan["source_sha256"].items() if k.startswith("backend/app/")
            }
            for filename, expected in json.loads(
                (root / "capture-manifest.json").read_text()
            ).items():
                assert sha256((root / filename).read_bytes()).hexdigest() == expected
            for filename in ("cases.json", "labels.json", "schedule.csv"):
                actual = sha256((root / filename).read_bytes()).hexdigest()
                assert actual == plan["file_sha256"][filename]
                if filename in inputs:
                    assert actual == inputs[filename]
                else:
                    inputs[filename] = actual
            sources[name] = {
                "plan_sha256": sha256((root / "plan.json").read_bytes()).hexdigest(),
                "capture_manifest_sha256": sha256(
                    (root / "capture-manifest.json").read_bytes()
                ).hexdigest(),
            }
            window = json.loads((root / "summary.json").read_text())
            windows.append(window)
            for reservation in rows(root / "reservations.jsonl"):
                payload = reservation["payload"]
                system = payload["messages"][0]["content"]
                prompt_hash = sha256(system.encode()).hexdigest()
                props = payload["response_format"]["json_schema"]["schema"].get("properties", {})
                stage = (
                    "planner"
                    if "action" in props
                    else "extraction"
                    if "observations" in props
                    else "retrieval"
                    if "candidate_ids" in props
                    else "selection"
                )
                item = prompts.setdefault(
                    prompt_hash, dict(stage=stage, sha256=prompt_hash, system=system, sources=[])
                )
                if name not in item["sources"]:
                    item["sources"].append(name)
            for row in rows(root / "reports.jsonl"):
                row["family"], row["window"] = family, name
                reports.append(row)
            window_calls = rows(root / "http-calls.jsonl")
            for call in window_calls:
                call["window"], call["family"] = name, family
            calls.extend(window_calls)
        all_http.extend(calls)
        accounting.append(
            dict(
                family=family,
                http_attempts=len(calls),
                http200=sum(r.get("status") == 200 for r in calls),
                unknown_usage=sum(not r.get("usage") for r in calls),
                known_tokens=sum((r.get("usage") or {}).get("total_tokens", 0) for r in calls),
                known_list_price_usd=sum(
                    (
                        (r.get("usage") or {}).get("prompt_tokens", 0)
                        * prices[r["requested_model"]][0]
                        + (r.get("usage") or {}).get("completion_tokens", 0)
                        * prices[r["requested_model"]][1]
                    )
                    / 1e6
                    for r in calls
                ),
                reserved_usd=sum(w["reserved_list_price_usd"] for w in windows),
                reserved_calls=sum(w["reserved_calls"] for w in windows),
            )
        )
    configurations = []
    specs = [
        ("All 20B", "all_20b", "openai/gpt-oss-20b", "openai/gpt-oss-20b"),
        ("120B + 20B", "mixed", "openai/gpt-oss-120b", "openai/gpt-oss-20b"),
        ("Qwen + 20B", "mixed", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"),
        ("All Qwen", "all_qwen", "qwen/qwen3.8-27b", "qwen/qwen3.8-27b"),
    ]
    for name, family, planner, worker in specs:
        attempted = [r for r in reports if r["family"] == family and r["planner_model"] == planner]
        # Recovery windows do not erase the original attempt. Latest result per planned comparison is shown separately.
        latest = {}
        for row in attempted:
            latest[row["case_id"], row["planner_slot"]] = row
        assert len(latest) == 4
        selected = list(latest.values())
        cohort = {(r["window"], r["case_id"], r["arm"]) for r in selected}
        cohort_calls = [r for r in all_http if (r["window"], r["case"], r["arm"]) in cohort]
        cohort_cost = sum(
            (
                (r.get("usage") or {}).get("prompt_tokens", 0) * prices[r["requested_model"]][0]
                + (r.get("usage") or {}).get("completion_tokens", 0)
                * prices[r["requested_model"]][1]
            )
            / 1e6
            for r in cohort_calls
        )
        finished = [r for r in selected if r["state"] == "ready_for_review"]
        stage_checks = {}
        for stage in ("planner", "extraction", "retrieval", "selection"):
            checks = [
                call for report in selected for call in report["calls"] if call["stage"] == stage
            ]
            timings = [
                r["seconds"] for r in cohort_calls if r["stage"] == stage and r.get("status") == 200
            ]
            stage_checks[stage] = dict(
                accepted=sum(bool(r["ok"]) for r in checks),
                attempted=len(checks),
                median_success_request_seconds=median(timings) if timings else None,
            )
        configurations.append(
            dict(
                name=name,
                planner=planner,
                worker=worker,
                planned=4,
                tested=len(selected),
                exact=sum(r["full_case_score"]["full_report_exact"] for r in selected),
                ready=len(finished),
                stage_checks=stage_checks,
                known_latest_cohort_cost_usd=cohort_cost,
                latest_cohort_unknown_usage=sum(not r.get("usage") for r in cohort_calls),
                latest_cohort_http_attempts=len(cohort_calls),
                all_attempts=len(attempted),
                retained_failed_attempts=sum(r["state"] != "ready_for_review" for r in attempted),
                latest_schema_error_reports=sum(
                    any(c.get("error_type") == "OllamaResponseError" for c in r["calls"])
                    for r in selected
                ),
                median_success_report_seconds=median(r["elapsed_ms"] / 1000 for r in finished)
                if finished
                else None,
                readiness_under_120s=sum(r["elapsed_ms"] <= 120000 for r in finished),
                all_approval_boundaries_intact=all(
                    r["ledger_writes"] == 0 and all(s == "pending" for s in r["review_states"])
                    for r in attempted
                ),
                terminal_replay_reused=sum(bool(r.get("terminal_replay_reused")) for r in finished),
                terminal_replay_duplicate_free=sum(
                    bool(r.get("terminal_replay_duplicate_free")) for r in finished
                ),
                cases=[
                    dict(
                        case=r["case_id"],
                        planner_slot=r["planner_slot"],
                        worker_slot=r["worker_slot"],
                        state=r["state"],
                        seconds=r["elapsed_ms"] / 1000,
                        exact=r["full_case_score"]["full_report_exact"],
                        error=r["error_code"],
                        window=r["window"],
                    )
                    for r in selected
                ],
            )
        )
    prompt_items = {}
    for name in (
        "PROMPT-02",
        "PROMPT-03",
        "PROMPT-04",
        "PROMPT-05",
        "PROMPT-06",
        "PROMPT-07",
        "PROMPT-09",
        "PROMPT-10",
        "MODEL-03",
    ):
        p = BASE / "batch-30/items" / f"{name}.json"
        prompt_items[name] = dict(
            source=str(p),
            sha256=sha256(p.read_bytes()).hexdigest(),
            record=json.loads(p.read_text()),
        )
    summary = dict(
        scope="Descriptive historical-window comparison on two consumed synthetic cases repeated across two key assignments; no independent population ranking",
        configurations=configurations,
        accounting=accounting,
        identical_fixture_sha256=inputs,
        evidence=sources,
        release_accepted=False,
    )
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (OUTPUT / "prompt-evidence.json").write_text(json.dumps(prompt_items, indent=2) + "\n")
    (OUTPUT / "prompt-catalog.json").write_text(json.dumps(list(prompts.values()), indent=2) + "\n")
    reference = app_sources[families["all_qwen"][0]]
    source_differences = {
        name: [p for p, value in manifest.items() if reference.get(p) != value]
        for name, manifest in app_sources.items()
    }
    (OUTPUT / "application-source-differences.json").write_text(
        json.dumps(source_differences, indent=2) + "\n"
    )
    (OUTPUT / "public-pricing.json").write_text(
        json.dumps(
            {
                "checked": "2026-10-22",
                "currency": "USD per million tokens",
                "prices": prices,
                "sources": [
                    "https://console.groq.com/docs/model/openai/gpt-oss-20b",
                    "https://console.groq.com/docs/model/openai/gpt-oss-120b",
                    "https://console.groq.com/docs/model/qwen/qwen3.8-27b",
                ],
                "cache_discount_assumed": False,
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
