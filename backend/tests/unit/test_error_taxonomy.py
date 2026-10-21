from hashlib import sha256
import json

import pytest

from evaluation.error_taxonomy import diagnose, summarize_capture, STAGES


@pytest.mark.parametrize('stage', sorted(STAGES))
def test_all_required_failure_stages_are_named_without_claiming_root_cause(stage):
    assert diagnose(state='failed', stage=stage) == dict(
        outcome='failed', stage=stage, cause=stage, attribution='stage_only')


@pytest.mark.parametrize('status,cause,attribution', [
    (400, 'provider_rejection', 'underlying_cause_unknown'),
    (500, 'provider_rejection', 'underlying_cause_unknown'),
    (429, 'quota', 'http_status'), (401, 'provider_access', 'http_status'),
])
def test_http_failure_overrides_success_claim_but_does_not_invent_cause(status, cause, attribution):
    result = diagnose(state='completed', stage='extraction', http_status=status)
    assert result['outcome'] == 'failed'
    assert (result['cause'], result['attribution']) == (cause, attribution)


def test_unknown_or_private_signals_never_become_exported_diagnosis():
    result = diagnose(state='failed', stage='PRIVATE SOURCE', error_code='SECRET TOKEN', http_status=True)
    assert result == dict(outcome='failed', stage='unknown', cause='unknown', attribution='unknown')
    assert 'PRIVATE' not in json.dumps(result) and 'SECRET' not in json.dumps(result)


def test_success_does_not_claim_semantic_quality_and_unattempted_is_separate():
    assert diagnose(state='completed', stage='selection')['cause'] == 'not_assessed'
    assert diagnose(state='unattempted', http_status=429)['outcome'] == 'unattempted'
    assert diagnose(state='failed', error_code='MODEL_QUOTA_EXHAUSTED')['cause'] == 'quota'


def bundle(tmp_path):
    schedule = [dict(trial_id=f'T{i}') for i in range(3)]
    data = {'config.json': dict(schedule=schedule), 'summary.json': {}, 'preflight.json': {}}
    for name, value in data.items():
        (tmp_path / name).write_text(json.dumps(value))
    (tmp_path / 'predictions.jsonl').write_text('\n'.join(json.dumps(row) for row in [
        dict(trial_id='T0', state='completed'), dict(trial_id='T1', state='failed')]))
    (tmp_path / 'usage.jsonl').write_text(json.dumps(dict(trial_id='T1', status=400)))
    seal(tmp_path)
    return tmp_path


def seal(path):
    (path / 'capture-manifest.json').write_text(json.dumps({
        p.name: sha256(p.read_bytes()).hexdigest() for p in path.iterdir()
        if p.name != 'capture-manifest.json'}))


def test_sealed_capture_keeps_all_denominators_and_rejection_unknown(tmp_path):
    result = summarize_capture(bundle(tmp_path))
    assert result['scheduled'] == 3 and result['attempted'] == 2
    assert result['outcome_counts'] == dict(completed=1, failed=1, unattempted=1)
    assert result['failure_causes'] == dict(provider_rejection=1)
    assert not result['release_accepted']


def test_modified_original_fails_seal(tmp_path):
    capture = bundle(tmp_path)
    (capture / 'predictions.jsonl').write_text('[]')
    with pytest.raises(ValueError, match='integrity'):
        summarize_capture(capture)


@pytest.mark.parametrize('kind', ['duplicate', 'unscheduled'])
def test_resealed_duplicate_or_unscheduled_rows_are_not_double_counted(tmp_path, kind):
    capture = bundle(tmp_path)
    with (capture / 'predictions.jsonl').open('a') as stream:
        stream.write('\n' + json.dumps(dict(trial_id='T0' if kind == 'duplicate' else 'OTHER', state='completed')))
    seal(capture)
    with pytest.raises(ValueError, match='Duplicate or unscheduled'):
        summarize_capture(capture)


@pytest.mark.parametrize('category,cause', [
    ('incomplete_output', 'incomplete_output'), ('model_refusal', 'model_refusal'),
    ('native_schema_invalid', 'schema_validation'), ('domain_schema_invalid', 'schema_validation'),
    ('application_validation', 'application_validation'),
])
def test_explicit_content_diagnostics_are_used_without_raw_error_text(category, cause):
    result = diagnose(state='failed', failure_category=category)
    assert (result['cause'], result['attribution']) == (cause, 'explicit_category')


def test_capacity_timeout_does_not_prove_provider_quota_exhaustion():
    assert diagnose(state='failed', error_code='MODEL_CAPACITY_TIMEOUT')['cause'] == 'admission_capacity'


def test_resealed_unscheduled_stage_call_is_rejected(tmp_path):
    capture = bundle(tmp_path)
    (capture / 'calls.jsonl').write_text(json.dumps(dict(case_id='UNSCHEDULED', arm='unknown', ok=False)))
    seal(capture)
    with pytest.raises(ValueError, match='Unscheduled stage call'):
        summarize_capture(capture)
