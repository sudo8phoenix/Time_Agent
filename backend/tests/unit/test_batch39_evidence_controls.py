"""Conservative cache, exposure and near-duplicate evidence boundaries."""

from hashlib import sha256
import json

import pytest

from evaluation.cache_capture_audit import audit, usage_cache
from evaluation.capture_inventory import inventory
from evaluation.content_overlap import cross_split_candidates, fingerprint
from evaluation.fresh_dataset_preflight import check, known_exposure


@pytest.mark.parametrize("usage,status", [
    (None, "missing"), ({"prompt_tokens": 100}, "missing"),
    ({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 0}}, "explicit_zero"),
    ({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 90}}, "hit"),
    ({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": True}}, "invalid"),
    ({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 101}}, "invalid"),
    ({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": -1}}, "invalid"),
    ({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": "90"}}, "invalid"),
])
def test_cache_unknown_zero_hit_and_invalid_remain_distinct(usage, status):
    assert usage_cache(usage)["status"] == status


def cache_fixture(tmp_path, *, mode="live_groq"):
    payload = dict(model="fixture/model", messages=[
        dict(role="system", content="Stable instructions"), dict(role="user", content="Variable source")])
    (tmp_path / "config.json").write_text(json.dumps(dict(execution_mode=mode)))
    (tmp_path / "requests.jsonl").write_text(json.dumps(dict(id="a", payload=payload)) + "\n")
    (tmp_path / "calls.jsonl").write_text(json.dumps(dict(id="a", status=200,
        returned_model="fixture/model", usage=dict(
        prompt_tokens=100, prompt_tokens_details=dict(cached_tokens=90)))) + "\n")
    (tmp_path / "capture-manifest.json").write_text(json.dumps({
        p.name: sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}))


def test_verified_cache_hit_does_not_certify_parallel_cold_starts(tmp_path):
    cache_fixture(tmp_path)
    result = audit(tmp_path)
    assert result["cached_tokens"] == 90 and result["explicit_cache_telemetry_calls"] == 1
    assert result["new_provider_calls"] == 0 and not result["release_accepted"]


def test_modified_cache_capture_rejected_before_metrics(tmp_path):
    cache_fixture(tmp_path)
    (tmp_path / "calls.jsonl").write_text("{}")
    with pytest.raises(ValueError, match="seal"):
        audit(tmp_path)


@pytest.mark.parametrize("field,value", [("status", 503), ("returned_model", "other/model")])
def test_failed_or_substituted_response_cannot_earn_cache_hit_credit(tmp_path, field, value):
    cache_fixture(tmp_path)
    path = tmp_path / "calls.jsonl"
    row = json.loads(path.read_text())
    row[field] = value
    path.write_text(json.dumps(row) + "\n")
    manifest = json.loads((tmp_path / "capture-manifest.json").read_text())
    manifest[path.name] = sha256(path.read_bytes()).hexdigest()
    (tmp_path / "capture-manifest.json").write_text(json.dumps(manifest))
    result = audit(tmp_path)
    assert result["explicit_cache_telemetry_calls"] == result["cached_tokens"] == 0
    assert result["telemetry_counts"] == {"unverified_response": 1}


@pytest.mark.parametrize("mode", [None, "injected_transport"])
def test_injected_or_unknown_transport_cannot_be_live_cache_evidence(tmp_path, mode):
    cache_fixture(tmp_path, mode=mode)
    with pytest.raises(ValueError, match="live capture"):
        audit(tmp_path)


def test_invalid_utf8_capture_is_quarantined_without_losing_other_exposure(tmp_path):
    (tmp_path / "calls.jsonl").write_bytes(b"\xff private source")
    (tmp_path / "reports.jsonl").write_text('{"case_id":"known-consumed"}\n')
    result = inventory(tmp_path)
    assert result["capture_count"] == 2 and result["unique_case_id_count"] == 1
    assert sum(bool(r["errors"]) for r in result["captures"]) == 1
    assert "private" not in json.dumps(result)


def test_case_and_punctuation_variant_crossing_splits_is_a_review_candidate():
    result = cross_split_candidates([
        dict(case_id="a", split="validation", fingerprint=fingerprint("Excavated 4 m3 today!")),
        dict(case_id="b", split="holdout", fingerprint=fingerprint("EXCAVATED 4 m3 today.")),
    ])
    assert len(result["candidates"]) == 1
    assert not result["candidates"][0]["lineage_confirmed"]


def test_minor_wording_change_on_long_report_is_quarantined_for_review():
    source = "The civil contractor excavated trench TR-001 in the northern site area today and removed all spoil to the approved temporary stockpile beside the access road"
    result = cross_split_candidates([
        dict(case_id="a", split="development", fingerprint=fingerprint(source)),
        dict(case_id="b", split="holdout", fingerprint=fingerprint(source.replace("temporary", "designated"))),
    ])
    assert len(result["candidates"]) == 1


def test_numbers_and_ids_are_not_erased_from_fingerprints():
    assert fingerprint("4 m3 TR-001") != fingerprint("400 m3 TR-0010")


def test_consumed_development_reuse_is_allowed_but_holdout_reuse_is_flagged():
    known = [dict(case_id="old", split="consumed", fingerprint=fingerprint("Excavated 4 m3 today."))]
    row = dict(case_id="new", split="development", fingerprint=known[0]["fingerprint"])
    assert not cross_split_candidates([row], known)["candidates"]
    row["split"] = "holdout"
    assert cross_split_candidates([row], known)["candidates"]


def test_oversized_source_or_comparison_pool_cannot_silently_skip_screening():
    with pytest.raises(ValueError):
        fingerprint("x" * 200001)
    with pytest.raises(ValueError):
        cross_split_candidates([{}] * 2001)


def test_real_preflight_consumer_rejects_renamed_punctuation_variant(tmp_path):
    from backend.tests.unit.test_fresh_dataset_preflight import bundle, row

    inputs, lineage = tmp_path / "old-inputs.json", tmp_path / "lineage.json"
    inputs.write_text(json.dumps([dict(case_id="old", text="Excavated 4 m3 today!")]))
    lineage.write_text(json.dumps(dict(cases={"old": dict(group_id="old-family")})))
    known = known_exposure(inputs, lineage)
    paths = bundle(tmp_path, [row("renamed", "renamed-family", "holdout", "EXCAVATED 4 m3 today.")])
    result = check(*(paths[k] for k in ("manifest", "inputs", "labels", "review", "configuration")), known)
    assert "cross_split_near_duplicate_requires_review" in result["failures"]
    assert not result["structurally_eligible"] and not result["labels_read"]
