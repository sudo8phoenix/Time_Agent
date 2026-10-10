"""Persist a label-blind capture from a genuinely live UI-to-export run.

This module stores already-observed artifacts. It does not drive a browser,
intercept routes, inject models, or read label files. A human/operator must
capture the actual run and pass only observed, non-label fields here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

FORBIDDEN_KEYS = {
    "expected_activity_ids", "expected_mapping_state", "expected_quantity",
    "expected_event_type", "expected_work_date", "expected_atomic_count",
    "correct_atomic_count", "self_reported_correct", "gold", "ground_truth",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def validate_capture(capture: Mapping[str, Any]) -> None:
    if capture.get("schema_version") != 1:
        raise ValueError("capture schema_version must be 1")
    run = capture.get("run")
    if not isinstance(run, Mapping) or not all(run.get(k) for k in ("commit", "model_digest", "prompt_config_sha256")):
        raise ValueError("run must freeze commit, model_digest, and prompt_config_sha256")
    if capture.get("mode") != "live_ui_to_export":
        raise ValueError("capture mode must be live_ui_to_export")
    cases = capture.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("capture must contain at least one case")
    ids: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping) or not case.get("case_id"):
            raise ValueError("each case requires case_id")
        case_id = str(case["case_id"])
        if case_id in ids:
            raise ValueError(f"duplicate case_id: {case_id}")
        ids.add(case_id)
        leaked = _forbidden(case)
        if leaked:
            raise ValueError(f"case {case_id} contains label/self-reported fields: {sorted(leaked)}")
        if not isinstance(case.get("atomic_events", []), list):
            raise ValueError(f"case {case_id} atomic_events must be a list")
        for event in case.get("atomic_events", []):
            if not isinstance(event, Mapping):
                raise ValueError(f"case {case_id} atomic events must be observed attribute objects")
        if not isinstance(case.get("candidate_ids", []), list):
            raise ValueError(f"case {case_id} candidate_ids must be a list")


def _forbidden(value: Any, path: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            if name in FORBIDDEN_KEYS or name.startswith("expected_"):
                found.add(f"{path}{name}")
            found.update(_forbidden(item, f"{path}{name}."))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found.update(_forbidden(item, f"{path}[{i}]."))
    return found


def save_capture(capture: Mapping[str, Any], output: Path) -> dict[str, Any]:
    validate_capture(capture)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing capture: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(capture, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    output.write_text(payload, encoding="utf-8")
    data = output.read_bytes()
    return {"capture_sha256": hashlib.sha256(data).hexdigest(), "case_count": len(capture["cases"]),
            "path": str(output)}


def prediction_rows(capture: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert observed capture cases to prediction JSONL rows, without labels."""
    validate_capture(capture)
    rows = []
    for case in capture["cases"]:
        row = {key: value for key, value in case.items() if key != "atomic_events"}
        row["atomic_events"] = list(case.get("atomic_events", []))
        rows.append(row)
    return rows


def write_predictions(capture_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing predictions: {output}")
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    rows = prediction_rows(capture)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return {"prediction_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "case_count": len(rows),
            "path": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_json", type=Path, help="label-blind observed capture JSON")
    parser.add_argument("output", type=Path, help="new destination path; existing files are preserved")
    parser.add_argument("--predictions", type=Path, help="also emit label-free prediction JSONL")
    args = parser.parse_args()
    capture = json.loads(args.capture_json.read_text(encoding="utf-8"))
    print(json.dumps(save_capture(capture, args.output), indent=2, sort_keys=True))
    if args.predictions:
        print(json.dumps(write_predictions(args.output, args.predictions), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
