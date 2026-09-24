"""Deterministic, label-side evaluation metrics.

Predictions are deliberately plain mappings so this module can evaluate saved
outputs from any selector.  Labels are supplied separately by the runner.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any, Iterable, Mapping


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _ids(row: Mapping[str, Any]) -> list[str]:
    value = row.get("selected_activity_id", row.get("selected_id"))
    if value is None:
        return []
    return [str(value)]


def _gold_ids(row: Mapping[str, Any]) -> list[str]:
    return [str(x) for x in row.get("expected_activity_ids", [])]


def atomic_extraction(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> dict[str, float | int]:
    """Event extraction P/R/F1, counting atomic event keys where available."""
    gold = {str(x) for row in labels for x in row.get("atomic_event_keys", [])}
    pred = {str(x) for row in predictions for x in row.get("atomic_event_keys", [])}
    if not gold and not pred:
        # Seed labels expose expected_atomic_count only for multi-event cases.
        gold_n = sum(int(row.get("expected_atomic_count", 1)) for row in labels)
        pred_n = sum(int(row.get("predicted_atomic_count", row.get("atomic_count", 1))) for row in predictions)
        correct = sum(int(row.get("correct_atomic_count", 0)) for row in predictions)
        tp, fp, fn = correct, max(0, pred_n - correct), max(0, gold_n - correct)
    else:
        tp, fp, fn = len(gold & pred), len(pred - gold), len(gold - pred)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"true_positive": tp, "false_positive": fp, "false_negative": fn, "precision": p, "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0}


def critical_fields(labels: Iterable[Mapping[str, Any]], predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    pred_by = {str(x["case_id"]): x for x in predictions}
    fields = {"tag": "expected_activity_ids", "work_date": "expected_work_date", "quantity": "expected_quantity",
              "quantity_kind": "expected_quantity_kind", "unit": "expected_unit"}
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
    correct = [x for x in selected if _ids(by[str(x["case_id"])])[0] in _gold_ids(x)]
    candidates_ok = [x for x in matchable if set(_gold_ids(x)) & set(str(i) for i in by.get(str(x["case_id"]), {}).get("candidate_ids", []))]
    safe_rows = [x for x in labels if x.get("expected_mapping_state") in {"ambiguous", "unmatched"}]
    safe = [x for x in safe_rows if not _ids(by.get(str(x["case_id"]), {}))]
    return {"recall_at_8": len(candidates_ok) / len(matchable) if matchable else 0.0,
            "recall_at_8_numerator": len(candidates_ok), "recall_at_8_denominator": len(matchable),
            "exact_choice": len(correct) / len(matchable) if matchable else 0.0,
            "exact_choice_numerator": len(correct), "exact_choice_denominator": len(matchable),
            "selected_precision": len(correct) / len(selected) if selected else 0.0,
            "coverage": len(selected) / len(matchable) if matchable else 0.0,
            "safe_abstention": len(safe) / len(safe_rows) if safe_rows else 0.0,
            "matchable": len(matchable), "selected": len(selected), "safe_abstention_denominator": len(safe_rows)}


def latency_summary(predictions: Iterable[Mapping[str, Any]]) -> dict[str, float | int]:
    values = sorted(float(x["latency_ms"]) for x in predictions if _num(x.get("latency_ms")) is not None)
    if not values:
        return {"count": 0, "median_ms": 0.0, "p95_ms": 0.0, "mean_ms": 0.0}
    return {"count": len(values), "median_ms": median(values), "p95_ms": values[max(0, int(len(values) * .95) - 1)], "mean_ms": mean(values)}


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
            "errors": error_categories(labels, predictions)}
