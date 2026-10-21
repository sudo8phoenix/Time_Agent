"""Alternative annotation proposals preserve coherent event inventories."""
import copy
import json
from pathlib import Path

import pytest

from evaluation.development_contract import score_case

ROOT = Path(__file__).resolve().parents[3]
LABELS = ROOT / 'evaluation/fixtures/regression/annotations-v4/labels.json'


def correction():
    return json.loads(LABELS.read_text())['cases']['DEV-20261020-04']


def test_proposed_conventions_keep_correction_safety_and_separate_today_no_work():
    case = correction()
    for alternative in case['alternatives']:
        events = alternative['events']
        result = score_case(case, list(reversed(events)), completed=True)
        assert result['accepted_alternative_ids'] == [alternative['id']]
        assert result['semantic_evidence_correct'] is None
        corrected = next(x for x in events if x['event_type'] == 'correction')
        assert corrected['quantity'] is None and corrected['unit'] is None
        assert corrected['quantity_kind'] == 'none'
        no_work = next(x for x in events if x['event_type'] == 'no_work')
        assert no_work['work_date'] == '2026-10-20'
        unsafe = copy.deepcopy(events)
        unsafe[0]['quantity'] = '6'
        assert not score_case(case, unsafe, completed=True)['fields_exact_any_alternative']
        assert not score_case(case, events[:1], completed=True)['fields_exact_any_alternative']


@pytest.mark.parametrize('completed', [False, None, 'completed'])
def test_matching_failed_or_unverified_outputs_do_not_pass(completed):
    case = correction()
    assert not score_case(case, case['alternatives'][0]['events'], completed=completed)['fields_exact_any_alternative']


def test_alternatives_do_not_allow_per_field_cherry_picking():
    case = correction()
    case['alternatives'][1]['events'][0]['area'] = 'Zone Different'
    hybrid = copy.deepcopy(case['alternatives'][1]['events'])
    hybrid[0]['area'] = 'Zone Cedar'
    assert not score_case(case, hybrid, completed=True)['fields_exact_any_alternative']


def test_invalid_or_inconsistent_alternative_inventories_fail_closed():
    with pytest.raises(ValueError):
        score_case({'alternatives': []}, [], completed=True)
    case = correction()
    case['alternatives'][1]['id'] = case['alternatives'][0]['id']
    with pytest.raises(ValueError, match='Duplicate'):
        score_case(case, [], completed=True)
    case = correction()
    del case['alternatives'][1]['events'][0]['date_basis']
    with pytest.raises(ValueError, match='same explicit fields'):
        score_case(case, [], completed=True)


def test_all_proposed_cases_have_full_consumed_source_inventory_and_preserved_parents():
    from hashlib import sha256
    labels = json.loads(LABELS.read_text())
    original = json.loads((ROOT / 'evaluation/fixtures/paired-development-v2/labels.json').read_text())
    assert set(labels['cases']) == set(original['cases'])
    assert labels['split'] == 'consumed-development'
    for case in labels['cases'].values():
        events = case['alternatives'][0]['events']
        assert score_case(case, events, completed=True)['fields_exact_any_alternative']
    provenance = json.loads(LABELS.with_name('provenance.json').read_text())
    assert not provenance['eligible_for_fresh_holdout']
    for path, digest in provenance['parents'].items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == digest


def test_unknown_annotation_fields_cannot_silently_escape_scoring():
    case = correction()
    for alternative in case['alternatives']:
        for event in alternative['events']:
            event['discipline'] = 'civil'
    with pytest.raises(ValueError, match='Unsupported annotation'):
        score_case(case, [], completed=True)
