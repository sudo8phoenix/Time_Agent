from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from evaluation.assembled_development import Recorder, prepare as assembled_plan
from evaluation.experiment_guard import EvaluationIntegrityError, FrozenExperimentGuard
from evaluation.prepare_repeated_development import prepare
from evaluation.repeated_development import execute


def check(plan):
    return dict(checked_at=datetime.now(timezone.utc).isoformat(), model=plan['model'], key_slot=2,
                model_access_verified=True, price_verified=True, prices_per_million=plan['prices_per_million'],
                no_pending_work=True, no_active_lease_or_cooldown=True, remaining_requests=100)


@pytest.mark.parametrize('artifact', ['plan.json', 'wire-schema.json', 'scorer', 'annotation'])
def test_midrun_frozen_change_stops_before_next_transport_and_seals_prior_evidence(tmp_path, artifact):
    prepared, output = tmp_path / 'prepared', tmp_path / 'capture'
    plan = prepare(prepared, case_ids=['DEV-20261020-01'], repetitions=1)
    tracked = tmp_path / artifact if artifact in {'scorer', 'annotation'} else prepared / artifact
    if artifact in {'scorer', 'annotation'}:
        tracked.write_text('original reviewed artifact')
        plan['source_sha256'][str(tracked)] = sha256(tracked.read_bytes()).hexdigest()
        (prepared / 'plan.json').write_text(json.dumps(plan))
    calls = []
    def transport(method, url, payload, timeout, headers):
        calls.append(payload)
        tracked.write_text('PRIVATE changed artifact')
        return 200, dict(model=plan['model'], usage={}, choices=[dict(
            finish_reason='stop', message=dict(content='{"observations":[]}'))])
    result = execute(prepared, output, check(plan), transport=transport)
    assert len(calls) == result['reserved_calls'] == 1
    assert result['attempted'] == 1 and result['completed'] == 0
    assert result['stop_reason'] == 'evaluation_integrity_failure'
    predictions = [json.loads(line) for line in (output / 'predictions.jsonl').read_text().splitlines()]
    assert predictions[0]['failure_code'] == 'FROZEN_INPUT_CHANGED'
    assert predictions[0]['diagnosis']['cause'] == 'evaluation_integrity'
    assert 'PRIVATE changed artifact' not in (output / 'predictions.jsonl').read_text()
    manifest = json.loads((output / 'capture-manifest.json').read_text())
    assert all(sha256((output / name).read_bytes()).hexdigest() == value for name, value in manifest.items())
    with pytest.raises(EvaluationIntegrityError):
        FrozenExperimentGuard(prepared, plan)


@pytest.mark.parametrize('row,reason', [
    ({'ledger_writes': 1, 'review_states': ['pending']}, 'hard_safety_violation'),
    ({'ledger_writes': 1}, 'hard_safety_violation'),
    ({'ledger_writes': 0, 'review_states': ['approved']}, 'hard_safety_violation'),
    ({'review_states': ['pending']}, 'safety_check_incomplete'),
    ({'ledger_writes': False, 'review_states': []}, 'safety_check_incomplete'),
    ({'ledger_writes': 0, 'review_states': ['unknown']}, 'safety_check_incomplete'),
])
def test_assembled_safety_stop_is_persistent_and_marks_results_for_review(tmp_path, row, reason):
    plan = assembled_plan(tmp_path / 'prepared')
    output = tmp_path / 'capture'
    output.mkdir()
    (output / 'reports.jsonl').write_text(json.dumps(row) + '\n')
    recorder = Recorder(plan, output, transport=lambda *args: pytest.fail('transport called'))
    recorder.observe_report(row)
    assert recorder.stopped and recorder.stop_reason == reason
    assessment = json.loads((output / 'stop-assessment.json').read_text())
    assert assessment['hard_safety_violation'] == (reason == 'hard_safety_violation')
    assert 'require review' in assessment['assessment']
    assert not assessment['release_accepted']
    assert json.loads((output / 'reports.jsonl').read_text()) == row


def test_pending_reports_do_not_trigger_stop(tmp_path):
    plan = assembled_plan(tmp_path / 'prepared')
    recorder = Recorder(plan, tmp_path)
    recorder.observe_report(dict(ledger_writes=0, review_states=['pending']))
    assert not recorder.stopped and recorder.stop_reason is None
    assert not (tmp_path / 'stop-assessment.json').exists()


def test_guard_missing_artifact_fails_closed_without_exporting_path(tmp_path):
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared, case_ids=['DEV-20261020-01'], repetitions=1)
    guard = FrozenExperimentGuard(prepared, plan)
    (prepared / 'wire-schema.json').unlink()
    with pytest.raises(EvaluationIntegrityError) as error:
        guard.check()
    assert str(tmp_path) not in str(error.value)
