"""Score sealed paired development captures; labels never enter model calls."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import argparse
import json
from pathlib import Path

from evaluation.metrics import _prediction_failed

LABELS = Path(__file__).parent / "fixtures/paired-pilot-v1/labels.json"


def _value(row, field):
    if field not in row:
        return ("missing",)
    value = row[field]
    if value is None:
        return None
    if field == "evidence":
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if field == "asset_tags":
        return ("tags", tuple(sorted(value))) if isinstance(value, list) and all(isinstance(x, str) for x in value) else ("invalid-tags",)
    if field == "quantity" and not isinstance(value, bool):
        try:
            number = Decimal(str(value))
            if number.is_finite():
                return str(number.normalize())
        except InvalidOperation:
            pass
    return str(value)


def _signature(row, fields):
    return tuple((field, _value(row, field)) for field in fields)


def fields_exact(expected, actual):
    fields = ("event_type", "work_date", "area", "quantity", "unit", "quantity_kind")
    for field in ("date_basis", "summary", "evidence"):
        if any(field in row for row in expected):
            if not all(field in row for row in expected):
                raise ValueError(f"Inconsistent {field} annotation fields")
            fields += (field,)
    if any("asset_tags" in row for row in expected):
        if not all("asset_tags" in row for row in expected):
            raise ValueError("Inconsistent asset-tag annotation fields")
        fields += ("asset_tags",)
    return Counter(_signature(x, fields) for x in actual) == Counter(_signature(x, fields) for x in expected)


def event_scores(expected, actual):
    fields = ("event_type", "work_date", "area")
    gold = Counter(_signature(row, fields) for row in expected)
    predicted = Counter(_signature(row, fields) for row in actual)
    return {"true_positive": sum((gold & predicted).values()),
            "false_positive": sum((predicted - gold).values()),
            "false_negative": sum((gold - predicted).values()),
            "complete": gold == predicted}


def completed_event_scores(expected, actual, *, completed):
    result = event_scores(expected, actual if completed else [])
    result["complete"] = completed and result["complete"]
    return result


def score(capture, labels=LABELS):
    manifest = json.loads((capture / "capture-manifest.json").read_text())
    for name, digest in manifest.items():
        if Path(name).name != name or sha256((capture / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Capture integrity check failed")
    for required in ("config.json", "predictions.jsonl", "summary.json"):
        if required not in manifest:
            raise ValueError("Missing sealed capture file")
    config = json.loads((capture / "config.json").read_text())
    digest = sha256(labels.read_bytes()).hexdigest()
    if config.get("label_sha256") and config["label_sha256"] != digest:
        raise ValueError("Labels changed after experiment freeze")
    truth = json.loads(labels.read_text())["cases"]
    rows = [json.loads(line) for line in (capture / "predictions.jsonl").read_text().splitlines()]
    raw = ([json.loads(line) for line in (capture / "model-outputs.jsonl").read_text().splitlines()]
           if "model-outputs.jsonl" in manifest else [])

    def identity(row):
        return row["case_id"], row.get("arm", row.get("requested_model", row.get("model")))

    predictions = {identity(row): row for row in rows}
    outputs = {identity(row): row for row in raw}
    planned = {(row["case_id"], row.get("arm", row["model"])) for row in config["schedule"]}
    if (len(planned) != len(config["schedule"]) or len(predictions) != len(rows) or
            len(outputs) != len(raw) or set(predictions) - planned or set(outputs) - planned):
        raise ValueError("Duplicate or unscheduled case/arm")
    detail = []
    for scheduled in config["schedule"]:
        key = scheduled["case_id"], scheduled.get("arm", scheduled["model"])
        expected = truth[key[0]]
        row = predictions.get(key, {})
        observed = row.get("observations", [])
        raw_value = outputs.get(key, {}).get("value", {})
        initial = raw_value.get("observations", [])
        completed = (row.get("state") == "completed" and not _prediction_failed(row)
                     and isinstance(row.get("observations"), list))
        detail.append({"case_id": key[0], "arm": key[1], "completed": completed,
                       "response_checks": row.get("response_checks", {}),
                       "raw": event_scores(expected, initial),
                       "normalized": completed_event_scores(expected, observed, completed=completed),
                       "raw_fields_exact": completed and isinstance(raw_value.get("observations"), list)
                       and fields_exact(expected, initial),
                       "normalized_fields_exact": completed and fields_exact(expected, observed),
                       "raw_nonactual_quantity_violations": sum(
                           x.get("event_type") in {"planned_work", "no_work", "material_delivery", "blocker"}
                           and (x.get("quantity") is not None or x.get("unit") is not None or
                                x.get("quantity_kind") != "none") for x in initial)})
    return {"scoring_version": "paired-development-v5-completion-fences",
            "scope": "AI-authored development regressions; no independent adjudication or acceptance",
            "labels_sha256": digest, "labels_frozen_before_run": "label_sha256" in config,
            "scheduled": len(detail), "completed": sum(x["completed"] for x in detail), "cases": detail}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=LABELS)
    args = parser.parse_args()
    result = score(args.capture_dir, args.labels)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
