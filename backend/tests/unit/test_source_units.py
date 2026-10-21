from copy import deepcopy
import json

import pytest

from app.llm.extract import extraction_schema
from app.llm.openrouter import _matches_schema
from evaluation.prepare_repeated_development import prepare, FIXTURE
from evaluation.repeated_development import execute
from evaluation.source_units import MAX_UNITS, source_units, unit_schema, project
from evaluation.strict_schema import build_wire_schema
from test_repeated_development_runtime import preflight


def test_spans_preserve_every_character_decimal_and_leading_whitespace_with_bounded_slots():
    for text in ['\n Today, excavated 5.5 m3. No work occurred today.\n\n', 'Note. '*200, 'One unpunctuated clause']:
        units = source_units(text)
        assert 1 <= len(units) <= MAX_UNITS
        assert ''.join(unit['focus'] for unit in units) == text
        assert all(unit['focus'] == text[unit['start']:unit['end']] for unit in units)
        assert units[0]['start'] == 0 and units[-1]['end'] == len(text)
    assert '5.5 m3.' in source_units('Excavated 5.5 m3. No work.')[0]['focus']
    with pytest.raises(ValueError):
        source_units(' \n')


def test_projection_preserves_fields_and_duplicates_but_requires_all_legal_units_once():
    units = source_units('A fact. Another fact.')
    observation = {'event_type': 'correction', 'quantity': '6', 'warnings': ['unmodified']}
    native = {'units': [{'unit_id': 'u2', 'observations': [observation]},
                        {'unit_id': 'u1', 'observations': [observation]}]}
    original = deepcopy(native)
    output = project(native, units)
    assert output == {'observations': [observation, observation]}
    assert native == original
    output['observations'][0]['quantity'] = None
    assert native == original
    for rows in [native['units'][:1], native['units'] * 2,
                 [{'unit_id': 'u3', 'observations': []}], [{'unit_id': 'u1', 'observations': [None]}]]:
        with pytest.raises(ValueError):
            project({'units': rows}, units)


def test_unit_schema_preserves_observation_contract_and_closes_output_objects():
    flat, _ = build_wire_schema(extraction_schema())
    original = deepcopy(flat)
    wire = unit_schema(flat)
    assert flat == original and flat['$defs'] == wire['$defs']
    assert wire['properties']['units']['items']['properties']['observations'] == flat['properties']['observations']
    assert _matches_schema({'units': [{'unit_id': 'u1', 'observations': []}]}, wire)
    assert not _matches_schema({'units': [{'unit_id': 'invented', 'observations': []}]}, wire)
    assert not _matches_schema({'units': [{'unit_id': 'u1', 'observations': [], 'approval': True}]}, wire)


def test_unit_runner_retains_native_and_projected_values_and_adequate_fixed_deadline(tmp_path):
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared, 'source-units', case_ids=['DEV-20261020-04','DEV-20261020-07'],
                   repetitions=1, request_seconds=180)
    seen = []
    def transport(method, url, payload, timeout, headers):
        seen.append(payload)
        if 'units' in payload['response_format']['json_schema']['schema']['properties']:
            user = json.loads(payload['messages'][1]['content'])
            assert set(user) == {'fragment_context', 'source_units'}
            assert 'expected' not in user
            content = {'units': [{'unit_id': u['unit_id'], 'observations': []} for u in user['source_units']]}
        else:
            content = {'observations': []}
        return 200, {'model': payload['model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content)}}]}
    output = tmp_path / 'capture'
    result = execute(prepared, output, preflight(plan), transport=transport)
    assert result['completed'] == 4 and result['reserved_calls'] == 4
    assert plan['budget']['request_seconds'] == 180 and plan['budget']['wall_seconds'] == 720
    rows = [json.loads(line) for line in (output/'model-outputs.jsonl').read_text().splitlines()]
    assert len([row for row in rows if 'wire_value' in row]) == 2
    assert all(row['value'] == {'observations': []} for row in rows)
    assert all(row['projection'] == 'source-order concatenation; no field changes' for row in rows if 'wire_value' in row)
    from evaluation.score_repeated_development import score
    scored = score(output, FIXTURE/'labels.json', FIXTURE/'lineage.json')
    assert all(not row['raw_fields_exact'] for row in scored['trials'])


def test_missing_source_unit_stops_without_inventing_the_missing_assertion(tmp_path):
    prepared = tmp_path / 'prepared'
    plan = prepare(prepared, 'source-units', case_ids=['DEV-20261020-04'], repetitions=1)
    def transport(method,url,payload,timeout,headers):
        units = 'units' in payload['response_format']['json_schema']['schema']['properties']
        value = {'units': [{'unit_id': 'u1', 'observations': []}]} if units else {'observations': []}
        return 200, {'model': payload['model'], 'choices': [{'finish_reason': 'stop','message': {'content': json.dumps(value)}}]}
    output = tmp_path/'capture'
    result = execute(prepared, output, preflight(plan), transport=transport)
    assert result['attempted'] == 2 and result['completed'] == 1
    row = json.loads((output/'predictions.jsonl').read_text().splitlines()[-1])
    assert row['state'] == 'failed' and row['response_checks']['source_units_complete'] is False
    assert 'observations' not in row


def test_strict_decomposition_closes_both_schemas_and_holds_flag_constant(tmp_path):
    plan = prepare(tmp_path/'prepared','source-units',case_ids=['DEV-20261020-04','DEV-20261020-07'],
                   repetitions=1,request_seconds=180,strict_all=True)
    assert {row['strict'] for row in plan['schedule']} == {True}
    assert {row['response_mode'] for row in plan['schedule']} == {'flat','source-units'}
    wire=json.loads((tmp_path/'prepared/unit-wire-schema.json').read_text())
    assert wire['required'] == ['units'] and wire['additionalProperties'] is False
    assert wire['properties']['units']['items']['additionalProperties'] is False
    assert wire['$defs']['Observation']['required'] == list(wire['$defs']['Observation']['properties'])
    with pytest.raises(ValueError):
        prepare(tmp_path/'confounded','strict',strict_all=True)


def test_fixed_sentence_map_keeps_both_correction_amounts_in_one_focus_and_preserves_raw_fields():
    from evaluation.source_units import mapped_schema, project_map
    case=json.loads((FIXTURE/'inputs.json').read_text())[3]
    units=source_units(case['text'],split_semicolons=False)
    assert len(units)==2
    assert '8 m3' in units[0]['focus'] and '6 m3' in units[0]['focus']
    assert 'no excavation occurred today' in units[1]['focus']
    flat,_=build_wire_schema(extraction_schema())
    wire=mapped_schema(flat,units)
    assert wire['required']==['u1','u2']
    values={'u2':{'observations':[{'quantity':'6'}]},'u1':{'observations':[{'quantity':None}]}}
    original=deepcopy(values)
    assert project_map(values,units)=={'observations':[{'quantity':None},{'quantity':'6'}]}
    assert original==values
    with pytest.raises(ValueError):
        project_map({'u1':values['u1']},units)


def test_mapped_runner_keeps_strict_native_shape_and_projection_separate(tmp_path):
    prepared=tmp_path/'prepared'
    plan=prepare(prepared,'source-map-concise',case_ids=['DEV-20261020-04','DEV-20261020-07'],
                 repetitions=1,request_seconds=180,strict_all=True)
    def transport(method,url,payload,timeout,headers):
        properties=payload['response_format']['json_schema']['schema']['properties']
        if 'observations' in properties:
            value={'observations':[]}
        else:
            source=json.loads(payload['messages'][1]['content'])
            value={unit['unit_id']:{'observations':[]} for unit in source['source_units']}
            assert set(value)==set(properties)
        return 200,{'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}
    output=tmp_path/'capture'
    result=execute(prepared,output,preflight(plan),transport=transport)
    assert result['completed']==4
    rows=[json.loads(line) for line in (output/'model-outputs.jsonl').read_text().splitlines()]
    mapped=[row for row in rows if row['response_mode']=='source-map']
    assert all(set(row['wire_value']) in ({'u1','u2'},{'u1','u2','u3'}) for row in mapped)
    assert all(row['value']=={'observations':[]} for row in mapped)
