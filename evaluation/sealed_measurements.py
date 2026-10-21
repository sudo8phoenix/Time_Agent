"""Read-only historical usage/call measurements from sealed live captures.

No provider APIs, current pricing, credentials, tokenizers or billing inference.
Unknown usage remains unknown. Saved scored mappings are provisional labels.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from statistics import mean


def distribution(values):
    values = sorted(values)
    return dict(n=len(values), mean=mean(values) if values else None,
                p95_nearest_rank=values[ceil(.95*len(values))-1] if values else None,
                maximum=max(values) if values else None)


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sealed(path):
    manifest = json.loads((path/'capture-manifest.json').read_text())
    for name, expected in manifest.items():
        if Path(name).name != name or sha256((path/name).read_bytes()).hexdigest() != expected:
            raise ValueError('capture seal mismatch')
    config = json.loads((path/'config.json').read_text())
    if config.get('execution_mode') != 'live_groq':
        raise ValueError('historical live capture required')
    needed = {'config.json', 'summary.json'} | ({'calls.jsonl', 'reports.jsonl', 'reservations.jsonl'}
             if (path/'calls.jsonl').exists() else {'usage.jsonl', 'predictions.jsonl', 'model-outputs.jsonl'})
    if not needed.issubset(manifest):
        raise ValueError('required capture files are not sealed')
    return config, manifest


def _integer(value):
    return type(value) is int and value >= 0


def usage_summary(calls, prices):
    measurements = {name: [] for name in ['prompt_tokens', 'completion_tokens', 'total_tokens']}
    unknown = Counter()
    cost = 0
    known_cost_calls = 0
    for call in calls:
        usage = call.get('usage') or {}
        for name in measurements:
            if _integer(usage.get(name)):
                measurements[name].append(usage[name])
            else:
                unknown[name] += 1
        if all(_integer(usage.get(key)) for key in ['prompt_tokens', 'completion_tokens']):
            cost += (usage['prompt_tokens']*prices['input'] + usage['completion_tokens']*prices['output'])/1_000_000
            known_cost_calls += 1
    return dict(calls=len(calls), tokens={key: {**distribution(values), 'sum': sum(values),
                     'unknown_calls': unknown[key]} for key, values in measurements.items()},
                observed_token_list_price_usd=round(cost, 9), known_cost_calls=known_cost_calls,
                unknown_cost_calls=len(calls)-known_cost_calls,
                total_cost_known=known_cost_calls == len(calls),
                reasoning_tokens_known_calls=sum(_integer((c.get('usage') or {}).get('reasoning_tokens')) for c in calls),
                cached_tokens_known_calls=sum(_integer((c.get('usage') or {}).get('cached_tokens')) for c in calls))


def analyze(path):
    path = Path(path)
    config, manifest = sealed(path)
    assembled = (path/'calls.jsonl').exists()
    reports = rows(path/'reports.jsonl') if assembled else rows(path/'predictions.jsonl')
    calls = rows(path/'calls.jsonl') if assembled else rows(path/'usage.jsonl')
    if not assembled:
        outputs = rows(path/'model-outputs.jsonl')
        if len(calls) != len(reports) or len(outputs) != len(reports):
            raise ValueError('usage/prediction/output attempt count mismatch')
        calls = [dict(row, stage='extraction', ok=prediction.get('state') == 'completed',
                      output=output.get('value')) for row, prediction, output in zip(calls, reports, outputs)]
        if any(call.get('trial_id') != output.get('trial_id') for call, output in zip(calls, outputs)):
            raise ValueError('usage/output identity mismatch')
        for call, report in zip(calls, reports):
            if call.get('trial_id') != report.get('trial_id'):
                raise ValueError('usage/prediction identity mismatch')
    stages = defaultdict(list)
    for call in calls:
        stages[call['stage']].append(call)
    prices = config['prices_per_million']
    measured = usage_summary(calls, prices)
    result = dict(capture=str(path), seal_verified=True, source_hashes=manifest,
                  execution_mode=config['execution_mode'], model=config.get('model'),
                  historical_key_slot=config.get('key_slot'), historical_prices_per_million=prices,
                  price_checked=config.get('price_checked'), budget=config['budget'],
                  attempts=len(reports), calls=len(calls), failed_calls=sum(c.get('ok') is not True for c in calls),
                  usage=measured, stages={key: usage_summary(value, prices) for key, value in stages.items()},
                  failed_attempt_usage=usage_summary([call for call in calls if call.get('ok') is not True], prices),
                  output_budget_review={key: dict(valid_completion_tokens=distribution([
                      c['usage']['completion_tokens'] for c in value if c.get('ok') is True
                      and _integer((c.get('usage') or {}).get('completion_tokens'))]),
                      existing_ceiling=config['budget']['output_tokens_per_call'],
                      ceiling_reduced=False, reasoning_breakdown_available=False) for key, value in stages.items()},
                  release_accepted=False, current_billing_known=False, conversations_observed=0,
                  cache_hit_rate=None)
    for key, value in stages.items():
        result['output_budget_review'][key]['valid_output_utf8_bytes'] = distribution([
            len(json.dumps(c['output'], ensure_ascii=False).encode()) for c in value
            if c.get('ok') is True and isinstance(c.get('output'), dict)])
        result['output_budget_review'][key]['valid_multi_event_outputs'] = sum(
            c.get('ok') is True and len((c.get('output') or {}).get('observations', [])) > 1 for c in value)
    if assembled:
        by_report = defaultdict(list)
        for call in calls:
            by_report[(call['case_id'], call['arm'])].append(call)
        arms = defaultdict(list)
        recall_hits = eligible = 0
        recall_rows = []
        for report in reports:
            key = (report['case_id'], report['arm'])
            group = by_report[key]
            embedded = report.get('calls', [])
            if embedded != [{k:v for k,v in call.items() if k not in {'case_id','arm'}} for call in group]:
                raise ValueError('embedded report calls disagree with call ledger')
            success = report.get('state') == 'ready_for_review' and report.get('full_case_score', {}).get('full_report_exact') is True
            planners = [call for call in group if call['stage'] == 'planner']
            actions = [call.get('output', {}).get('action') for call in planners]
            arms[report['arm']].append(dict(calls=len(group), planner_calls=len(planners), success=success,
                stage_counts=dict(Counter(call['stage'] for call in group)), elapsed_ms=report.get('elapsed_ms'),
                plan_valid=actions == ['intake','analysis','review'] if planners else None,
                usage=usage_summary(group, prices)))
            # Gold eligibility is the saved synthetic expectation, not selected-ID presence.
            if report.get('scores', {}).get('abstention_expected') is False:
                eligible += 1
                retrieval = [call for call in group if call['stage'] == 'retrieval']
                selection = [call for call in group if call['stage'] == 'selection']
                correct = report.get('full_case_score', {}).get('mapping_exact') is True
                selected = selection[0].get('output', {}).get('candidate_id') if len(selection) == 1 and correct else None
                candidates = retrieval[0].get('output', {}).get('candidate_ids', []) if len(retrieval) == 1 else []
                hit = selected is not None and selected in candidates[:8]
                recall_hits += hit
                recall_rows.append(dict(case_id=key[0], arm=key[1], hit=hit, shortlist_size=len(candidates),
                    gold_identity_recovered_from_saved_correct_mapping=selected is not None))
        result['candidate_recall_at8'] = dict(eligible=eligible, hits=recall_hits,
            recall=recall_hits/eligible if eligible else None, rows=recall_rows,
            limitation='Two synthetic matchable reports; gold UUID recovered through separately saved exact-mapping result; ambiguous reports excluded; not representative recall')
        result['arms'] = {}
        for arm, samples in arms.items():
            successes = sum(sample['success'] for sample in samples)
            arm_calls = [call for call in calls if call['arm'] == arm]
            arm_usage = usage_summary(arm_calls, prices)
            result['arms'][arm] = dict(attempts=len(samples), exact_successes=successes,
                calls_per_attempt=distribution([sample['calls'] for sample in samples]),
                planner_calls=sum(sample['planner_calls'] for sample in samples),
                planner_calls_per_success=sum(sample['planner_calls'] for sample in samples)/successes if successes else None,
                valid_plan_reports=sum(sample['plan_valid'] is True for sample in samples),
                invalid_plan_reports=sum(sample['plan_valid'] is False for sample in samples),
                elapsed_ms=distribution([sample['elapsed_ms'] for sample in samples]), usage=arm_usage,
                tokens_per_report=distribution([sample['usage']['tokens']['total_tokens']['sum'] for sample in samples
                    if sample['usage']['tokens']['total_tokens']['unknown_calls'] == 0]),
                known_list_price_per_exact_success=arm_usage['observed_token_list_price_usd']/successes if successes and arm_usage['total_cost_known'] else None)
        reservations = rows(path/'reservations.jsonl')
        estimates = []
        previous = 0
        for reservation, call in zip(reservations, calls):
            if any(reservation.get(key) != call.get(key) for key in ['case_id','arm','stage']):
                raise ValueError('reservation/call identity mismatch')
            estimate = reservation['reserved_tokens'] - previous
            previous = reservation['reserved_tokens']
            actual = (call.get('usage') or {}).get('total_tokens')
            estimates.append(dict(stage=call['stage'], reserved_token_estimate_including_output_ceiling=estimate,
                                  provider_total_tokens=actual, ratio=estimate/actual if _integer(actual) and actual else None))
        if len(reservations) != len(calls):
            raise ValueError('reservation/call attempt count mismatch')
        result['reservation_vs_observed'] = estimates
        result['observed_spend_within_frozen_budget'] = measured['observed_token_list_price_usd'] <= config['budget']['list_price_usd'] if measured['total_cost_known'] else None
    result['limitations'] = ['Historical observed usage and dated list prices, not current account quota or billing.',
        'Small consumed synthetic cohorts; empirical p95 is descriptive, not a population estimate.',
        'No separate reasoning/cache usage was captured; missing usage is never zero.',
        'No conversations, embedding comparison, oracle context or independent semantic adjudication measured.']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.output.open('x') as stream:
        json.dump({'version':'sealed-measurements-v1', 'captures':[analyze(path) for path in args.capture]}, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
