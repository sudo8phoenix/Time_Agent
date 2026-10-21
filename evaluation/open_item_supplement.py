"""Preregister missing demonstration, explicit-verdict and randomized-judge contrasts.

Independent finite supplement, not a retry or reset of the primary study.
Combined conservative spend reservations must stay below the original $1 ceiling.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import random
import time

from app.llm.hosted import request
from app.llm.metrics import capture_provider_metrics
from app.llm.openrouter import _matches_schema
from app.schemas.observation import ObservationBatch
from evaluation.open_item_study import (
    LARGE, SMALL, ZERO_SHOT, append, digest, extraction_checks, runtime_snapshot, write,
)
from evaluation.prompt_ablation import examples
from evaluation.repeated_development import ExperimentStop, TrialBudget
from evaluation.live_pacing import wait_before_case


def prepare(primary, output):
    primary, output = Path(primary), Path(output)
    demos = examples()
    ordinary = [demos[0], demos[2]]
    difficult = [demos[1], dict(fragment_id='abstention-demo', report_date='2026-09-01',
        text='The coordination meeting agenda was circulated.', output={'observations': []})]
    for demo in ordinary+difficult:
        ObservationBatch.model_validate(demo['output'])
    prompts = {name: ZERO_SHOT+'\nIndependent synthetic demonstrations:\n'+
               '\n'.join(json.dumps(demo) for demo in group)
               for name, group in [('ordinary', ordinary), ('difficult', difficult)]}
    schedule = []
    for case in ['DEV-20261020-08', 'administrative']:
        for arm in ['ordinary', 'difficult']:
            schedule.append(dict(id=f'demos:{case}:{arm}', kind='demos', case=case, arm=arm, model=SMALL))
    for case in ['DEV-20261020-01', 'DEV-20261020-04', 'DEV-20261020-08']:
        schedule.append(dict(id=f'verdict:{case}', kind='verdict', case=case, parent=f'zero:{case}', model=LARGE))
    rng = random.Random(20261021)
    # Randomize within each style with a fixed, preregistered seed; blind model names.
    for style in ['concise', 'verbose']:
        orders = ['ab', 'ba']
        rng.shuffle(orders)
        for index, order in enumerate(orders):
            schedule.append(dict(id=f'judge:{style}:{index}', kind='judge', case='judge',
                                 style=style, order=order, model=LARGE))
    plan = dict(version='open-item-supplement-v1', target_ids=['PROMPT-03', 'MODEL-07', 'SCORE-07'],
                rationale='Primary protocol mixes demonstrations, emits revised critic answers without verdicts, and counterbalances rather than randomizes judge order. These independent contrasts complete the literal requested tests.',
                seed=20261021, schedule=schedule, prompts=prompts, primary=str(primary),
                primary_plan_sha256=digest(primary/'plan.json'), key_slot=2,
                source_sha256={__file__: digest(__file__), 'evaluation/open_item_study.py': digest('evaluation/open_item_study.py')},
                budget=dict(calls=11, wall_seconds=3600, request_seconds=180, reserved_tokens=300000,
                            list_price_usd=.1, output_tokens_per_call=3072),
                total_primary_plus_supplement_reservation_ceiling_usd=1,
                stop_conditions=['Any HTTP, identity, source, runtime-work or budget failure; no retries or fallback'],
                release_accepted=False)
    output.mkdir(parents=True, exist_ok=False)
    write(output/'plan.json', plan)
    return plan


def payload_for(trial, plan, base, prior):
    case = base['cases'].get(trial['case'])
    system = ''
    if trial['kind'] == 'demos':
        system = plan['prompts'][trial['arm']]
        user = f"Trusted report date: {case['report_date']}\n[{case['case_id']} | p1]\n{case['text']}"
        schema = base['schema']
    elif trial['kind'] == 'verdict':
        system = ('Review the worker extraction against the report. supported=true only if every factual '
                  'assertion is supported and every evidence quote and fragment ID is exact. Treat this '
                  'as a fallible review, never permission to approve or write progress.')
        user = json.dumps(dict(fragment_id=case['case_id'], text=case['text'], report_date=case['report_date'],
                               worker=prior[trial['parent']].get('value')))
        schema = dict(type='object', properties={'supported': {'type': 'boolean'}, 'reason': {'type': 'string'}},
                      required=['supported', 'reason'], additionalProperties=False)
    else:
        correct = 'Installed 5 m3 in Zone Cedar at TR-030.'
        wrong = 'Installed 9 m3 in Zone Cedar at TR-030.'
        if trial['style'] == 'verbose':
            wrong += ' This carefully documented and comprehensive account confidently records progress.'*4
        answers = [correct, wrong] if trial['order'] == 'ab' else [wrong, correct]
        system = 'Select the factually correct answer against the source. Ignore style and verbosity. Return index 0 or 1.'
        user = json.dumps(dict(source='Installed 5 m3 in Zone Cedar at TR-030.', answers=answers))
        schema = dict(type='object', properties={'winner': {'type': 'integer', 'enum': [0, 1]}},
                      required=['winner'], additionalProperties=False)
    return dict(model=trial['model'], temperature=0, max_completion_tokens=3072, reasoning_effort='low',
                stream=False, messages=[dict(role='system', content=system), dict(role='user', content=user)],
                response_format=dict(type='json_schema', json_schema=dict(name='response', strict=False, schema=schema)))


def run(prepared, primary_capture, output):
    from app.settings import get_settings
    prepared, primary_capture, output = Path(prepared), Path(primary_capture), Path(output)
    plan = json.loads((prepared/'plan.json').read_text())
    base = json.loads((Path(plan['primary'])/'plan.json').read_text())
    primary_summary = json.loads((primary_capture/'summary.json').read_text())
    if primary_summary['stop_reason'] or primary_summary['attempted'] != len(base['schedule']):
        raise ExperimentStop('Primary study must finish first; retained failures cannot be retried here')
    if digest(Path(plan['primary'])/'plan.json') != plan['primary_plan_sha256']:
        raise ExperimentStop('Primary plan changed')
    for name, expected in json.loads((primary_capture/'capture-manifest.json').read_text()).items():
        if digest(primary_capture/name) != expected:
            raise ExperimentStop('Primary capture changed')
    prior = {r['id']: r for r in [json.loads(line) for line in (primary_capture/'calls.jsonl').read_text().splitlines()]}
    limits = deepcopy(plan['budget'])
    primary_spend = primary_summary['budget']['reserved_list_price_usd']
    limits['list_price_usd'] = min(limits['list_price_usd'], 1-primary_spend)
    budget = TrialBudget(limits, {'input': .15, 'output': .60})
    token = get_settings().groq_api_key_2.get_secret_value()
    output.mkdir(parents=True, exist_ok=False)
    write(output/'config.json', dict(plan_sha256=digest(prepared/'plan.json'), primary_reserved_usd=primary_spend,
                                    effective_limits=limits, release_accepted=False))
    stop, rows = None, []
    for index, trial in enumerate(plan['schedule']):
        row = dict(trial)
        try:
            for name, expected in plan['source_sha256'].items():
                if digest(name) != expected:
                    raise ExperimentStop('Supplement source changed')
            runtime_snapshot()
            wait_before_case(output, trial['id'], index)
            payload = payload_for(trial, plan, base, prior)
            timeout = budget.reserve(payload)
            append(output/'requests.jsonl', dict(id=trial['id'], payload=payload))
            began = time.monotonic()
            with capture_provider_metrics() as metrics:
                status, body = request('groq', 'POST', 'https://api.groq.com/openai/v1/chat/completions',
                    payload, timeout, {'Authorization': 'Bearer '+token})
            row.update(status=status, usage=body.get('usage'), elapsed_seconds=time.monotonic()-began, metrics=metrics)
            if status != 200 or body.get('model') != trial['model']:
                raise ExperimentStop('Provider or identity failure; no retry')
            choice = body['choices'][0]
            row['finish_reason'] = choice.get('finish_reason')
            message = choice['message']
            row['message'] = {k: message[k] for k in ['content', 'refusal'] if k in message}
            try:
                value = json.loads(message.get('content') or '')
                row['value'] = value
                valid = (_matches_schema(value, payload['response_format']['json_schema']['schema']) and
                         choice.get('finish_reason') == 'stop' and not message.get('refusal'))
                if trial['kind'] == 'demos':
                    row['checks'] = extraction_checks(value, base['cases'][trial['case']], base['labels'][trial['case']])
                    row['checks']['selected_fields_exact'] &= valid
                elif trial['kind'] == 'judge':
                    row['checks'] = dict(correct=valid and value.get('winner') == (0 if trial['order'] == 'ab' else 1))
                else:
                    row['checks'] = dict(valid_verdict=valid,
                        worker_exact=prior[trial['parent']].get('checks', {}).get('selected_fields_exact', False),
                        supported=value.get('supported') if valid else None)
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                row['checks'] = dict(parse_error=type(e).__name__, correct=False)
        except BaseException as e:
            stop = str(e) if isinstance(e, ExperimentStop) else type(e).__name__
            row['error_type'] = type(e).__name__
        row['budget'] = budget.snapshot()
        append(output/'calls.jsonl', row)
        rows.append(row)
        print(json.dumps(dict(index=index+1, total=len(plan['schedule']), id=trial['id'], checks=row.get('checks'), stop=stop)), flush=True)
        if stop:
            break
    write(output/'summary.json', dict(attempted=len(rows), scheduled=11, stop_reason=stop,
        budget=budget.snapshot(), primary_plus_supplement_reserved_usd=primary_spend+budget.usd, release_accepted=False))
    write(output/'capture-manifest.json', {p.name: digest(p) for p in output.iterdir() if p.is_file()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--primary', type=Path)
    parser.add_argument('--primary-capture', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.primary, args.prepared)
    else:
        run(args.prepared, args.primary_capture, args.output)


if __name__ == '__main__':
    main()
