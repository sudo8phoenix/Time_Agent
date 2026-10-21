"""New frozen study after retained strict-grammar rejection; no budget reset.

Original failed and unattempted work remains explicit. Unattempted ordinary trials
are carried forward unchanged; a separately defined equivalent-wire contrast and
previously frozen follow-up controls are scheduled once under remaining ceilings.
"""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import time

from app.llm.hosted import request
from app.llm.metrics import capture_provider_metrics
from app.llm.openrouter import _matches_schema
from evaluation.open_item_study import (
    append, digest, extraction_checks, make_payload, runtime_snapshot, write,
)
from evaluation.open_item_supplement import payload_for
from evaluation.repeated_development import ExperimentStop, TrialBudget
from evaluation.live_pacing import wait_before_case


RETAINED = ['live', 'strict-canary-20b-live', 'strict-canary-120b-live', 'strict-union-live']


def sealed_rows(folder):
    manifest = json.loads((folder/'capture-manifest.json').read_text())
    for name, expected in manifest.items():
        if digest(folder/name) != expected:
            raise ExperimentStop('Retained capture changed')
    return [json.loads(line) for line in (folder/'calls.jsonl').read_text().splitlines()]


def prepare(batch, output):
    batch, output = Path(batch), Path(output)
    base = json.loads((batch/'prepared/plan.json').read_text())
    supplemental = json.loads((batch/'supplement-prepared-v2/plan.json').read_text())
    original = json.loads((batch/'live/summary.json').read_text())
    rows, retained = [], {}
    for name in RETAINED:
        rows += sealed_rows(batch/name)
        retained[name] = dict(manifest_sha256=digest(batch/name/'capture-manifest.json'),
                              summary=json.loads((batch/name/'summary.json').read_text()))
    if original['attempted'] != 24 or not original['stop_reason']:
        raise ExperimentStop('Expected retained strict rejection missing')
    for name in RETAINED[1:]:
        if retained[name]['summary']['stop_reason']:
            raise ExperimentStop('Capability diagnostic did not finish')
    if not rows[-1].get('checks', {}).get('wire_valid'):
        raise ExperimentStop('Equivalent union schema not verified')
    attempted = {row['id'] for row in rows}
    obsolete = ['strict:DEV-20261020-07']
    unattempted = [r for r in base['schedule'] if r['id'] not in attempted]
    carried = [deepcopy(r) for r in unattempted if r['id'] not in obsolete]
    assert len(unattempted) == 64 and len(carried) == 63
    # Strict comparison uses identical accepted wire in both arms, not legacy/new mixing.
    native = []
    for index, case in enumerate(['DEV-20261020-04', 'DEV-20261020-07']):
        order = [False, True] if index == 0 else [True, False]
        for strict in order:
            native.append(dict(id=f'native-{strict}:{case}', case=case, prompt='zero',
                model='openai/gpt-oss-20b', strict=strict, effort='low', kind='extraction',
                schema_variant='explicit_multi_union'))
    followup = [{**r, 'followup': True} for r in supplemental['schedule']]
    control = json.loads((batch/'repair-control-prepared/plan.json').read_text())['trial']
    control = {**control, 'correct_control': True}
    # Do not mix old unsupported strict requests into quality metrics.
    schedule = native+carried+followup+[control]
    assert len(schedule) == 79
    costs = [record['summary']['budget'] for record in retained.values()]
    usage = {key: sum(row[key] for row in costs) for key in
             ['reserved_calls', 'reserved_tokens', 'reserved_list_price_usd']}
    started = datetime.fromisoformat(rows[0]['started_at'])
    deadline = started.timestamp()+base['budget']['wall_seconds']
    limits = dict(base['budget'], calls=79,
                  wall_seconds=max(1, int(deadline-time.time())),
                  reserved_tokens=base['budget']['reserved_tokens']-usage['reserved_tokens'],
                  list_price_usd=base['budget']['list_price_usd']-usage['reserved_list_price_usd'])
    source = dict(base['source_sha256'])
    for path in ['evaluation/open_item_continuation.py', 'evaluation/open_item_supplement.py',
                 'evaluation/strict_union_diagnostic.py']:
        source[path] = digest(path)
    plan = dict(version='open-item-continuation-v1', target_ids=base['target_ids'],
        rationale='Retained original strict HTTP400; minimal strict succeeds and equivalent explicit multi-primitive union grammar succeeds. No failed trial is reissued unchanged.',
        original_plan_sha256=digest(batch/'prepared/plan.json'),
        supplemental_plan_sha256=digest(batch/'supplement-prepared-v2/plan.json'),
        original_unattempted_ids=[r['id'] for r in unattempted],
        carried_forward_ids=[r['id'] for r in carried], retired_unattempted_ids=obsolete,
        retained=retained, retained_budget=usage, absolute_deadline_unix=deadline,
        combined_max_calls=usage['reserved_calls']+len(schedule), combined_max_reserved_tokens=2400000,
        combined_max_reserved_usd=1, budget=limits, key_slot=2,
        schema=json.loads((batch/'strict-union-prepared/plan.json').read_text())['schema'],
        schedule=schedule, source_sha256=source,
        stop_conditions=['New HTTP, identity, source, runtime-work or ceiling failure stops this plan with no retries/fallback.',
                         'Previously stopped original evidence and failed-attempt usage uncertainty remain retained.'],
        release_accepted=False)
    output.mkdir(parents=True, exist_ok=False)
    write(output/'plan.json', plan)
    return plan


def run(batch, prepared, output):
    from app.settings import get_settings
    batch, prepared, output = Path(batch), Path(prepared), Path(output)
    plan = json.loads((prepared/'plan.json').read_text())
    base = json.loads((batch/'prepared/plan.json').read_text())
    supplemental = json.loads((batch/'supplement-prepared-v2/plan.json').read_text())
    if (digest(batch/'prepared/plan.json') != plan['original_plan_sha256'] or
            digest(batch/'supplement-prepared-v2/plan.json') != plan['supplemental_plan_sha256']):
        raise ExperimentStop('Frozen parent plan changed')
    prior = {}
    for name, control in plan['retained'].items():
        if digest(batch/name/'capture-manifest.json') != control['manifest_sha256']:
            raise ExperimentStop('Retained manifest changed')
        for row in sealed_rows(batch/name):
            if row['id'] in prior:
                raise ExperimentStop('Duplicate retained trial')
            prior[row['id']] = row
    if any(r['id'] in prior for r in plan['schedule']):
        raise ExperimentStop('Cannot repeat a retained trial')
    budget = TrialBudget(plan['budget'], {'input': .15, 'output': .60})
    output.mkdir(parents=True, exist_ok=False)
    write(output/'config.json', dict(plan_sha256=digest(prepared/'plan.json'), retained=plan['retained'],
                                    retained_budget=plan['retained_budget'], release_accepted=False))
    write(output/'runtime-before.json', runtime_snapshot())
    token = get_settings().groq_api_key_2.get_secret_value()
    stop = None
    done = 0
    for index, trial in enumerate(plan['schedule']):
        row = {**trial, 'started_at': datetime.now(timezone.utc).isoformat()}
        try:
            for name, expected in plan['source_sha256'].items():
                if digest(name) != expected:
                    raise ExperimentStop('Frozen continuation source changed')
            if time.time() >= plan['absolute_deadline_unix']:
                raise ExperimentStop('Original combined wall-time ceiling reached')
            runtime_snapshot()
            wait_before_case(output, trial['id'], index)
            if trial.get('correct_control') and not prior[trial['parent']].get('checks', {}).get('selected_fields_exact'):
                raise ExperimentStop('Prespecified correct-parent control not correct; no substitution')
            if trial.get('followup'):
                payload = payload_for(trial, supplemental, base, prior)
            else:
                effective = {**base, 'schema': plan['schema']} if trial.get('schema_variant') else base
                payload = make_payload(trial, effective, prior)
            timeout = min(budget.reserve(payload), max(.1, plan['absolute_deadline_unix']-time.time()))
            append(output/'requests.jsonl', dict(id=trial['id'], payload=payload))
            began = time.monotonic()
            with capture_provider_metrics() as metrics:
                status, body = request('groq', 'POST', 'https://api.groq.com/openai/v1/chat/completions',
                    payload, timeout, {'Authorization': 'Bearer '+token})
            row.update(status=status, returned_model=body.get('model'), usage=body.get('usage'),
                       elapsed_seconds=time.monotonic()-began, metrics=metrics)
            if status != 200 or body.get('model') != trial['model']:
                raise ExperimentStop(f'HTTP/identity failure ({status}); no retry or fallback')
            choice = body['choices'][0]
            row['finish_reason'] = choice.get('finish_reason')
            message = choice['message']
            row['message'] = {k: message[k] for k in ['content', 'tool_calls', 'refusal'] if k in message}
            kind = trial['kind']
            if kind == 'guard':
                try:
                    probability = float(message.get('content'))
                    if not 0 <= probability <= 1:
                        raise ValueError()
                    row['checks'] = dict(probability=probability, predicted_attack=probability >= .5,
                                         correct=(probability >= .5) == trial['attack'])
                except (TypeError, ValueError):
                    row['checks'] = dict(unknown_guard_output=True, correct=False)
            elif kind == 'tool':
                calls = message.get('tool_calls') or []
                row['checks'] = dict(tool_called=len(calls) == 1 and
                    calls[0].get('function', {}).get('name') == 'lookup_activity' and
                    json.loads(calls[0]['function'].get('arguments', '{}')) == {'activity_id': 'CB-007'})
            else:
                try:
                    value = json.loads(message.get('content') or '')
                    row['value'] = value
                    schema = payload['response_format']['json_schema']['schema']
                    valid = _matches_schema(value, schema)
                    complete = choice.get('finish_reason') == 'stop' and not message.get('refusal')
                    if kind in {'extraction', 'repair', 'critic', 'demos'}:
                        checks = extraction_checks(value, base['cases'][trial['case']], base['labels'][trial['case']])
                    elif kind == 'selection':
                        expected = 'east' if trial['case'] == 'supported' else None
                        checks = dict(selected_fields_exact=value.get('candidate_id') == expected,
                            quoted_support=value.get('candidate_id') is None or
                                           value.get('quote') == 'Installed cable at asset tag CB-007 in Zone East.')
                    elif kind == 'verdict':
                        checks = dict(valid_verdict=valid and bool(complete), supported=value.get('supported'),
                                      worker_exact=prior[trial['parent']].get('checks', {}).get('selected_fields_exact', False))
                    else:
                        checks = dict(correct=value.get('winner') == (0 if trial['order'] == 'ab' else 1))
                    checks.update(wire_valid=valid, complete=bool(complete))
                    if not valid or not complete:
                        checks.update(selected_fields_exact=False, correct=False)
                    row['checks'] = checks
                except (ValueError, TypeError, KeyError, AttributeError) as e:
                    row['checks'] = dict(parse_error=type(e).__name__, selected_fields_exact=False, correct=False)
            prior[trial['id']] = row
        except BaseException as e:
            stop = str(e) if isinstance(e, ExperimentStop) else type(e).__name__
            row['error_type'] = type(e).__name__
        finally:
            row['budget'] = budget.snapshot()
            row['combined_budget'] = {key: plan['retained_budget'][key]+row['budget'][key]
                for key in ['reserved_calls', 'reserved_tokens', 'reserved_list_price_usd']}
            append(output/'calls.jsonl', row)
            done += 1
            print(json.dumps(dict(index=index+1, total=len(plan['schedule']), id=trial['id'],
                                  checks=row.get('checks'), stop=stop)), flush=True)
        if stop:
            break
    write(output/'summary.json', dict(scheduled=len(plan['schedule']), attempted=done, stop_reason=stop,
        original_stop_retained=plan['retained']['live']['summary']['stop_reason'],
        budget=budget.snapshot(), combined_budget={key: plan['retained_budget'][key]+budget.snapshot()[key]
            for key in ['reserved_calls', 'reserved_tokens', 'reserved_list_price_usd']},
        retired_original_unattempted_ids=plan['retired_unattempted_ids'], release_accepted=False))
    write(output/'runtime-after.json', runtime_snapshot())
    write(output/'capture-manifest.json', {p.name: digest(p) for p in output.iterdir() if p.is_file()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.batch, args.prepared)
        print(json.dumps(dict(calls=len(result['schedule']), retained=result['retained_budget'],
                              remaining_limits=result['budget'], combined_max_calls=result['combined_max_calls'])))
    else:
        run(args.batch, args.prepared, args.output)
