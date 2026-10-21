"""Score sealed assembled captures; missing reports stay in planned denominators."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from evaluation.assembled_development import full_case_score
from evaluation.summarize_repeated_development import percentile


def summarize(capture, prepared):
    manifest = json.loads((capture/'capture-manifest.json').read_text())
    if not {'config.json', 'summary.json', 'preflight.json'} <= set(manifest):
        raise ValueError('Unsealed assembled capture')
    for name, expected in manifest.items():
        if Path(name).name != name or sha256((capture/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Capture integrity failure')
    config = json.loads((capture/'config.json').read_text())
    for name, expected in config['file_sha256'].items():
        if Path(name).name != name or sha256((prepared/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen assembled fixture changed')
    labels = json.loads((prepared/'labels.json').read_text())['cases']
    inputs = {r['case_id']: r for r in json.loads((prepared/'inputs.json').read_text())}
    planned = {r['trial_id']: r for r in config['schedule']}
    if len(planned) != len(config['schedule']):
        raise ValueError('Duplicate scheduled trial')
    reports = [json.loads(line) for line in (capture/'reports.jsonl').read_text().splitlines()] if 'reports.jsonl' in manifest else []
    rows = {}
    for row in reports:
        tid = row['trial_id']
        if (tid not in planned or tid in rows or
                any(row.get(k) != planned[tid][k] for k in ('case_id', 'arm'))):
            raise ValueError('Duplicate, unscheduled or inconsistent report')
        rows[tid] = row
    calls = [json.loads(line) for line in (capture/'calls.jsonl').read_text().splitlines()] if 'calls.jsonl' in manifest else []
    pairs = {(r['case_id'], r['arm']) for r in planned.values()}
    if any((c.get('case_id'), c.get('arm')) not in pairs for c in calls):
        raise ValueError('Unscheduled stage call')
    details = []
    for tid, trial in planned.items():
        row = rows.get(tid)
        details.append(dict(**trial, state=row['state'] if row else 'unattempted',
                            score=full_case_score(row, labels[trial['case_id']], inputs[trial['case_id']]['report_date']) if row else None))
    arms = {}
    for arm in config['arms']:
        scheduled = [r for r in details if r['arm'] == arm]
        attempted = [rows[r['trial_id']] for r in scheduled if r['trial_id'] in rows]
        measured = [c for c in calls if c['arm'] == arm]
        prompt = sum(c.get('usage', {}).get('prompt_tokens', 0) for c in measured)
        output = sum(c.get('usage', {}).get('completion_tokens', 0) for c in measured)
        unknown = sum(not {'prompt_tokens', 'completion_tokens'} <= set(c.get('usage', {})) for c in measured)
        tp = fp = expected_links = correct_link_cases = 0
        ambiguities = 0
        for r in scheduled:
            label = labels[r['case_id']]
            expected = set(label['expected_activity_ids'])
            expected_links += len(expected)
            ambiguities += label['expected_mapping_state'] == 'ambiguous'
            row = rows.get(r['trial_id'], {})
            selected = set(row.get('selected_activity_ids', []))
            ready = row.get('state') == 'ready_for_review'
            matches = len(selected & expected) if ready else 0
            tp += matches
            fp += len(selected) - matches
            correct_link_cases += bool(expected) and ready and selected == expected
        times = [r['elapsed_ms'] for r in attempted]
        arms[arm] = dict(scheduled=len(scheduled), attempted=len(attempted),
            ready=sum(r['state'] == 'ready_for_review' for r in attempted),
            scoped_report_exact=sum(bool(r['score'] and r['score']['full_report_exact']) for r in scheduled),
            selected_link_true_positive=tp, selected_link_false_positive=fp, expected_links=expected_links,
            selected_link_precision=tp/(tp+fp) if tp+fp else None,
            expected_link_case_coverage=correct_link_cases/sum(bool(labels[r['case_id']]['expected_activity_ids']) for r in scheduled),
            ambiguity_successes=sum(bool(r['score'] and r['score']['ambiguity_success']) for r in scheduled),
            ambiguity_cases=ambiguities,
            stage_call_attempts=len(measured), reserved_calls=sum('payload_sha256' in c for c in measured),
            planner_calls=sum(c['stage'] == 'planner' for c in measured),
            failed_stage_calls=sum(not c['ok'] for c in measured),
            terminal_replay_verified=sum(r.get('terminal_replay_reused', False) and r.get('terminal_replay_duplicate_free', False) for r in attempted),
            observed_ledger_writes=sum(r['ledger_writes'] for r in attempted),
            usage=dict(prompt_tokens=prompt, completion_tokens=output, unknown_call_usage=unknown),
            known_list_price_usd=(prompt*config['prices_per_million']['input']+output*config['prices_per_million']['output'])/1e6,
            empirical_attempt_latency_ms=dict(support=len(times), p50=percentile(times, .5), p95=percentile(times, .95)))
    return dict(scoring_version='assembled-development-v1', execution_mode=config['execution_mode'],
                metric_scope=config.get('metric_scope', 'Historical capture lacks a declared metric scope; no expanded quality claim'),
                scheduled=len(planned), arms=arms, trials=details,
                capture_summary=json.loads((capture/'summary.json').read_text()),
                release_accepted=False, decision='Development only; no assembled candidate promoted',
                limitations=['Two consumed synthetic inputs, not independent representative reports.',
                             'Empirical quantiles from two cases per arm are not operational p95 assurance.',
                             'Missing outputs stay in all planned quality/coverage denominators.',
                             'Usage may be unknown on failed calls; known list-price cost is not a bill.',
                             'Semantic evidence/summary review, retrieval Recall@8, endpoints, confidence and fresh validation remain unmeasured.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.capture, args.prepared)
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')
