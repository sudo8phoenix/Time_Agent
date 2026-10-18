"""Score sealed initial captures separately from normalized runtime proposals.

No model calls or database writes. Labels are read only after capture hashes
have been checked. Alignment is by unique event type within these frozen cases.
"""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path

from evaluation.confidence_estimator import estimate


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def number(value):
    if value is None:
        return None
    try:
        value = Decimal(str(value))
        return format(value.normalize(), "f") if value.is_finite() else "invalid"
    except (ValueError, TypeError, InvalidOperation):
        return "invalid"


def targets(event):
    return {"event": event["event_type"], "field:area": (event.get("area") or "").casefold() or None,
        "field:quantity": number(event.get("quantity")), "field:unit": event.get("unit"),
        **({"field:work_date": event.get("work_date")} if event.get("work_date_scored", True) else {}),
        **({"field:endpoint_" + k: v for k, v in event["endpoint"].items()
            if k != "timezone" or v is not None} if event.get("endpoint") else {})}


def actual_targets(observation, expected):
    if observation is None:
        return {}
    effects = observation.get("lifecycle_effects", [])
    endpoint = effects[0].get("endpoint", {}) if len(effects) == 1 else {}
    value = {"event": observation.get("event_type"),
        "field:area": (observation.get("area") or "").casefold() or None,
        "field:quantity": number(observation.get("quantity")), "field:unit": observation.get("unit")}
    if expected.get("work_date_scored", True):
        value["field:work_date"] = observation.get("work_date")
    if expected.get("endpoint") and endpoint:
        value.update({"field:endpoint_"+k: endpoint.get(k) for k,v in expected["endpoint"].items()
                      if k != "timezone" or v is not None})
    return value


def unmasked_targets(observation):
    """Prediction values before consulting the label's scored-field inventory."""
    values = actual_targets(observation, {"work_date_scored": True})
    effects = observation.get("lifecycle_effects", [])
    if len(effects) == 1:
        endpoint = effects[0].get("endpoint", {})
        values.update({"field:endpoint_"+key: endpoint.get(key)
            for key in ("local_date", "local_time", "precision")})
        if endpoint.get("timezone") is not None:
            values["field:endpoint_timezone"] = endpoint["timezone"]
    elif effects:
        values["field:extra_lifecycle_endpoints"] = len(effects)
    return values


def estimate_predictions(source_rows, predictions):
    source = {r["case_id"]: r for r in source_rows}
    result = json.loads(json.dumps(predictions))
    for row in result:
        for event in row.get("events", []):
            event["confidence"] = estimate(event["fields"], source=source[row["case_id"]]["text"],
                selected_activity=event["selected_activity"], candidate_ids=event["candidate_ids"],
                activities=source[row["case_id"]]["activities"])
    return result


def atomic_counts(expected, actual):
    gold = Counter(e["event_type"] for e in expected)
    emitted = Counter(e.get("event_type", "invalid") for e in actual)
    tp = sum((gold & emitted).values())
    return {"true_positive": tp, "false_positive": sum(emitted.values())-tp,
        "false_negative": sum(gold.values())-tp}


def f1(counts):
    tp, fp, fn = (counts[k] for k in ("true_positive", "false_positive", "false_negative"))
    return 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 1.0


def percentile(values, p):
    values = sorted(values)
    return values[max(0, math.ceil(len(values)*p)-1)] if values else None


def score(source_rows, label_rows, predictions, calls):
    source = {r["case_id"]: r for r in source_rows}
    truth = {r["case_id"]: r for r in label_rows}
    predicted = {r["case_id"]: r for r in predictions}
    if len(truth) != len(label_rows) or len(predicted) != len(predictions) or set(predicted)-set(truth):
        raise ValueError("Duplicate or non-frozen prediction cases")
    totals = Counter()
    detail = []
    calibration_labels, calibration_predictions = [], []
    for case_id, label in truth.items():
        row = predicted.get(case_id, {})
        ready = row.get("state") == "ready_for_review"
        case_calls = [c for c in calls if c["case_id"] == case_id]
        extraction = next((c for c in case_calls if c["stage"] == "extraction"), {})
        raw = extraction.get("value", {}).get("observations", [])
        normalized = row.get("events", [])
        expected = label["events"]
        initial_counts = atomic_counts(expected, raw)
        normalized_counts = atomic_counts(expected, [e["fields"] for e in normalized])
        counters = Counter({"expected_events": len(expected), "ready_reports": int(ready),
            "failed_reports": int(not ready), "approved_progress_events": row.get("approved_progress_events", 0)})
        for prefix, counts in (("initial", initial_counts), ("normalized", normalized_counts)):
            counters.update({prefix+"_"+k: v for k,v in counts.items()})
        # These references have at most one event of each type per report.
        if len({e["event_type"] for e in expected}) != len(expected):
            raise ValueError("Explicit duplicate-type alignment is required for this label")
        expected_by_type = {e["event_type"]: e for e in expected}
        id_map = row.get("activity_external_ids", {})
        first_selections = {}
        selection_items = []
        seen_selection_inputs = set()
        discoveries = defaultdict(list)
        selection_repairs = 0
        for call in case_calls:
            kind = call.get("observation", {}).get("event_type")
            if call["stage"] == "retrieval" and call.get("ok"):
                discoveries[kind].append(call["value"].get("candidate_ids", []))
            if call["stage"] == "selection":
                identity = (kind, call.get("observation", {}).get("summary"))
                if identity in seen_selection_inputs:
                    selection_repairs += 1
                    continue
                seen_selection_inputs.add(identity)
                decision = call.get("value", {})
                first_selections.setdefault(kind, decision)
                selection_items.append((kind, decision))
        counters["selection_repair_calls"] = selection_repairs
        counted_link_kinds = set()
        for kind, decision in selection_items:
            chosen = decision.get("candidate_id")
            if chosen:
                counters["initial_selected_links"] += 1
                external = id_map.get(str(chosen), "UNKNOWN_ID")
                if kind not in counted_link_kinds and kind in expected_by_type and expected_by_type[kind]["link"] == external:
                    counters["initial_correct_links"] += 1
                else:
                    counters["initial_false_links"] += 1
                counted_link_kinds.add(kind)
        needed = initial_counts["false_positive"] + initial_counts["false_negative"] > 0
        for index, gold in enumerate(expected):
            kind = gold["event_type"]
            norm = [e for e in normalized if e["fields"].get("event_type") == kind]
            raw_items = [e for e in raw if e.get("event_type") == kind]
            norm_item = norm[0] if len(norm) == 1 else None
            raw_item = raw_items[0] if len(raw_items) == 1 else None
            expected_values = targets(gold)
            for prefix, observed in (("initial", raw_item), ("normalized", norm_item["fields"] if norm_item else None)):
                values = actual_targets(observed, gold)
                for field, expected_value in expected_values.items():
                    if field == "event":
                        continue
                    correct = field in values and values[field] == expected_value
                    counters[prefix+"_field_count"] += 1
                    counters[prefix+"_field_correct"] += int(correct)
                    if field.startswith("field:endpoint_"):
                        counters[prefix+"_endpoint_field_count"] += 1
                        counters[prefix+"_endpoint_field_correct"] += int(correct)
                    if prefix == "initial" and not correct:
                        needed = True
            if gold["link"] is not None:
                counters["matchable_events"] += 1
                candidate_ids = norm_item["candidate_ids"] if norm_item else [
                    id_map.get(str(item)) for item in (discoveries[kind][-1] if discoveries[kind] else [])]
                counters["candidate_hits"] += int(gold["link"] in candidate_ids)
                decision = first_selections.get(kind, {})
                linked = id_map.get(str(decision.get("candidate_id"))) == gold["link"]
                counters["correct_selected_matchable"] += int(linked)
                needed = needed or not linked
            if gold.get("safe_abstention_required"):
                counters["ambiguity_events"] += 1
                decision = first_selections.get(kind, {})
                safe = ready and norm_item is not None and not norm_item["selected_activity"] and not decision.get("candidate_id")
                counters["safe_abstentions"] += int(safe)
                needed = needed or not safe
            # The frozen labels explicitly mark unsupported/unspecified source
            # dates unscored. Exclude those whole events from this small
            # calibration study, rather than filtering predictions using truth.
            if not gold.get("work_date_scored", True):
                counters["calibration_events_excluded_unscored_date"] += 1
                continue
            atomic_id = f"{case_id}:e{index+1}"
            calibration_labels.append({"case_id": atomic_id, "group_id": label["group_id"],
                "review_status": "ai_assisted_adjudicated", "targets": {**expected_values, "link": gold["link"]}})
            if norm_item:
                confidence = norm_item.get("confidence") or estimate(norm_item["fields"], source=source[case_id]["text"],
                    selected_activity=norm_item["selected_activity"], candidate_ids=norm_item["candidate_ids"],
                    activities=source[case_id]["activities"])
                calibration_predictions.append({"case_id": atomic_id,
                    "targets": {**unmasked_targets(norm_item["fields"]), "link": norm_item["selected_activity"]},
                    "confidence": confidence})
        counters["reports_needing_initial_model_correction"] = int(needed or not ready)
        totals.update(counters)
        detail.append({"case_id": case_id, "group_id": label["group_id"], "state": row.get("state", "missing"),
            "elapsed_seconds": row.get("elapsed_seconds"), "counts": dict(counters),
            "initial_atomic_f1": f1(initial_counts), "normalized_atomic_f1": f1(normalized_counts)})
    def ratio(numerator, denominator):
        return totals[numerator]/totals[denominator] if totals[denominator] else None
    ready_times = [r["elapsed_seconds"] for r in detail if r["state"] == "ready_for_review"]
    def total_f1(prefix):
        return f1({k: totals[prefix+"_"+k] for k in ("true_positive", "false_positive", "false_negative")})
    project_f1 = []
    for group in {r["group_id"] for r in detail}:
        project = Counter()
        for r in detail:
            if r["group_id"] == group:
                project.update(r["counts"])
        project_f1.append(f1({k: project["initial_"+k] for k in ("true_positive", "false_positive", "false_negative")}))
    return {"status": "bounded_ai_reviewed_prototype_evaluation", "report_count": len(truth), "counts": dict(totals),
        "initial_atomic_event_f1": total_f1("initial"), "normalized_atomic_event_f1": total_f1("normalized"),
        "project_macro_initial_atomic_f1": sum(project_f1)/len(project_f1),
        "initial_selected_link_precision": ratio("initial_correct_links", "initial_selected_links"),
        "initial_selected_link_coverage": ratio("correct_selected_matchable", "matchable_events"),
        "candidate_recall_at_8": ratio("candidate_hits", "matchable_events"),
        "initial_field_accuracy": ratio("initial_field_correct", "initial_field_count"),
        "normalized_field_accuracy": ratio("normalized_field_correct", "normalized_field_count"),
        "initial_endpoint_field_accuracy": ratio("initial_endpoint_field_correct", "initial_endpoint_field_count"),
        "normalized_endpoint_field_accuracy": ratio("normalized_endpoint_field_correct", "normalized_endpoint_field_count"),
        "safe_ambiguity_handling": ratio("safe_abstentions", "ambiguity_events"),
        "proposal_readiness_seconds": {"count": len(ready_times), "p50": percentile(ready_times,.5),
            "p95": percentile(ready_times,.95), "max": max(ready_times) if ready_times else None},
        "cases": detail, "limitations": [
            "Small synthetic denominators; no owner-specific accuracy claim or independent human review.",
            "Initial model metrics use first extraction/selection attempts, before normalization or model repairs. Schema-invalid first attempts count as missing, even if later repaired.",
            "Normalized metrics describe initial persisted proposals, never reviewer-corrected state.",
            "Schema-invalid responses count as failed/missing cases; rejected raw provider bodies are not retained.",
            "No approvals, mock delivery latency, browser timings, reviewer-corrected outcomes or sustained mixed workload are measured here.",
            "Support-index scores are experimental review-priority indices, not probabilities; no runtime thresholds are installed."]}, calibration_labels, calibration_predictions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Output directory must be new")
    sealed = json.loads((args.capture/"capture-manifest.json").read_text())
    for name in ("config.json", "predictions.jsonl", "calls.jsonl"):
        if sealed["hashes"].get(name) != digest(args.capture/name):
            parser.error("Captured predictions/calls/config were modified after sealing")
    manifest = json.loads(args.manifest.read_text())
    config = json.loads((args.capture/"config.json").read_text())
    if (manifest["hashes"].get(args.labels.name) != digest(args.labels) or
        manifest["hashes"].get(args.inputs.name) != digest(args.inputs) or
        config["manifest_sha256"] != digest(args.manifest)):
        parser.error("Inputs/labels/manifest must match their frozen capture hashes")
    predictions = rows(args.capture/"predictions.jsonl")
    source_rows = rows(args.inputs)
    predictions = estimate_predictions(source_rows, predictions)
    args.output_dir.mkdir()
    estimates = args.output_dir/"estimated-predictions.jsonl"
    estimates.write_text("".join(json.dumps(row)+"\n" for row in predictions))
    # Seal label-free estimates before parsing any expected outcome values.
    (args.output_dir/"pre-scoring-estimates-manifest.json").write_text(json.dumps({
        "expected_labels_parsed": False, "estimated_predictions_sha256": digest(estimates),
        "estimator_source_sha256": digest(Path("evaluation/confidence_estimator.py")),
        "policy": {"target_precision": .98, "min_support": 20},
    },indent=2)+"\n")
    labels = rows(args.labels)
    expected_inventory = {r["case_id"]: r["group_id"] for r in manifest["splits"][config["split"]]}
    if (manifest.get("status") != "frozen_inputs_and_ai_labels" or
        manifest.get("review", {}).get("kind") != "ai_assisted" or
        manifest.get("review", {}).get("status") != "ai_assisted_adjudicated" or
        manifest.get("review", {}).get("human_review_completed") is not False or
        any(r.get("review_status") != "ai_assisted_adjudicated" for r in labels) or
        {r["case_id"]: r["group_id"] for r in labels} != expected_inventory):
        parser.error("Labels must exactly cover the declared AI-reviewed split and project groups")
    if {r["case_id"] for r in predictions} != {r["case_id"] for r in labels}:
        parser.error("Every frozen case must have a recorded result, including failures")
    summary, calibration_labels, calibration_predictions = score(source_rows, labels,
        predictions, rows(args.capture/"calls.jsonl"))
    summary["hashes"] = {"capture_manifest": digest(args.capture/"capture-manifest.json"),
        "labels": digest(args.labels), "inputs": digest(args.inputs), "split_manifest": digest(args.manifest)}
    (args.output_dir/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    for name, data in (("calibration-labels.jsonl",calibration_labels),("calibration-predictions.jsonl",calibration_predictions)):
        (args.output_dir/name).write_text("".join(json.dumps(r)+"\n" for r in data))
    print(json.dumps({k:v for k,v in summary.items() if k not in {"cases","limitations","hashes"}}))


if __name__ == "__main__":
    main()
