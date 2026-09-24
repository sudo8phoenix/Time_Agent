"""Run a saved prediction file against a separately supplied split of labels."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any
from .metrics import evaluate

FORBIDDEN = {"expected_activity_ids", "expected_mapping_state", "expected_quantity", "expected_event_type"}

def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def validate_split(labels: list[dict[str, Any]], split: dict[str, Any], name: str) -> None:
    families = split.get("splits", {})
    memberships = {str(f): bucket for bucket, fs in families.items() for f in fs}
    chosen = set(families.get(name, []))
    if not chosen: raise ValueError(f"unknown or empty split: {name}")
    seen: set[str] = set()
    for label in labels:
        family = str(label.get("event_family_id", ""))
        seen.add(family)
        if family not in memberships: raise ValueError(f"family missing from split manifest: {family}")
        if memberships[family] != name: raise ValueError(f"label family {family} leaks from {memberships[family]} into {name}")
    if seen != chosen: raise ValueError(f"{name} labels do not cover exactly its manifest families")
    all_families: set[str] = set()
    for bucket, fs in families.items():
        overlap = all_families.intersection(fs)
        if overlap:
            raise ValueError(f"event family appears in more than one split: {sorted(overlap)}")
        all_families.update(fs)

def run(prediction_path: Path, labels_path: Path, splits_path: Path, split_name: str, config: dict[str, Any]) -> dict[str, Any]:
    predictions, all_labels, split = _lines(prediction_path), _lines(labels_path), json.loads(splits_path.read_text())
    chosen_families = set(split.get("splits", {}).get(split_name, []))
    if not chosen_families:
        raise ValueError(f"unknown or empty split: {split_name}")
    labels = [label for label in all_labels if str(label.get("event_family_id", "")) in chosen_families]
    if not predictions: raise ValueError("prediction file is empty")
    for row in predictions:
        leaked = FORBIDDEN & set(row)
        if leaked: raise ValueError(f"prediction contains held-out label fields: {sorted(leaked)}")
    validate_split(labels, split, split_name)
    label_ids, pred_ids = {str(x["case_id"]) for x in labels}, {str(x.get("case_id")) for x in predictions}
    if label_ids != pred_ids: raise ValueError("predictions and labels must have identical case IDs")
    result = evaluate(labels, predictions)
    result["run"] = {"split": split_name, "prediction_sha256": hashlib.sha256(prediction_path.read_bytes()).hexdigest(),
                      "label_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(), "config": config, "config_sha256": _json_hash(config),
                      "label_count": len(labels), "real_model": bool(config.get("real_model", False))}
    return result

def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("predictions"); ap.add_argument("labels"); ap.add_argument("splits"); ap.add_argument("--split", default="held_out"); ap.add_argument("--config", default="{}")
    ap.add_argument("--output")
    args = ap.parse_args(); result = run(Path(args.predictions), Path(args.labels), Path(args.splits), args.split, json.loads(args.config))
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output: Path(args.output).write_text(text + "\n", encoding="utf-8")
    else: print(text)
if __name__ == "__main__": main()
