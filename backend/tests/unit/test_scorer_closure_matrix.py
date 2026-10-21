"""Known-answer checks across public saved-output scoring entry points."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from evaluation.metrics import evaluate
from evaluation.score_frozen_acceptance import actual_targets, unmasked_targets
from evaluation.score_paired_pilot import fields_exact, score as score_paired
from evaluation.score_repeated_development import score as score_repeated


EVENT = dict(event_type='actual_progress', work_date='2026-10-21', area=None,
             quantity='3', unit='m', quantity_kind='delta')
CHECKS = dict(response_complete=True, refusal_present=False, wire_schema_valid=True,
              raw_domain_schema_valid=True)


def seal(capture):
    (capture / 'capture-manifest.json').write_text(json.dumps({
        p.name: sha256(p.read_bytes()).hexdigest() for p in capture.iterdir()
        if p.name != 'capture-manifest.json'}))


def fixture(tmp_path, *, repeated, failure):
    labels = tmp_path / 'labels.json'
    lineage = tmp_path / 'lineage.json'
    labels.write_text(json.dumps({'cases': {'a': [EVENT]}}))
    lineage.write_text(json.dumps({'cases': {'a': {'group_id': 'P'}}}))
    trial = dict(case_id='a', arm='baseline', model='test-model')
    if repeated:
        trial.update(trial_id='a:baseline:1', repetition=1, strict=False)
    config = dict(schedule=[trial], prompts={'baseline': 'test'},
                  label_sha256=sha256(labels.read_bytes()).hexdigest(),
                  source_sha256={str(p): sha256(p.read_bytes()).hexdigest() for p in (labels, lineage)})
    capture = tmp_path / 'capture'
    capture.mkdir()
    row = dict(**trial, state='completed', response_checks=CHECKS, observations=[EVENT])
    row.update(failure)
    files = {'config.json': config, 'summary.json': {}, 'preflight.json': {},
             'predictions.jsonl': row,
             'model-outputs.jsonl': {**trial, 'value': {'observations': [EVENT]}}}
    for name, value in files.items():
        (capture / name).write_text(json.dumps(value) + '\n')
    seal(capture)
    return capture, labels, lineage


@pytest.mark.parametrize('repeated', [False, True])
@pytest.mark.parametrize('failure', [{'state': 'failed'}, {'status': 'failed'},
                                    {'failure': 'provider_error'}, {'state': 'cancelled'}])
def test_failed_diagnostic_events_never_earn_normalized_event_credit(tmp_path, repeated, failure):
    capture, labels, lineage = fixture(tmp_path, repeated=repeated, failure=failure)
    result = score_repeated(capture, labels, lineage) if repeated else score_paired(capture, labels)
    detail = result['trials'][0] if repeated else result['cases'][0]
    events = detail['normalized_events'] if repeated else detail['normalized']
    assert not detail['completed']
    assert not detail['normalized_fields_exact']
    assert events == dict(true_positive=0, false_positive=0, false_negative=1, complete=False)
    # Independent initial observations remain available for diagnostics.
    assert (detail['raw_events'] if repeated else detail['raw'])['true_positive'] == 1


def test_paired_duplicate_schedule_is_rejected_instead_of_multiplying_support(tmp_path):
    capture, labels, _ = fixture(tmp_path, repeated=False, failure={})
    config = json.loads((capture / 'config.json').read_text())
    config['schedule'] *= 2
    (capture / 'config.json').write_text(json.dumps(config))
    seal(capture)
    with pytest.raises(ValueError, match='Duplicate'):
        score_paired(capture, labels)


@pytest.mark.parametrize('key', ['area', 'quantity', 'unit', 'work_date'])
def test_frozen_missing_fields_do_not_match_explicit_null_targets(key):
    complete = {**EVENT, key: None}
    missing = {k: v for k, v in complete.items() if k != key}
    assert actual_targets(complete, {})['field:' + key] is None
    assert 'field:' + key not in actual_targets(missing, {})


def test_frozen_missing_endpoint_fields_do_not_match_nullable_endpoints():
    expected = {'endpoint': {'local_date': '2026-10-21', 'local_time': None, 'precision': 'day'}}
    event = {**EVENT, 'lifecycle_effects': [{'endpoint': {'local_date': '2026-10-21'}}]}
    targets = actual_targets(event, expected)
    assert targets['field:endpoint_local_date'] == '2026-10-21'
    assert 'field:endpoint_local_time' not in targets
    assert 'field:endpoint_precision' not in targets
    calibration = unmasked_targets(event)
    assert 'field:endpoint_local_time' not in calibration
    assert 'field:endpoint_precision' not in calibration


@pytest.mark.parametrize('change,expected', [
    ({}, (1, 0, 0, 1)),
    ({'selected_activity_id': 'INVENTED'}, (1, 0, 0, 0)),
    ({'atomic_events': []}, (0, 0, 1, 1)),
    ({'atomic_events': [dict(event_type='actual_progress', quantity='3')] * 2}, (1, 1, 0, 1)),
    ({'quantity': 'null'}, (1, 0, 0, 1)),
])
def test_general_known_answer_matrix(change, expected):
    label = dict(case_id='a', expected_mapping_state='suggested', expected_activity_ids=['A'],
                 expected_quantity=None, atomic_events=[
                     dict(expected_event_type='actual_progress', expected_quantity='3')])
    prediction = dict(case_id='a', selected_activity_id='A', quantity=None,
                      atomic_events=[dict(event_type='actual_progress', quantity='3')])
    prediction.update(change)
    result = evaluate([label], [prediction])
    extraction = result['extraction']
    assert (extraction['true_positive'], extraction['false_positive'], extraction['false_negative'],
            result['selection']['selected_precision']) == expected
    assert result['critical_fields']['quantity']['correct'] == int(change.get('quantity') != 'null')


def test_whole_event_alignment_never_cherry_picks_fields_between_repeated_types():
    first = {**EVENT, 'asset_tags': ['TR-001']}
    second = {**EVENT, 'asset_tags': ['TR-002'], 'quantity': '8'}
    gold = [first, second, first]
    assert fields_exact(gold, [first, first, second])
    crossed = [deepcopy(first), deepcopy(second), deepcopy(first)]
    crossed[0]['quantity'], crossed[1]['quantity'] = '8', '3'
    assert not fields_exact(gold, crossed)


@pytest.mark.parametrize('repeated', [False, True])
@pytest.mark.parametrize('failure', [{}, {'state': 'failed'}])
def test_explicit_empty_no_event_results_are_distinct_from_failed_empty_outputs(tmp_path, repeated, failure):
    capture, labels, lineage = fixture(tmp_path, repeated=repeated, failure=failure)
    labels.write_text(json.dumps({'cases': {'a': []}}))
    config = json.loads((capture / 'config.json').read_text())
    config['label_sha256'] = config['source_sha256'][str(labels)] = sha256(labels.read_bytes()).hexdigest()
    (capture / 'config.json').write_text(json.dumps(config))
    for name in ('predictions.jsonl', 'model-outputs.jsonl'):
        row = json.loads((capture / name).read_text())
        if name.startswith('predictions'):
            row['observations'] = []
        else:
            row['value']['observations'] = []
        (capture / name).write_text(json.dumps(row) + '\n')
    seal(capture)
    result = score_repeated(capture, labels, lineage) if repeated else score_paired(capture, labels)
    detail = result['trials'][0] if repeated else result['cases'][0]
    events = detail['normalized_events'] if repeated else detail['normalized']
    assert detail['normalized_fields_exact'] == (not failure)
    assert events['complete'] == (not failure)
    if not failure:
        assert detail['raw_fields_exact']
