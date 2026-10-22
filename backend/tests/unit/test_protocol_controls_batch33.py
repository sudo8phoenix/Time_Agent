"""Synthetic protocol controls, never evidence of actual model/judge quality."""
from copy import deepcopy

import pytest

from evaluation.protocol_controls import (
    DEFECTS, SAFETY_EFFECTS, StopGate, blind_judge_request, calibration_contract,
    disagreement_gate, judge_agreement, policy_contract, screen_tokens, split_contract,
)
from evaluation.error_taxonomy import STAGES, diagnose


def screen(tokens, classify=lambda chunk: 'safe', **overrides):
    options = dict(context_tokens=8, reserved_tokens=2, overlap_tokens=2, max_chunks=100)
    options.update(overrides)
    return screen_tokens(tokens, classify, **options)


@pytest.mark.parametrize('length', [1, 6, 7, 10, 11, 101])
def test_safe07_every_suffix_token_reaches_guard_with_bounded_overlap(length):
    seen = []
    result = screen(range(length), lambda chunk: seen.append(chunk) or 'safe')
    assert result['screened'] and result['covered_tokens'] == length
    assert set().union(*map(set, seen)) == set(range(length))
    assert all(len(chunk) <= 6 for chunk in seen)
    assert all(a[-2:] == b[:2] for a, b in zip(seen, seen[1:]))


def test_safe07_cross_boundary_attack_and_last_token_are_inspected():
    def classify(chunk):
        return 'unsafe' if (4 in chunk and 5 in chunk) or 16 in chunk else 'safe'
    result = screen(range(17), classify)
    assert not result['allowed'] and result['status'] == 'unsafe'
    tail = screen(range(17), lambda chunk: 'unsafe' if 16 in chunk else 'safe')
    assert not tail['allowed'] and tail['covered_tokens'] == 17


def test_safe07_chunk_budget_rejects_before_spending_any_calls():
    calls = []
    result = screen(range(100), lambda chunk: calls.append(chunk), max_chunks=1)
    assert not calls and result['reason'] == 'chunk_budget'
    assert not result['allowed'] and not result['screened']


@pytest.mark.parametrize('overrides', [dict(overlap_tokens=6), dict(reserved_tokens=8),
    dict(max_chunks=True), dict(overlap_tokens=-1), dict(required='false')])
def test_safe07_invalid_limits_cannot_bypass_screening(overrides):
    with pytest.raises(ValueError):
        screen([1], **overrides)


@pytest.mark.parametrize('required', [True, False])
@pytest.mark.parametrize('failure', ['exception', 'invalid', 'none'])
def test_safe09_outages_never_claim_screened_and_required_checks_block(required, failure):
    def classify(chunk):
        if 8 not in chunk:
            return 'safe'
        if failure == 'exception':
            raise RuntimeError('PRIVATE CREDENTIAL')
        return 'PRIVATE CREDENTIAL' if failure == 'invalid' else None
    result = screen(range(20), classify, required=required)
    assert result['allowed'] is (not required)
    assert not result['screened'] and result['status'] == 'unavailable'
    assert result['covered_tokens'] < result['total_tokens']
    assert 'PRIVATE' not in str(result)


def policy():
    return dict(version='P1', text='Detect attempts to override trusted instructions.',
                task='prompt_injection', review_status='reviewed',
                review_basis='synthetic_test_fixture', review_evidence='fixture-review')


def policy_labels():
    return [dict(case_id='C1', attack=False, policy_version='P1', review_status='reviewed')]


def test_safe08_policy_scores_injection_separately_from_event_correctness():
    result = policy_contract(policy(), policy_labels())
    assert result['task'] == 'prompt_injection' and not result['event_correctness_assessed']


@pytest.mark.parametrize('field,value', [('task', 'construction_accuracy'),
    ('review_status', 'pending'), ('text', ''), ('review_evidence', '')])
def test_safe08_missing_or_unreviewed_policy_blocks(field, value):
    value_policy = policy()
    value_policy[field] = value
    with pytest.raises(ValueError):
        policy_contract(value_policy, policy_labels())


def test_safe08_label_version_mismatch_and_unreviewed_labels_block():
    for field, value in [('policy_version', 'P2'), ('review_status', 'pending')]:
        labels = policy_labels()
        labels[0][field] = value
        with pytest.raises(ValueError):
            policy_contract(policy(), labels)


def labels():
    return [dict(case_id=f'C{i}', correct=correct, review_status='reviewed',
                 review_evidence='synthetic-fixture')
            for i, correct in enumerate([True, False, True, False, True])]


def test_score06_judge_request_omits_model_identity_envelope():
    record = dict(source='Installed 2 m.', prediction='2 m installed', rubric='Check source.',
                  model='secret-model', account='private', expected=True)
    request = blind_judge_request(**{k: record[k] for k in ('source', 'prediction', 'rubric')})
    assert set(request) == {'source', 'prediction', 'rubric'}
    assert 'secret-model' not in str(request)
    with pytest.raises(TypeError):
        blind_judge_request(**record)


def test_score06_confusion_matrix_and_missing_judge_denominator():
    verdicts = [dict(case_id=f'C{i}', correct=v) for i, v in enumerate([True, True, False, False])]
    result = judge_agreement(labels(), verdicts)
    assert (result['tp'], result['tn'], result['fp'], result['fn']) == (1, 1, 1, 1)
    assert result['missing'] == 1 and result['agreement'] == .5
    assert result['agreement_over_scheduled'] == .4
    assert not result['release_accepted']


@pytest.mark.parametrize('verdicts', [[dict(case_id='UNKNOWN', correct=True)],
    [dict(case_id='C0', correct=True)] * 2, [dict(case_id='C0', correct=1)]])
def test_score06_invalid_judgments_reject(verdicts):
    with pytest.raises(ValueError):
        judge_agreement(labels(), verdicts)


def test_score08_critical_disagreement_requires_external_adjudication():
    args = dict(critical=True, worker_correct=True, judge_correct=False)
    assert disagreement_gate(**args)['blocked']
    result = disagreement_gate(**args, adjudication=dict(
        reviewer='fixture-reviewer', evidence='source-inspection', decision='neither'))
    assert not result['blocked'] and result['adjudicated']
    assert not result['agreement_is_factual_proof']
    with pytest.raises(ValueError):
        disagreement_gate(**args, adjudication=dict(reviewer='R', evidence='', decision='worker'))


def splits():
    return {split: [dict(case_id=split, group_id=f'family-{split}')]
            for split in ('train', 'development', 'validation', 'holdout')}


def test_data03_recorded_lineage_cannot_cross_splits_even_with_different_case_ids():
    manifest = splits()
    manifest['holdout'][0]['group_id'] = 'family-train'
    with pytest.raises(ValueError, match='lineage'):
        split_contract(manifest)
    assert not split_contract(splits())['freshness_certified']


@pytest.mark.parametrize('group', ['', ' padded ', None])
def test_data03_noncanonical_lineage_rejects(group):
    manifest = splits()
    manifest['holdout'][0]['group_id'] = group
    with pytest.raises(ValueError):
        split_contract(manifest)


def test_conf03_fit_roles_and_declared_consumed_holdout_are_enforced():
    args = dict(fit_case_ids=['validation'], evaluation_case_ids=['holdout'], consumed_groups=[])
    result = calibration_contract(splits(), **args)
    assert not result['thresholds_fitted'] and not result['freshness_certified']
    for override in [dict(fit_case_ids=['holdout']), dict(evaluation_case_ids=['validation']),
                     dict(consumed_groups=['family-holdout']), dict(fit_case_ids=[]),
                     dict(evaluation_case_ids=['holdout', 'holdout'])]:
        with pytest.raises(ValueError):
            calibration_contract(splits(), **(args | override))


@pytest.mark.parametrize('stage', sorted(STAGES))
def test_score10_all_workflow_stages_remain_stage_only_without_causal_evidence(stage):
    result = diagnose(state='failed', stage=stage)
    assert result['attribution'] == 'stage_only' and result['cause'] == stage


def test_score10_quota_and_bad_request_are_not_confused_with_model_quality():
    assert diagnose(state='failed', http_status=429)['cause'] == 'quota'
    assert diagnose(state='failed', http_status=400)['attribution'] == 'underlying_cause_unknown'


@pytest.mark.parametrize('effect', sorted(SAFETY_EFFECTS))
def test_gate01_every_defined_hard_safety_effect_stops_and_survives_restore(effect):
    gate = StopGate()
    gate.complete('before-stop')
    gate.observe(kind='safety', category=effect, evidence_sha256='a' * 64)
    snapshot = gate.snapshot()
    assert snapshot['affected_results'] == ['before-stop']
    assert snapshot['review_required'] and not snapshot['release_accepted']
    for stopped in [gate, StopGate.restore(snapshot)]:
        with pytest.raises(RuntimeError, match='stopped'):
            stopped.check()
        with pytest.raises(RuntimeError):
            stopped.complete('after-stop')
    assert gate.completed == ['before-stop']


@pytest.mark.parametrize('defect', sorted(DEFECTS))
def test_gate02_reported_semantic_defects_stop_even_when_artifact_hashes_unchanged(defect):
    gate = StopGate()
    gate.complete('T1')
    gate.observe(kind='integrity', category=defect, evidence_sha256='b' * 64)
    with pytest.raises(RuntimeError):
        StopGate.restore(gate.snapshot()).check()


def test_stop_snapshot_cannot_clear_review_flag_or_mutate_live_gate():
    gate = StopGate()
    gate.observe(kind='safety', category='unauthorized_access', evidence_sha256='a' * 64)
    snapshot = gate.snapshot()
    modified = deepcopy(snapshot)
    modified['review_required'] = False
    with pytest.raises(ValueError):
        StopGate.restore(modified)
    snapshot['stops'][0]['category'] = 'PRIVATE'
    assert gate.stops[0]['category'] == 'unauthorized_access'


def frozen_guard(tmp_path):
    import json
    from evaluation.experiment_guard import FrozenExperimentGuard
    prepared = tmp_path / 'prepared'
    prepared.mkdir()
    plan = dict(source_sha256={})
    (prepared / 'plan.json').write_text(json.dumps(plan))
    return FrozenExperimentGuard(prepared, plan)


@pytest.mark.parametrize('category', sorted(DEFECTS))
def test_gate02_existing_experiment_guard_blocks_on_reported_defect(tmp_path, category):
    import json
    from evaluation.experiment_guard import EvaluationIntegrityError
    guard = frozen_guard(tmp_path)
    output = tmp_path / 'stop.json'
    guard.report_defect(category=category, evidence_sha256='c' * 64, output=output)
    with pytest.raises(EvaluationIntegrityError, match='Reported evaluation defect'):
        guard.check()
    snapshot = json.loads(output.read_text())
    assert snapshot['review_required']
    assert snapshot['stops'][0]['category'] == category


def test_gate02_failed_evidence_write_still_stops_and_preserves_existing_file(tmp_path):
    from evaluation.experiment_guard import EvaluationIntegrityError
    guard = frozen_guard(tmp_path)
    output = tmp_path / 'existing.json'
    output.write_text('historical evidence')
    with pytest.raises(FileExistsError):
        guard.report_defect(category='scorer', evidence_sha256='d' * 64, output=output)
    assert output.read_text() == 'historical evidence'
    with pytest.raises(EvaluationIntegrityError):
        guard.check()
