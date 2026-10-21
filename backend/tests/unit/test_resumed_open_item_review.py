"""Prevent partial or altered resumed evidence from becoming completed results."""
from hashlib import sha256
import json

import pytest

from evaluation.open_item_review import review, verify_capture


def test_owner_resume_still_rejects_an_interrupted_capture_before_outcome_parsing(tmp_path):
    batch, resumed = tmp_path/'old', tmp_path/'resumed'
    records = {
        batch/'prepared/plan.json': {},
        batch/'live/summary.json': {'stop_reason': 'Provider HTTP 400'},
        batch/'continuation-live-v2/summary.json': {'stop_reason': 'KeyboardInterrupt'},
        resumed/'summary.json': {'stop_reason': 'KeyboardInterrupt'},
    }
    for path, value in records.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    output = tmp_path/'review.json'
    with pytest.raises(ValueError, match='completed continuation required'):
        review(batch, output, resumed=resumed)
    assert not output.exists()


def test_changed_retained_capture_rejects_before_parsing_poisoned_rows(tmp_path):
    path = tmp_path/'calls.jsonl'
    original = b'{"id":"original","status":400}\n'
    path.write_bytes(original)
    (tmp_path/'capture-manifest.json').write_text(json.dumps({
        'calls.jsonl': sha256(original).hexdigest()}))
    path.write_text('not JSON; original failure must not be replaced')
    with pytest.raises(ValueError, match='Changed capture'):
        verify_capture(tmp_path)
