"""Executable examples for specification definitions, not model quality trials."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent.schedule_decision import select_activity, shortlist_activities
from app.llm.extract import FragmentInput, extract_fragments
from app.schemas.observation import ObservationBatch

FIXTURE = Path('evaluation/fixtures/stage-specification-v1/cases.json')
CASES = json.loads(FIXTURE.read_text())['cases']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['case_id'])
def test_defined_examples_pass_domain_and_source_evidence_pipeline(case):
    expected = deepcopy(case['expected'])
    validated = ObservationBatch.model_validate(expected).model_dump(mode='json')
    result = extract_fragments(
        [FragmentInput(case['case_id'], 'specification-example', case['text'])],
        lambda **_: deepcopy(expected), report_date=date.fromisoformat(case['report_date']),
        report_date_trusted=case['report_date_trusted'])
    assert len(result) == 1 and not result[0].errors
    if case['case_id'] == 'SPEC-CONFLICT':
        # The production normalizer clears conflicting dates and preserves the
        # conflict as warnings/evidence; raw conflicting basis remains in fixture.
        normalized = validated['observations'][0]
        normalized['date_basis'] = 'unknown'
        normalized['warnings'].append(
            'Conflicting report/current-day dates require reviewer clarification.')
    assert [o.model_dump(mode='json') for o in result[0].observations] == validated['observations']
    assert case['expected'] == expected


@pytest.mark.parametrize('field', ['unit', 'quantity', 'work_date', 'actual_start'])
def test_strings_are_not_raw_json_null(field):
    value = deepcopy(next(c for c in CASES if c['case_id'] == 'SPEC-MISSING')['expected'])
    assert value['observations'][0][field] is None
    value['observations'][0][field] = 'null'
    with pytest.raises(ValidationError):
        ObservationBatch.model_validate(value)


def test_schedule_context_cannot_backfill_source_unit_or_quantity_during_matching():
    case = next(c for c in CASES if c['case_id'] == 'SPEC-NOUNIT')
    source = deepcopy(case['expected']['observations'][0])
    original = deepcopy(source)
    identifier = str(uuid4())
    schedule = dict(id=identifier, external_id='TR-001', name='Excavation',
                    discipline='civil', work_type='excavation', area=None,
                    asset_tags='', is_leaf=True, **case['schedule_context'])
    seen = []

    def shortlist(**request):
        seen.append(request)
        assert request['user']['observation']['unit'] is None
        assert request['user']['schedule_activities'][0]['unit'] == 'm3'
        return {'candidate_ids': [identifier]}

    candidates = shortlist_activities(source, 'pinned', [schedule], model_call=shortlist)

    def selection(**request):
        seen.append(request)
        assert request['user']['observation']['quantity'] is None
        return dict(candidate_id=None, mapping_state='unmatched',
                    evidence_fragment_ids=[], reason_codes=['REVIEW'],
                    explanation='Clarify identity and measurement.',
                    missing_information=['Activity identity and source measurement'])

    proposal = select_activity(source, candidates, {case['case_id']: case['text']},
                               model_call=selection)
    assert proposal.candidate_id is None
    assert source == original and source['raw_unit'] is None
    assert len(seen) == 2


def test_no_candidates_abstains_without_model_and_empty_extraction_is_valid():
    def forbidden(**_):
        pytest.fail('No candidates must not invoke selection')
    proposal = select_activity({'summary': 'Unresolved work'}, [], {}, model_call=forbidden)
    assert proposal.candidate_id is None and proposal.mapping_state.value == 'unmatched'
    assert ObservationBatch.model_validate({'observations': []}).observations == []
