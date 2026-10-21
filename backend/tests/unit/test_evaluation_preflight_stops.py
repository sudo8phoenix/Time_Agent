"""A malformed capability/quota assertion cannot authorize evaluation transport."""
from datetime import datetime, timezone
import pytest
from evaluation.prepare_repeated_development import prepare
from evaluation.repeated_development import execute, ExperimentStop


@pytest.mark.parametrize('field,value', [
    ('model_access_verified', False), ('model_access_verified', 'true'),
    ('price_verified', False), ('price_verified', 1),
    ('no_pending_work', False), ('no_active_lease_or_cooldown', False),
    ('remaining_requests', None), ('remaining_requests', '100'),
    ('remaining_requests', True), ('remaining_requests', 0),
    ('remaining_requests', float('nan')), ('remaining_requests', float('inf')),
    ('prices_per_million', None), ('model', 'unexpected'), ('key_slot', 1),
    ('checked_at', 'invalid'), ('checked_at', '2026-10-20T10:00:00'),
    ('checked_at', None),
])
def test_preflight_rejects_before_output_or_transport(tmp_path, field, value):
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared, case_ids=['DEV-20261020-01'], repetitions=1)
    check = dict(checked_at=datetime.now(timezone.utc).isoformat(), model=plan['model'],
                 key_slot=2, model_access_verified=True, price_verified=True,
                 no_pending_work=True, no_active_lease_or_cooldown=True,
                 remaining_requests=100, prices_per_million=plan['prices_per_million'])
    check[field] = value
    called = []
    output = tmp_path / 'capture'
    with pytest.raises(ExperimentStop):
        execute(prepared, output, check, transport=lambda *args: called.append(args))
    assert called == []
    assert not output.exists()
