from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

import pytest

from evaluation.prepare_repeated_development import FIXTURE, prepare
from evaluation.repeated_development import ExperimentStop, TrialBudget, execute, validate_preflight, verify_plan
from evaluation.score_repeated_development import score


def preflight(plan):
    return dict(checked_at=datetime.now(timezone.utc).isoformat(), model=plan['model'], key_slot=2,
                model_access_verified=True, price_verified=True, prices_per_million=plan['prices_per_million'],
                no_pending_work=True, no_active_lease_or_cooldown=True, remaining_requests=1000)


def response(payload, *, refusal=None, finish='stop', model=None):
    return 200, {'model': model or payload['model'], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
                 'choices': [{'finish_reason': finish, 'message': {
                     'content': '{"observations":[]}', 'refusal': refusal}}]}


def test_repeated_capture_keeps_all_unique_trials_and_seals_empty_output_failures(tmp_path):
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared)
    seen = []
    def transport(method, url, payload, timeout, headers):
        seen.append(payload)
        assert 'expected' not in json.dumps(payload['messages'])
        assert timeout <= 60
        return response(payload)
    output = tmp_path / 'capture'
    result = execute(prepared, output, preflight(plan), transport=transport)
    assert result['attempted'] == result['reserved_calls'] == result['completed'] == 60
    assert len(seen) == 60
    scored = score(output, FIXTURE / 'labels.json', FIXTURE / 'lineage.json')
    assert scored['scheduled'] == 60
    assert all(a['raw_exact'] == a['normalized_exact'] == 0 for a in scored['arms'].values())
    assert all('injected-test-token' not in p.read_text() for p in output.iterdir())
    with pytest.raises(FileExistsError):
        execute(prepared, output, preflight(plan), transport=transport)


@pytest.mark.parametrize('kind', ['refusal', 'length', 'provider', 'identity', 'interrupt'])
def test_stop_preserves_one_attempt_and_all_unattempted_trials(tmp_path, kind):
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared)
    def transport(method, url, payload, timeout, headers):
        if kind == 'interrupt':
            raise KeyboardInterrupt()
        if kind == 'provider':
            return 429, {}
        return response(payload, refusal='declined' if kind == 'refusal' else None,
                        finish='length' if kind == 'length' else 'stop',
                        model='unexpected' if kind == 'identity' else None)
    output = tmp_path / 'capture'
    result = execute(prepared, output, preflight(plan), transport=transport)
    assert result['attempted'] == result['reserved_calls'] == 1
    assert result['completed'] == 0
    scored = score(output, FIXTURE / 'labels.json', FIXTURE / 'lineage.json')
    assert sum(r['state'] == 'unattempted' for r in scored['trials']) == 59
    assert all(not r['raw_fields_exact'] and not r['normalized_fields_exact'] for r in scored['trials'])


def test_cumulative_budgets_count_failed_reservations_and_include_input_bytes():
    limits = dict(wall_seconds=10, calls=1, reserved_tokens=10000, list_price_usd=.01,
                  output_tokens_per_call=100, request_seconds=5)
    now = [0]
    budget = TrialBudget(limits, {'input': .075, 'output': .30}, clock=lambda: now[0])
    payload = {'max_completion_tokens': 100, 'messages': [{'content': 'hello'}]}
    assert budget.reserve(payload) == 5
    assert budget.tokens > 1124
    with pytest.raises(ExperimentStop):
        budget.reserve(payload)
    assert budget.calls == 1
    for key, value in [('reserved_tokens', 1), ('list_price_usd', .0000001), ('wall_seconds', 0)]:
        fresh = TrialBudget({**limits, key: value}, {'input': .075, 'output': .30}, clock=lambda: now[0])
        with pytest.raises(ExperimentStop):
            fresh.reserve(payload)
        assert fresh.calls == 0


def test_fixed_stronger_model_and_output_allowance_are_reserved_without_fallback(tmp_path):
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared, 'correction', case_ids=['DEV-20261020-04', 'DEV-20261020-07'],
                   repetitions=1, strict_all=True, model='openai/gpt-oss-120b', output_tokens=3072)
    seen = []
    def transport(method, url, payload, timeout, headers):
        seen.append(payload)
        assert payload['model'] == plan['model']
        assert payload['max_completion_tokens'] == 3072
        assert payload['response_format']['json_schema']['strict'] is True
        return 400, {}
    output = tmp_path / 'capture'
    result = execute(prepared, output, preflight(plan), transport=transport)
    assert len(seen) == result['reserved_calls'] == result['attempted'] == 1
    assert result['completed'] == 0
    assert result['reserved_tokens'] > 3072
    assert sum(r['state'] == 'unattempted' for r in score(output, FIXTURE / 'labels.json', FIXTURE / 'lineage.json')['trials']) == 3


def test_preflight_and_frozen_wire_fail_closed(tmp_path):
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared)
    check = preflight(plan)
    for key, value in [('no_pending_work', False), ('remaining_requests', 59),
                       ('key_slot', 0), ('model_access_verified', False),
                       ('checked_at', (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())]:
        with pytest.raises(ExperimentStop):
            validate_preflight({**check, key: value}, plan)
    (prepared / 'wire-schema.json').write_text('{}')
    with pytest.raises(ExperimentStop):
        verify_plan(prepared)


def test_scorer_rejects_duplicate_trials_even_after_manifest_reseal(tmp_path):
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared)
    output = tmp_path / 'capture'
    execute(prepared, output, preflight(plan), transport=lambda *args: (429, {}))
    path = output / 'predictions.jsonl'
    path.write_text(path.read_text() * 2)
    manifest = json.loads((output / 'capture-manifest.json').read_text())
    manifest[path.name] = sha256(path.read_bytes()).hexdigest()
    (output / 'capture-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Duplicate'):
        score(output, FIXTURE / 'labels.json', FIXTURE / 'lineage.json')


@pytest.mark.parametrize('comparison,variable', [('strict', 'strict'), ('reasoning', 'reasoning_effort')])
def test_isolated_comparisons_change_only_the_preregistered_wire_setting(tmp_path, comparison, variable):
    from copy import deepcopy
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared, comparison)
    payloads = []
    def transport(method, url, payload, timeout, headers):
        payloads.append(deepcopy(payload))
        return response(payload)
    execute(prepared, tmp_path / 'capture', preflight(plan), transport=transport)
    assert len(payloads) == 60
    for index in range(0, len(payloads), 2):
        a, b = payloads[index:index+2]
        if variable == 'strict':
            left = a['response_format']['json_schema'].pop('strict')
            right = b['response_format']['json_schema'].pop('strict')
        else:
            left, right = a.pop(variable), b.pop(variable)
        assert left != right
        assert a == b


def test_known_correct_trial_and_provider_rejection_remain_separate_in_quality_and_cost(tmp_path):
    from evaluation.prompt_ablation import observation
    from evaluation.summarize_repeated_development import summarize
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared)
    case = json.loads((FIXTURE / 'inputs.json').read_text())[0]
    calls = []
    def transport(method, url, payload, timeout, headers):
        calls.append(payload)
        if len(calls) == 2:
            return 429, {}
        value = observation(case['case_id'], case['text'], area='Zone Cedar', asset_tags=['TR-030'],
                            work_date='2026-10-20', quantity='5', quantity_kind='delta', unit='m3', raw_unit='m3')
        status, body = response(payload)
        body['choices'][0]['message']['content'] = json.dumps({'observations': [value]})
        return status, body
    output = tmp_path / 'capture'
    result = execute(prepared, output, preflight(plan), transport=transport)
    assert result['attempted'] == 2 and result['completed'] == 1
    scored = score(output, FIXTURE / 'labels.json', FIXTURE / 'lineage.json')
    assert scored['arms']['v12']['raw_exact'] == scored['arms']['v12']['normalized_exact'] == 1
    assert scored['arms']['coverage-and-quantity']['raw_exact'] == 0
    assert sum(t['state'] == 'unattempted' for t in scored['trials']) == 58
    summary = summarize(output, FIXTURE / 'labels.json', FIXTURE / 'lineage.json')
    assert summary['metrics']['v12']['token_usage']['prompt_tokens'] == 10
    assert summary['metrics']['v12']['all_scheduled_denominator'] == 30
    assert summary['metrics']['v12']['returned_response_denominator'] == 1
    assert summary['metrics']['v12']['returned_response_raw_exact_rate'] == 1
    assert summary['metrics']['v12']['all_attempted_raw_exact_rate'] == 1
    assert summary['metrics']['v12']['all_scheduled_raw_exact_rate'] == 1/30
    assert summary['metrics']['coverage-and-quantity']['token_usage']['responses_with_unknown_usage'] == 1
    assert summary['metrics']['coverage-and-quantity']['attempted_denominator'] == 1
    assert summary['metrics']['coverage-and-quantity']['returned_response_raw_exact_rate'] is None
    assert summary['metrics']['coverage-and-quantity']['all_attempted_raw_exact_rate'] == 0
    assert 'unknown, not zero billing' in summary['economics_limitations']


def test_selected_fields_cannot_hide_an_invalid_domain_object(tmp_path):
    from evaluation.prompt_ablation import observation
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared, case_ids=['DEV-20261020-01'], repetitions=1)
    case = json.loads((FIXTURE / 'inputs.json').read_text())[0]
    def transport(method, url, payload, timeout, headers):
        value = observation(case['case_id'], case['text'], area='Zone Cedar', asset_tags=['TR-030'],
                            work_date='2026-10-20', quantity='5', quantity_kind='delta', unit='m3', raw_unit='m3')
        value['summary'] = ''  # Native schema compatibility drops minLength; domain must still enforce it.
        status, body = response(payload)
        body['choices'][0]['message']['content'] = json.dumps({'observations': [value]})
        return status, body
    output = tmp_path / 'capture'
    execute(prepared, output, preflight(plan), transport=transport)
    scored = score(output, FIXTURE / 'labels.json', FIXTURE / 'lineage.json')
    trial = scored['trials'][0]
    assert trial['response_checks']['wire_schema_valid']
    assert not trial['response_checks']['raw_domain_schema_valid']
    assert not trial['raw_fields_exact'] and not trial['normalized_fields_exact']
    assert scored['scoring_version'] == 'repeated-development-v3-completion-fences'


@pytest.mark.parametrize('kind', ['domain', 'native', 'refusal', 'length', 'provider', 'identity'])
def test_preregistered_content_failures_count_and_continue_but_provider_or_identity_stops(tmp_path, kind):
    from evaluation.prompt_ablation import observation
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared, case_ids=['DEV-20261020-01'], repetitions=1, continue_content_failures=True)
    case = json.loads((FIXTURE / 'inputs.json').read_text())[0]
    def transport(method, url, payload, timeout, headers):
        if kind == 'provider':
            return 400, {}
        status, body = response(payload, refusal='declined' if kind == 'refusal' else None,
                                finish='length' if kind == 'length' else 'stop',
                                model='wrong' if kind == 'identity' else None)
        if kind == 'native':
            body['choices'][0]['message']['content'] = '{"wrong":[]}'
        elif kind == 'domain':
            value = observation(case['case_id'], case['text'])
            value['summary'] = ''
            body['choices'][0]['message']['content'] = json.dumps({'observations': [value]})
        return status, body
    output = tmp_path / 'capture'
    result = execute(prepared, output, preflight(plan), transport=transport)
    assert result['attempted'] == (1 if kind in {'provider', 'identity'} else 2)
    assert result['completed'] == 0
    scored = score(output, FIXTURE / 'labels.json', FIXTURE / 'lineage.json')
    assert all(not r['raw_fields_exact'] and not r['normalized_fields_exact'] for r in scored['trials'])
