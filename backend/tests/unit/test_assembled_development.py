from copy import deepcopy
import json

import pytest

from app.llm.groq import GroqChatAdapter
from app.settings import Settings
from evaluation.assembled_development import MODEL, Recorder, full_case_score, prepare, verify
from evaluation.repeated_development import ExperimentStop


def test_plan_keeps_input_and_gold_separate_and_rejects_role_tampering(tmp_path):
    prepared = tmp_path/'prepared'
    plan = prepare(prepared)
    frozen, inputs = verify(prepared)
    assert frozen == plan
    assert len(plan['schedule']) == 4
    assert all(set(row) == {'case_id', 'report_date', 'text'} for row in inputs)
    plan['roles']['selection']['key_slot'] = 0
    (prepared/'plan.json').write_text(json.dumps(plan))
    with pytest.raises(ExperimentStop):
        verify(prepared)


def test_ambiguity_requires_preserved_facts_and_exact_mapping_state():
    label = dict(expected_activity_ids=[], expected_mapping_state='ambiguous', expected_quantity='2',
                 expected_area=None, expected_asset_tags=[])
    row = dict(state='ready_for_review', mapping_states=['ambiguous'], selected_activity_ids=[],
               ledger_writes=0, review_states=['pending'], observations=[dict(event_type='actual_progress',
               quantity='2.0000', quantity_kind='delta', unit='m3', work_date='2026-10-20', area=None, asset_tags=[])])
    assert full_case_score(row, label, '2026-10-20')['full_report_exact']
    for changes in [dict(observations=[]), dict(mapping_states=['unmatched']),
                    dict(ledger_writes=1), dict(selected_activity_ids=['EXC-CEDAR']),
                    dict(review_states=['approved']), dict(state='failed')]:
        assert not full_case_score({**row, **changes}, label, '2026-10-20')['full_report_exact']
    invented = deepcopy(row)
    invented['observations'][0]['asset_tags'] = ['TR-030']
    assert not full_case_score(invented, label, '2026-10-20')['full_report_exact']


def test_recorder_enforces_output_budget_and_stops_without_credential_fallback(tmp_path):
    plan = prepare(tmp_path/'prepared')
    output = tmp_path/'capture'
    output.mkdir()
    seen = []
    def transport(provider, method, url, payload, timeout, headers):
        seen.append(deepcopy(payload))
        assert provider == 'groq' and payload['model'] == MODEL
        assert payload['max_completion_tokens'] == 3072
        assert payload['response_format']['json_schema']['strict'] is True
        assert payload['messages'][0]['content'] == plan['extraction_prompt']
        return 400, {}
    recorder = Recorder(plan, output, transport=transport)
    recorder.factory = lambda *args, **kwargs: GroqChatAdapter(MODEL, bearer_token='injected-token')
    adapter = recorder.create(Settings(_env_file=None), role='extraction', timeout=180)
    kwargs = dict(system='original', user={'fragments': []}, schema={'type': 'object', 'properties': {
        'observations': {'type': 'array', 'items': {'type': 'object', 'properties': {}}}}, 'required': ['observations']})
    with pytest.raises(ExperimentStop):
        adapter.chat(**kwargs)
    with pytest.raises(ExperimentStop):
        adapter.chat(**kwargs)
    assert len(seen) == recorder.budget.calls == len(recorder.calls) == 1
    assert recorder.stopped
