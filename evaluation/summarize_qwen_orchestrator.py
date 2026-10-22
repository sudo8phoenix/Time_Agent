"""Independently rescore retained Qwen graph windows without inference."""

import json
from pathlib import Path
from statistics import median
from hashlib import sha256

from app.agent.hierarchy import validated_decision
from evaluation.assembled_development import full_case_score

BASE = Path("evaluation/results/prompting-checklist-2026-10-20")
NAMES = ["qwen-orchestrator-graph-2026-10-22", "qwen-orchestrator-graph-2026-10-22-rerun"]


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def summarize():
    reports, http, windows = [], [], []
    for name in NAMES:
        root = BASE / name
        plan = json.loads((root / "plan.json").read_text())
        window = json.loads((root / "summary.json").read_text())
        for filename, expected in json.loads((root / "capture-manifest.json").read_text()).items():
            assert sha256((root / filename).read_bytes()).hexdigest() == expected
        for filename, expected in plan["source_sha256"].items():
            assert sha256(Path(filename).read_bytes()).hexdigest() == expected
        for filename, expected in plan["file_sha256"].items():
            assert sha256((root / filename).read_bytes()).hexdigest() == expected
        labels = json.loads((root / "labels.json").read_text())
        cases = {r["case_id"]: r for r in json.loads((root / "cases.json").read_text())}
        window_reports = read_rows(root / "reports.jsonl")
        for row in window_reports:
            assert (
                full_case_score(row, labels[row["case_id"]], cases[row["case_id"]]["report_date"])
                == row["full_case_score"]
            )
            row["window"] = name
        window_http = read_rows(root / "http-calls.jsonl")
        reservations = read_rows(root / "reservations.jsonl")
        ordinals = {}
        for row in window_http:
            row["window"] = name
            if row["stage"] != "planner":
                continue
            identity = row["case"], row["arm"]
            ordinal = ordinals.get(identity, 0)
            ordinals[identity] = ordinal + 1
            if row.get("status") != 200:
                continue
            matching = [
                r
                for r in reservations
                if r["case"] == row["case"]
                and r["arm"] == row["arm"]
                and r["payload"]["model"] == row["requested_model"]
            ]
            expected = json.loads(matching[ordinal]["payload"]["messages"][1]["content"])[
                "legal_actions"
            ][0]
            assert (
                validated_decision(lambda **kwargs: json.loads(row["content"]), expected)
                == expected
            )
        reports.extend(window_reports)
        http.extend(window_http)
        windows.append(window)
    groups = []
    for model in plan["models"]:
        attempted = [r for r in reports if r["planner_model"] == model]
        finished = [r for r in attempted if r["state"] == "ready_for_review"]
        planners = [r for r in http if r["stage"] == "planner" and r["requested_model"] == model]
        success = [r for r in planners if r.get("status") == 200]
        groups.append(
            dict(
                model=model,
                attempted_reports=len(attempted),
                completed_reports=len(finished),
                exact_reports=sum(r["full_case_score"]["full_report_exact"] for r in finished),
                planner_attempts=len(planners),
                valid_planner_responses=len(success),
                median_planner_request_seconds=median(r["seconds"] for r in success),
                report_seconds=[r["elapsed_ms"] / 1000 for r in finished],
                readiness_under_120s=sum(r["elapsed_ms"] <= 120000 for r in finished),
                per_key={
                    str(slot): dict(
                        completed=sum(r["planner_slot"] == slot for r in finished),
                        exact=sum(
                            r["planner_slot"] == slot and r["full_case_score"]["full_report_exact"]
                            for r in finished
                        ),
                    )
                    for slot in (1, 2)
                },
            )
        )
    prices = plan["prices_per_million"]
    completed = [r for r in reports if r["state"] == "ready_for_review"]
    assert len({(r["case_id"], r["planner_model"], r["planner_slot"]) for r in completed}) == len(
        completed
    )
    summary = dict(
        scope="Two consumed synthetic inputs, both planner keys, actual V2 graph and live fixed 20B workers",
        planned_unique_comparisons=8,
        completed_unique_comparisons=len(completed),
        attempted_reports=len(reports),
        retained_failed_reports=sum(r["state"] != "ready_for_review" for r in reports),
        owner_network_issue="Owner attributes initial timeout to an issue on their side and explicitly requests rerun; not independently diagnosed",
        groups=groups,
        http_attempts=len(http),
        http200=sum(r.get("status") == 200 for r in http),
        unknown_usage_attempts=sum(not r.get("usage") for r in http),
        known_tokens=sum((r.get("usage") or {}).get("total_tokens", 0) for r in http),
        known_list_price_usd=sum(
            (
                (r.get("usage") or {}).get("prompt_tokens", 0) * prices[r["requested_model"]][0]
                + (r.get("usage") or {}).get("completion_tokens", 0)
                * prices[r["requested_model"]][1]
            )
            / 1e6
            for r in http
        ),
        cumulative_reserved_calls=sum(w["reserved_calls"] for w in windows),
        cumulative_reserved_tokens=sum(w["reserved_tokens"] for w in windows),
        cumulative_reserved_usd=sum(w["reserved_list_price_usd"] for w in windows),
        all_approval_boundaries_intact=all(
            r["ledger_writes"] == 0 and all(s == "pending" for s in r["review_states"])
            for r in reports
        ),
        terminal_replays_reused=sum(bool(r.get("terminal_replay_reused")) for r in completed),
        terminal_replays_duplicate_free=sum(
            bool(r.get("terminal_replay_duplicate_free")) for r in completed
        ),
        frozen_sources_and_captures_verified=True,
        release_accepted=False,
    )
    assert summary["cumulative_reserved_usd"] <= 1
    assert summary["cumulative_reserved_calls"] <= 96
    (BASE / NAMES[0] / "combined-quality-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    summarize()
