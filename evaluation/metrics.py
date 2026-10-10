"""Deterministic, label-side evaluation metrics.

Predictions are deliberately plain mappings so this module can evaluate saved
outputs from any selector.  Labels are supplied separately by the runner.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
from statistics import mean, median
from typing import Any, Iterable, Mapping


def _num(v: Any) -> float | None:
    try:
        value = float(v) if v is not None else None
        return value if value is not None and math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def _ids(row: Mapping[str, Any]) -> list[str]:
    value = row.get("selected_activity_ids", row.get("selected_activity_id", row.get("selected_id")))
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x) for x in value]
    return [str(value)]


def _gold_ids(row: Mapping[str, Any]) -> list[str]:
    return [str(x) for x in row.get("expected_activity_ids", [])]


EVENT_FIELDS = ("event_type", "work_date", "start_date", "finish_date", "start_time", "finish_time",
                "quantity", "quantity_kind", "unit", "scope", "precision")


def _event_signature(event: Mapping[str, Any], *, label: bool) -> tuple[tuple[str, str], ...] | None:
    attrs = {}
    for field in EVENT_FIELDS:
        source = f"expected_{field}" if label else field
        value = event.get(source)
        if value is not None and value != "":
            attrs[field] = str(value).strip().casefold()
    # Event type plus at least one discriminating attribute forms a usable
    # case-scoped identity. Opaque IDs never participate in alignment.
    if "event_type" not in attrs or len(attrs) < 2:
        return None
    return tuple(sorted(attrs.items()))


def atomic_extraction(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Align atomic events by observed attributes within each report case."""
    labels, predictions = list(labels), list(predictions)
    gold: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
    pred: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
    unavailable_gold = unavailable_pred = 0
    for row in labels:
        events = row.get("atomic_events", [])
        if not events:
            unavailable_gold += int(row.get("expected_atomic_count", 1))
        for event in events:
            signature = _event_signature(event, label=True)
            if signature is None:
                unavailable_gold += 1
            else:
                gold[(str(row.get("case_id", "")), signature)] += 1
    for row in predictions:
        events = row.get("atomic_events", [])
        if not events:
            count = row.get("atomic_count", row.get("predicted_atomic_count"))
            unavailable_pred += int(count) if count is not None else 0
        for event in events:
            signature = _event_signature(event, label=False)
            if signature is None:
                unavailable_pred += 1
            else:
                pred[(str(row.get("case_id", "")), signature)] += 1
    if not gold and not pred:
        return {"status": "unavailable", "true_positive": None, "false_positive": None,
                "false_negative": None, "precision": None, "recall": None, "f1": None,
                "unmatched_gold_count": unavailable_gold, "unmatched_prediction_count": unavailable_pred}
    keys = set(gold) | set(pred)
    tp = sum(min(gold[key], pred[key]) for key in keys)
    fp = sum(max(0, pred[key] - gold[key]) for key in keys)
    fn = sum(max(0, gold[key] - pred[key]) for key in keys)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"status": "scored_with_unaligned_events" if unavailable_gold or unavailable_pred else "scored",
            "true_positive": tp, "false_positive": fp, "false_negative": fn, "precision": p, "recall": r,
            "unmatched_gold_count": unavailable_gold, "unmatched_prediction_count": unavailable_pred,
            "f1": 2 * p * r / (p + r) if p + r else 0.0}


def critical_fields(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    pred_by = {str(x["case_id"]): x for x in predictions}
    fields = {"tag": "expected_activity_ids", "work_date": "expected_work_date", "start_date": "expected_start_date",
              "finish_date": "expected_finish_date", "start_time": "expected_start_time",
              "finish_time": "expected_finish_time", "time_precision": "expected_time_precision",
              "quantity": "expected_quantity", "quantity_kind": "expected_quantity_kind", "unit": "expected_unit"}
    result: dict[str, Any] = {}
    for name, gold_key in fields.items():
        applicable = correct = 0
        for label in labels:
            if gold_key not in label and name == "work_date":
                continue
            pred = pred_by.get(str(label.get("case_id")), {})
            if name == "tag":
                expected, actual = set(_gold_ids(label)), set(_ids(pred))
                applicable += bool(expected)
                correct += int(expected == actual) if expected else 0
            elif name == "time_precision":
                endpoints = [k for k in ("expected_start_time", "expected_finish_time", "expected_work_date",
                                         "expected_start_date", "expected_finish_date") if label.get(k) is not None]
                if not endpoints:
                    continue
                applicable += len(endpoints)
                actual_precision = pred.get("time_precision", pred.get("event_precision"))
                correct += sum(str(actual_precision) == str(label.get("expected_time_precision")) for _ in endpoints)
            else:
                expected = label.get(gold_key)
                if expected is None:
                    continue
                applicable += 1
                actual = pred.get(name, pred.get(f"predicted_{name}"))
                correct += int(str(actual) == str(expected))
        result[name] = {"correct": correct, "applicable": applicable,
                        "accuracy": correct / applicable if applicable else 0.0}
    return result


def selection_metrics(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    labels, predictions = list(labels), list(predictions)
    by = {str(x["case_id"]): x for x in predictions}
    matchable = [x for x in labels if x.get("expected_mapping_state") == "suggested" and _gold_ids(x)]
    selected = [x for x in matchable if _ids(by.get(str(x["case_id"]), {}))]
    correct = [x for x in selected if set(_ids(by[str(x["case_id"])])) == set(_gold_ids(x))]
    candidates_ok = [x for x in matchable if set(_gold_ids(x)) & set(str(i) for i in by.get(str(x["case_id"]), {}).get("candidate_ids", [])[:8])]
    all_selected = [x for x in labels if _ids(by.get(str(x["case_id"]), {}))]
    all_correct = [x for x in all_selected if x.get("expected_mapping_state") == "suggested" and
                   set(_ids(by[str(x["case_id"])])) == set(_gold_ids(x))]
    safe_rows = [x for x in labels if x.get("expected_mapping_state") in {"ambiguous", "unmatched"}]
    safe = [x for x in safe_rows if not _ids(by.get(str(x["case_id"]), {}))]
    return {"candidate_recall": len(candidates_ok) / len(matchable) if matchable else 0.0,
            "recall_at_8": len(candidates_ok) / len(matchable) if matchable else 0.0,
            "recall_at_8_numerator": len(candidates_ok), "recall_at_8_denominator": len(matchable),
            "exact_choice": len(correct) / len(matchable) if matchable else 0.0,
            "exact_choice_numerator": len(correct), "exact_choice_denominator": len(matchable),
            "selected_precision": len(correct) / len(selected) if selected else 0.0,
            "overall_selected_precision": len(all_correct) / len(all_selected) if all_selected else 0.0,
            "overall_selected": len(all_selected),
            "coverage": len(selected) / len(matchable) if matchable else 0.0,
            "safe_abstention": len(safe) / len(safe_rows) if safe_rows else 0.0,
            "matchable": len(matchable), "selected": len(selected), "safe_abstention_denominator": len(safe_rows)}


def latency_summary(predictions: Iterable[Mapping[str, Any]]) -> dict[str, float | int]:
    values = sorted(float(x["latency_ms"]) for x in predictions if _num(x.get("latency_ms")) is not None)
    if not values:
        return {"count": 0, "median_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None, "mean_ms": None}
    return {"count": len(values), "median_ms": median(values), "p50_ms": median(values),
            "p95_ms": values[max(0, math.ceil(.95 * len(values)) - 1)], "max_ms": values[-1], "mean_ms": mean(values)}


def lifecycle_latency_summary(predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize observed wall intervals, review wait and retry time separately."""
    pairs = {"submission_to_update": ("submitted_at", "internal_update_at"),
             "acceptance_to_update": ("accepted_at", "internal_update_at"),
             "external_delivery": ("accepted_at", "external_acknowledged_at")}
    rows = list(predictions)
    result: dict[str, Any] = {}
    for name, (start, end) in pairs.items():
        vals = []
        for row in rows:
            try:
                a, b = datetime.fromisoformat(str(row[start])), datetime.fromisoformat(str(row[end]))
                if a.tzinfo is None or b.tzinfo is None:
                    continue
                duration = (b - a).total_seconds() * 1000
                if duration < 0:
                    continue
                vals.append(duration)
            except (KeyError, TypeError, ValueError):
                pass
        result[name] = latency_summary([{"latency_ms": v} for v in vals])
    result["review_wait"] = latency_summary([{"latency_ms": _timestamp_delta(row, "review_started_at", "review_completed_at")}
                                             for row in rows if _timestamp_delta(row, "review_started_at", "review_completed_at") is not None])
    result["system_submission_to_update_excluding_review"] = latency_summary([
        {"latency_ms": duration - review}
        for row in rows
        if (duration := _timestamp_delta(row, "submitted_at", "internal_update_at")) is not None
        and (review := _timestamp_delta(row, "review_started_at", "review_completed_at")) is not None
        and review <= duration
    ])
    retry_counts = [_num(row.get("retry_count")) for row in rows]
    observed_counts = [value for value in retry_counts if value is not None]
    result["retries"] = {"case_count": len(observed_counts), "total": sum(observed_counts) if observed_counts else None,
                         "cases_with_retry": sum(value > 0 for value in observed_counts)}
    result["retry_duration"] = latency_summary([{"latency_ms": value} for row in rows
                                                  if (value := _num(row.get("retry_duration_ms"))) is not None])
    return result


def _timestamp_delta(row: Mapping[str, Any], start: str, end: str) -> float | None:
    try:
        a, b = datetime.fromisoformat(str(row[start])), datetime.fromisoformat(str(row[end]))
        if a.tzinfo is None or b.tzinfo is None:
            return None
        value = (b - a).total_seconds() * 1000
        return value if math.isfinite(value) and value >= 0 else None
    except (KeyError, TypeError, ValueError):
        return None


def error_categories(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by = {str(x["case_id"]): x for x in predictions}
    counts: Counter[str] = Counter()
    for label in labels:
        pred = by.get(str(label.get("case_id")), {})
        cats = []
        if label.get("expected_mapping_state") == "ambiguous" and _ids(pred): cats.append("unsafe_ambiguous_selection")
        if label.get("expected_mapping_state") == "unmatched" and _ids(pred): cats.append("false_match")
        if label.get("expected_event_type") != pred.get("event_type", pred.get("predicted_event_type")): cats.append("event_type")
        if label.get("expected_quantity") is not None and str(label["expected_quantity"]) != str(pred.get("quantity", pred.get("predicted_quantity"))): cats.append("quantity")
        for cat in cats or ["correct"]: counts[cat] += 1
    return [{"category": key, "count": counts[key]} for key in sorted(counts)]


def evaluate(labels: list[Mapping[str, Any]], predictions: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {"extraction": atomic_extraction(labels, predictions), "critical_fields": critical_fields(labels, predictions),
            "selection": selection_metrics(labels, predictions), "latency": latency_summary(predictions),
            "lifecycle_latency": lifecycle_latency_summary(predictions), "errors": error_categories(labels, predictions),
            "case_outcomes": _case_outcomes(labels, predictions),
            "scope": _scope_metrics(labels, predictions),
            "review_burden": _review_burden(labels, predictions),
            "strata": _stratified_metrics(labels, predictions),
            "project_weighted": _project_weighted_metrics(labels, predictions),
            "initial_review_state": _review_quality(labels, predictions, "initial"),
            "corrected_review_state": _review_quality(labels, predictions, "final")}


def _prediction_index(predictions: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(row.get("case_id", "")): row for row in predictions}


def _case_outcomes(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    by = _prediction_index(predictions)
    rows = list(labels)
    failed = [row for row in rows if str(by.get(str(row.get("case_id")), {}).get("status", "")).lower() in
              {"failed", "error", "timeout"} or by.get(str(row.get("case_id")), {}).get("failure")]
    abstained = [row for row in rows if not _ids(by.get(str(row.get("case_id")), {}))]
    return {"cases": len(rows), "failed": len(failed), "failure_rate": len(failed) / len(rows) if rows else None,
            "abstained": len(abstained), "abstention_rate": len(abstained) / len(rows) if rows else None,
            "failure_cases": [str(row.get("case_id")) for row in failed]}


def _scope_metrics(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    by = _prediction_index(predictions)
    applicable = matched = missing = 0
    for label in labels:
        expected = label.get("expected_scope")
        if expected is None:
            continue
        applicable += 1
        actual = by.get(str(label.get("case_id")), {}).get("scope")
        if actual is None:
            missing += 1
        elif str(actual) == str(expected):
            matched += 1
    return {"correct": matched, "applicable": applicable, "missing": missing,
            "accuracy": matched / applicable if applicable else None}


def _review_burden(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    by = _prediction_index(predictions)
    rows = list(labels)
    review_cases = [row for row in rows if by.get(str(row.get("case_id")), {}).get("review_required") is True]
    completed = [row for row in rows if isinstance(by.get(str(row.get("case_id")), {}).get("reviewer_corrected_state"), Mapping)]
    return {"cases": len(rows), "review_required": len(review_cases),
            "review_required_rate": len(review_cases) / len(rows) if rows else None,
            "review_completed": len(completed), "review_completed_rate": len(completed) / len(review_cases) if review_cases else None}


def _case_selection_correct(label: Mapping[str, Any], prediction: Mapping[str, Any]) -> bool | None:
    if label.get("expected_mapping_state") != "suggested" or not _gold_ids(label):
        return None
    return bool(_ids(prediction)) and set(_ids(prediction)) == set(_gold_ids(label))


def _group_summary(labels: list[Mapping[str, Any]], by: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    applicable = [row for row in labels if _case_selection_correct(row, by.get(str(row.get("case_id")), {})) is not None]
    selected = sum(bool(_ids(by.get(str(row.get("case_id")), {}))) for row in applicable)
    correct = sum(_case_selection_correct(row, by.get(str(row.get("case_id")), {})) is True for row in applicable)
    return {"cases": len(labels), "matchable_cases": len(applicable), "selected": selected, "correct": correct,
            "exact_choice_micro": correct / len(applicable) if applicable else None,
            "coverage": selected / len(applicable) if applicable else None,
            "selected_precision": correct / selected if selected else None}


def _stratified_metrics(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    by = _prediction_index(predictions)
    results = {}
    for dimension, aliases in {"format": ("report_format", "source_format", "format"),
                               "discipline": ("discipline", "expected_discipline")}.items():
        groups: dict[str, list[Mapping[str, Any]]] = {}
        unclassified = 0
        for row in labels:
            value = next((row.get(key) for key in aliases if row.get(key) not in (None, "")), None)
            if value is None:
                unclassified += 1
            else:
                groups.setdefault(str(value), []).append(row)
        results[dimension] = {"unclassified_cases": unclassified,
                              "groups": {name: _group_summary(items, by) for name, items in sorted(groups.items())},
                              "status": "unavailable" if not groups else "scored"}
    return results


def _project_weighted_metrics(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    by = _prediction_index(predictions)
    groups: dict[str, list[Mapping[str, Any]]] = {}
    missing = 0
    for row in labels:
        project = row.get("project_id", row.get("expected_project_id"))
        if project in (None, ""):
            missing += 1
        else:
            groups.setdefault(str(project), []).append(row)
    per_project = {project: _group_summary(rows, by) for project, rows in sorted(groups.items())}
    values = [value["exact_choice_micro"] for value in per_project.values() if value["exact_choice_micro"] is not None]
    coverages = [value["coverage"] for value in per_project.values() if value["coverage"] is not None]
    return {"status": "unavailable" if not groups else "scored", "project_count": len(groups),
            "unclassified_cases": missing, "macro_project_exact_choice": mean(values) if values else None,
            "macro_project_coverage": mean(coverages) if coverages else None,
            "micro_case": _group_summary(list(labels), by), "by_project": per_project}


def _review_quality(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]], stage: str) -> dict[str, Any]:
    pred_by = {str(x["case_id"]): x for x in predictions}
    total = correct = applicable = 0
    for label in labels:
        pred = pred_by.get(str(label.get("case_id")), {})
        if stage == "initial":
            actual = pred.get("initial_state", pred)
        else:
            actual = pred.get("reviewer_corrected_state", pred.get("final_state"))
        if not isinstance(actual, Mapping):
            continue
        total += 1
        fields = {"event_type": "expected_event_type", "quantity": "expected_quantity",
                  "work_date": "expected_work_date"}
        for field, gold in fields.items():
            if gold in label and label[gold] is not None:
                applicable += 1
                correct += int(str(actual.get(field)) == str(label[gold]))
    return {"cases": total, "field_correct": correct, "field_applicable": applicable,
            "field_accuracy": correct / applicable if applicable else None}
