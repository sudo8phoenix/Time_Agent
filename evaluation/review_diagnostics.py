"""Label-side review signals, probability diagnostics and paired escalation cost.

No thresholds are fitted and no record is accepted automatically. Correctness
labels and estimator declarations must be independently reviewed for real use.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path


COMPLETED = {'completed', 'ready_for_review', 'succeeded', 'success'}
BANDS = ((0, .5), (.5, .8), (.8, .9), (.9, 1.0000001))


def _correct(row):
    if row is None:
        return False
    if type(row.get('correct')) is not bool:
        raise ValueError('Explicit binary correctness label required')
    return row.get('state') in COMPLETED and row['correct'] and not row.get('failure')


def _identities(rows):
    identities = [row.get('case_id') for row in rows]
    if (any(not isinstance(identity, str) or not identity.strip() for identity in identities) or
            len(identities) != len(set(identities))):
        raise ValueError('Unique nonblank case identities required')


def _counts(rows):
    correct = sum(_correct(row) for row in rows)
    return dict(count=len(rows), errors=len(rows)-correct,
                error_rate=(len(rows)-correct)/len(rows) if rows else None)


def review_signals(records):
    """Measure observable provenance signals without interpreting them as probabilities."""
    _identities(records)
    signals = {name: [] for name in (
        'missing_evidence', 'missing_information', 'field_issues', 'ambiguous_candidates',
        'validator_failed', 'failed_or_missing_output')}
    for row in records:
        audit = row.get('provenance')
        if not isinstance(audit, dict):
            raise ValueError('Captured provenance required')
        selection, validation = audit.get('original_selection', {}), audit.get('validation', {})
        flags = dict(
            missing_evidence=not audit.get('evidence'),
            missing_information=bool(validation.get('missing_information')),
            field_issues=bool(validation.get('field_issues')),
            ambiguous_candidates=selection.get('mapping_state') == 'ambiguous',
            validator_failed=row.get('validator_state') == 'invalid',
            failed_or_missing_output=row.get('state') not in COMPLETED or bool(row.get('failure')))
        _correct(row)
        for name, present in flags.items():
            if present:
                signals[name].append(row)
    return dict(case_count=len(records), signals={k: _counts(v) for k, v in signals.items()},
                overall=_counts(records), probabilities_inferred=False, thresholds_fitted=False,
                release_accepted=False,
                limitation='Overlapping observed signals are diagnostics, not causal error attribution or acceptance rules.')


def probability_diagnostics(records):
    """Brier and reliability bins only for explicitly declared correctness probabilities."""
    _identities(records)
    scored, unavailable, failed, estimators = [], 0, 0, set()
    for row in records:
        correct = _correct(row)
        probability = row.get('probability')
        if probability is None:
            unavailable += 1
            continue
        estimator = row.get('estimator', {})
        method, version = estimator.get('method'), estimator.get('version')
        if (row.get('probability_kind') != 'correctness_probability' or
                not isinstance(method, str) or not method.strip() or
                method in {'not_estimated', 'match_strength', 'model_reported_strength', 'quote_check'} or
                not isinstance(version, str) or not version.strip()):
            raise ValueError('Declared probability semantics and estimator method/version required')
        if (isinstance(probability, bool) or not isinstance(probability, (int, float)) or
                not math.isfinite(probability) or not 0 <= probability <= 1):
            raise ValueError('Finite probability in [0,1] required')
        estimators.add((method, version))
        if row.get('state') not in COMPLETED or row.get('failure'):
            failed += 1
            continue
        scored.append((probability, correct))
    if len(estimators) > 1:
        raise ValueError('Do not pool estimator versions or methods')
    bands, tradeoffs = [], []
    for low, high in BANDS:
        selected = [(p, y) for p, y in scored if low <= p < high]
        count, correct = len(selected), sum(y for _, y in selected)
        bands.append(dict(min=low, max=min(1, high), count=count, errors=count-correct,
                          mean_probability=sum(p for p, _ in selected)/count if count else None,
                          observed_correct_fraction=correct/count if count else None,
                          error_rate=(count-correct)/count if count else None))
    for threshold in sorted({p for p, _ in scored}):
        selected = [(p, y) for p, y in scored if p >= threshold]
        tradeoffs.append(dict(threshold=threshold, count=len(selected),
                              precision=sum(y for _, y in selected)/len(selected),
                              coverage=len(selected)/len(records)))
    return dict(case_count=len(records), scored_count=len(scored), unavailable_count=unavailable,
                failed_probability_count=failed,
                estimator=list(next(iter(estimators))) if estimators else None,
                brier=sum((p-int(y))**2 for p, y in scored)/len(scored) if scored else None,
                calibration_bins=bands, precision_coverage=tradeoffs,
                thresholds_fitted=False, release_accepted=False,
                limitation='Estimator semantics and labels are declarations; finite sample Brier/bin accuracy does not establish calibration on new data.')


def escalation_diagnostics(pairs):
    """Count errors fixed and introduced; charge observed added resources on failures too."""
    _identities(pairs)
    outcomes = Counter()
    known = {name: 0 for name in ('calls', 'tokens', 'latency_ms', 'cost_usd')}
    unknown = {name: 0 for name in known}
    for pair in pairs:
        before, after = pair.get('before'), pair.get('after')
        if before is None:
            raise ValueError('Primary worker outcome must be retained')
        original_correct, reviewed_correct = _correct(before), _correct(after)
        category = ('unchanged_correct' if original_correct else 'fixed') if reviewed_correct else (
            'introduced_error' if original_correct else 'unchanged_error')
        outcomes[category] += 1
        if after is None:
            outcomes['missing_review'] += 1
        resources = pair.get('additional_resources', {})
        for name in known:
            value = resources.get(name)
            if value is None:
                unknown[name] += 1
            elif (isinstance(value, bool) or not isinstance(value, (int, float)) or
                  not math.isfinite(value) or value < 0 or (name in {'calls', 'tokens'} and type(value) is not int)):
                raise ValueError('Invalid additional resource measurement: ' + name)
            else:
                known[name] += value
    fixed, harmed = outcomes['fixed'], outcomes['introduced_error']
    return dict(case_count=len(pairs), outcomes=dict(outcomes), errors_fixed=fixed,
                errors_introduced=harmed, net_errors_reduced=fixed-harmed,
                known_additional_resources=known, unknown_measurement_counts=unknown,
                complete_additional_resources={k: known[k] if not unknown[k] else None for k in known},
                release_accepted=False,
                limitation='Paired observed outcomes only; no causal gain, operational cost, or escalation routing policy is inferred.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() == args.input.resolve():
        parser.error('Output must be a new evidence artifact')
    source = args.input.read_bytes()
    data = json.loads(source)
    result = dict(version='review-diagnostics-v1', input_sha256=sha256(source).hexdigest(),
                  review_signals=review_signals(data['signal_records']),
                  probability_diagnostics=probability_diagnostics(data['probability_records']),
                  escalation_diagnostics=escalation_diagnostics(data['escalation_pairs']),
                  release_accepted=False)
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
