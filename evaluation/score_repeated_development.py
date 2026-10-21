"""Score every frozen trial, retaining missing/error outcomes and paired groups."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import random
from statistics import mean

from evaluation.metrics import _prediction_failed
from evaluation.score_paired_pilot import completed_event_scores, event_scores, fields_exact


def score(capture, labels, lineage):
    manifest = json.loads((capture / 'capture-manifest.json').read_text())
    required = {'config.json', 'summary.json', 'preflight.json'}
    if not required.issubset(manifest):
        raise ValueError('Unsealed capture')
    for name, digest in manifest.items():
        if Path(name).name != name or sha256((capture / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Capture integrity failure')
    config = json.loads((capture / 'config.json').read_text())
    for path in (labels, lineage):
        if config['source_sha256'].get(str(path)) != sha256(path.read_bytes()).hexdigest():
            raise ValueError('Frozen labels/lineage changed')
    truth = json.loads(labels.read_text())['cases']
    groups = json.loads(lineage.read_text())['cases']
    scheduled = {r['trial_id']: r for r in config['schedule']}
    if len(scheduled) != len(config['schedule']):
        raise ValueError('Duplicate scheduled trial')

    def read_rows(name):
        rows = [json.loads(s) for s in (capture / name).read_text().splitlines()] if name in manifest else []
        indexed = {}
        for row in rows:
            trial = scheduled.get(row.get('trial_id'))
            if (not trial or row['trial_id'] in indexed or
                    any(row.get(k) != trial[k] for k in ('case_id', 'arm', 'repetition', 'strict'))):
                raise ValueError('Duplicate, unscheduled or inconsistent trial')
            indexed[row['trial_id']] = row
        return indexed

    predictions = read_rows('predictions.jsonl')
    outputs = read_rows('model-outputs.jsonl')
    details = []
    for tid, trial in scheduled.items():
        row = predictions.get(tid, {})
        checks = row.get('response_checks', {})
        completed = (row.get('state') == 'completed' and not _prediction_failed(row)
                     and isinstance(row.get('observations'), list))
        valid_response = (checks.get('response_complete') is True and checks.get('refusal_present') is False
                          and checks.get('wire_schema_valid') is True
                          and checks.get('raw_domain_schema_valid') is True
                          and checks.get('source_units_complete', True) is True)
        raw_value = outputs.get(tid, {}).get('value', {})
        valid_response = valid_response and isinstance(raw_value.get('observations'), list)
        initial = raw_value.get('observations', [])
        observed = row.get('observations', [])
        expected = truth[trial['case_id']]
        details.append({**trial, 'group_id': groups[trial['case_id']]['group_id'],
                        'state': row.get('state', 'unattempted'), 'completed': completed,
                        'response_checks': checks,
                        'raw_fields_exact': valid_response and fields_exact(expected, initial),
                        'normalized_fields_exact': completed and valid_response and fields_exact(expected, observed),
                        'raw_events': event_scores(expected, initial),
                        'normalized_events': completed_event_scores(
                            expected, observed, completed=completed and valid_response)})
    arms = {}
    for arm in config['prompts']:
        rows = [r for r in details if r['arm'] == arm]
        arms[arm] = dict(scheduled=len(rows), attempted=sum(r['state'] != 'unattempted' for r in rows),
                         completed=sum(r['completed'] for r in rows),
                         raw_exact=sum(r['raw_fields_exact'] for r in rows),
                         normalized_exact=sum(r['normalized_fields_exact'] for r in rows),
                         per_case={cid: dict(scheduled=len(sub), raw_exact=sum(r['raw_fields_exact'] for r in sub),
                                             normalized_exact=sum(r['normalized_fields_exact'] for r in sub),
                                             states=dict(Counter(r['state'] for r in sub)))
                                   for cid in sorted({r['case_id'] for r in rows})
                                   if (sub := [r for r in rows if r['case_id'] == cid])})
    comparison = None
    arm_names = list(arms)
    if len(arm_names) == 2:
        a, b = arm_names
        grouped = sorted({r['group_id'] for r in details})
        differences = []
        for group in grouped:
            values = {arm: mean(r['raw_fields_exact'] for r in details if r['group_id'] == group and r['arm'] == arm)
                      for arm in arm_names}
            differences.append(values[b] - values[a])
        rng = random.Random(20261020)
        boot = sorted(mean(rng.choices(differences, k=len(differences))) for _ in range(5000))
        comparison = dict(candidate=b, baseline=a, paired_groups=len(grouped),
                          raw_macro_difference=mean(differences),
                          exploratory_group_bootstrap_95=[boot[124], boot[4874]],
                          warning='Small synthetic consumed groups; repeated trials are correlated; no release assurance')
    return dict(scoring_version='repeated-development-v3-completion-fences', scheduled=len(details), arms=arms,
                paired_comparison=comparison, trials=details,
                decision='inconclusive for production; development evidence only',
                unmeasured=['evidence entailment', 'correction summary', 'workflow safety/quality', 'latency gates'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--lineage', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = score(args.capture, args.labels, args.lineage)
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
