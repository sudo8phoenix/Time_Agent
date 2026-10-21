from copy import deepcopy
import json
from pathlib import Path

import pytest

from evaluation.release_gate_review import CRITICAL_SLICE_TARGETS, REQUIRED_CRITICAL_SLICES, review


def fixture():
    targets = json.loads(Path('evaluation/contracts/approved-targets.json').read_text())
    observations = {key: dict(value=value, support=200, status='assessed')
                    for key, value in targets['targets'].items()}
    evidence = dict(observations=observations, required_critical_slices=list(REQUIRED_CRITICAL_SLICES),
                    critical_slices={name: dict(applicable_targets=list(CRITICAL_SLICE_TARGETS[name]),
                        observations=deepcopy(observations)) for name in REQUIRED_CRITICAL_SLICES},
                    prerequisites={key: True for key in ('assembled_candidate_frozen', 'fresh_reviewed_corpus',
                        'source_and_configuration_verified', 'all_safety_and_workflow_checks_complete',
                        'uncertainty_and_sampling_reviewed')})
    return targets, evidence


def test_high_precision_cannot_hide_below_target_coverage():
    targets, evidence = fixture()
    evidence['observations']['selected_link_precision_min']['value'] = 1
    evidence['observations']['selected_link_coverage_min']['value'] = 0.79
    result = review(targets, evidence)
    assert result['metrics']['selected_link_precision_min']['status'] == 'pass'
    assert result['metrics']['selected_link_coverage_min']['status'] == 'fail'
    assert not result['eligible_for_authorized_review']


def test_failing_critical_slice_blocks_even_when_pooled_metrics_pass():
    targets, evidence = fixture()
    evidence['critical_slices']['ambiguity']['observations']['safe_ambiguity_handling_min']['value'] = 0.5
    result = review(targets, evidence)
    assert all(row['status'] == 'pass' for row in result['metrics'].values())
    assert result['critical_slices']['ambiguity']['status'] == 'fail'
    assert not result['eligible_for_authorized_review']


@pytest.mark.parametrize('defect', ['missing_slice', 'zero_support', 'nan', 'development', 'missing_metric'])
def test_missing_or_invalid_evidence_fails_closed(defect):
    targets, evidence = fixture()
    if defect == 'missing_slice':
        evidence['critical_slices'] = {}
    elif defect == 'development':
        evidence['prerequisites']['fresh_reviewed_corpus'] = False
    elif defect == 'missing_metric':
        del evidence['observations']['endpoint_exact_accuracy_min']
    else:
        row = evidence['observations']['selected_link_precision_min']
        row['support' if defect == 'zero_support' else 'value'] = 0 if defect == 'zero_support' else float('nan')
    assert not review(targets, evidence)['eligible_for_authorized_review']


def test_exact_target_boundaries_only_enable_review_never_acceptance():
    targets, evidence = fixture()
    result = review(targets, evidence)
    assert result['eligible_for_authorized_review']
    assert not result['release_accepted']
    evidence['observations']['hard_safety_violations_max']['value'] = 1
    assert not review(targets, evidence)['eligible_for_authorized_review']


def test_missing_critical_slice_inventory_is_not_a_vacuous_pass():
    targets, evidence = fixture()
    evidence['required_critical_slices'] = []
    with pytest.raises(ValueError, match='critical-slice inventory'):
        review(targets, evidence)


def test_omitting_known_failing_slice_cannot_create_eligible_review():
    targets, evidence = fixture()
    evidence['required_critical_slices'].remove('injection')
    del evidence['critical_slices']['injection']
    with pytest.raises(ValueError, match='critical-slice inventory'):
        review(targets, evidence)


def test_relaxed_forged_target_record_is_rejected_despite_status_string():
    targets, evidence = fixture()
    targets['targets']['selected_link_coverage_min'] = 0
    with pytest.raises(ValueError, match='owner-approved frozen targets'):
        review(targets, evidence)


def test_omitting_a_required_metric_within_slice_is_not_a_pass():
    targets, evidence = fixture()
    evidence['critical_slices']['correction']['applicable_targets'] = ['atomic_event_f1_min']
    result = review(targets, evidence)
    assert result['critical_slices']['correction']['status'] == 'unassessed'
    assert not result['eligible_for_authorized_review']
