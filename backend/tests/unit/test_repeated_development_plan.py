import json
from hashlib import sha256

import pytest

from evaluation.prepare_repeated_development import FIXTURE, prepare
from evaluation.score_paired_pilot import fields_exact


def test_repeated_plan_pairs_every_case_without_treating_v12_as_zero_shot(tmp_path):
    plan = prepare(tmp_path / 'prepared')
    assert len(plan['schedule']) == plan['budget']['calls'] == 60
    assert len({row['trial_id'] for row in plan['schedule']}) == 60
    for case in json.loads((FIXTURE / 'inputs.json').read_text()):
        for repetition in range(1, 4):
            pair = [row for row in plan['schedule']
                    if row['case_id'] == case['case_id'] and row['repetition'] == repetition]
            assert {row['arm'] for row in pair} == {'v12', 'coverage-and-quantity'}
            assert not any(row['strict'] for row in pair)
    assert plan['schedule'][0]['arm'] != plan['schedule'][2]['arm']
    assert plan['schedule'][0]['arm'] != plan['schedule'][20]['arm']
    assert 'neither arm is zero-shot' in plan['prompt_definition']
    assert not plan['labels_in_requests']
    for path, digest in plan['source_sha256'].items():
        from pathlib import Path
        assert sha256(Path(path).read_bytes()).hexdigest() == digest
    with pytest.raises(FileExistsError):
        prepare(tmp_path / 'prepared')


def test_slice_labels_preserve_repeated_events_and_exact_ids():
    labels = json.loads((FIXTURE / 'labels.json').read_text())['cases']
    similar_ids = labels['DEV-20261020-06']
    assert fields_exact(similar_ids, list(reversed(similar_ids)))
    wrong = [dict(row, asset_tags=['TR-030']) for row in similar_ids]
    assert not fields_exact(similar_ids, wrong)
    assert not fields_exact(similar_ids, similar_ids[:1])
    assert not fields_exact(similar_ids, similar_ids + similar_ids[:1])
    correction = labels['DEV-20261020-04']
    assert correction[0]['event_type'] == 'correction'
    assert correction[0]['work_date'] == '2026-10-19'
    assert correction[0]['quantity'] is None
    assert correction[1]['event_type'] == 'no_work'


def test_few_shot_and_order_plans_keep_other_settings_fixed(tmp_path):
    forward = prepare(tmp_path / 'few-shot', 'few-shot')
    order = prepare(tmp_path / 'order', 'example-order')
    assert forward['prompts']['few-shot'].startswith(forward['prompts']['zero-shot'])
    assert set(forward['prompts']) == {'zero-shot', 'few-shot'}
    assert order['prompts']['forward'] != order['prompts']['reverse']
    assert forward['wire_schema_sha256'] == order['wire_schema_sha256']
    for plan in (forward, order):
        assert len(plan['schedule']) == 60
        assert {r['reasoning_effort'] for r in plan['schedule']} == {'low'}
        assert {r['strict'] for r in plan['schedule']} == {False}


def test_small_correction_diagnostic_is_a_separate_fixed_four_call_plan(tmp_path):
    plan = prepare(tmp_path / 'correction', 'correction',
                   case_ids=['DEV-20261020-04', 'DEV-20261020-07'], repetitions=1)
    assert len(plan['schedule']) == plan['budget']['calls'] == 4
    assert plan['budget']['list_price_usd'] == .05
    assert plan['budget']['reserved_tokens'] == 160000
    assert plan['budget']['wall_seconds'] == 360
    assert {r['case_id'] for r in plan['schedule']} == {'DEV-20261020-04', 'DEV-20261020-07'}
    with pytest.raises(ValueError):
        prepare(tmp_path / 'unknown', case_ids=['unknown'])
    with pytest.raises(ValueError):
        prepare(tmp_path / 'duplicate', case_ids=['DEV-20261020-04'] * 2)
    with pytest.raises(ValueError):
        prepare(tmp_path / 'unbounded', repetitions=4)


def test_date_provenance_ablation_keeps_model_and_other_instructions_fixed(tmp_path):
    from evaluation.prompt_ablation import DATE_BASIS_SUFFIX
    plan = prepare(tmp_path / 'dates', 'date-basis', model='openai/gpt-oss-120b',
                   output_tokens=3072, strict_all=True,
                   case_ids=['DEV-20261020-04', 'DEV-20261020-07'], repetitions=3,
                   request_seconds=180)
    assert plan['prompts']['date-basis-contract'] == plan['prompts']['correction-contract'] + DATE_BASIS_SUFFIX
    assert len(plan['schedule']) == 12
    assert all(row['strict'] and row['reasoning_effort'] == 'low' for row in plan['schedule'])
    assert plan['budget']['output_tokens_per_call'] == 3072
