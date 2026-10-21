"""Saved failed outputs and absent annotations must not earn quality credit."""
import pytest

from evaluation.metrics import evaluate
from evaluation.score_paired_pilot import fields_exact


@pytest.mark.parametrize('failure', [{'status': 'failed'}, {'state': 'failed'}, {'state': 'cancelled'}, {'failure': 'provider'}])
def test_failed_outputs_cannot_earn_any_success_credit(failure):
    event = {'event_type': 'actual_progress', 'work_date': '2026-10-20'}
    label = {'case_id': 'a', 'expected_mapping_state': 'suggested', 'expected_activity_ids': ['A'],
             'expected_scope': 'S', 'project_id': 'P', 'report_format': 'text',
             'expected_date_basis': 'report_date', 'expected_quantity': 2,
             'atomic_events': [{'expected_event_type': 'actual_progress', 'expected_work_date': '2026-10-20'}]}
    prediction = {'case_id': 'a', 'selected_activity_ids': ['A'], 'candidate_ids': ['A'],
                  'scope': 'S', 'quantity': 2, 'date_basis': 'report_date', 'atomic_events': [event], **failure}
    result = evaluate([label], [prediction])
    assert result['extraction']['true_positive'] == 0
    assert result['extraction']['false_negative'] == 1
    assert result['critical_fields']['date_basis']['correct'] == 0
    assert result['scope']['correct'] == 0
    assert result['project_weighted']['macro_project_exact_choice'] == 0
    assert result['project_weighted']['macro_project_coverage'] == 0
    assert result['initial_review_state']['field_correct'] == 0
    assert result['case_outcomes']['failed'] == 1


def test_missing_output_is_a_failure_even_with_nullable_gold():
    result = evaluate([{'case_id': 'a', 'expected_work_date': None}], [])
    assert result['critical_fields']['work_date']['correct'] == 0
    assert result['case_outcomes']['failed'] == 1
    assert result['initial_review_state']['cases'] == 0


@pytest.mark.parametrize('field,value,wrong', [('date_basis', 'report_date', 'explicit'),
                                             ('summary', 'Corrected yesterday to 4 m', '4 m'),
                                             ('evidence', {'quote': '4 m'}, {'quote': '8 m'})])
def test_optional_annotations_are_exact_when_explicit(field, value, wrong):
    base = dict(event_type='correction', work_date='2026-10-19', area=None,
                quantity=None, unit=None, quantity_kind='none')
    assert fields_exact([base], [{**base, field: wrong}])
    gold = [{**base, field: value}]
    assert fields_exact(gold, [{**base, field: value}])
    assert not fields_exact(gold, [base])
    assert not fields_exact(gold, [{**base, field: wrong}])
    with pytest.raises(ValueError, match='Inconsistent'):
        fields_exact([*gold, base], [*gold, base])


def test_explicit_date_basis_is_not_inferred_from_correct_work_date():
    label = {'case_id': 'a', 'expected_work_date': '2026-10-20', 'expected_date_basis': 'report_date'}
    result = evaluate([label], [{'case_id': 'a', 'work_date': '2026-10-20', 'date_basis': 'explicit'}])
    assert result['critical_fields']['work_date']['correct'] == 1
    assert result['critical_fields']['date_basis']['correct'] == 0


def test_repeated_event_types_align_by_full_tuple_and_preserve_multiplicity():
    from evaluation.score_paired_pilot import event_scores
    first = dict(event_type='actual_progress', work_date='2026-10-20', area='Zone A',
                 quantity='4', unit='m', quantity_kind='delta', asset_tags=['TR-001'],
                 date_basis='report_date', summary='Installed 4 m on TR-001')
    second = {**first, 'quantity': '8', 'asset_tags': ['TR-002'], 'summary': 'Installed 8 m on TR-002'}
    expected = [first, second, first]
    assert fields_exact(expected, [second, first, first])
    assert not fields_exact(expected, [second, first])
    assert not fields_exact(expected, [second, first, second])
    crossed = [{**first, 'quantity': '8'}, {**second, 'quantity': '4'}, first]
    assert not fields_exact(expected, crossed)
    # The coarse event diagnostic deliberately cannot detect cross-asset errors;
    # the full-field comparator must remain the gate for these labels.
    assert event_scores(expected, crossed)['complete']


def test_paired_failed_payload_matching_labels_does_not_earn_raw_exact(tmp_path):
    import json
    from hashlib import sha256
    from evaluation.paired_pilot import run
    from evaluation.score_paired_pilot import LABELS, score

    capture = tmp_path / 'capture'
    config = run(capture)
    trial = config['schedule'][0]
    observations = json.loads(LABELS.read_text())['cases'][trial['case_id']]
    identity = {'case_id': trial['case_id'], 'arm': trial['arm']}
    (capture / 'predictions.jsonl').write_text(json.dumps({**identity, 'state': 'failed',
                                                         'observations': observations}) + '\n')
    (capture / 'model-outputs.jsonl').write_text(json.dumps({**identity, 'value': {
        'observations': observations}}) + '\n')
    (capture / 'summary.json').write_text('{"completed": 0}')
    (capture / 'capture-manifest.json').write_text(json.dumps({
        path.name: sha256(path.read_bytes()).hexdigest() for path in capture.iterdir()
        if path.name != 'capture-manifest.json'}))
    result = score(capture)
    assert result['scheduled'] == len(config['schedule'])
    assert not any(case['raw_fields_exact'] or case['normalized_fields_exact'] for case in result['cases'])
