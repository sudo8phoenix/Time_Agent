"""Twenty-five offline checks at preflight, plan and budget boundaries."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from evaluation.prepare_repeated_development import prepare
from evaluation.repeated_development import ExperimentStop, TrialBudget, execute
from backend.tests.unit.test_repeated_development_runtime import preflight


@pytest.fixture
def prepared(tmp_path):
    folder = tmp_path / 'prepared'
    plan = prepare(folder, case_ids=['DEV-20261020-01'], repetitions=1)
    return folder, plan


PREFLIGHT_MUTATIONS = [
    (flag, value)
    for flag in ('model_access_verified', 'price_verified', 'no_pending_work',
                 'no_active_lease_or_cooldown')
    for value in (1, None)
] + [('checked_at', 'future'), ('checked_at', 'naive'),
     ('remaining_requests', True), ('model', 'wrong-model')]


@pytest.mark.parametrize('field,value', PREFLIGHT_MUTATIONS)
def test_preflight_rejects_before_transport_credentials_or_capture(prepared, tmp_path, monkeypatch,
                                                                 field, value):
    folder, plan = prepared
    check = preflight(plan)
    if value == 'future':
        value = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    elif value == 'naive':
        value = datetime.now().isoformat()
    check[field] = value
    monkeypatch.setattr('app.settings.get_settings', lambda: pytest.fail('credentials reached'))
    output = tmp_path / 'capture'
    with pytest.raises(ExperimentStop):
        execute(folder, output, check)
    assert not output.exists()
    assert json.loads((folder / 'plan.json').read_text()) == plan


@pytest.mark.parametrize('field,value', [
    ('repetition', 0), ('repetition', -1), ('repetition', True), ('repetition', 1.5),
    ('key_slot', 2.0), ('retries', False), ('repairs', False), ('concurrency', True),
])
def test_plan_rejects_coerced_or_invalid_trial_controls_before_execution(prepared, tmp_path,
                                                                      monkeypatch, field, value):
    folder, plan = prepared
    if field == 'repetition':
        plan['schedule'][0][field] = value
    elif field == 'key_slot':
        plan[field] = value
    else:
        plan['budget'][field] = value
    path = folder / 'plan.json'
    path.write_text(json.dumps(plan))
    before = path.read_bytes()
    monkeypatch.setattr('app.settings.get_settings', lambda: pytest.fail('credentials reached'))
    output = tmp_path / 'capture'
    with pytest.raises(ExperimentStop):
        execute(folder, output, preflight(plan))
    assert not output.exists() and path.read_bytes() == before


@pytest.mark.parametrize('boundary', ['calls', 'reserved_tokens', 'list_price_usd',
                                    'wall_seconds', 'unicode'])
def test_reservation_boundaries_preserve_accounting_and_limit_timeout(boundary):
    limits = dict(wall_seconds=100, calls=2, reserved_tokens=100000,
                  list_price_usd=1, output_tokens_per_call=100, request_seconds=30)
    now = [0.0]
    prices = {'input': .075, 'output': .30}
    payload = {'max_completion_tokens': 100, 'messages': [{'content': 'مرحبا施工🙂'}]}
    budget = TrialBudget(limits, prices, clock=lambda: now[0])
    assert budget.reserve(payload) == 30
    before = (budget.calls, budget.tokens, budget.usd)
    if boundary == 'unicode':
        source = len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) + 1024
        assert budget.tokens == source + 100
        assert budget.usd == (source * prices['input'] + 100 * prices['output']) / 1e6
        now[0] = 95
        assert budget.reserve(payload) == 5
        assert budget.calls == 2 and budget.tokens == 2 * before[1]
        return
    if boundary == 'wall_seconds':
        now[0] = 100
    else:
        limits[boundary] = {'calls': before[0], 'reserved_tokens': before[1],
                            'list_price_usd': before[2]}[boundary]
    with pytest.raises(ExperimentStop):
        budget.reserve(payload)
    assert (budget.calls, budget.tokens, budget.usd) == before
