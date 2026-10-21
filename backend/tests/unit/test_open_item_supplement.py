"""Known-answer protections for the literal missing study contrasts."""
from copy import deepcopy
import json

import pytest

from evaluation.open_item_study import prepare as primary_plan
from evaluation.open_item_supplement import payload_for, prepare


@pytest.fixture
def prepared(tmp_path):
    folder = tmp_path / 'primary'
    base = primary_plan(folder)
    plan = prepare(folder, tmp_path / 'supplement')
    return base, plan


def test_demonstration_groups_have_equal_count_and_explicit_abstention(prepared):
    _, plan = prepared
    groups = [text.split('Independent synthetic demonstrations:\n')[1].splitlines()
              for text in plan['prompts'].values()]
    assert all(len(group) == 2 for group in groups)
    ordinary, difficult = [[json.loads(line) for line in group] for group in groups]
    assert all(demo['output']['observations'] for demo in ordinary)
    assert any(demo['output']['observations'] == [] for demo in difficult)
    assert any(len(demo['output']['observations']) == 2 for demo in difficult)


def test_explicit_verdict_is_separate_and_never_receives_the_gold_or_worker_score(prepared):
    base, plan = prepared
    trial = next(row for row in plan['schedule'] if row['kind'] == 'verdict')
    prior = {trial['parent']: dict(value={'observations': []},
                                  checks={'selected_fields_exact': False}, secret_gold='HIDDEN-GOLD')}
    before = deepcopy(prior)
    payload = payload_for(trial, plan, base, prior)
    text = json.dumps(payload)
    assert 'HIDDEN-GOLD' not in text and 'selected_fields_exact' not in text
    assert 'supported' in payload['response_format']['json_schema']['schema']['properties']
    assert json.loads(payload['messages'][1]['content'])['worker'] == {'observations': []}
    assert prior == before


def test_randomized_judges_are_blinded_and_balanced_per_style(prepared):
    base, plan = prepared
    for style in ['concise', 'verbose']:
        trials = [r for r in plan['schedule'] if r['kind'] == 'judge' and r['style'] == style]
        assert {r['order'] for r in trials} == {'ab', 'ba'}
        for trial in trials:
            payload = payload_for(trial, plan, base, {})
            source = json.dumps(payload['messages'])
            assert '20b' not in source and '120b' not in source
            user = json.loads(payload['messages'][1]['content'])
            assert len(user['answers']) == 2
            assert '5 m3' in user['answers'][0 if trial['order'] == 'ab' else 1]
    assert plan['seed'] == 20261021
