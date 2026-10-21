import pytest

from app.llm.extract import FragmentInput, extract_fragments
from evaluation.prompt_ablation import examples, prompts


def test_few_shot_changes_only_demonstrations_and_order_is_explicit():
    forward = prompts()
    reverse = prompts((2, 1, 0))
    assert forward['zero-shot'] == reverse['zero-shot']
    assert forward['few-shot'].startswith(forward['zero-shot'])
    assert forward['few-shot'] != reverse['few-shot']
    assert 'demonstration-a' not in forward['zero-shot']
    with pytest.raises(ValueError):
        prompts((0, 0, 1))


@pytest.mark.parametrize('example', examples())
def test_demonstration_outputs_pass_domain_and_exact_evidence_validation(example):
    from datetime import date
    results = extract_fragments([FragmentInput(example['fragment_id'], 'demonstration', example['text'])],
                                lambda **kwargs: example['output'],
                                report_date=date.fromisoformat(example['report_date']),
                                report_date_trusted=True)
    assert all(not result.errors for result in results)
    assert sum(len(result.observations) for result in results) == len(example['output']['observations'])


@pytest.mark.parametrize('basis,expected_date', [('relative_resolved', '2026-09-02'), ('report_context', None)])
def test_tomorrow_requires_relative_provenance_and_unsupported_basis_stays_reviewable(basis, expected_date):
    from copy import deepcopy
    from datetime import date
    from app.prompts.extraction_v1 import V12_PROMPT_VERSION
    example = examples()[1]
    output = deepcopy(example['output'])
    output['observations'][0]['date_basis'] = basis
    results = extract_fragments([FragmentInput(example['fragment_id'], 'demonstration', example['text'])],
                                lambda **kwargs: output, report_date=date(2026, 9, 1),
                                report_date_trusted=True, prompt_version=V12_PROMPT_VERSION)
    assert not results[0].errors
    plan = next(o for o in results[0].observations if o.event_type.value == 'planned_work')
    assert (plan.work_date.isoformat() if plan.work_date else None) == expected_date
    if expected_date is None:
        assert plan.date_basis.value == 'unknown' and plan.warnings
