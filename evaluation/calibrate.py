"""Reproducible review-routing calibration using frozen, independently reviewed labels.

This tool only reads validation labels. Thresholds prioritize review; they never
permit automatic acceptance. See evaluation/contracts/confidence-calibration.md for the input contract.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

VERSION = "review-calibration-v3-completion-fence"
BANDS = ((0, .5), (.5, .8), (.8, .9), (.9, 1.0000001))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _index(rows: list[dict]) -> dict:
    result = {}
    for row in rows:
        key = row["case_id"]
        if key in result:
            raise ValueError(f"Duplicate case: {key}")
        result[key] = row
    return result


def freeze_gate(manifest: dict, labels: list[dict], labels_hash: str, *,
                review_policy="independent_human", authorization=None,
                authorization_hash=None) -> None:
    if manifest.get("status") != "frozen" or manifest.get("labels_sha256") != labels_hash:
        raise ValueError("Validation labels must match a frozen manifest hash")
    review = manifest.get("review", {})
    if review_policy == "independent_human":
        review_status = "independently_reviewed"
        if (review.get("status") != review_status or review.get("kind") != "human" or
            not review.get("reviewer_id") or not review.get("reviewed_at") or
            not review.get("attestation") or not review.get("label_authors") or
            review["reviewer_id"] in review["label_authors"]):
            raise ValueError("Independent human review and author separation are required")
    elif review_policy == "owner_authorized_ai_assisted":
        review_status = "ai_assisted_adjudicated"
        if (not isinstance(authorization, dict) or
            authorization.get("status") != "owner_approved_frozen" or
            authorization.get("review_policy", {}).get("kind") != "ai_assisted" or
            authorization.get("review_policy", {}).get("human_review_completed") is not False or
            authorization.get("review_policy", {}).get("authorized_acceptance_required") is not True or
            not authorization_hash or review.get("authorization_sha256") != authorization_hash):
            raise ValueError("Explicit owner AI-review authorization and matching hash are required")
        if (review.get("kind") != "ai_assisted" or review.get("status") != review_status or
            review.get("human_review_completed") is not False or not review.get("reviewer_id") or
            not review.get("reviewed_at") or not review.get("attestation") or not review.get("label_authors")):
            raise ValueError("AI-assisted adjudication must be declared honestly")
    else:
        raise ValueError("Unknown review policy")
    if manifest.get("group_review_status") != review_status:
        raise ValueError("D05 project/scenario grouping must match the selected review policy")
    splits = manifest["splits"]
    if set(splits) != {"development", "train", "validation", "holdout"}:
        raise ValueError("All four split inventories are required")
    seen_cases, seen_groups = set(), set()
    for split, rows in splits.items():
        cases = [row["case_id"] for row in rows]
        groups = {row["group_id"] for row in rows}
        if len(cases) != len(set(cases)) or seen_cases.intersection(cases) or seen_groups.intersection(groups):
            raise ValueError("Case or underlying scenario/project group leaks across splits")
        seen_cases.update(cases)
        seen_groups.update(groups)
    expected = {row["case_id"]: row["group_id"] for row in splits["validation"]}
    if not expected or {row["case_id"]: row["group_id"] for row in labels} != expected:
        raise ValueError("Labels must exactly cover the frozen validation inventory")
    if any(row.get("review_status") != review_status for row in labels):
        raise ValueError("Every validation case must match the selected review policy")


def _score(value: dict | None) -> tuple[float | None, tuple | None]:
    if value is None or value.get("score") is None:
        return None, None
    score = value["score"]
    if (isinstance(score, bool) or not isinstance(score, (int, float)) or
        not math.isfinite(score) or not 0 <= score <= 1 or
        value.get("method") in (None, "not_estimated") or not value.get("version")):
        raise ValueError("Scores require finite [0,1] values and method/version")
    return score, (value["method"], value["version"])


def assess(labels: list[dict], predictions: list[dict], *, target_precision=.95, min_support=20) -> dict:
    if not 0 < target_precision <= 1 or min_support < 1:
        raise ValueError("Invalid precision/support policy")
    truth, predicted = _index(labels), _index(predictions)
    if set(predicted) - set(truth):
        raise ValueError("Predictions contain non-validation or unknown cases")
    targets = {"field": [], "event": [], "link": []}
    methods = {name: set() for name in targets}
    extra = {name: 0 for name in targets}
    for case, label in truth.items():
        prediction = predicted.get(case, {})
        # Legacy sealed rows omit lifecycle state. Explicit failure/pending state
        # never supplies quality or confidence support, even with diagnostic gold.
        verified = bool(prediction) and not prediction.get("failure") and all(
            prediction.get(key) in {"completed", "succeeded", "success", "ready_for_review"}
            for key in ("state", "status") if key in prediction
        )
        actual = prediction.get("targets", {})
        confidence = prediction.get("confidence", {})
        for name, expected in label["targets"].items():
            kind = "field" if name.startswith("field:") else name
            if kind not in targets:
                raise ValueError(f"Unknown target type: {name}")
            value = actual.get(name)
            score, method = _score(confidence.get("linking" if kind == "link" else "extraction"))
            if method:
                methods[kind].add(method)
            emitted = name in actual and value is not None
            targets[kind].append({"score": score if emitted and verified else None,
                                  "correct": verified and emitted and value == expected,
                                  "emitted": emitted, "correct_abstention": verified and name in actual and value is None and expected is None})
        for name in set(actual) - set(label["targets"]):
            kind = "field" if name.startswith("field:") else name
            if kind not in targets:
                raise ValueError(f"Unknown target type: {name}")
            if actual[name] is not None:
                score, method = _score(confidence.get("linking" if kind == "link" else "extraction"))
                if method:
                    methods[kind].add(method)
                targets[kind].append({"score": score if verified else None, "correct": False, "emitted": True,
                                      "correct_abstention": False, "extra": True})
                extra[kind] += 1
    results = {}
    for kind, rows in targets.items():
        if len(methods[kind]) > 1:
            raise ValueError(f"Mixed estimator versions for {kind}; calibrate each version separately")
        total = len(rows) - extra[kind]
        scored = [row for row in rows if row["score"] is not None]
        bands = []
        for low, high in BANDS:
            band = [row for row in scored if low <= row["score"] < high]
            correct = sum(row["correct"] for row in band)
            bands.append({"min": low, "max": min(high, 1), "count": len(band),
                          "errors": len(band) - correct,
                          "exact_match_precision": correct / len(band) if band else None})
        tradeoffs = []
        for threshold in sorted({row["score"] for row in scored}):
            selected = [row for row in scored if row["score"] >= threshold]
            correct = sum(row["correct"] for row in selected)
            # Coverage excludes extra predictions, which still count as precision errors.
            covered = sum(not row.get("extra", False) for row in selected)
            tradeoffs.append({"threshold": threshold, "count": len(selected),
                              "correct": correct, "errors": len(selected) - correct,
                              "precision": correct / len(selected),
                              "coverage": covered / total if total else 0})
        eligible = [point for point in tradeoffs if point["count"] >= min_support and
                    point["precision"] >= target_precision]
        chosen = max(eligible, key=lambda point: (point["coverage"], -point["threshold"])) if eligible else None
        results[kind] = {"label_target_count": total, "extra_prediction_count": extra[kind],
                         "prediction_count": sum(row["emitted"] for row in rows),
                         "missing_or_abstained": sum(not row["emitted"] for row in rows),
                         "correct_abstentions": sum(row["correct_abstention"] for row in rows),
                         "unavailable_score_count": sum(row["emitted"] and row["score"] is None for row in rows),
                         "estimator": list(next(iter(methods[kind]))) if methods[kind] else None,
                         "bands": bands, "tradeoffs": tradeoffs, "review_priority_threshold": chosen}
    return {"case_count": len(truth), "missing_prediction_cases": len(set(truth) - set(predicted)),
            "policy": {"target_precision": target_precision, "min_support": min_support,
                       "authorized_acceptance_required": True}, "metrics": results}


def calibrate(labels_path: Path, predictions_path: Path, manifest_path: Path, *,
              review_policy="independent_human", authorization_path: Path | None = None,
              **policy) -> dict:
    labels, predictions = read_rows(labels_path), read_rows(predictions_path)
    manifest = json.loads(manifest_path.read_text())
    _index(labels)
    authorization = json.loads(authorization_path.read_text()) if authorization_path else None
    authorization_hash = digest(authorization_path) if authorization_path else None
    freeze_gate(manifest, labels, digest(labels_path), review_policy=review_policy,
                authorization=authorization, authorization_hash=authorization_hash)
    if manifest.get("predictions_sha256") != digest(predictions_path):
        raise ValueError("Predictions must match the frozen pre-scoring prediction hash")
    expected_policy = {"target_precision": policy.get("target_precision", .95),
                       "min_support": policy.get("min_support", 20)}
    if manifest.get("policy") != expected_policy:
        raise ValueError("Precision/support policy must match the frozen manifest")
    return {"version": VERSION,
            "status": "ai_assisted_validation_evidence" if review_policy == "owner_authorized_ai_assisted" else "reviewed_validation_evidence",
            "review_policy": review_policy,
            "hashes": {"labels": digest(labels_path), "predictions": digest(predictions_path),
                       "manifest": digest(manifest_path),
                       **({"authorization": authorization_hash} if authorization_hash else {})}, "review": manifest["review"],
            **assess(labels, predictions, **policy),
            "limitations": ["Review identity/independence are declared attestations, not verified by this tool.",
                            "Empirical validation precision is not a guarantee on new projects.",
                            "Field metrics weight targets; event/link metrics weight cases.",
                            "No holdout labels were read. No automatic acceptance is permitted."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("labels", "predictions", "manifest", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--target-precision", type=float, default=.95)
    parser.add_argument("--min-support", type=int, default=20)
    parser.add_argument("--review-policy", choices=("independent_human", "owner_authorized_ai_assisted"), default="independent_human")
    parser.add_argument("--authorization", type=Path)
    args = parser.parse_args()
    # Do not overwrite an evidence artifact or any input, even through a symlink.
    inputs = (args.labels, args.predictions, args.manifest) + ((args.authorization,) if args.authorization else ())
    if args.output.exists() or args.output.resolve() in {p.resolve() for p in inputs}:
        parser.error("Output must be a new artifact path")
    try:
        result = calibrate(args.labels, args.predictions, args.manifest,
                           review_policy=args.review_policy, authorization_path=args.authorization,
                           target_precision=args.target_precision, min_support=args.min_support)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
