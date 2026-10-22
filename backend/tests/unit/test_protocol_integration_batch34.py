"""Exercise actual evaluation consumers with deterministic injected transport."""
from hashlib import sha256
import json

import pytest

from app.llm.groq import GroqChatAdapter
from evaluation.assembled_development import MODEL, Recorder, full_case_score, prepare
from evaluation.calibrate import freeze_gate
from evaluation.experiment_guard import EvaluationIntegrityError, FrozenExperimentGuard
from evaluation.protocol_controls import calibration_contract, screen_tokens, split_contract


def minimal_guard(tmp_path):
    prepared = tmp_path / 'prepared'
    prepared.mkdir()
    plan = dict(source_sha256={})
    (prepared / 'plan.json').write_text(json.dumps(plan))
    return prepared, plan, FrozenExperimentGuard(prepared, plan)


@pytest.mark.parametrize('kind,category', [('defect', 'schema'), ('defect', 'annotation'),
    ('defect', 'scorer'), ('safety', 'unapproved_delivery'), ('safety', 'cross_project_leakage')])
def test_stop_rejects_new_guard_even_without_changed_source(tmp_path, kind, category):
    prepared, plan, guard = minimal_guard(tmp_path)
    original = (prepared / 'plan.json').read_bytes()
    guard.record_result('T0')
    getattr(guard, 'report_' + kind)(category=category, evidence_sha256='a' * 64,
                                    output=tmp_path / 'stop.json')
    assert (prepared / 'plan.json').read_bytes() == original
    snapshot = json.loads((tmp_path / 'stop.json').read_text())
    assert snapshot['affected_results'] == ['T0']
    with pytest.raises(EvaluationIntegrityError, match='Retained evaluation stop'):
        FrozenExperimentGuard(prepared, plan)


def test_existing_guard_observes_other_instance_stop_before_next_call(tmp_path):
    prepared, plan, first = minimal_guard(tmp_path)
    second = FrozenExperimentGuard(prepared, plan)
    first.report_defect(category='schema', evidence_sha256='b' * 64, output=tmp_path / 'stop.json')
    with pytest.raises(EvaluationIntegrityError):
        second.check()


@pytest.mark.parametrize('contents', ['', '{broken', '{}'])
def test_partial_or_corrupt_stop_marker_fails_closed(tmp_path, contents):
    prepared, plan, guard = minimal_guard(tmp_path)
    guard.stop_marker.write_text(contents)
    with pytest.raises(EvaluationIntegrityError):
        FrozenExperimentGuard(prepared, plan)


def test_broken_symlink_marker_cannot_bypass_restart_stop(tmp_path):
    prepared, plan, guard = minimal_guard(tmp_path)
    guard.stop_marker.symlink_to(tmp_path / 'missing')
    with pytest.raises(EvaluationIntegrityError):
        FrozenExperimentGuard(prepared, plan)


def test_failed_capture_write_still_persists_permanent_stop(tmp_path):
    prepared, plan, guard = minimal_guard(tmp_path)
    output = tmp_path / 'historical.json'
    output.write_text('historical')
    with pytest.raises(FileExistsError):
        guard.report_defect(category='scorer', evidence_sha256='c' * 64, output=output)
    assert output.read_text() == 'historical'
    with pytest.raises(EvaluationIntegrityError):
        FrozenExperimentGuard(prepared, plan)


@pytest.mark.parametrize('row,category', [
    (dict(ledger_writes=1, review_states=['pending']), 'unapproved_progress_mutation'),
    (dict(ledger_writes=0, review_states=['approved']), 'unapproved_progress_mutation'),
    (dict(ledger_writes=0), 'scorer'),
])
def test_actual_recorder_stops_transport_and_reuse_after_database_evidence(tmp_path, row, category):
    prepared, output = tmp_path / 'prepared', tmp_path / 'capture'
    plan = prepare(prepared)
    output.mkdir()
    guard = FrozenExperimentGuard(prepared, plan)
    guard.record_result('report-0')
    calls = []
    recorder = Recorder(plan, output, integrity=guard,
                        transport=lambda *args: calls.append(args))
    recorder.observe_report(row)
    assert recorder.stopped and calls == []
    stop = json.loads((output / 'evaluation-stop.json').read_text())
    assert stop['stops'][0]['category'] == category
    assert stop['affected_results'] == ['report-0']
    assert 'require review' in json.loads((output / 'stop-assessment.json').read_text())['assessment']
    with pytest.raises(EvaluationIntegrityError):
        FrozenExperimentGuard(prepared, plan)


def test_real_adapter_with_injected_transport_is_blocked_after_external_stop(tmp_path):
    prepared, output = tmp_path / 'prepared', tmp_path / 'capture'
    plan = prepare(prepared)
    output.mkdir()
    guard = FrozenExperimentGuard(prepared, plan)
    calls = []
    def transport(*args):
        calls.append(args)
        return 200, dict(model=MODEL, choices=[dict(
            finish_reason='stop', message=dict(content='{"observations":[]}'))])
    recorder = Recorder(plan, output, integrity=guard, transport=transport)
    recorder.factory = lambda *args, **kwargs: GroqChatAdapter(
        MODEL, bearer_token='fixture-token', transport=lambda *args: pytest.fail('unrecorded transport'))
    adapter = recorder.create(None, role='extraction')
    kwargs = dict(system='Extract.', user='No work.', schema=dict(type='object', properties={
        'observations': dict(type='array', items=dict(type='string'))}, required=['observations']))
    assert adapter.chat(**kwargs).value == {'observations': []}
    assert len(calls) == 1
    FrozenExperimentGuard(prepared, plan).report_defect(
        category='annotation', evidence_sha256='f' * 64, output=tmp_path / 'external-stop.json')
    with pytest.raises(EvaluationIntegrityError):
        adapter.chat(**kwargs)
    assert len(calls) == 1
    assert recorder.budget.snapshot()['reserved_calls'] == 1


@pytest.mark.parametrize('bad', [{}, {'ledger_writes': False, 'review_states': []},
    {'ledger_writes': 0}, {'ledger_writes': 0, 'review_states': None}])
def test_actual_scorer_cannot_award_safety_credit_without_typed_evidence(bad):
    label = dict(expected_quantity='1', expected_area=None, expected_asset_tags=[],
                 expected_mapping_state='ambiguous', expected_activity_ids=[])
    assert not full_case_score(bad, label, '2026-10-22')['approval_boundary_intact']


def splits():
    return {s: [dict(case_id=s, group_id=s+'-family')] for s in
            ('train', 'development', 'validation', 'holdout')}


@pytest.mark.parametrize('mode', ['cousins', 'chain', 'cycle', 'same_document', 'same_text'])
def test_declared_renamed_or_duplicate_sources_cannot_cross_splits(mode):
    manifest = splits()
    a, b = manifest['development'][0], manifest['holdout'][0]
    if mode == 'cousins':
        a['parent_group_ids'] = b['parent_group_ids'] = ['shared-parent']
    elif mode == 'chain':
        a['parent_group_ids'] = ['intermediate']
        b['parent_group_ids'] = ['development-family']
    elif mode == 'cycle':
        a['parent_group_ids'] = ['holdout-family']
        b['parent_group_ids'] = ['development-family']
    else:
        key = 'source_document_sha256' if mode == 'same_document' else 'text_sha256'
        a[key] = b[key] = 'a' * 64
    with pytest.raises(ValueError, match='crosses splits'):
        split_contract(manifest)


def test_fit_contract_rejects_consumed_ancestor_even_when_child_id_changed():
    manifest = splits()
    manifest['holdout'][0]['parent_group_ids'] = ['old-consumed-source']
    with pytest.raises(ValueError, match='Consumed'):
        calibration_contract(manifest, fit_case_ids=['validation'],
                             evaluation_case_ids=['holdout'], consumed_groups=['old-consumed-source'])


def test_actual_calibration_freeze_gate_uses_lineage_contract_before_fitting():
    labels = [dict(case_id='validation', group_id='validation-family',
                   review_status='independently_reviewed')]
    manifest = dict(status='frozen', labels_sha256='a' * 64,
                    group_review_status='independently_reviewed', splits=splits(),
                    review=dict(status='independently_reviewed', kind='human', reviewer_id='fixture-reviewer',
                                reviewed_at='2026-10-22', attestation='fixture-only', label_authors=['fixture-author']))
    manifest['splits']['holdout'][0]['parent_group_ids'] = ['validation-family']
    with pytest.raises(ValueError, match='lineage crosses splits'):
        freeze_gate(manifest, labels, 'a' * 64)


def test_guard_chunk_limit_rejects_large_sequence_without_materializing_it():
    class HugeSequence(list):
        def __len__(self):
            return 10**12
        def __iter__(self):
            pytest.fail('oversized token sequence materialized')
    result = screen_tokens(HugeSequence([1]), lambda chunk: pytest.fail('classifier called'),
                           context_tokens=512, reserved_tokens=2, overlap_tokens=32, max_chunks=10)
    assert result['reason'] == 'chunk_budget' and result['calls'] == 0
    assert result['total_tokens'] == 10**12


def test_new_prepared_plans_pin_shared_control_dependency(tmp_path):
    from evaluation.prepare_repeated_development import prepare as prepare_repeated
    for i, factory in enumerate([prepare, prepare_repeated]):
        plan = factory(tmp_path / f'prepared-{i}')
        assert plan['source_sha256']['evaluation/protocol_controls.py'] == sha256(
            __import__('pathlib').Path('evaluation/protocol_controls.py').read_bytes()).hexdigest()


def test_actual_repeated_runner_and_scorer_withhold_after_external_semantic_stop(tmp_path):
    from datetime import datetime, timezone
    from pathlib import Path
    from evaluation.prepare_repeated_development import prepare as prepare_repeated
    from evaluation.repeated_development import execute
    from evaluation.score_repeated_development import score
    prepared, output = tmp_path / 'prepared', tmp_path / 'capture'
    plan = prepare_repeated(prepared, case_ids=['DEV-20261020-01'], repetitions=1)
    preflight = dict(checked_at=datetime.now(timezone.utc).isoformat(), model=plan['model'], key_slot=2,
                     model_access_verified=True, price_verified=True, prices_per_million=plan['prices_per_million'],
                     no_pending_work=True, no_active_lease_or_cooldown=True, remaining_requests=100)
    calls = []
    def transport(*args):
        calls.append(args)
        FrozenExperimentGuard(prepared, plan).report_defect(
            category='annotation', evidence_sha256='a' * 64, output=output / 'evaluation-stop.json')
        return 200, dict(model=plan['model'], choices=[dict(
            finish_reason='stop', message=dict(content='{"observations":[]}'))])
    summary = execute(prepared, output, preflight, transport=transport)
    assert len(calls) == summary['reserved_calls'] == 1
    assert summary['review_required'] and summary['attempted'] == 1
    assert summary['affected_results'] == [plan['schedule'][0]['trial_id']]
    assert summary['stop_reason'] == 'evaluation_integrity_failure'
    labels = Path('evaluation/fixtures/paired-development-v2/labels.json')
    lineage = labels.with_name('lineage.json')
    with pytest.raises(ValueError, match='withheld'):
        score(output, labels, lineage)
    diagnostic = score(output, labels, lineage, historical_diagnostic=True)
    assert diagnostic['historical_diagnostic'] and not diagnostic['quality_usable']
    with pytest.raises(EvaluationIntegrityError):
        execute(prepared, tmp_path / 'forbidden-rerun', preflight, transport=transport)
    assert len(calls) == 1 and not (tmp_path / 'forbidden-rerun').exists()


def test_actual_assembled_runner_rejects_stopped_plan_before_database_setup(tmp_path, monkeypatch):
    import evaluation.assembled_development as assembled
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared)
    FrozenExperimentGuard(prepared, plan).report_defect(
        category='scorer', evidence_sha256='a' * 64, output=tmp_path / 'stop.json')
    monkeypatch.setattr(assembled, 'create_engine', lambda *args: pytest.fail('database setup after stop'))
    with pytest.raises(EvaluationIntegrityError):
        assembled.run(prepared, tmp_path / 'capture', 'unused', tmp_path / 'unused-preflight')
