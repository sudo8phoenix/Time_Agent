"""Model lifecycle faults must stop frozen evaluations without fallback or score credit."""
from datetime import datetime, timezone
import json

import pytest

from evaluation.prepare_repeated_development import FIXTURE, prepare
from evaluation.repeated_development import execute
from evaluation.score_repeated_development import score


@pytest.mark.parametrize('fault', [
    'retired_404', 'retired_410', 'parameter_400', 'parameter_422',
    'replacement', 'missing_identity', 'null_identity', 'empty_identity',
])
def test_lifecycle_fault_stops_even_when_content_failures_may_continue(tmp_path, fault):
    prepared, output = tmp_path / 'prepared', tmp_path / 'capture'
    plan = prepare(prepared, case_ids=['DEV-20261020-01'], repetitions=2,
                   continue_content_failures=True)
    preflight = dict(checked_at=datetime.now(timezone.utc).isoformat(), model=plan['model'],
                     key_slot=2, model_access_verified=True, price_verified=True,
                     prices_per_million=plan['prices_per_million'], no_pending_work=True,
                     no_active_lease_or_cooldown=True, remaining_requests=100)
    calls = []

    def transport(method, url, payload, timeout, headers):
        calls.append(payload)
        body = {'model': payload['model'], 'choices': [
            {'finish_reason': 'stop', 'message': {'content': '{"observations":[]}'}}]}
        if fault.startswith(('retired_', 'parameter_')):
            return int(fault.rsplit('_', 1)[1]), {'error': {
                'message': 'private-report-secret', 'code': fault}}
        if fault == 'missing_identity':
            del body['model']
        else:
            body['model'] = {'replacement': 'replacement-model', 'null_identity': None,
                             'empty_identity': ''}[fault]
        return 200, body

    result = execute(prepared, output, preflight, transport=transport)
    assert len(calls) == result['reserved_calls'] == result['attempted'] == 1
    assert calls[0]['model'] == plan['model']
    assert result['completed'] == 0 and result['stop_reason']
    assert result['reserved_tokens'] > 0
    scored = score(output, FIXTURE / 'labels.json', FIXTURE / 'lineage.json')
    assert scored['scheduled'] == 4
    assert sum(row['state'] == 'unattempted' for row in scored['trials']) == 3
    assert all(not row['raw_fields_exact'] and not row['normalized_fields_exact']
               for row in scored['trials'])
    assert not (output / 'model-outputs.jsonl').exists()
    exported = '\n'.join(path.read_text() for path in output.iterdir() if path.is_file())
    assert 'private-report-secret' not in exported
    assert 'replacement-model' not in exported
    assert 'injected-test-token' not in exported
    # A frozen result cannot be overwritten by a retry with changed defaults.
    manifest = json.loads((output / 'capture-manifest.json').read_text())
    with pytest.raises(FileExistsError):
        execute(prepared, output, preflight, transport=transport)
    assert len(calls) == 1
    assert json.loads((output / 'capture-manifest.json').read_text()) == manifest
