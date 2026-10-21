"""Known-answer diagnostics, with negative controls and clustered dependencies."""
from copy import deepcopy
import json
import sys

import pytest

from evaluation.selection_diagnostics import scorecard, failure_breakdown, pareto_review, main


def fixture():
    labels, predictions = [], []
    for identity, group, slices, expected, selected, candidates, state in [
        ('ordinary', 'report-a', ['ordinary'], 'A', 'A', ['A'], 'completed'),
        ('wrong', 'report-a', ['difficult'], 'B', 'X', ['B', 'X'], 'completed'),
        ('retrieval', 'report-b', ['difficult'], 'C', None, ['X'], 'completed'),
        ('failed', 'report-b', ['difficult'], 'D', 'D', ['D'], 'failed'),
        ('attack', 'report-c', ['attack'], None, 'X', ['X'], 'completed'),
        ('unreadable', 'report-c', ['unreadable'], None, 'X', ['X'], 'completed'),
        ('missing', 'report-d', ['ordinary'], 'E', None, [], None),
    ]:
        labels.append(dict(case_id=identity, group_id=group, slices=slices,
                           expected_mapping_state='suggested' if expected else 'unmatched',
                           expected_activity_ids=[expected] if expected else []))
        if state:
            predictions.append(dict(case_id=identity, candidate_ids=candidates,
                                    selected_activity_id=selected, state=state,
                                    extraction_valid=True))
    return labels, predictions


def test_ret07_precision_counts_failed_and_unmatchable_false_links():
    labels, predictions = fixture()
    result = scorecard(labels, predictions, replicates=100)
    metric = result['metrics']['selected_precision']
    assert (metric['numerator'], metric['denominator'], metric['value']) == (1, 5, .2)
    assert result['slices']['attack']['selected_precision']['value'] == 0
    assert result['slices']['unreadable']['selected_precision']['value'] == 0


def test_ret08_all_abstention_has_zero_coverage_and_undefined_precision():
    labels, predictions = fixture()
    for row in predictions:
        row['selected_activity_id'] = None
    result = scorecard(labels, predictions, replicates=100)
    assert result['metrics']['coverage']['value'] == 0
    assert result['metrics']['coverage']['denominator'] == 5
    assert result['metrics']['selected_precision']['value'] is None
    assert result['metrics']['selected_precision']['valid_replicates'] == 0
    assert result['metrics']['selected_precision']['undefined_replicates'] == 100


def test_exp11_difficult_slice_cannot_disappear_under_passing_ordinary_slice():
    labels, predictions = fixture()
    result = scorecard(labels, predictions, replicates=100)
    assert result['slices']['ordinary']['coverage']['value'] == .5
    assert result['slices']['difficult']['selected_precision']['value'] == 0
    assert result['slices']['difficult']['recall_at_8']['value'] == pytest.approx(1/3)
    assert result['missing_outputs'] == 1
    assert result['release_accepted'] is False


def test_exp08_whole_cluster_resampling_does_not_invent_event_independence():
    labels = [dict(case_id=str(i), group_id=str(i), slices=['all'],
                   expected_mapping_state='suggested', expected_activity_ids=['A']) for i in range(2)]
    predictions = [dict(case_id=str(i), selected_activity_id='A' if i == 0 else 'X',
                        candidate_ids=['A'], state='completed') for i in range(2)]
    small = scorecard(labels, predictions, replicates=500, seed=17)
    expanded_labels, expanded_predictions = [], []
    for repeat in range(10):
        expanded_labels.extend({**row, 'case_id': f'{repeat}:{row["case_id"]}'} for row in labels)
        expanded_predictions.extend({**row, 'case_id': f'{repeat}:{row["case_id"]}'} for row in predictions)
    expanded = scorecard(expanded_labels, expanded_predictions, replicates=500, seed=17)
    assert expanded['cluster_count'] == 2
    for name in small['metrics']:
        first, repeated = small['metrics'][name], expanded['metrics'][name]
        assert repeated['numerator'] == 10 * first['numerator']
        assert repeated['denominator'] == 10 * first['denominator']
        assert repeated['descriptive_cluster_bootstrap_95'] == first['descriptive_cluster_bootstrap_95']
        assert repeated['valid_replicates'] == first['valid_replicates']
    assert small['metrics']['selected_precision']['descriptive_cluster_bootstrap_95'] == [0, 1]


def test_exp08_single_cluster_withholds_interval_even_with_many_events():
    labels, predictions = fixture()
    for row in labels:
        row['group_id'] = 'one-report'
    result = scorecard(labels, predictions, replicates=100)
    assert result['cluster_count'] == 1
    assert all(row['descriptive_cluster_bootstrap_95'] is None for row in result['metrics'].values())


def test_seeded_bootstrap_is_repeatable_and_does_not_mutate_inputs():
    labels, predictions = fixture()
    before = deepcopy((labels, predictions))
    assert scorecard(labels, predictions, replicates=100) == scorecard(labels, predictions, replicates=100)
    assert (labels, predictions) == before


@pytest.mark.parametrize('fault', ['duplicate_label', 'duplicate_output', 'unlabelled', 'group', 'slices'])
def test_invalid_inventories_fail_closed(fault):
    labels, predictions = fixture()
    if fault == 'duplicate_label':
        labels.append(labels[0])
    elif fault == 'duplicate_output':
        predictions.append(predictions[0])
    elif fault == 'unlabelled':
        predictions.append({'case_id': 'unlabelled'})
    elif fault == 'group':
        labels[0]['group_id'] = ''
    else:
        labels[0]['slices'] = ['ordinary', 'ordinary']
    with pytest.raises(ValueError):
        scorecard(labels, predictions, replicates=100)


def test_ret09_failure_localization_keeps_missing_failed_extraction_retrieval_and_selection_separate():
    labels, predictions = fixture()
    result = failure_breakdown(labels, predictions)
    counts = result['counts']
    assert counts == dict(correct_selection=1, selection_error_with_gold_candidate=1,
                          retrieval_miss_at_8=1, failed_output=1,
                          false_selection_on_ineligible=2, missing_output=1)
    predictions[1]['extraction_valid'] = False
    assert failure_breakdown(labels, predictions)['counts']['extraction_invalid_declared'] == 1
    predictions[1].pop('extraction_valid')
    assert failure_breakdown(labels, predictions)['counts']['extraction_not_assessed'] == 1
    predictions[1]['extraction_valid'] = True
    predictions[1].pop('candidate_ids')
    assert failure_breakdown(labels, predictions)['counts']['retrieval_not_assessed'] == 1


def test_ret09_gold_beyond_eighth_candidate_remains_retrieval_failure():
    labels, predictions = fixture()
    predictions[0]['candidate_ids'] = [f'X{i}' for i in range(8)] + ['A']
    assert failure_breakdown(labels, predictions)['cases'][0]['category'] == 'retrieval_miss_at_8'


def config(identity, **updates):
    return dict(configuration_id=identity, comparison_sha256='a'*64,
                task_success=.8, precision=.9, coverage=.8, availability=1.,
                cost=1., latency_ms=100., tokens=100., calls=2.,
                hard_safety_violations=0, **updates)


def test_exp12_reject_dominated_preserve_real_tradeoffs_ties_and_safety():
    baseline = config('baseline')
    worse = {**config('worse'), 'cost': 2, 'task_success': .7}
    faster = {**config('faster'), 'cost': 2, 'latency_ms': 50}
    unsafe = {**config('unsafe'), 'hard_safety_violations': 1, 'cost': 0}
    tied = config('tied')
    result = pareto_review([baseline, worse, faster, unsafe, tied])
    by = {r['configuration_id']: r for r in result['configurations']}
    assert by['worse']['dominated_by'] == ['baseline', 'faster', 'tied']
    assert by['faster']['decision'] == 'tradeoff_candidate'
    assert by['tied']['decision'] == 'tradeoff_candidate'
    assert by['baseline']['decision'] == 'tradeoff_candidate'
    assert by['unsafe']['decision'] == 'reject_safety'
    assert result['release_accepted'] is False


@pytest.mark.parametrize('update', [dict(cost=float('nan')), dict(coverage=2), dict(calls=True),
                                  dict(comparison_sha256='b'*64), dict(hard_safety_violations=None)])
def test_exp12_invalid_or_unpaired_comparisons_cannot_be_ranked(update):
    with pytest.raises(ValueError):
        pareto_review([config('a'), {**config('b'), **update}])


@pytest.mark.parametrize('replicates,seed', [(99, 0), (True, 0), (100, True)])
def test_invalid_bootstrap_settings_reject(replicates, seed):
    labels, predictions = fixture()
    with pytest.raises(ValueError):
        scorecard(labels, predictions, replicates=replicates, seed=seed)


def test_cli_saved_inputs_hashed_output_is_exclusive(tmp_path, monkeypatch):
    labels, predictions = fixture()
    source, capture, output = [tmp_path/name for name in ['labels.json', 'capture.json', 'result.json']]
    source.write_text(json.dumps(labels))
    capture.write_text(json.dumps(predictions))
    monkeypatch.setattr(sys, 'argv', ['diagnostics', '--labels', str(source), '--predictions', str(capture),
                                    '--output', str(output), '--replicates', '100'])
    main()
    result = json.loads(output.read_text())
    assert result['scorecard']['metrics']['selected_precision']['value'] == .2
    assert len(result['input_sha256'][str(source)]) == 64
    before = output.read_bytes()
    with pytest.raises(SystemExit):
        main()
    assert output.read_bytes() == before


def test_cli_cannot_overwrite_label_input_through_symlink(tmp_path, monkeypatch):
    labels, predictions = fixture()
    source, capture, output = [tmp_path/name for name in ['labels.json', 'capture.json', 'alias.json']]
    source.write_text(json.dumps(labels))
    capture.write_text(json.dumps(predictions))
    output.symlink_to(source)
    monkeypatch.setattr(sys, 'argv', ['diagnostics', '--labels', str(source), '--predictions', str(capture),
                                    '--output', str(output)])
    before = source.read_bytes()
    with pytest.raises(SystemExit):
        main()
    assert source.read_bytes() == before
