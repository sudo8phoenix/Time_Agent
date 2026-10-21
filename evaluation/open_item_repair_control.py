"""One preregistered correct-answer repair control; combined spend stays under $1."""
from hashlib import sha256
import argparse
import json
from pathlib import Path
import time

from app.llm.hosted import request
from app.llm.metrics import capture_provider_metrics
from evaluation.open_item_study import (
    SMALL, digest, extraction_checks, make_payload, runtime_snapshot, write,
)
from evaluation.repeated_development import ExperimentStop, TrialBudget


def prepare(batch, output):
    batch, output = Path(batch), Path(output)
    source = Path(__file__)
    plan = dict(version='correct-repair-control-v1', target='PROMPT-09', parent='zero:administrative',
        reason='All three primary repair parents failed the complete contract. A prespecified correct no-event control measures damage rather than reporting zero damage with no correct-parent denominator.',
        trial=dict(id='correct-repair:administrative', case='administrative', prompt='zero', model=SMALL,
                   strict=False, effort='low', kind='repair', parent='zero:administrative'),
        primary_plan_sha256=digest(batch/'prepared/plan.json'), source_sha256={str(source): digest(source)},
        budget=dict(calls=1, wall_seconds=300, request_seconds=180, reserved_tokens=30000,
                    list_price_usd=.01, output_tokens_per_call=3072),
        combined_primary_supplement_control_ceiling_usd=1, key_slot=2, release_accepted=False)
    output.mkdir(parents=True, exist_ok=False)
    write(output/'plan.json', plan)


def run(batch, prepared, output):
    from app.settings import get_settings
    batch, prepared, output = Path(batch), Path(prepared), Path(output)
    plan = json.loads((prepared/'plan.json').read_text())
    base = json.loads((batch/'prepared/plan.json').read_text())
    for path in [batch/'live', batch/'supplement-live']:
        summary = json.loads((path/'summary.json').read_text())
        if summary['stop_reason']:
            raise ExperimentStop('Earlier study stopped; no repair control attempt')
        for name, expected in json.loads((path/'capture-manifest.json').read_text()).items():
            if digest(path/name) != expected:
                raise ExperimentStop('Earlier capture changed')
    if digest(batch/'prepared/plan.json') != plan['primary_plan_sha256']:
        raise ExperimentStop('Primary plan changed')
    for name, expected in plan['source_sha256'].items():
        if digest(name) != expected:
            raise ExperimentStop('Control source changed')
    prior = {r['id']: r for r in [json.loads(line) for line in (batch/'live/calls.jsonl').read_text().splitlines()]}
    original = prior[plan['parent']]
    if original.get('checks', {}).get('selected_fields_exact') is not True:
        raise ExperimentStop('Prespecified correct control was not correct; do not substitute')
    earlier = json.loads((batch/'supplement-live/summary.json').read_text())['primary_plus_supplement_reserved_usd']
    limits = {**plan['budget'], 'list_price_usd': min(plan['budget']['list_price_usd'], 1-earlier)}
    budget = TrialBudget(limits, {'input': .15, 'output': .60})
    runtime_snapshot()
    output.mkdir(parents=True, exist_ok=False)
    payload = make_payload(plan['trial'], base, prior)
    write(output/'request.json', dict(id=plan['trial']['id'], payload=payload))
    token = get_settings().groq_api_key_2.get_secret_value()
    row = dict(plan['trial'])
    stop = None
    try:
        timeout = budget.reserve(payload)
        began = time.monotonic()
        with capture_provider_metrics() as metrics:
            status, body = request('groq', 'POST', 'https://api.groq.com/openai/v1/chat/completions',
                payload, timeout, {'Authorization': 'Bearer '+token})
        row.update(status=status, usage=body.get('usage'), elapsed_seconds=time.monotonic()-began, metrics=metrics)
        if status != 200 or body.get('model') != SMALL:
            raise ExperimentStop('Provider/identity failure; no retry')
        choice = body['choices'][0]
        row['finish_reason'] = choice.get('finish_reason')
        message = choice['message']
        row['message'] = {k: message[k] for k in ['content', 'refusal'] if k in message}
        try:
            value = json.loads(message.get('content') or '')
            row['value'] = value
            row['checks'] = extraction_checks(value, base['cases']['administrative'], [])
            row['checks']['selected_fields_exact'] &= choice.get('finish_reason') == 'stop' and not message.get('refusal')
        except (ValueError, TypeError, KeyError, AttributeError):
            row['checks'] = dict(selected_fields_exact=False, parse_error=True)
    except BaseException as e:
        stop = str(e) if isinstance(e, ExperimentStop) else type(e).__name__
        row['error_type'] = type(e).__name__
    row['budget'] = budget.snapshot()
    with (output/'calls.jsonl').open('x') as f:
        f.write(json.dumps(row)+'\n')
    write(output/'summary.json', dict(attempted=1, scheduled=1, stop_reason=stop, budget=budget.snapshot(),
        all_study_reserved_usd=earlier+budget.usd, before=True,
        after=row.get('checks', {}).get('selected_fields_exact', False), release_accepted=False))
    write(output/'capture-manifest.json', {p.name: sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()})
    print(json.dumps(row.get('checks')), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.batch, args.prepared)
    else:
        run(args.batch, args.prepared, args.output)
