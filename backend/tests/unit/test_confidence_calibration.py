"""Safety gates and precision/coverage denominators, using developer fixtures only."""
import json
import pytest
from evaluation.calibrate import assess, calibrate, digest
from app.confidence.provenance import capture


def fixture(tmp_path):
    labels = [{"case_id": "a", "group_id": "validation-project", "review_status": "independently_reviewed",
               "targets": {"event": "start", "link": "A", "field:date": "2026-01-02"}},
              {"case_id": "b", "group_id": "validation-project", "review_status": "independently_reviewed",
               "targets": {"event": "finish", "link": "B", "field:date": "2026-01-03"}}]
    score = {"score": .9, "method": "fixture", "version": "v1"}
    predictions = [{"case_id": "a", "targets": labels[0]["targets"],
                    "confidence": {"extraction": score, "linking": score}},
                   {"case_id": "b", "targets": {"event": "start", "link": "B"},
                    "confidence": {"extraction": {**score, "score": .4}, "linking": score}}]
    lp, pp, mp = (tmp_path / name for name in ("labels.jsonl", "predictions.jsonl", "manifest.json"))
    for path, rows in ((lp, labels), (pp, predictions)):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest = {"status": "frozen", "labels_sha256": digest(lp), "predictions_sha256": digest(pp),
                "group_review_status": "independently_reviewed",
                "policy": {"target_precision": .95, "min_support": 1},
                "review": {"status": "independently_reviewed", "kind": "human",
                           "reviewer_id": "fixture-reviewer", "reviewed_at": "2026-01-01",
                           "label_authors": ["fixture-author"], "attestation": "TEST ONLY"},
                "splits": {"development": [], "train": [],
                           "validation": [{"case_id": row["case_id"], "group_id": row["group_id"]} for row in labels],
                           "holdout": [{"case_id": "secret", "group_id": "holdout-project"}]}}
    mp.write_text(json.dumps(manifest))
    return lp, pp, mp, manifest


def test_no_probability_inferred_from_strong_link_or_quote():
    record = capture({"evidence": [{"quote": "Finished", "fragment_id": "f"}], "warnings": ["missing date"]},
                     {"match_strength": "strong"})
    assert all(item["score"] is None for item in record["confidence"].values())
    assert record["validation"]["status"] == "requires_authorized_review"
    assert record["validation"]["field_issues"][0]["code"] == "missing date"


def test_thresholds_and_missing_fields(tmp_path):
    lp, pp, mp, _ = fixture(tmp_path)
    result = calibrate(lp, pp, mp, min_support=1)
    assert result["metrics"]["event"]["review_priority_threshold"]["threshold"] == .9
    assert result["metrics"]["event"]["review_priority_threshold"]["coverage"] == .5
    assert result["metrics"]["field"]["missing_or_abstained"] == 1
    assert result["policy"]["authorized_acceptance_required"]
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("mutation", ["unreviewed", "author", "ai", "hash", "group", "leak"])
def test_review_and_split_gates(tmp_path, mutation):
    lp, pp, mp, manifest = fixture(tmp_path)
    if mutation == "unreviewed":
        manifest["review"]["status"] = "pending"
    if mutation == "author":
        manifest["review"]["label_authors"] = ["fixture-reviewer"]
    if mutation == "ai":
        manifest["review"]["kind"] = "ai"
    if mutation == "hash":
        manifest["labels_sha256"] = "changed"
    if mutation == "group":
        manifest["group_review_status"] = "pending"
    if mutation == "leak":
        manifest["splits"]["holdout"][0]["group_id"] = "validation-project"
    mp.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        calibrate(lp, pp, mp)


def test_unavailable_scores_and_missing_cases_are_counted():
    labels = [{"case_id": "a", "targets": {"event": "start"}}, {"case_id": "b", "targets": {"event": "finish"}}]
    result = assess(labels, [{"case_id": "a", "targets": {"event": "start"}}])
    assert result["metrics"]["event"]["unavailable_score_count"] == 1
    assert result["missing_prediction_cases"] == 1
    assert result["metrics"]["event"]["review_priority_threshold"] is None


def test_extra_prediction_is_error_not_free_coverage():
    labels = [{"case_id": "a", "targets": {"field:date": "today"}}]
    score = {"score": .9, "method": "fixture", "version": "v1"}
    result = assess(labels, [{"case_id": "a", "targets": {"field:date": "today", "field:time": "08:00"},
                             "confidence": {"extraction": score}}], min_support=1)
    field = result["metrics"]["field"]
    assert field["tradeoffs"][0]["precision"] == .5
    assert field["tradeoffs"][0]["coverage"] == 1
    assert field["review_priority_threshold"] is None


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -.1, 1.1, True])
def test_invalid_scores_rejected(score):
    with pytest.raises(ValueError):
        assess([{"case_id": "a", "targets": {"event": "start"}}],
               [{"case_id": "a", "targets": {"event": "start"},
                 "confidence": {"extraction": {"score": score, "method": "fixture", "version": "v1"}}}])


def test_prediction_hash_and_policy_are_frozen(tmp_path):
    lp, pp, mp, manifest = fixture(tmp_path)
    with pytest.raises(ValueError, match="policy"):
        calibrate(lp, pp, mp, min_support=2)
    pp.write_text(pp.read_text() + "\n")
    with pytest.raises(ValueError, match="prediction hash"):
        calibrate(lp, pp, mp, min_support=1)


def test_mixed_estimators_and_unknown_cases_rejected(tmp_path):
    lp, pp, _, _ = fixture(tmp_path)
    labels = [json.loads(line) for line in lp.read_text().splitlines()]
    predictions = [json.loads(line) for line in pp.read_text().splitlines()]
    predictions[1]["confidence"]["extraction"]["version"] = "v2"
    with pytest.raises(ValueError, match="Mixed estimator"):
        assess(labels, predictions)
    with pytest.raises(ValueError, match="unknown cases"):
        assess(labels, [{"case_id": "holdout", "targets": {}}])
