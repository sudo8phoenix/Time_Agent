"""Combine sealed trial quality, measured usage and separated provider timings."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from evaluation.score_repeated_development import score


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    # Nearest-rank empirical quantile; small samples are not sustained p95 proof.
    import math
    return values[max(0, math.ceil(len(values) * fraction) - 1)]


def summarize(capture, labels, lineage):
    quality = score(capture, labels, lineage)  # Checks the complete sealed manifest first.
    config = json.loads((capture / 'config.json').read_text())
    manifest = json.loads((capture / 'capture-manifest.json').read_text())
    rows = [json.loads(line) for line in (capture / 'predictions.jsonl').read_text().splitlines()] if 'predictions.jsonl' in manifest else []
    usage = [json.loads(line) for line in (capture / 'usage.jsonl').read_text().splitlines()] if 'usage.jsonl' in manifest else []
    planned = {row['trial_id']: row for row in config['schedule']}
    by_trial = {}
    for row in usage:
        if row.get('trial_id') not in planned or row['trial_id'] in by_trial:
            raise ValueError('Duplicate or unscheduled usage')
        by_trial[row['trial_id']] = row
    metrics = {}
    for arm in config['prompts']:
        predictions = [row for row in rows if row['arm'] == arm]
        timings = defaultdict(list)
        for row in predictions:
            timings['stage_ms'].append(row['elapsed_ms'])
            provider = row.get('provider_metrics', {}).get('groq', {})
            for field in ('admission_ms', 'transport_ms'):
                if field in provider:
                    timings[field].append(provider[field])
        measured = [row for row in usage if row['arm'] == arm]
        prompt = sum(row.get('usage', {}).get('prompt_tokens', 0) for row in measured)
        completion = sum(row.get('usage', {}).get('completion_tokens', 0) for row in measured)
        unknown = sum(not {'prompt_tokens', 'completion_tokens'}.issubset(row.get('usage', {})) for row in measured)
        returned = sum(row.get('status') == 200 and row.get('returned_model') == config['model'] for row in measured)
        exact = quality['arms'][arm]['raw_exact']
        attempted = quality['arms'][arm]['attempted']
        scheduled = quality['arms'][arm]['scheduled']
        metrics[arm] = dict(
            token_usage=dict(prompt_tokens=prompt, completion_tokens=completion,
                            responses_with_unknown_usage=unknown, response_count=len(measured)),
            known_token_list_price_usd=(prompt * config['prices_per_million']['input'] +
                                       completion * config['prices_per_million']['output']) / 1e6,
            timings={field: dict(support=len(values), p50=percentile(values, .5),
                                 p95=percentile(values, .95), maximum=max(values))
                     for field, values in timings.items()},
            all_scheduled_raw_exact=quality['arms'][arm]['raw_exact'],
            all_scheduled_denominator=scheduled,
            attempted_denominator=attempted,
            returned_response_denominator=returned,
            returned_response_raw_exact_rate=exact/returned if returned else None,
            all_attempted_raw_exact_rate=exact/attempted if attempted else None,
            all_scheduled_raw_exact_rate=exact/scheduled if scheduled else None)
    return dict(scope='Sealed synthetic extraction component; empirical timing only, no full-report readiness claim',
                quality=quality, metrics=metrics,
                experiment_summary=json.loads((capture / 'summary.json').read_text()),
                economics_limitations='List-price estimates for returned usage only; rejected/missing usage is unknown, not zero billing. No cache discount assumed.',
                selection_decision='No production promotion: broader assembled workflow, reviewed labels, validation and holdout remain required')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--lineage', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.capture, args.labels, args.lineage)
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
