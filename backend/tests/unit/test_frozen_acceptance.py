import json

import pytest

from evaluation.frozen_acceptance import digest, load_inputs


def fixture(tmp_path, *, expected=False, leak=False):
    inputs, manifest = tmp_path / "inputs.jsonl", tmp_path / "manifest.json"
    row = {"case_id": "A", "group_id": "project-a", "split": "validation", "text": "work"}
    if expected:
        row["activities"] = [{"expected_activity": "answer must never enter capture"}]
    inputs.write_text(json.dumps(row) + "\n")
    manifest.write_text(json.dumps({"status": "frozen_inputs_and_ai_labels",
        "hashes": {inputs.name: digest(inputs)}, "splits": {
            "development": [], "train": [], "validation": [{"case_id": "A", "group_id": "project-a"}],
            "holdout": [{"case_id": "B", "group_id": "project-a" if leak else "project-b"}]}}))
    return inputs, manifest


def test_frozen_capture_rejects_nested_answers_even_with_matching_hash(tmp_path):
    inputs, manifest = fixture(tmp_path, expected=True)
    with pytest.raises(ValueError, match="no expected labels"):
        load_inputs(inputs, manifest, "validation")


def test_frozen_capture_rejects_project_leakage(tmp_path):
    inputs, manifest = fixture(tmp_path, leak=True)
    with pytest.raises(ValueError, match="leakage"):
        load_inputs(inputs, manifest, "validation")


def test_frozen_capture_requires_exact_bytes_and_complete_inventory(tmp_path):
    inputs, manifest = fixture(tmp_path)
    assert len(load_inputs(inputs, manifest, "validation")) == 1
    inputs.write_text(inputs.read_text() + "\n")
    with pytest.raises(ValueError, match="frozen input"):
        load_inputs(inputs, manifest, "validation")
