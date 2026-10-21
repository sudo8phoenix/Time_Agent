"""Offline selection diagnostics with explicit clusters and comparison controls.

Inputs are label-side saved outcomes, never model-visible context. Bootstrap
intervals describe this sample; degenerate finite samples do not establish safety.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path
import random

from evaluation.metrics import _prediction_failed, _ids, _gold_ids, selection_metrics


def _index(rows):
    index = {}
    for row in rows:
        identity = row.get('case_id')
        if not isinstance(identity, str) or not identity.strip() or identity in index:
            raise ValueError('Missing or duplicate case identity')
        index[identity] = row
    return index


def _ratio_counts(labels, predictions):
    metrics = selection_metrics(labels, predictions)
    by = {row['case_id']: row for row in predictions}
    correct_links = sum(
        not _prediction_failed(row := by.get(label['case_id'])) and bool(_ids(row)) and
        label.get('expected_mapping_state') == 'suggested' and set(_ids(row)) == set(_gold_ids(label))
        for label in labels)
    return {
        'selected_precision': (correct_links, metrics['overall_selected']),
        'coverage': (metrics['successful_selected'], metrics['matchable']),
        'recall_at_8': (metrics['recall_at_8_numerator'], metrics['recall_at_8_denominator']),
    }


def _interval(values):
    values = sorted(values)
    return [values[math.floor(.025 * (len(values) - 1))],
            values[math.ceil(.975 * (len(values) - 1))]] if values else None


def scorecard(labels, predictions, *, replicates=2000, seed=0):
    """Report precision/coverage by slice and resample whole declared clusters."""
    if type(replicates) is not int or replicates < 100 or type(seed) is not int:
        raise ValueError('Use at least 100 replicates and an integer seed')
    truth, predicted = _index(labels), _index(predictions)
    if not truth or set(predicted) - set(truth):
        raise ValueError('Empty labels or unlabelled prediction')
    groups = defaultdict(list)
    slices = defaultdict(list)
    for row in labels:
        group, memberships = row.get('group_id'), row.get('slices')
        if not isinstance(group, str) or not group.strip():
            raise ValueError('Every case requires a declared independent cluster')
        if (not isinstance(memberships, list) or not memberships or
                any(not isinstance(s, str) or not s.strip() for s in memberships) or
                len(set(memberships)) != len(memberships)):
            raise ValueError('Every case requires unique slice names')
        groups[group].append(row)
        for name in memberships:
            slices[name].append(row)

    counts = _ratio_counts(labels, predictions)
    rng = random.Random(seed)
    bootstrap = {name: [] for name in counts}
    keys = sorted(groups)
    if len(groups) >= 2:
        # Rename duplicated case identities in each drawn cluster, preserving
        # every dependent event and failed/missing output within that cluster.
        for _ in range(replicates):
            sampled_labels, sampled_predictions = [], []
            for draw, group in enumerate(rng.choices(keys, k=len(keys))):
                for row in groups[group]:
                    identity = f'{draw}:{row["case_id"]}'
                    sampled_labels.append({**row, 'case_id': identity})
                    if row['case_id'] in predicted:
                        sampled_predictions.append({**predicted[row['case_id']], 'case_id': identity})
            for name, (numerator, denominator) in _ratio_counts(sampled_labels, sampled_predictions).items():
                if denominator:
                    bootstrap[name].append(numerator / denominator)

    metrics = {
        name: dict(numerator=n, denominator=d, value=n/d if d else None,
                   descriptive_cluster_bootstrap_95=_interval(bootstrap[name]),
                   valid_replicates=len(bootstrap[name]),
                   undefined_replicates=replicates-len(bootstrap[name]) if len(groups) >= 2 else 0)
        for name, (n, d) in counts.items()
    }
    per_slice = {}
    for name, rows in sorted(slices.items()):
        case_ids = {row['case_id'] for row in rows}
        per_slice[name] = {
            metric: dict(numerator=n, denominator=d, value=n/d if d else None)
            for metric, (n, d) in _ratio_counts(
                rows, [p for p in predictions if p['case_id'] in case_ids]).items()
        }
    return dict(version='selection-diagnostics-v1', case_count=len(labels),
                missing_outputs=len(set(truth)-set(predicted)), cluster_count=len(groups),
                seed=seed, requested_replicates=replicates, metrics=metrics, slices=per_slice,
                release_accepted=False, limitations=[
                    'Cluster independence and labels are caller declarations, not independently verified.',
                    'Percentile bootstrap is descriptive; sparse/degenerate samples need a reviewed inferential design.',
                    'Zero observed errors cannot establish zero future error or a release confidence bound.',
                    'Missing outputs remain in eligible-event denominators; undefined resamples are counted.',
                ])


def failure_breakdown(labels, predictions):
    """Localize observed failure boundaries, without claiming semantic root cause."""
    truth, predicted = _index(labels), _index(predictions)
    if set(predicted) - set(truth):
        raise ValueError('Unlabelled prediction')
    outcomes = []
    for identity, label in truth.items():
        row = predicted.get(identity)
        if row is None:
            category = 'missing_output'
        elif _prediction_failed(row):
            category = 'failed_output'
        elif row.get('extraction_valid') is False:
            category = 'extraction_invalid_declared'
        elif label.get('expected_mapping_state') != 'suggested':
            category = 'false_selection_on_ineligible' if _ids(row) else 'safe_abstention'
        elif row.get('extraction_valid') is not True:
            category = 'extraction_not_assessed'
        elif 'candidate_ids' not in row:
            category = 'retrieval_not_assessed'
        elif not isinstance(row['candidate_ids'], list):
            raise ValueError('candidate_ids must be a list')
        elif not set(_gold_ids(label)) & set(row['candidate_ids'][:8]):
            category = 'retrieval_miss_at_8'
        elif set(_ids(row)) != set(_gold_ids(label)):
            category = 'selection_error_with_gold_candidate'
        else:
            category = 'correct_selection'
        outcomes.append(dict(case_id=identity, category=category))
    return dict(counts=dict(Counter(row['category'] for row in outcomes)), cases=outcomes,
                limitation='Declared extraction validity is not a causal or independently adjudicated diagnosis.')


MAXIMIZE = ('task_success', 'precision', 'coverage', 'availability')
MINIMIZE = ('cost', 'latency_ms', 'tokens', 'calls')


def pareto_review(configurations):
    """Compare only frozen same-workload metrics; never authorize promotion."""
    seen, contexts = set(), set()
    for row in configurations:
        identity, context = row.get('configuration_id'), row.get('comparison_sha256')
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError('Missing or duplicate configuration identity')
        if not isinstance(context, str) or len(context) != 64 or any(c not in '0123456789abcdef' for c in context):
            raise ValueError('Frozen comparison hash required')
        seen.add(identity)
        contexts.add(context)
        if type(row.get('hard_safety_violations')) is not int or row['hard_safety_violations'] < 0:
            raise ValueError('Observed hard-safety count required')
        for metric in MAXIMIZE + MINIMIZE:
            value = row.get(metric)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value) or value < 0 or (metric in MAXIMIZE and value > 1)):
                raise ValueError('Finite comparable metrics required: ' + metric)
    if not configurations or len(contexts) != 1:
        raise ValueError('Identical frozen workload/labels/settings/metric definitions required')
    eligible = [r for r in configurations if not r['hard_safety_violations']]
    results = []
    for row in configurations:
        dominators = []
        for other in eligible:
            no_worse = (all(other[m] >= row[m] for m in MAXIMIZE) and
                        all(other[m] <= row[m] for m in MINIMIZE))
            better = (any(other[m] > row[m] for m in MAXIMIZE) or
                      any(other[m] < row[m] for m in MINIMIZE))
            if no_worse and better:
                dominators.append(other['configuration_id'])
        results.append(dict(configuration_id=row['configuration_id'], dominated_by=sorted(dominators),
                            decision='reject_safety' if row['hard_safety_violations'] else
                            'dominated' if dominators else 'tradeoff_candidate'))
    return dict(configurations=results, release_accepted=False,
                limitation='Same-workload hashes are declarations; sample uncertainty and release gates require review.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--configurations', type=Path)
    parser.add_argument('--replicates', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args()
    sources = [args.labels, args.predictions] + ([args.configurations] if args.configurations else [])
    # Exclusive output also prevents alias/symlink overwrites of historical data.
    if args.output.exists() or args.output.resolve() in {p.resolve() for p in sources}:
        parser.error('Output must be a new artifact path')
    labels = json.loads(args.labels.read_text())
    predictions = json.loads(args.predictions.read_text())
    result = dict(scorecard=scorecard(labels, predictions, replicates=args.replicates, seed=args.seed),
                  failure_breakdown=failure_breakdown(labels, predictions),
                  input_sha256={str(p): sha256(p.read_bytes()).hexdigest() for p in sources},
                  release_accepted=False)
    if args.configurations:
        result['pareto_review'] = pareto_review(json.loads(args.configurations.read_text()))
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
