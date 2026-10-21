"""Accounting and outcome checks over actual offline graph executions."""
import pytest

from evaluation.orchestration_fixture_probe import run, summarize


@pytest.fixture(scope='module')
def measured():
    return run(repetitions=1)


def test_identical_initial_tasks_compare_flat_hierarchy_and_planner(measured):
    for workload in {r['workload'] for r in measured}:
        group = [r for r in measured if r['workload'] == workload]
        assert len({r['task_fingerprint'] for r in group}) == 1
        normal = [r for r in group if r['configuration'] != 'hierarchy_invalid_planner']
        assert len({r['terminal'] for r in normal}) == 1
        assert len({r['draft_fingerprint'] for r in normal}) == 1


def test_root_durable_usage_matches_observed_tool_and_model_attempts(measured):
    for row in measured:
        if row['configuration'] == 'flat':
            continue
        assert row['durable_usage']['model_calls'] == row['total_model_calls']
        assert row['durable_usage'].get('tool_calls', 0) == len(row['tools'])
        assert row['durable_usage']['delegations'] == sum(t['role'] not in {'root', 'matching'} for t in row['tasks'])


def test_repair_cost_is_separated_from_model_inference_cost(measured):
    for row in measured:
        if row['configuration'] == 'hierarchy_invalid_planner':
            continue
        if row['workload'] == 'simple':
            assert row['failed_tool_calls'] == row['counters']['corrective_retries'] == 0
        else:
            assert row['counters']['corrective_retries'] == 1
            assert row['tool_counts']['select_candidate'] == 2
            assert row['failed_tool_calls'] == (1 if row['workload'] == 'one_selection_repair' else 2)


def test_invalid_plan_fails_before_domain_work_and_is_charged(measured):
    for row in measured:
        if row['configuration'] != 'hierarchy_invalid_planner':
            continue
        assert not row['success'] and not row['plan_valid']
        assert row['total_model_calls'] == 1
        assert row['tools'] == [] and row['persistence_attempts'] == 0
        assert row['errors'] == ['AGENT_PLANNER_INVALID']


def test_singleton_planner_overhead_has_no_observed_success_gain(measured):
    for workload in {r['workload'] for r in measured}:
        deterministic = next(r for r in measured if r['workload'] == workload and r['configuration'] == 'hierarchy')
        assisted = next(r for r in measured if r['workload'] == workload and r['configuration'] == 'hierarchy_planner')
        assert assisted['success'] == deterministic['success']
        assert assisted['total_model_calls'] - deterministic['total_model_calls'] == assisted['singleton_action_planner_calls']
        assert assisted['singleton_action_planner_calls'] in {2, 3}


def test_finite_normal_target_is_below_emergency_ceiling_and_not_a_release_gate(measured):
    simple = [r for r in summarize(measured) if r['workload'] == 'simple' and r['successes']]
    assert {r['measured_normal_call_target'] for r in simple} == {3, 6}
    assert all(r['measured_normal_call_target'] < 806 / 100 for r in simple)


def test_timing_sample_does_not_invent_tail_or_queue_measurements(measured):
    for row in measured:
        assert row['elapsed_ms'] > 0 and row['compilation_ms'] > 0
        assert all(tool['elapsed_ms'] >= 0 for tool in row['tools'])
        assert row['queue_wait_ms'] is row['provider_transport_ms'] is None
        assert row['paid_calls'] == 0
    for group in summarize(measured):
        assert group['sample_count'] == 1
        assert group['p95_ms'] is None
        assert group['p50_ms'] == group['max_ms']


def test_failed_workload_not_given_success_cost_denominator(measured):
    for group in summarize(measured):
        if group['successes'] == 0:
            assert group['model_calls_per_success'] is None
        else:
            assert group['model_calls_per_success'] > 0
