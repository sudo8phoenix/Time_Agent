"""Regression safeguards for equivalent schema grammar and retained attempts."""
from copy import deepcopy
import json
from hashlib import sha256

import pytest

from app.llm.extract import extraction_schema
from app.llm.openrouter import _matches_schema
from evaluation.open_item_continuation import run
from evaluation.prompt_ablation import observation
from evaluation.repeated_development import ExperimentStop
from evaluation.strict_schema import build_wire_schema
from evaluation.strict_union_diagnostic import explicit_multi_unions


def test_equivalent_numeric_unions_preserve_acceptance_without_mutating_domain_wire():
    original, _ = build_wire_schema(extraction_schema())
    saved = deepcopy(original)
    transformed, changes = explicit_multi_unions(original)
    assert len(changes) == 2 and original == saved
    accepted = rejected = 0
    for quantity in [None, '5', 5, 5.5, True, {}, []]:
        for percent in [None, '25', 25, 25.5, True, {}, []]:
            value = observation('id', 'Invented source.', quantity=quantity, reported_percent=percent)
            before = _matches_schema({'observations': [value]}, original)
            after = _matches_schema({'observations': [value]}, transformed)
            assert before == after
            accepted += before
            rejected += not before
    assert accepted > 0 and rejected > 0


def test_explicit_union_retains_parent_enum_restrictions():
    source = {'type': ['string', 'number', 'null'], 'enum': ['allowed', 5, None]}
    transformed, _ = explicit_multi_unions(source)
    for value in ['allowed', 'forbidden', 5, 6, None, False]:
        assert _matches_schema(value, transformed) == _matches_schema(value, source)


def test_nonprimitive_multi_union_is_rejected_instead_of_reinterpreted():
    with pytest.raises(ValueError):
        explicit_multi_unions({'type': ['object', 'string', 'null']})


def test_continuation_cannot_repeat_a_retained_trial_or_reach_credentials(tmp_path, monkeypatch):
    batch, prepared, capture = tmp_path/'batch', tmp_path/'prepared', tmp_path/'capture'
    prepared.mkdir()
    for name in ['prepared', 'supplement-prepared-v2', 'retained']:
        (batch/name).mkdir(parents=True)
    for name in ['prepared', 'supplement-prepared-v2']:
        (batch/name/'plan.json').write_text('{}')
    calls = batch/'retained/calls.jsonl'
    calls.write_text(json.dumps({'id': 'already-attempted', 'status': 400})+'\n')
    manifest = batch/'retained/capture-manifest.json'
    manifest.write_text(json.dumps({'calls.jsonl': sha256(calls.read_bytes()).hexdigest()}))
    config = dict(original_plan_sha256=sha256((batch/'prepared/plan.json').read_bytes()).hexdigest(),
        supplemental_plan_sha256=sha256((batch/'supplement-prepared-v2/plan.json').read_bytes()).hexdigest(),
        retained={'retained': {'manifest_sha256': sha256(manifest.read_bytes()).hexdigest()}},
        schedule=[{'id': 'already-attempted'}])
    (prepared/'plan.json').write_text(json.dumps(config))
    monkeypatch.setattr('app.settings.get_settings', lambda: pytest.fail('credentials reached'))
    with pytest.raises(ExperimentStop, match='repeat a retained trial'):
        run(batch, prepared, capture)
    assert not capture.exists()
    assert json.loads(calls.read_text())['status'] == 400
