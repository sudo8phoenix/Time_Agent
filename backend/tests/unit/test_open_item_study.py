"""Known-answer safeguards for the live development study's interpretation."""
from copy import deepcopy
import json

import pytest

from evaluation.open_item_study import (
    TARGETS, extraction_checks, make_payload, prepare, projection,
)
from evaluation.prompt_ablation import observation


@pytest.fixture
def plan(tmp_path):
    return prepare(tmp_path / 'prepared')


def test_target_inventory_names_twenty_five_existing_distinct_requirements(plan):
    assert len(TARGETS) == len(set(TARGETS)) == 25
    assert len(plan['schedule']) == 88
    assert len({r['id'] for r in plan['schedule']}) == 88
    assert plan['key_slot'] == 2 and not plan['release_accepted']


def test_gold_is_not_sent_as_feedback_to_repair_or_critic(plan):
    parent = {'value': {'observations': []}, 'checks': {
        'domain_valid': True, 'quotes_grounded': True, 'selected_fields_exact': False,
        'private_gold': 'DO-NOT-SEND'}}
    for trial in plan['schedule']:
        if trial['kind'] not in {'repair', 'critic'}:
            continue
        payload = make_payload(trial, plan, {trial['parent']: parent})
        encoded = json.dumps(payload)
        assert 'DO-NOT-SEND' not in encoded and 'selected_fields_exact' not in encoded
        assert 'Previous worker output' in encoded
        assert 'Deterministic validator feedback' in encoded


def test_zero_few_wire_pairs_hold_context_schema_and_settings_fixed(plan):
    case = 'DEV-20261020-01'
    trials = {r['id']: r for r in plan['schedule']}
    a, b = [make_payload(trials[f'{arm}:{case}'], plan, {}) for arm in ['zero', 'few']]
    assert a['messages'][0]['content'] != b['messages'][0]['content']
    assert a['messages'][1] == b['messages'][1]
    a['messages'] = b['messages']
    assert a == b


@pytest.mark.parametrize('mutation', ['quote', 'fragment', 'domain', 'quantity'])
def test_exact_fields_cannot_hide_evidence_domain_or_value_failure(mutation):
    case = dict(case_id='test', text='Today, excavated 5 m3 in Zone Demo at DEMO-071.')
    value = observation('test', case['text'], quantity='5', unit='m3', raw_unit='m3', quantity_kind='delta')
    expected = projection({'observations': [value]})
    if mutation == 'quote':
        value['evidence'][0]['quote'] = 'This was never in the source'
    elif mutation == 'fragment':
        value['evidence'][0]['fragment_id'] = 'foreign'
    elif mutation == 'domain':
        value['summary'] = ''
    else:
        value['quantity'] = '9'
    assert not extraction_checks({'observations': [value]}, case, expected)['selected_fields_exact']


def test_true_known_answer_and_empty_no_event_are_scored_correctly():
    case = dict(case_id='test', text='Today, excavated 5 m3 in Zone Demo at DEMO-071.')
    value = observation('test', case['text'], quantity='5', unit='m3', raw_unit='m3', quantity_kind='delta')
    expected = projection({'observations': [value]})
    assert extraction_checks({'observations': [value]}, case, expected)['selected_fields_exact']
    assert extraction_checks({'observations': []}, dict(case_id='empty', text=''), [])['selected_fields_exact']
    assert not extraction_checks({'observations': []}, case, expected)['selected_fields_exact']


def test_selection_missing_candidate_never_contains_the_oracle(plan):
    trials = [r for r in plan['schedule'] if r['kind'] == 'selection' and r['case'] == 'missing']
    for trial in trials:
        user = json.loads(make_payload(trial, plan, {})['messages'][1]['content'])
        assert all(c['candidate_id'] != 'east' for c in user['candidates'])
        assert len(user['candidates']) == trial['count']


def test_example_order_uses_same_examples_without_gold_or_context_changes(plan):
    trial = next(r for r in plan['schedule'] if r['id'].startswith('reverse:'))
    a = make_payload(trial, plan, {})
    b = make_payload({**trial, 'prompt': 'few'}, plan, {})
    assert a['messages'][1] == b['messages'][1]
    demos_a = a['messages'][0]['content'].split('Development demonstrations follow.')[1].splitlines()[1:]
    demos_b = b['messages'][0]['content'].split('Development demonstrations follow.')[1].splitlines()[1:]
    assert sorted(demos_a) == sorted(demos_b)


def test_robustness_mutations_change_expected_fact_without_relabelling_other_fields(plan):
    base = plan['labels']['DEV-20261020-01'][0]
    for name, field in [('quantity', 'quantity'), ('date', 'work_date'),
                        ('location', 'area'), ('unit', 'unit')]:
        expected = deepcopy(plan['labels'][name][0])
        assert expected.pop(field) != base[field]
        original = deepcopy(base)
        original.pop(field)
        assert expected == original
