"""Fail-closed numerical review; never grants authorized release acceptance.

Observations are declared evidence, not independently authenticated data. Keep
this review separate from corpus provenance, model identity and release policy.
"""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path

APPROVED_TARGET_SHA256 = '6f1d457eacb74901ac9b12373a59752f830c3f32d964c6bf5f230b20bbb99bac'
REQUIRED_CRITICAL_SLICES = ('ambiguity', 'injection', 'correction', 'long_multi_event', 'endpoint')
CRITICAL_SLICE_TARGETS = {
    'ambiguity': ('safe_ambiguity_handling_min', 'hard_safety_violations_max'),
    'injection': ('hard_safety_violations_max',),
    'correction': ('atomic_event_f1_min', 'selected_link_precision_min', 'selected_link_coverage_min'),
    'long_multi_event': ('atomic_event_f1_min', 'candidate_recall_at_8_min',
                         'proposal_readiness_p95_seconds_max'),
    'endpoint': ('endpoint_exact_accuracy_min',),
}


def metric_review(targets, observations):
    result = {}
    for key, target in targets.items():
        row = observations.get(key, {})
        value, support = row.get('value'), row.get('support')
        valid = (row.get('status') == 'assessed' and
                 type(value) in (int, float) and math.isfinite(value) and value >= 0 and
                 type(support) is int and support > 0)
        if key.endswith('_min'):
            valid = valid and (value <= 1 if type(value) in (int, float) else False)
        if not valid:
            status = 'unassessed'
        elif key.endswith('_min'):
            status = 'pass' if value >= target else 'fail'
        elif key.endswith('_max'):
            status = 'pass' if value <= target else 'fail'
        else:
            raise ValueError('Unknown target direction')
        result[key] = dict(status=status, value=value, support=support, target=target)
    return result


def review(target_record, evidence):
    canonical = json.dumps(target_record, sort_keys=True, separators=(',', ':')).encode()
    if sha256(canonical).hexdigest() != APPROVED_TARGET_SHA256:
        raise ValueError('Use the owner-approved frozen targets')
    targets = target_record['targets']
    global_metrics = metric_review(targets, evidence.get('observations', {}))
    required = evidence.get('required_critical_slices')
    if (not isinstance(required, list) or not all(isinstance(name, str) for name in required) or
            len(set(required)) != len(required) or set(required) != set(REQUIRED_CRITICAL_SLICES)):
        raise ValueError('Declare the complete critical-slice inventory from the review policy')
    slices = evidence.get('critical_slices', {})
    if set(slices)-set(required):
        raise ValueError('Undeclared critical slice')
    slice_reviews = {}
    for name in required:
        row = slices.get(name, {})
        names = row.get('applicable_targets', [])
        if (not isinstance(names, list) or not all(isinstance(key, str) for key in names) or
                len(set(names)) != len(names) or set(names) != set(CRITICAL_SLICE_TARGETS[name])):
            slice_reviews[name] = dict(status='unassessed', metrics={})
            continue
        metrics = metric_review({key: targets[key] for key in names}, row.get('observations', {}))
        status = ('fail' if any(r['status'] == 'fail' for r in metrics.values()) else
                  'pass' if all(r['status'] == 'pass' for r in metrics.values()) else 'unassessed')
        slice_reviews[name] = dict(status=status, metrics=metrics)
    numerical_pass = (all(r['status'] == 'pass' for r in global_metrics.values()) and
                      all(r['status'] == 'pass' for r in slice_reviews.values()))
    prerequisites = evidence.get('prerequisites', {})
    prerequisites_pass = all(prerequisites.get(key) is True for key in (
        'assembled_candidate_frozen', 'fresh_reviewed_corpus', 'source_and_configuration_verified',
        'all_safety_and_workflow_checks_complete', 'uncertainty_and_sampling_reviewed'))
    return dict(version='release-gate-review-v1', metrics=global_metrics, critical_slices=slice_reviews,
                numerical_gates_pass=numerical_pass, prerequisites_pass=prerequisites_pass,
                eligible_for_authorized_review=numerical_pass and prerequisites_pass,
                release_accepted=False,
                limitations=['Declared evidence still requires provenance and authorized review.',
                             'Support is reported, not a substitute for cluster-aware uncertainty.',
                             'Passing these numerical comparisons never grants release acceptance.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = review(json.loads(args.targets.read_text()), json.loads(args.evidence.read_text()))
    result['input_sha256'] = {str(p): sha256(p.read_bytes()).hexdigest()
                              for p in (args.targets, args.evidence)}
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')
