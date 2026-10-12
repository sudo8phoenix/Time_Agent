#!/usr/bin/env python3
"""Reproducible technical review of the queued schedule issues and 16 dev labels.

This tool produces suggestions only. It never edits source records or adjudication.
Run from the repository root with .venv/bin/python ops/review_development_data.py.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ingest.schedule_datasets.gt10_xlsx import read_gt10  # noqa: E402

OUT = ROOT / "data/review/technical-review-2026-10-12.json"
REPORT = ROOT / "data/review/schedule-quality-review.jsonl"
REPORTS = ROOT / "data/synthetic/v2/reports.jsonl"
LABELS = ROOT / "data/synthetic/v2/proposed-labels.jsonl"
SOURCES = ROOT.parent / "data/GT10BLDG-P6-Schedule"
CAMBRIDGE_SCREEN = ROOT / "data/review/cambridge-5060-technical-screen.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def indexed(rows: list[dict], key: str) -> dict:
    return {str(r["cells"].get(key)): r for r in rows}


def main() -> None:
    inp_path = SOURCES / "source/GT10BLDG_input_activities_relationships.xlsx"
    exp_path = SOURCES / "exports/GT10BLDG_v1_P6_export.xlsx"
    inp = read_gt10(inp_path, version="input")
    exp = read_gt10(exp_path, version="export")
    input_tasks = indexed(inp["tasks"], "Activity ID")
    export_tasks = indexed(exp["tasks"], "task_code")
    input_edges = {(str(r["cells"].get("Predecessor Activity ID")), str(r["cells"].get("Successor Activity ID"))): r for r in inp["relationships"]}
    export_edges = {(str(r["cells"].get("pred_task_id")), str(r["cells"].get("task_id"))): r for r in exp["relationships"]}

    source_quality = jsonl(REPORT)
    reports = jsonl(REPORTS)
    labels = jsonl(LABELS)
    cambridge_screen = json.loads(CAMBRIDGE_SCREEN.read_text()) if CAMBRIDGE_SCREEN.exists() else None
    if (len(source_quality), len(reports), len(labels)) != (21, 16, 16):
        raise SystemExit("unexpected source record counts")
    if {r["id"] for r in reports} != {label["report_id"] for label in labels}:
        raise SystemExit("report/label IDs do not match")
    report_by_id = {r["id"]: r for r in reports}
    findings = []
    # Each queued item is retained verbatim and given a technical disposition.
    for n, item in enumerate(source_quality, 1):
        f = {"source_record": item, "queue_locator": f"schedule-quality-review.jsonl:{n}"}
        if item["source"] == "gt10" and item["field"] == "task_name":
            a = input_tasks.get("SUP-F8-06")
            b = export_tasks.get("SUP-F8-06")
            f.update({"technical_disposition": "identity_supported_name_conflict_unresolved",
                      "source_evidence": [{"file": str(inp_path.relative_to(ROOT.parent)), "locator": a["locator"], "cells": a["cells"]},
                                          {"file": str(exp_path.relative_to(ROOT.parent)), "locator": b["locator"], "cells": b["cells"]}],
                      "suggestion": "Keep SUP-F8-06 as the stable identity; quarantine the exported display name from matching until planner confirms/corrects it. Do not relabel the task by name alone."})
        elif item["source"] == "gt10":
            pred, succ = item["locator"].split("->")
            a, b = input_edges[(pred, succ)], export_edges[(pred, succ)]
            ac, bc = a["cells"], b["cells"]
            f.update({"technical_disposition": "source_versions_disagree_planner_decision_required",
                      "source_evidence": [{"file": str(inp_path.relative_to(ROOT.parent)), "locator": a["locator"], "cells": ac},
                                          {"file": str(exp_path.relative_to(ROOT.parent)), "locator": b["locator"], "cells": bc}],
                      "suggestion": "Exclude this relationship from dependency-quality claims until a planner selects a source version and resolves relationship semantics and lag units. Input has Relationship Type/Lag; export has pred_type/lag_hr_cnt, whose unit meaning must be verified. Do not infer a corrected value."})
        else:
            supplements = []
            screen_flag = {"actual_after_status_date": "actual_after_status_date",
                           "external_or_unresolved_predecessor": "external_or_unresolved_predecessor",
                           "redacted_identifiers": "redacted_activity_description"}.get(item["field"])
            if cambridge_screen and screen_flag:
                subset_rows = [{"task_id": row["task_id"], "locator": row["locator"], "flags": row["flags"], "external_predecessors": row.get("external_predecessors", [])}
                               for row in cambridge_screen["rows"] if screen_flag in row["flags"]]
                supplements.append({"file": str(CAMBRIDGE_SCREEN.relative_to(ROOT)), "locator": "project 5060 bounded technical screen", "snapshot_sha256": cambridge_screen["snapshot_sha256"],
                                    "matched_flag": screen_flag, "rows": subset_rows,
                                    "field_equivalence": "related_screen_signal_only" if item["field"] == "redacted_identifiers" else "same_flag_name"})
            f.update({"technical_disposition": "aggregate_only_cannot_validate_rows",
                      "source_evidence": [{"file": "../data/schedule-audit-2026-10-09/cambridge-profile.json", "locator": "aggregate profile only", "value": item["old_value"]},
                                          {"file": "docs/d01-d05-completion-audit-2026-10-10.md", "locator": "D03/D02 audit statements", "note": "row-level review remains required"}],
                      "supplemental_subset_evidence": supplements,
                      "suggestion": "Keep global aggregate field out of trusted labels/duration claims pending row-level review and planner decision. Any project 5060 screen evidence is bounded to that derived subset and does not identify rows behind global counts. Redacted-description evidence is related to, but not identical with, the queued redacted-identifiers field. No source rows are corrected by this review."})
        findings.append(f)

    # Suggestions preserve source-supported events and separate application blockers.
    label_review = []
    for n, original in enumerate(labels, 1):
        r = report_by_id[original["report_id"]]
        rid = r["id"]
        finding = {"report_id": rid, "report_locator": f"reports.jsonl:{n}", "label_locator": f"proposed-labels.jsonl:{n}",
                   "report_text": r["text"], "original_label": original, "suggested_label": None,
                   "technical_disposition": "requires_independent_review", "reason": "Synthetic scenario only; not owner evidence or human-approved gold."}
        family = r["scenario_family"]
        event_kind, activity_id = original["proposed_event_kind"], original["proposed_activity_id"]
        value, precision, scope, evidence = original["proposed_value"], original["precision"], original["scope"], r["text"]
        status = "pending_independent_review"
        events = []
        if family in {"start_timed", "start_date_only", "finish_timed"}:
            activity_id = "SUB-010"
            finding.update(technical_disposition="event_text_and_schedule_target_supported", reason="The event and date/time are explicit; both GT10 workbooks contain SUB-010, Excavation for Foundation. These authored examples remain synthetic candidates, not field truth.")
        elif family == "ambiguous_time":
            activity_id, event_kind, value, precision, scope, status = "SUB-010", "start", None, "unknown", "whole_activity", "blocked_missing_date_and_exact_time"
            finding.update(technical_disposition="start_reported_date_time_missing", reason="The text reports foundation excavation starting, but gives only approximate morning shift with no date or clock time. Preserve the start candidate; block application and request date/time.")
        elif family == "missing_location":
            activity_id, event_kind, value, precision, scope, status = None, "start", "2026-10-12T08:30", "minute", "unresolved", "blocked_missing_floor_activity_identity"
            finding.update(technical_disposition="start_reported_activity_mapping_ambiguous", reason="The text states a start at the exact minute, but omits floor. Multiple floor-specific de-shuttering tasks prevent a supported target assignment; preserve candidate and block application.")
        elif family == "future":
            activity_id, event_kind, value, precision, scope, status = None, "none", None, "unknown", "unresolved", "no_actual_event_reported"
            finding.update(technical_disposition="future_intent_no_actual_event", reason="Future intent does not report actual work; do not create a start event.")
        elif family == "negated":
            activity_id, event_kind, value, precision, scope, status = "SUB-010", "none", None, "unknown", "unresolved", "no_actual_event_reported"
            finding.update(technical_disposition="explicit_negation_no_actual_event", reason="The text states excavation has not started. Record no start event; the named activity maps to SUB-010 in both workbooks.")
        elif family == "multiple":
            finding.update(technical_disposition="split_into_two_atomic_source_supported_targets", reason="The report asserts starts for two named activities on one date. Both SUB-010 Excavation for Foundation and SUB-020 Anti-termite Treatment exist in both workbooks.")
            events = [{"event_kind": "start", "activity_id": "SUB-010", "value": "2026-10-12", "precision": "date", "scope": "whole_activity", "evidence_span": evidence, "application_status": status},
                      {"event_kind": "start", "activity_id": "SUB-020", "value": "2026-10-12", "precision": "date", "scope": "whole_activity", "evidence_span": evidence, "application_status": status}]
        elif family == "duplicate":
            activity_id, event_kind, value, precision, scope, status = "SUB-010", "duplicate", None, "unknown", "unresolved", "blocked_duplicate_of_gt10-dev-001"
            finding.update(technical_disposition="duplicate_candidate_exact_text", reason="The text exactly matches gt10-dev-001. Preserve duplicate lineage and do not count a second event.")
        elif family == "correction":
            activity_id, event_kind, value, status = "SUB-010", "correction", "2026-10-12T09:30", "blocked_unverified_original_event_link"
            finding.update(technical_disposition="correction_original_reference_unverified", reason="Correction and corrected time are explicit. Scenario metadata links report 001, but the text has no report/event ID; preserve candidate and block application until that link is verified.")
        elif family == "reordered_finish":
            activity_id, value, status = "SUB-010", "2026-10-14T16:15", "blocked_start_prerequisite"
            finding.update(technical_disposition="finish_reported_start_prerequisite_unavailable", reason="Finish time and target are supported, but no accepted prior start exists. Preserve candidate and block its state transition.")
        elif family == "impossible_chronology":
            activity_id, value, status = "SUB-010", "2026-10-11T07:00", "blocked_chronology_conflict"
            finding.update(technical_disposition="chronology_conflict_explicit", reason="Text reports this finish before its reported start. Preserve the conflict candidate but block normal application pending chronology resolution.")
        elif family == "subactivity":
            activity_id, value, scope, status = "SUP-F8-03", "2027-10-12T16:00", "unresolved", "blocked_scope_policy_decision"
            finding.update(technical_disposition="subactivity_scope_policy_unresolved", reason="Both workbooks contain SUP-F8-03, Slab Shuttering - F8. Preserve finish candidate; whole/subactivity scope and parent propagation require planner policy.")
        elif family == "unknown_activity":
            activity_id, event_kind, value, precision, scope, status = None, "finish", "2026-10-12T15:00", "minute", "unresolved", "blocked_unmatched_schedule_activity"
            finding.update(technical_disposition="unmatched_asset_activity", reason="The report explicitly states a finish time for tower crane inspection; no matching task was identified in either workbook. Preserve candidate and block application pending mapping.")
        elif family == "blocker":
            activity_id, event_kind, value, precision, scope, status = "SUB-010", "blocker", "2026-10-12", "date", "whole_activity", "pending_blocker_taxonomy_review"
            finding.update(technical_disposition="blocker_only_no_start_finish", reason="The text reports blocked access and stopped excavation, not a start/finish. Preserve a dated blocker candidate for source-supported SUB-010; blocker taxonomy needs review.")
        elif family == "fictional_asset":
            activity_id, event_kind, value, precision, scope, status = None, "start", "2026-10-12T08:30", "minute", "unresolved", "blocked_fictional_asset_unmapped"
            finding.update(technical_disposition="fictional_asset_target_unresolved", reason="The text reports a start at the stated minute/date but calls F-01 fictional. Preserve event candidate; do not map it to another task and block application pending a valid target.")

        if not events:
            events = [{"event_kind": event_kind, "activity_id": activity_id, "value": value, "precision": precision,
                       "scope": scope, "evidence_span": evidence, "application_status": status}]
        for event in events:
            assert event["evidence_span"] in r["text"], f"non-verbatim evidence span for {rid}"
            target = event["activity_id"]
            if target is not None:
                assert target in input_tasks and target in export_tasks, f"unknown proposed target: {target}"
                event["target_evidence"] = [{"file": str(inp_path.relative_to(ROOT.parent)), "locator": input_tasks[target]["locator"], "activity_id": target, "activity_name": input_tasks[target]["cells"]["Activity Name"]},
                                            {"file": str(exp_path.relative_to(ROOT.parent)), "locator": export_tasks[target]["locator"], "activity_id": target, "activity_name": export_tasks[target]["cells"]["task_name"]}]
        if family == "duplicate":
            assert original["duplicate_of"] in report_by_id and report_by_id[original["duplicate_of"]]["text"] == r["text"], f"duplicate text mismatch for {rid}"
        finding["suggested_label"] = events
        label_review.append(finding)

    source_paths = [REPORT, REPORTS, LABELS, inp_path, exp_path, ROOT / "data/synthetic/v2/check_splits.py", ROOT / "docs/d01-d05-completion-audit-2026-10-10.md", Path(__file__).resolve()]
    if cambridge_screen:
        source_paths.append(CAMBRIDGE_SCREEN)
    result = {
        "schema_version": 1,
        "review_kind": "reproducible_technical_review_suggestions_not_independent_approval",
        "review_date": "2026-10-12",
        "reviewer_id": None,
        "adjudication_status": "pending_independent_human_review",
        "method": "Read queued source records, each report and proposed label, and GT10 input/export workbook rows via backend.app.ingest.schedule_datasets.gt10_xlsx.read_gt10. Record source row locators and preserve originals. Suggestions are non-authoritative.",
        "source_manifest": [{"path": str(p.relative_to(ROOT.parent)), "sha256": sha(p), "bytes": p.stat().st_size} for p in source_paths],
        "gt10_workbooks": {"input": {"task_count": inp["task_count"], "relationship_count": inp["relationship_count"], "path": str(inp_path.relative_to(ROOT.parent))},
                           "export": {"task_count": exp["task_count"], "relationship_count": exp["relationship_count"], "path": str(exp_path.relative_to(ROOT.parent))}},
        "schedule_quality_review": {"source_count": len(source_quality), "finding_count": len(findings), "findings": findings},
        "development_labels": {"report_count": len(reports), "label_count": len(labels), "findings": label_review},
        "cambridge_scope_limit": "The six global Cambridge quality records cite aggregate profile counts. A separate technical screen of derived project 5060 lists 1,496 activity rows and flags five actual-after-status-date rows, three unresolved predecessor rows, and 181 redacted activity descriptions. These subset findings do not reconstruct the global aggregates or constitute planner acceptance; redacted descriptions are related to but not identical with the queued redacted-identifiers field.",
        "independent_gates": ["independent planner disposition for GT10 identity/relationships and any Cambridge subset", "independent first and required second label reviews plus adjudication using real reviewer identities", "human-approved correction overlay and derived hashes", "reviewed physical-project/scenario split groups and frozen validation/holdout inventories", "owner package remains not received"],
        "outputs_are_not_gold": True,
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(OUT.relative_to(ROOT)), "quality_records": len(findings), "labels": len(label_review), "sha256": sha(OUT)}, indent=2))


if __name__ == "__main__":
    main()
