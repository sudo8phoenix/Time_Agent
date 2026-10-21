"""Real plan, runner and durable registry tests; no network or holdout inference."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

from evaluation.frozen_acceptance import capture, load_inputs
from evaluation.prepare_repeated_development import FIXTURE, prepare
from evaluation.repeated_development import execute
from evaluation.score_repeated_development import score
from evaluation.study_controls import (
    ConsumptionRegistry, configuration_digest, guard_holdout, pairing, preregister, verify_registration,
    verify_holdout_result,
)
from backend.tests.unit.test_repeated_development_runtime import preflight, response


@pytest.fixture
def prepared(tmp_path):
    folder = tmp_path/'prepared'
    plan = prepare(folder, 'few-shot', case_ids=['DEV-20261020-01', 'DEV-20261020-02'], repetitions=1)
    return folder, plan


def test_prompt01_real_wire_requests_share_schema_context_settings_scorer_and_exclude_gold(prepared, tmp_path):
    folder, plan = prepared
    seen = []
    def transport(method, url, payload, timeout, headers):
        seen.append(deepcopy(payload))
        return response(payload)
    execute(folder, tmp_path/'capture', preflight(plan), transport=transport)
    assert len(seen) == 4
    for first, second in zip(seen[::2], seen[1::2]):
        assert first['messages'][1:] == second['messages'][1:]
        assert {p['messages'][0]['content'] for p in (first, second)} == set(plan['prompts'].values())
        assert first['response_format'] == second['response_format']
        assert first['model'] == second['model']
        assert first['max_completion_tokens'] == second['max_completion_tokens']
        assert 'expected_activity_ids' not in json.dumps(first['messages'])
        assert 'expected_activity_ids' not in json.dumps(second['messages'])
    assert plan['prompts']['few-shot'].startswith(plan['prompts']['zero-shot'])
    result = score(tmp_path/'capture', FIXTURE/'labels.json', FIXTURE/'lineage.json')
    assert all(arm['raw_exact'] == 0 for arm in result['arms'].values())
    # Empty fixture outputs receive no semantic credit, despite valid schemas.


def test_exp01_freezes_real_plan_primary_budget_source_and_stops_exclusively(prepared, tmp_path):
    folder, plan = prepared
    path = tmp_path/'registration.json'
    registration = preregister(folder, path, hypothesis='Three fixed examples improve exact fields over concise zero-shot.')
    assert registration['budget'] == plan['budget']
    assert registration['budget']['calls'] == 4
    assert registration['primary_metric'] == plan['primary_metric']
    assert registration['stop_conditions'] == plan['stop_conditions']
    assert registration['live_execution_authorized'] is False
    assert verify_registration(folder, path) == registration
    with pytest.raises(FileExistsError):
        preregister(folder, path, hypothesis='Overwrite hypothesis')


def test_exp02_pairs_counterbalance_case_order_without_claiming_equivalent_live_quotas(prepared):
    _, plan = prepared
    result = pairing(plan)
    assert result['pair_count'] == 2 and result['counterbalanced']
    assert {r['first_arm'] for r in result['orders']} == {'zero-shot', 'few-shot'}
    assert result['quota_conditions_verified'] is False
    bad = deepcopy(plan)
    bad['schedule'][1]['arm'] = bad['schedule'][0]['arm']
    with pytest.raises(ValueError, match='both distinct arms'):
        pairing(bad)


@pytest.mark.parametrize('field', ['baseline_prompt_sha256', 'controls_source_sha256', 'model',
                                  'credential_slot_alias', 'primary_metric', 'membership'])
def test_registered_metadata_drift_rejects(prepared, tmp_path, field):
    folder, _ = prepared
    path = tmp_path/'registration.json'
    record = preregister(folder, path, hypothesis='Fixed development comparison')
    record[field] = [] if field == 'membership' else 'tampered'
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        verify_registration(folder, path)


def test_data12_dataset_labels_code_and_membership_are_hashed_and_consumption_survives_reopen(prepared, tmp_path):
    folder, _ = prepared
    path = tmp_path/'registration.json'
    record = preregister(folder, path, hypothesis='Development only')
    sources = record['dataset_label_source_sha256']
    assert any(p.endswith('labels.json') for p in sources)
    assert any(p.endswith('lineage.json') for p in sources)
    assert any(p.endswith('repeated_development.py') for p in sources)
    for name, expected in sources.items():
        assert sha256(Path(name).read_bytes()).hexdigest() == expected
    registry = ConsumptionRegistry(tmp_path/'consumed.sqlite')
    registry.reserve(record['membership'], split='development', configuration_sha256='a'*64,
                     dataset_sha256=record['plan_sha256'], tuning_status='ongoing')
    saved = ConsumptionRegistry(registry.path).snapshot()
    assert len(saved) == 2 and all(row['recorded_at'] for row in saved)
    with pytest.raises(ValueError, match='already consumed'):
        ConsumptionRegistry(registry.path).reserve(record['membership'], split='holdout',
            configuration_sha256='b'*64, dataset_sha256='c'*64, tuning_status='stopped')
    assert registry.snapshot() == saved


def test_exp10_holdout_input_never_opened_while_tuning(tmp_path, monkeypatch):
    inputs, manifest = tmp_path/'inputs.jsonl', tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'holdout_control': {'tuning_status': 'ongoing'}}))
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        assert path != inputs, 'Holdout content opened before tuning gate'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)
    with pytest.raises(ValueError, match='Stop tuning'):
        load_inputs(inputs, manifest, 'holdout')


def test_holdout_capture_without_registry_stops_before_settings_db_or_provider(tmp_path, monkeypatch):
    monkeypatch.setattr('evaluation.frozen_acceptance.get_settings', lambda: pytest.fail('Settings reached'))
    with pytest.raises(ValueError, match='retained consumption registry'):
        capture(tmp_path/'in', tmp_path/'manifest', tmp_path/'out', 'holdout', 'unused')


def test_exp10_actual_guard_consumes_before_attempt_and_retains_failed_attempt_families(tmp_path):
    config = {'model': 'contract-only-fixture', 'prompt': 'v1'}
    manifest = {'holdout_control': {'tuning_status': 'stopped', 'configuration_sha256': configuration_digest(config)}}
    rows = [dict(group_id='contract-only-family', parent_group_ids=['source-ancestor'])]
    registry = tmp_path/'retained.sqlite'
    result = guard_holdout(rows, manifest, registry=registry, configuration=config, dataset_sha256='a'*64)
    assert result['families_reserved'] == 2
    # Inference may now fail. There is no reset/rollback API that restores freshness.
    with pytest.raises(ValueError, match='already consumed'):
        guard_holdout(rows, manifest, registry=registry, configuration=config, dataset_sha256='a'*64)
    changed = {'model': 'contract-only-fixture', 'prompt': 'v2'}
    updated_manifest = {'holdout_control': {'tuning_status': 'stopped', 'configuration_sha256': configuration_digest(changed)}}
    with pytest.raises(ValueError, match='already consumed'):
        guard_holdout(rows, updated_manifest, registry=registry, configuration=changed, dataset_sha256='b'*64)
    fresh_rows = [dict(group_id='second-contract-only-family')]
    assert guard_holdout(fresh_rows, updated_manifest, registry=registry,
                         configuration=changed, dataset_sha256='b'*64)['families_reserved'] == 1


@pytest.mark.parametrize('mutation', ['tuning', 'configuration', 'registry'])
def test_guard_failure_creates_no_consumption(mutation, tmp_path):
    config = {'model': 'fixture'}
    manifest = {'holdout_control': {'tuning_status': 'stopped', 'configuration_sha256': configuration_digest(config)}}
    registry = tmp_path/'registry.sqlite'
    if mutation == 'tuning':
        manifest['holdout_control']['tuning_status'] = 'ongoing'
    elif mutation == 'configuration':
        config['model'] = 'changed'
    with pytest.raises(ValueError):
        guard_holdout([dict(group_id='test')], manifest, registry=None if mutation == 'registry' else registry,
                      configuration=config, dataset_sha256='a'*64)
    assert not registry.exists()


def test_concurrent_holdout_reservations_have_only_one_winner(tmp_path):
    path = tmp_path/'registry.sqlite'
    ConsumptionRegistry(path)
    def attempt(_):
        try:
            return ConsumptionRegistry(path).reserve([dict(group_id='same-family')], split='holdout',
                configuration_sha256='a'*64, dataset_sha256='b'*64, tuning_status='stopped')
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(r is not None for r in results) == 1
    assert len(ConsumptionRegistry(path).snapshot()) == 1


def test_new_holdout_scorer_requires_frozen_reservation_and_preserves_explicit_historical_mode():
    with pytest.raises(ValueError, match='pre-inference'):
        verify_holdout_result({'split': 'holdout'}, {})
    historic = verify_holdout_result({'split': 'holdout'}, {}, historical_diagnostic=True)
    assert historic['fresh_acceptance_evidence'] is False
    assert historic['release_accepted'] is False
    assert verify_holdout_result({'split': 'validation'}, {})['holdout'] is False


def test_scorer_gate_stops_before_parsing_labels_or_predictions(tmp_path, monkeypatch):
    from evaluation import score_frozen_acceptance as scorer
    capture_path = tmp_path/'capture'
    capture_path.mkdir()
    for name, value in [('config.json', '{"split":"holdout"}'), ('predictions.jsonl', ''), ('calls.jsonl', '')]:
        (capture_path/name).write_text(value)
    manifest = tmp_path/'manifest.json'
    manifest.write_text('{}')
    (capture_path/'capture-manifest.json').write_text(json.dumps({'hashes': {
        p.name: sha256(p.read_bytes()).hexdigest() for p in capture_path.iterdir()}}))
    monkeypatch.setattr(scorer, 'rows', lambda _: pytest.fail('Outcome/label content parsed before gate'))
    monkeypatch.setattr(sys, 'argv', ['scorer', '--capture', str(capture_path), '--inputs', str(tmp_path/'unopened-input'),
                                    '--labels', str(tmp_path/'unopened-labels'), '--manifest', str(manifest),
                                    '--output-dir', str(tmp_path/'output')])
    with pytest.raises(SystemExit):
        scorer.main()
    assert not (tmp_path/'output').exists()


def test_holdout_result_uses_actual_sealed_configuration_not_just_a_declared_reservation():
    configuration = dict(provider='fixture', model='model', key_slot=2, prompt_version='v1',
                         prompt_sha256='a'*64, timeout_seconds=60, source_sha256={'source.py': 'b'*64})
    identity = configuration_digest(configuration)
    manifest = {'holdout_control': {'tuning_status': 'stopped', 'configuration_sha256': identity}}
    config = dict(configuration, split='holdout', inputs_sha256='c'*64,
                  holdout_reservation=dict(configuration_sha256=identity, dataset_sha256='c'*64, families_reserved=1))
    assert verify_holdout_result(config, manifest)['historical_diagnostic'] is False
    config['model'] = 'new-tuned-model'
    with pytest.raises(ValueError, match='changed'):
        verify_holdout_result(config, manifest)
