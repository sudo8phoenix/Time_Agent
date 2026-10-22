"""Independently rescore all-GPT-OSS 20B two-key graph windows without inference."""

import json
from pathlib import Path
from statistics import median
from hashlib import sha256

from app.agent.hierarchy import validated_decision
from app.llm.openrouter import _matches_schema
from evaluation.assembled_development import full_case_score

BASE = Path("evaluation/results/prompting-checklist-2026-10-20")
NAMES = ["gpt20-all-roles-graph-2026-10-22"]


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def summarize():
    reports, http, windows, schema_diagnostics = [], [], [], []
    for name in NAMES:
        root = BASE / name
        plan = json.loads((root / "plan.json").read_text())
        window = json.loads((root / "summary.json").read_text())
        for filename, expected in json.loads((root / "capture-manifest.json").read_text()).items():
            assert sha256((root / filename).read_bytes()).hexdigest() == expected
        for filename, expected in plan["source_sha256"].items():
            candidate = Path(filename)
            if not candidate.exists() or sha256(candidate.read_bytes()).hexdigest() != expected:
                archive_file = root / "source-archive-manifest.json"
                archive = json.loads(archive_file.read_text()) if archive_file.exists() else {}
                relative = archive.get(filename, {}).get("relative_path", filename)
                candidate = root / "source-snapshot" / relative
            assert sha256(candidate.read_bytes()).hexdigest() == expected
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
        assert len(window_http) == len(reservations)
        for response, reservation in zip(window_http, reservations):
            assert response["case"] == reservation["case"] and response["arm"] == reservation["arm"]
            if response.get("status") == 200:
                schema = reservation["payload"]["response_format"]["json_schema"]["schema"]
                try:
                    value = json.loads(response["content"])
                    valid = _matches_schema(value, schema)
                except (ValueError, TypeError):
                    value, valid = None, False
                schema_diagnostics.append(
                    dict(
                        window=name,
                        case=response["case"],
                        arm=response["arm"],
                        stage=response["stage"],
                        valid=valid,
                        required_keys=schema.get("required"),
                        actual_keys=list(value) if isinstance(value, dict) else None,
                    )
                )
        ordinals = {}
        for row in window_http:
            row["window"] = name
            assert row["requested_model"] == "openai/gpt-oss-20b"
            if row.get("status") == 200:
                assert row["returned_model"] == "openai/gpt-oss-20b"
            trial = next(
                r
                for r in plan["schedule"]
                if r["case_id"] == row["case"]
                and row["arm"] == r["model"] + ":key" + str(r["planner_slot"])
            )
            expected_slot = (
                trial["planner_slot"] if row["role"] == "orchestrator" else trial["worker_slot"]
            )
            assert row["slot"] == expected_slot
            assert trial["planner_slot"] != trial["worker_slot"]
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
                and "action"
                in r["payload"]["response_format"]["json_schema"]["schema"].get("properties", {})
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
        scope="Two consumed synthetic inputs, both planner keys, actual V2 graph, GPT-OSS 20B in every model role, distinct planner/worker keys",
        planned_unique_comparisons=4,
        completed_unique_comparisons=len(completed),
        tested_unique_comparisons=len(
            {(r["case_id"], r["planner_model"], r["planner_slot"]) for r in reports}
        ),
        schema_failures=[r for r in schema_diagnostics if not r["valid"]],
        valid_http200_schemas=sum(r["valid"] for r in schema_diagnostics),
        attempted_reports=len(reports),
        retained_failed_reports=sum(r["state"] != "ready_for_review" for r in reports),
        recovery_policy="No automatic model/key fallback; retain every attempt",
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
        all_gpt20_models_and_separate_role_keys_verified=True,
        release_accepted=False,
    )
    assert summary["cumulative_reserved_usd"] <= 0.25
    assert summary["cumulative_reserved_calls"] <= 48
    (BASE / NAMES[0] / "schema-diagnostics.json").write_text(
        json.dumps(schema_diagnostics, indent=2) + "\n"
    )
    (BASE / NAMES[0] / "combined-quality-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    summarize()
