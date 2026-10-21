"""Sample-size planning, never a release or confidence-routing decision.

Exact one-sided binomial bounds here assume independent Bernoulli trials and
zero observed errors. Repeated events from a report are not independent trials.
"""
import argparse
import json
import math
from pathlib import Path


def _probability(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
        raise ValueError(f'{name} must be finite and strictly between zero and one')


def zero_error_plan(max_error_rate, alpha=0.05):
    """Minimum all-success sample with a one-sided upper error bound at target."""
    _probability(max_error_rate, 'max_error_rate')
    _probability(alpha, 'alpha')
    ratio = math.log(alpha) / math.log1p(-max_error_rate)
    if not math.isfinite(ratio):
        raise ValueError('Requested error bound is below supported numerical precision')
    count = math.ceil(ratio)
    return dict(independent_trials_required=count, observed_errors_required=0,
                confidence=1-alpha, target_max_error_rate=max_error_rate,
                exact_one_sided_upper_error_bound=-math.expm1(math.log(alpha)/count),
                assumptions='Independent identically distributed Bernoulli trials; no optional stopping',
                limitation='Any observed error requires a new analysis, not this zero-error bound')


def planning_report():
    return dict(version='statistical-planning-v1', release_accepted=False,
                scope='Planning examples, not an approved sampling design or runtime thresholds',
                link_precision_98_percent_zero_error=zero_error_plan(0.02),
                rare_failure_examples={str(rate): zero_error_plan(rate) for rate in (0.01, 0.001)},
                requirements=[
                    'Freeze sample size, independent sampling units, slices and stopping rules before inference.',
                    'Selected-link precision uses selected links; assess coverage >= 0.80 separately on all matchable events.',
                    'Report/source/project dependencies require cluster-aware uncertainty; repeated calls do not add independent support.',
                    'The listed sample counts are independent-unit illustrations, not report counts for a clustered workload.',
                    'At zero errors, a finite sample never proves a population hard-safety violation rate of zero.',
                    'Representative prevalence, reviewed labels, frozen candidate and fresh validation/holdout remain prerequisites.',
                    'Critical slices need their own denominators and review; a pooled pass cannot override a failing slice.',
                    'Multiple slice comparisons and interim looks need a preregistered uncertainty/stopping policy.',
                ])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.output.open('x') as stream:
        stream.write(json.dumps(planning_report(), indent=2)+'\n')
