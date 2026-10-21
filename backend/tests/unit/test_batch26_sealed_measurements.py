"""Historical measurements plus hostile/missing-telemetry accounting boundaries."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from evaluation.sealed_measurements import analyze, distribution, usage_summary

BASE = Path(__file__).resolve().parents[3]/'evaluation/fixtures/regression/sealed-measurements'


def rewrite(path, name, value):
    content = ''.join(json.dumps(row)+'\n' for row in value) if name.endswith('.jsonl') else json.dumps(value)
    (path/name).write_text(content)
    seal = json.loads((path/'capture-manifest.json').read_text())
    seal[name] = sha256((path/name).read_bytes()).hexdigest()
    (path/'capture-manifest.json').write_text(json.dumps(seal))


def copied(tmp_path, name='assembled-live-v1'):
    shutil.copytree(BASE/name, tmp_path/'capture')
    return tmp_path/'capture'


def test_saved_live_actual_stage_counts_plans_success_and_budget_are_measured():
    result = analyze(BASE/'assembled-live-v1')
    assert result['calls'] == 18 and result['attempts'] == 4
    assert {stage: row['calls'] for stage, row in result['stages'].items()} == {
        'extraction':4, 'retrieval':4, 'selection':4, 'planner':6}
    deterministic, assisted = result['arms']['deterministic'], result['arms']['model_assisted']
    assert deterministic['calls_per_attempt']['mean'] == 3
    assert assisted['calls_per_attempt']['mean'] == 6
    assert assisted['planner_calls_per_success'] == 3 and assisted['valid_plan_reports'] == 2
    assert assisted['invalid_plan_reports'] == 0
    assert deterministic['exact_successes'] == assisted['exact_successes'] == 2
    assert result['usage']['tokens']['total_tokens']['sum'] == 24929
    assert result['usage']['observed_token_list_price_usd'] == pytest.approx(.0052968)
    assert result['observed_spend_within_frozen_budget'] is True
    assert result['cache_hit_rate'] is None and result['current_billing_known'] is False
    assert result['conversations_observed'] == 0


@pytest.mark.parametrize('capture,calls,failures,tokens', [
    ('completeness-live-v2',4,1,17363), ('completeness-live-v3',12,3,52306)])
def test_original_live_failures_keep_their_calls_and_provider_tokens(capture, calls, failures, tokens):
    result = analyze(BASE/capture)
    assert result['calls'] == calls and result['failed_calls'] == failures
    assert result['usage']['tokens']['total_tokens']['sum'] == tokens
    assert result['failed_attempt_usage']['calls'] == failures
    assert result['failed_attempt_usage']['observed_token_list_price_usd'] > 0
    review = result['output_budget_review']['extraction']
    assert review['valid_multi_event_outputs'] == calls-failures
    assert review['valid_completion_tokens']['n'] == calls-failures
    assert review['ceiling_reduced'] is False


def test_saved_candidate_recall_uses_matchable_denominator_and_saved_uuid_join():
    result = analyze(BASE/'assembled-live-v1')['candidate_recall_at8']
    assert result['eligible'] == 2 and result['hits'] == 2 and result['recall'] == 1
    assert all(row['shortlist_size'] == 1 for row in result['rows'])


def test_missing_candidate_cannot_be_hidden_by_correct_final_mapping(tmp_path):
    path = copied(tmp_path)
    calls = [json.loads(line) for line in (path/'calls.jsonl').read_text().splitlines()]
    calls[1]['output']['candidate_ids'] = []
    reports = [json.loads(line) for line in (path/'reports.jsonl').read_text().splitlines()]
    reports[0]['calls'][1]['output']['candidate_ids'] = []
    rewrite(path, 'calls.jsonl', calls)
    rewrite(path, 'reports.jsonl', reports)
    result = analyze(path)['candidate_recall_at8']
    assert result['eligible'] == 2 and result['hits'] == 1 and result['recall'] == .5


def test_unverified_mapping_cannot_be_used_as_gold_candidate_identity(tmp_path):
    path = copied(tmp_path)
    reports = [json.loads(line) for line in (path/'reports.jsonl').read_text().splitlines()]
    reports[0]['full_case_score']['mapping_exact'] = False
    rewrite(path, 'reports.jsonl', reports)
    result = analyze(path)['candidate_recall_at8']
    assert result['eligible'] == 2 and result['hits'] == 1


@pytest.mark.parametrize('value', [None, -1, True, '100'])
def test_unknown_or_invalid_provider_usage_is_never_imputed_zero_or_billable(value):
    result = usage_summary([{'usage': {'prompt_tokens':value, 'completion_tokens':10}}], {'input':.15,'output':.6})
    assert result['tokens']['prompt_tokens']['unknown_calls'] == 1
    assert result['tokens']['prompt_tokens']['mean'] is None
    assert result['unknown_cost_calls'] == 1 and result['total_cost_known'] is False
    assert result['cached_tokens_known_calls'] == result['reasoning_tokens_known_calls'] == 0


def test_zero_known_usage_is_distinct_from_missing_usage():
    result = usage_summary([{'usage':{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}},
                            {'usage':{}}], {'input':.15,'output':.6})
    assert result['tokens']['total_tokens']['n'] == 1
    assert result['tokens']['total_tokens']['unknown_calls'] == 1
    assert result['known_cost_calls'] == result['unknown_cost_calls'] == 1


def test_empirical_p95_uses_preregistered_nearest_rank_not_mean():
    result = distribution([1]*19+[100])
    assert result['mean'] == 5.95 and result['p95_nearest_rank'] == 1 and result['maximum'] == 100
    assert distribution([])['p95_nearest_rank'] is None


def test_original_manifest_tampering_fails_before_measurement(tmp_path):
    path = copied(tmp_path)
    with (path/'calls.jsonl').open('a') as stream:
        stream.write('{}\n')
    with pytest.raises(ValueError, match='seal mismatch'):
        analyze(path)


def test_resealed_embedded_call_disagreement_is_not_double_counted(tmp_path):
    path = copied(tmp_path)
    reports = [json.loads(line) for line in (path/'reports.jsonl').read_text().splitlines()]
    reports[0]['calls'].pop()
    rewrite(path,'reports.jsonl',reports)
    with pytest.raises(ValueError, match='disagree'):
        analyze(path)


@pytest.mark.parametrize('mutation', ['extra_usage','wrong_identity','extra_output'])
def test_repeated_usage_and_output_identity_alignment_cannot_silently_truncate(tmp_path, mutation):
    path = copied(tmp_path, 'completeness-live-v3')
    name = 'model-outputs.jsonl' if mutation == 'extra_output' else 'usage.jsonl'
    values = [json.loads(line) for line in (path/name).read_text().splitlines()]
    if mutation == 'wrong_identity':
        values[0]['trial_id'] = 'wrong'
    else:
        values.append(deepcopy(values[-1]))
    rewrite(path,name,values)
    with pytest.raises(ValueError, match='identity|count'):
        analyze(path)


def test_valid_output_ceiling_and_actual_reservation_comparison_are_stage_specific():
    result = analyze(BASE/'assembled-live-v1')
    assert result['output_budget_review']['planner']['valid_completion_tokens']['maximum'] == 63
    assert result['output_budget_review']['extraction']['valid_completion_tokens']['maximum'] == 544
    assert len(result['reservation_vs_observed']) == 18
    assert all(row['reserved_token_estimate_including_output_ceiling'] > 0 for row in result['reservation_vs_observed'])


def test_misaligned_reservation_cannot_manufacture_stage_estimation_accuracy(tmp_path):
    path = copied(tmp_path)
    reservations = [json.loads(line) for line in (path/'reservations.jsonl').read_text().splitlines()]
    reservations[0]['stage'] = 'wrong'
    rewrite(path,'reservations.jsonl',reservations)
    with pytest.raises(ValueError, match='reservation/call identity mismatch'):
        analyze(path)
