"""Twenty additional offline study-integrity checks; no provider inference."""
from copy import deepcopy

import pytest

from evaluation.study_controls import (
    ConsumptionRegistry, configuration_digest, pairing, verify_holdout_result,
    preregister, verify_registration,
)
from evaluation.prepare_repeated_development import prepare


@pytest.mark.parametrize('schedule', [[], [('a', 'x')], [('a', 'x'), ('a', 'x')],
                                    [('a', 'x'), ('a', 'y'), ('a', 'y')]])
def test_pairing_rejects_empty_missing_duplicate_or_extra_arm(schedule):
    plan = {'prompts': {'x': '', 'y': ''}, 'schedule': [
        {'case_id': case, 'repetition': 1, 'arm': arm} for case, arm in schedule]}
    with pytest.raises(ValueError):
        pairing(plan)


@pytest.mark.parametrize('bad_hash', ['', 'a' * 63, 'A' * 64, 'g' * 64])
def test_invalid_hash_never_reserves_a_family(tmp_path, bad_hash):
    registry = ConsumptionRegistry(tmp_path / 'registry.sqlite')
    with pytest.raises(ValueError):
        registry.reserve([{'group_id': 'family'}], split='holdout',
                         configuration_sha256=bad_hash, dataset_sha256='b' * 64,
                         tuning_status='stopped')
    assert registry.snapshot() == []


@pytest.mark.parametrize('row', [
    {'group_id': ' family'}, {'group_id': 'family '},
    {'group_id': 'family', 'parent_group_ids': [' ancestor']},
    {'group_id': 'family', 'parent_group_ids': ['ancestor ']},
])
def test_whitespace_cannot_disguise_consumed_lineage(tmp_path, row):
    registry = ConsumptionRegistry(tmp_path / 'registry.sqlite')
    with pytest.raises(ValueError):
        registry.reserve([row], split='holdout', configuration_sha256='a' * 64,
                         dataset_sha256='b' * 64, tuning_status='stopped')
    assert registry.snapshot() == []


@pytest.mark.parametrize('rows', [
    [{'group_id': 'fresh'}, {'group_id': 'used'}],
    [{'group_id': 'fresh', 'parent_group_ids': ['used']}],
    [{'group_id': 'fresh'}, {'group_id': 'child', 'parent_group_ids': ['used']}],
])
def test_lineage_collision_rolls_back_entire_reservation(tmp_path, rows):
    registry = ConsumptionRegistry(tmp_path / 'registry.sqlite')
    kwargs = dict(split='development', configuration_sha256='a' * 64,
                  dataset_sha256='b' * 64, tuning_status='ongoing')
    registry.reserve([{'group_id': 'used'}], **kwargs)
    before = registry.snapshot()
    with pytest.raises(ValueError, match='already consumed'):
        registry.reserve(rows, **{**kwargs, 'split': 'holdout', 'tuning_status': 'stopped'})
    assert ConsumptionRegistry(registry.path).snapshot() == before


@pytest.mark.parametrize('count', [True, 0, -1])
def test_holdout_scorer_rejects_false_family_counts(count):
    configuration = dict(provider='fixture', model='fixture', key_slot=2,
                         prompt_version='v1', prompt_sha256='a' * 64,
                         timeout_seconds=60, source_sha256={'test.py': 'b' * 64})
    identity = configuration_digest(configuration)
    manifest = {'holdout_control': {'tuning_status': 'stopped', 'configuration_sha256': identity}}
    config = dict(configuration, split='holdout', inputs_sha256='c' * 64,
                  holdout_reservation=dict(configuration_sha256=identity,
                                          dataset_sha256='c' * 64, families_reserved=count))
    before = deepcopy(config)
    with pytest.raises(ValueError):
        verify_holdout_result(config, manifest)
    assert config == before


@pytest.mark.parametrize('field', ['release_accepted', 'consumed_development'])
def test_registration_cannot_claim_release_or_unconsumed_development(tmp_path, field):
    import json
    prepared = tmp_path / 'prepared'
    prepare(prepared, 'few-shot', case_ids=['DEV-20261020-01'], repetitions=1)
    path = tmp_path / 'registration.json'
    registration = preregister(prepared, path, hypothesis='Fixed offline integrity test')
    registration[field] = field == 'release_accepted'
    path.write_text(json.dumps(registration))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        verify_registration(prepared, path)
    assert path.read_bytes() == before
