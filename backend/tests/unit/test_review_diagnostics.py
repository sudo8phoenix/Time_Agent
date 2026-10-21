"""Observable review diagnostics with controlled, labelled negative controls."""
from copy import deepcopy
import json
import sys

import pytest

from app.confidence.provenance import capture
from evaluation.review_diagnostics import review_signals, probability_diagnostics, escalation_diagnostics, main


def row(identity, correct, **updates):
    return dict(case_id=identity, correct=correct, state='completed', **updates)


def test_conf02_actual_provenance_signals_remain_observable_not_probabilities():
    audit = capture({'evidence': [], 'warnings': ['Conflicting source dates.']},
                    {'mapping_state': 'ambiguous', 'missing_information': ['Which date?']})
    bad = row('bad', False, provenance=audit, validator_state='invalid')
    good = row('good', True, provenance=capture({'evidence': [{'quote': 'Installed'}]}, {}))
    snapshot = deepcopy([bad, good])
    result = review_signals([bad, good])
    for name in ['missing_evidence', 'missing_information', 'field_issues', 'ambiguous_candidates', 'validator_failed']:
        assert result['signals'][name] == dict(count=1, errors=1, error_rate=1)
    assert result['overall'] == dict(count=2, errors=1, error_rate=.5)
    assert not result['probabilities_inferred'] and not result['thresholds_fitted']
    assert all(v['score'] is None for v in audit['confidence'].values())
    assert [bad, good] == snapshot


def test_signal_presence_can_coexist_with_correct_answer_and_absence_with_error():
    flagged = row('flagged-correct', True, provenance=capture({'warnings': ['Missing optional date']}, {}))
    unflagged = row('unflagged-wrong', False, provenance=capture({'evidence': [{'quote': 'Work'}]}, {}))
    result = review_signals([flagged, unflagged])
    assert result['signals']['field_issues']['error_rate'] == 0
    assert result['overall']['error_rate'] == .5
    assert result['release_accepted'] is False


def test_failed_output_cannot_receive_correctness_credit_from_diagnostic_gold():
    failed = {**row('failed', True, provenance=capture({}, {})), 'state': 'failed'}
    result = review_signals([failed])
    assert result['signals']['failed_or_missing_output']['errors'] == 1
    assert result['overall']['errors'] == 1


def probability_row(identity, correct, p):
    return row(identity, correct, probability=p, probability_kind='correctness_probability',
               estimator={'method': 'test-only-declared-estimator', 'version': 'v1'})


def test_conf04_brier_reliability_bins_and_precision_coverage_known_answer():
    rows = [probability_row('a', True, .8), probability_row('b', False, .2),
            probability_row('c', False, .9), row('unavailable', False)]
    result = probability_diagnostics(rows)
    assert result['brier'] == pytest.approx((.04+.04+.81)/3)
    assert result['scored_count'] == 3 and result['unavailable_count'] == 1
    assert result['calibration_bins'][0]['error_rate'] == 1
    assert result['calibration_bins'][2]['observed_correct_fraction'] == 1
    assert result['calibration_bins'][3]['mean_probability'] == .9
    assert result['precision_coverage'][-1] == dict(threshold=.9, count=1, precision=0, coverage=.25)
    assert not result['thresholds_fitted']


def test_production_missing_probabilities_do_not_become_zero_or_strength_scores():
    audit = capture({'evidence': [{'quote': 'Installed'}]}, {'match_strength': 'strong'})
    records = [row('production', True, probability=audit['confidence']['linking']['score'])]
    result = probability_diagnostics(records)
    assert result['brier'] is None and result['scored_count'] == 0
    assert result['unavailable_count'] == 1
    assert result['precision_coverage'] == []
    assert all(band['error_rate'] is None for band in result['calibration_bins'])


def test_failed_probability_is_excluded_from_brier_but_not_coverage_denominator():
    rows = [probability_row('a', True, 1), {**probability_row('b', True, 1), 'state': 'failed'}]
    result = probability_diagnostics(rows)
    assert result['brier'] == 0
    assert result['failed_probability_count'] == 1
    assert result['precision_coverage'][0]['coverage'] == .5


@pytest.mark.parametrize('probability', [True, -1, 2, float('nan'), float('inf')])
def test_invalid_probabilities_fail_closed(probability):
    with pytest.raises(ValueError):
        probability_diagnostics([probability_row('a', True, probability)])


@pytest.mark.parametrize('method', ['not_estimated', 'match_strength', 'model_reported_strength', 'quote_check'])
def test_nonprobability_signals_cannot_be_used_for_brier(method):
    record = probability_row('a', True, .9)
    record['estimator']['method'] = method
    with pytest.raises(ValueError):
        probability_diagnostics([record])


def test_estimator_version_mixture_rejected():
    first, second = probability_row('a', True, .9), probability_row('b', False, .9)
    second['estimator']['version'] = 'v2'
    with pytest.raises(ValueError):
        probability_diagnostics([first, second])


def pair(identity, before, after, **resources):
    return dict(case_id=identity, before=row(identity, before),
                after=row(identity, after) if after is not None else None,
                additional_resources=resources)


def test_conf08_count_fixed_harmed_unchanged_and_missing_and_charge_every_attempt():
    pairs = [pair('fixed', False, True, calls=1, tokens=100, latency_ms=5, cost_usd=.01),
             pair('harmed', True, False, calls=1, tokens=100, latency_ms=7, cost_usd=.02),
             pair('good', True, True, calls=1, tokens=50, latency_ms=3, cost_usd=.01),
             pair('bad', False, False, calls=1, tokens=50, latency_ms=3, cost_usd=.01),
             pair('missing', True, None, calls=1, tokens=None, latency_ms=10)]
    before = deepcopy(pairs)
    result = escalation_diagnostics(pairs)
    assert result['errors_fixed'] == 1 and result['errors_introduced'] == 2
    assert result['net_errors_reduced'] == -1
    assert result['outcomes']['missing_review'] == 1
    assert result['known_additional_resources']['calls'] == 5
    assert result['known_additional_resources']['tokens'] == 300
    assert result['complete_additional_resources']['tokens'] is None
    assert result['unknown_measurement_counts']['tokens'] == 1
    assert pairs == before


def test_failed_review_cannot_overwrite_original_error_or_receive_gold_credit():
    record = pair('failed', False, True, calls=1, tokens=10, latency_ms=8, cost_usd=.01)
    record['after']['state'] = 'failed'
    result = escalation_diagnostics([record])
    assert result['errors_fixed'] == 0
    assert result['outcomes']['unchanged_error'] == 1
    assert result['known_additional_resources']['cost_usd'] == .01
    assert record['before']['correct'] is False


@pytest.mark.parametrize('resource,value', [('calls', True), ('tokens', 1.5), ('latency_ms', -1),
                                          ('cost_usd', float('nan'))])
def test_invalid_usage_never_becomes_free_review(resource, value):
    with pytest.raises(ValueError):
        escalation_diagnostics([pair('a', False, True, **{resource: value})])


@pytest.mark.parametrize('function', [review_signals, probability_diagnostics, escalation_diagnostics])
def test_duplicate_inventory_rejected(function):
    with pytest.raises(ValueError, match='identities'):
        function([{'case_id': 'a'}, {'case_id': 'a'}])


def test_primary_outcome_cannot_be_erased():
    with pytest.raises(ValueError, match='Primary'):
        escalation_diagnostics([{'case_id': 'a', 'after': row('a', True)}])


def test_cli_hashes_inputs_and_refuses_existing_evidence(tmp_path, monkeypatch):
    source, output = tmp_path/'records.json', tmp_path/'report.json'
    source.write_text(json.dumps(dict(signal_records=[row('a', False, provenance=capture({}, {}))],
                                     probability_records=[probability_row('a', False, .9)],
                                     escalation_pairs=[pair('a', True, False, calls=1)])))
    monkeypatch.setattr(sys, 'argv', ['diagnostics', '--input', str(source), '--output', str(output)])
    main()
    result = json.loads(output.read_text())
    assert len(result['input_sha256']) == 64
    assert result['probability_diagnostics']['brier'] == pytest.approx(.81)
    assert result['escalation_diagnostics']['errors_introduced'] == 1
    before = output.read_bytes()
    with pytest.raises(SystemExit):
        main()
    assert output.read_bytes() == before


def test_cli_rejects_output_alias_of_input(tmp_path, monkeypatch):
    source, output = tmp_path/'records.json', tmp_path/'alias.json'
    source.write_text('private original source')
    output.symlink_to(source)
    monkeypatch.setattr(sys, 'argv', ['diagnostics', '--input', str(source), '--output', str(output)])
    with pytest.raises(SystemExit):
        main()
    assert source.read_text() == 'private original source'
