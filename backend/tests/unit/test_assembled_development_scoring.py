from hashlib import sha256
import json

import pytest

from evaluation.assembled_development import prepare
from evaluation.summarize_assembled_development import summarize


def bundle(tmp_path, *, wrong_location=False, duplicate=False):
    prepared, capture = tmp_path/'prepared', tmp_path/'capture'
    plan = prepare(prepared)
    capture.mkdir()
    row = dict(**plan['schedule'][0], state='ready_for_review', mapping_states=['suggested'],
               selected_activity_ids=['EXC-CEDAR'], ledger_writes=0, review_states=['pending'], elapsed_ms=10,
               observations=[dict(event_type='actual_progress', quantity='5', quantity_kind='delta', unit='m3',
                                  work_date='2026-10-20', area='invented' if wrong_location else 'Zone Cedar', asset_tags=['TR-030'])],
               full_case_score={'full_report_exact': True})  # Scorer must recompute instead of trusting this claim.
    data = {'config.json':{**plan,'execution_mode':'injected_transport'},'summary.json':{},'preflight.json':{}}
    for name,value in data.items():
        (capture/name).write_text(json.dumps(value))
    (capture/'reports.jsonl').write_text((json.dumps(row)+'\n')*(2 if duplicate else 1))
    (capture/'capture-manifest.json').write_text(json.dumps({p.name:sha256(p.read_bytes()).hexdigest() for p in capture.iterdir()}))
    return prepared,capture


def test_missing_reports_remain_in_planned_quality_and_ambiguity_denominators(tmp_path):
    prepared,capture=bundle(tmp_path)
    result=summarize(capture,prepared)
    assert result['scheduled']==4
    assert result['arms']['deterministic']['scheduled']==2
    assert result['arms']['deterministic']['scoped_report_exact']==1
    assert result['arms']['model_assisted']['attempted']==0
    assert result['arms']['model_assisted']['expected_link_case_coverage']==0
    assert result['arms']['model_assisted']['selected_link_precision'] is None
    assert all(arm['ambiguity_cases']==1 and arm['ambiguity_successes']==0 for arm in result['arms'].values())
    assert not result['release_accepted']


def test_matching_selected_activity_does_not_hide_invented_fact_or_stored_success_claim(tmp_path):
    prepared,capture=bundle(tmp_path,wrong_location=True)
    result=summarize(capture,prepared)
    assert result['arms']['deterministic']['selected_link_precision']==1
    assert result['arms']['deterministic']['scoped_report_exact']==0


def test_duplicate_report_cannot_inflate_coverage_even_if_capture_is_resealed(tmp_path):
    prepared,capture=bundle(tmp_path,duplicate=True)
    with pytest.raises(ValueError,match='Duplicate'):
        summarize(capture,prepared)


def test_changed_capture_and_frozen_labels_fail_integrity_checks(tmp_path):
    prepared,capture=bundle(tmp_path)
    original=(capture/'reports.jsonl').read_text()
    (capture/'reports.jsonl').write_text(original+'\n')
    with pytest.raises(ValueError,match='integrity'):
        summarize(capture,prepared)
    (capture/'reports.jsonl').write_text(original)
    (prepared/'labels.json').write_text('{}')
    with pytest.raises(ValueError,match='fixture'):
        summarize(capture,prepared)


def test_legacy_capture_without_scope_is_identified_without_expanding_its_claim(tmp_path):
    prepared,capture=bundle(tmp_path)
    config=json.loads((capture/'config.json').read_text())
    config.pop('metric_scope')
    (capture/'config.json').write_text(json.dumps(config))
    manifest=json.loads((capture/'capture-manifest.json').read_text())
    manifest['config.json']=sha256((capture/'config.json').read_bytes()).hexdigest()
    (capture/'capture-manifest.json').write_text(json.dumps(manifest))
    result=summarize(capture,prepared)
    assert 'Historical capture' in result['metric_scope']
    assert not result['release_accepted']
