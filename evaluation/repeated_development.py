"""Execute sealed development plans with unique trials and cumulative ceilings.

Production admission remains enabled. No credential fallback, retries, repairs,
resume, production setting changes or side effects beyond saved test evidence.
"""
from datetime import date, datetime, timezone
from dataclasses import replace
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path
import time

from pydantic import ValidationError

from app.llm.extract import MAX_BATCH_CHARS, FragmentInput, extract_fragments
from app.llm.groq import GroqChatAdapter
from app.llm.hosted import request
from app.llm.metrics import capture_provider_metrics
from app.llm.openrouter import _matches_schema
from app.schemas.observation import ObservationBatch
from evaluation.source_units import source_units, project, project_map
from evaluation.experiment_guard import FrozenExperimentGuard
from evaluation.error_taxonomy import diagnose


class ExperimentStop(RuntimeError):
    pass


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, default=str) + '\n')


def append(path, value):
    with path.open('a') as stream:
        stream.write(json.dumps(value, default=str) + '\n')
        stream.flush()


class TrialBudget:
    def __init__(self, limits, prices, *, clock=time.monotonic):
        self.limits, self.prices, self.clock = limits, prices, clock
        self.started = clock()
        self.calls = self.tokens = 0
        self.usd = 0.0

    def reserve(self, payload):
        remaining = self.limits['wall_seconds'] - (self.clock() - self.started)
        output = payload['max_completion_tokens']
        if type(output) is not int or not 0 < output <= self.limits['output_tokens_per_call']:
            raise ExperimentStop('Invalid output reservation')
        # UTF-8 bytes plus framing: conservative reservation, not measured usage.
        source = len(json.dumps(payload, ensure_ascii=False).encode()) + 1024
        tokens = source + output
        usd = (source * self.prices['input'] + output * self.prices['output']) / 1e6
        if (remaining <= 1 or self.calls + 1 > self.limits['calls'] or
                self.tokens + tokens > self.limits['reserved_tokens'] or
                self.usd + usd > self.limits['list_price_usd']):
            raise ExperimentStop('Cumulative budget exhausted')
        self.calls += 1
        self.tokens += tokens
        self.usd += usd
        return min(remaining, self.limits['request_seconds'])

    def snapshot(self):
        return dict(reserved_calls=self.calls, reserved_tokens=self.tokens,
                    reserved_list_price_usd=self.usd,
                    elapsed_seconds=round(self.clock() - self.started, 3))


def verify_plan(prepared):
    plan = json.loads((prepared / 'plan.json').read_text())
    for name, expected in plan['source_sha256'].items():
        if digest(Path(name)) != expected:
            raise ExperimentStop('Frozen source changed: ' + name)
    wire = json.loads((prepared / 'wire-schema.json').read_text())
    if sha256(json.dumps(wire, sort_keys=True).encode()).hexdigest() != plan['wire_schema_sha256']:
        raise ExperimentStop('Wire schema changed')
    schedule = plan['schedule']
    if type(plan.get('continue_content_failures', False)) is not bool:
        raise ExperimentStop('Invalid content-failure policy')
    if not schedule or len({r['trial_id'] for r in schedule}) != len(schedule):
        raise ExperimentStop('Duplicate/empty trial schedule')
    numeric_limits = ('calls', 'reserved_tokens', 'list_price_usd', 'wall_seconds',
                      'request_seconds', 'output_tokens_per_call')
    if any(type(plan['budget'][k]) not in (int, float) or not math.isfinite(plan['budget'][k])
           or plan['budget'][k] <= 0 for k in numeric_limits):
        raise ExperimentStop('Invalid budget limits')
    if any(type(plan['budget'][k]) is not int for k in ('calls', 'reserved_tokens', 'output_tokens_per_call')):
        raise ExperimentStop('Invalid integer budget limits')
    if (plan['model'] not in {'openai/gpt-oss-20b', 'openai/gpt-oss-120b'} or
            type(plan['key_slot']) is not int or plan['key_slot'] != 2 or
            plan['budget']['calls'] > 60 or len(schedule) > plan['budget']['calls'] or
            plan['budget']['list_price_usd'] > 1 or plan['budget']['reserved_tokens'] > 2400000 or
            plan['budget']['wall_seconds'] > 10800 or not 30 <= plan['budget']['request_seconds'] <= 180 or
            not 1536 <= plan['budget']['output_tokens_per_call'] <= 4096 or
            any(type(plan['budget'][key]) is not int or plan['budget'][key] != value
                for key, value in [('retries', 0), ('repairs', 0), ('concurrency', 1)])):
        raise ExperimentStop('Unsupported experiment settings')
    prices = plan['prices_per_million']
    if any(type(prices[k]) not in (int, float) or not math.isfinite(prices[k]) or prices[k] <= 0
           for k in ('input', 'output')):
        raise ExperimentStop('Invalid price reservation')
    cases = json.loads(Path(plan['fixture_path']).read_text())
    if any(set(c) != {'case_id', 'report_date', 'text'} for c in cases):
        raise ExperimentStop('Model inputs must contain only allowlisted fields')
    if any(not c['text'].strip() or len(c['text']) > MAX_BATCH_CHARS for c in cases):
        raise ExperimentStop('Unsupported input length')
    inputs = {c['case_id']: c for c in cases}
    if len(inputs) != len(cases):
        raise ExperimentStop('Duplicate case inputs')
    for row in schedule:
        if (type(row.get('repetition')) is not int or not 1 <= row['repetition'] <= 3 or
                row['case_id'] not in inputs or row['arm'] not in plan['prompts'] or
                type(row['strict']) is not bool or row.get('reasoning_effort', 'low') not in {'low', 'medium'} or
                row.get('response_mode', 'flat') not in {'flat', 'source-units', 'source-map'}):
            raise ExperimentStop('Unknown trial input/arm')
    if any(row.get('response_mode') == 'source-units' for row in schedule):
        units_wire = json.loads((prepared / 'unit-wire-schema.json').read_text())
        if sha256(json.dumps(units_wire, sort_keys=True).encode()).hexdigest() != plan.get('unit_wire_schema_sha256'):
            raise ExperimentStop('Source-unit wire schema changed')
    if any(row.get('response_mode') == 'source-map' for row in schedule):
        maps = json.loads((prepared / 'unit-map-schemas.json').read_text())
        digests = {key: sha256(json.dumps(value, sort_keys=True).encode()).hexdigest() for key, value in maps.items()}
        if digests != plan.get('unit_map_schema_sha256') or any(r['case_id'] not in maps for r in schedule):
            raise ExperimentStop('Source-map schemas changed')
    return plan, wire, inputs


def validate_preflight(preflight, plan):
    now = datetime.now(timezone.utc)
    try:
        checked_at = datetime.fromisoformat(preflight['checked_at'])
        if checked_at.tzinfo is None:
            raise ValueError('Unanchored preflight timestamp')
        age = (now - checked_at).total_seconds()
    except (KeyError, TypeError, ValueError):
        raise ExperimentStop('Invalid preflight timestamp') from None
    if not 0 <= age <= 3600:
        raise ExperimentStop('Preflight must be at most one hour old')
    flags = ('model_access_verified', 'price_verified', 'no_pending_work',
             'no_active_lease_or_cooldown')
    remaining = preflight.get('remaining_requests')
    if (preflight.get('model') != plan['model'] or preflight.get('key_slot') != 2 or
            any(preflight.get(flag) is not True for flag in flags) or
            preflight.get('prices_per_million') != plan['prices_per_million'] or
            type(remaining) is not int or remaining < len(plan['schedule'])):
        raise ExperimentStop('Provider/account/runtime preflight incomplete')


def execute(prepared, output, preflight, *, token=None, transport=None, clock=time.monotonic):
    plan, wire, inputs = verify_plan(prepared)
    validate_preflight(preflight, plan)
    integrity = FrozenExperimentGuard(prepared, plan)
    if transport is None:
        from app.settings import get_settings
        key = get_settings().groq_api_key_2
        if not key:
            raise ExperimentStop('Slot 2 not configured')
        token = key.get_secret_value()
    budget = TrialBudget(plan['budget'], plan['prices_per_million'], clock=clock)
    unit_wire = (json.loads((prepared / 'unit-wire-schema.json').read_text())
                 if 'unit_wire_schema_sha256' in plan else None)
    map_wires = (json.loads((prepared / 'unit-map-schemas.json').read_text())
                 if 'unit_map_schema_sha256' in plan else {})
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'config.json', {**plan,
                                  'scope': 'AI-authored consumed development; unaccepted candidate',
                                  'execution_mode': 'injected_transport' if transport else 'live_groq',
                                  'execution_status': 'started', 'prepared_plan_sha256': digest(prepared / 'plan.json'),
                                  'started_at': datetime.now(timezone.utc).isoformat()})
    write(output / 'preflight.json', preflight)
    rows = []
    stopped = None
    try:
        for trial in plan['schedule']:
            case = inputs[trial['case_id']]
            row = {**trial, 'state': 'failed', 'requested_model': plan['model']}
            checks, metrics = {}, {}
            content_failure = None
            mode = trial.get('response_mode', 'flat')
            units = source_units(case['text'], split_semicolons=mode != 'source-map') if mode != 'flat' else None
            effective_wire = map_wires[case['case_id']] if mode == 'source-map' else unit_wire if units else wire
            project_value = project_map if mode == 'source-map' else project
            row['source_unit_count'] = len(units) if units else None
            began = clock()

            def call_transport(method, url, payload, timeout, headers):
                nonlocal content_failure
                # Evaluation-only override, frozen and reserved before transport.
                # The production adapter's output cap remains unchanged.
                payload['max_completion_tokens'] = plan['budget']['output_tokens_per_call']
                payload['response_format']['json_schema']['strict'] = trial['strict']
                payload['reasoning_effort'] = trial.get('reasoning_effort', 'low')
                integrity.check()
                allowed = budget.reserve(payload)
                append(output / 'reservations.jsonl', {**trial, **budget.snapshot(),
                       'effective_schema_sha256': sha256(json.dumps(effective_wire, sort_keys=True).encode()).hexdigest()})
                status, body = (transport or request)(
                    *(() if transport else ('groq',)), method, url, payload, min(allowed, timeout), headers)
                row['http_status'] = status
                usage = {k: v for k, v in body.get('usage', {}).items()
                         if type(v) in (int, float) and math.isfinite(v) and v >= 0}
                append(output / 'usage.jsonl', {**trial, 'status': status,
                       'returned_model': body.get('model') if body.get('model') == plan['model'] else None,
                       'usage': usage})
                if status >= 400:
                    raise ExperimentStop('Provider rejection')
                if body.get('model') != plan['model']:
                    raise ExperimentStop('Unexpected model identity')
                choices = body.get('choices')
                choice = choices[0] if isinstance(choices, list) and choices else {}
                message = choice.get('message') or {}
                try:
                    value = json.loads(message.get('content', ''))
                except (TypeError, ValueError):
                    value = None
                native_value = value
                units_complete = True
                if units:
                    try:
                        value = project_value(native_value, units)
                    except ValueError:
                        value, units_complete = {}, False
                checks.update(source_units_complete=units_complete, response_complete=choice.get('finish_reason') == 'stop',
                              refusal_present=bool(message.get('refusal')),
                              parsed_json_object=isinstance(value, dict),
                              wire_schema_valid=isinstance(native_value, dict) and _matches_schema(native_value, effective_wire))
                try:
                    ObservationBatch.model_validate(value)
                    checks['raw_domain_schema_valid'] = True
                except ValidationError:
                    checks['raw_domain_schema_valid'] = False
                if not checks['response_complete']:
                    content_failure = 'incomplete_output'
                elif checks['refusal_present']:
                    content_failure = 'model_refusal'
                elif not checks['wire_schema_valid'] or not units_complete:
                    content_failure = 'native_schema_invalid'
                elif not checks['raw_domain_schema_valid']:
                    content_failure = 'domain_schema_invalid'
                if isinstance(value, dict):
                    append(output / 'model-outputs.jsonl', {**trial, 'value': value,
                           **({'wire_value': native_value, 'projection': 'source-order concatenation; no field changes'} if units else {})})
                if (not checks['response_complete'] or checks['refusal_present'] or
                        not checks['parsed_json_object'] or not checks['wire_schema_valid'] or not units_complete):
                    raise ExperimentStop('Incomplete/refused/invalid response')
                return status, body

            adapter = GroqChatAdapter(plan['model'], bearer_token=token or 'injected-test-token',
                                      timeout=plan['budget']['request_seconds'], max_retries=0,
                                      transport=call_transport)

            def model_call(**kwargs):
                kwargs['system'] = plan['prompts'][trial['arm']]
                kwargs['schema'] = effective_wire
                if units:
                    kwargs['user'] = json.dumps({'fragment_context': kwargs['user'], 'source_units': units})
                result = adapter.chat(**kwargs)
                return replace(result, value=project_value(result.value, units)) if units else result

            try:
                with capture_provider_metrics() as metrics:
                    results = extract_fragments(
                        [FragmentInput(case['case_id'], 'synthetic:1', case['text'], 1)], model_call,
                        report_date=date.fromisoformat(case['report_date']), report_date_trusted=True,
                        prompt_version=plan['prompt_version'])
                integrity.check()
                errors = [e for r in results for e in r.errors]
                row.update(state='invalid' if errors else 'completed',
                           observations=[o.model_dump(mode='json') for r in results for o in r.observations],
                           validation_error_count=len(errors))
                if errors:
                    row['failure_category'] = 'application_validation'
                    if not plan.get('continue_content_failures', False):
                        stopped = 'extraction_validation_failure'
            except BaseException as error:
                # No arbitrary exception text/response bodies in exported evidence.
                row['error_type'] = type(error).__name__
                code = getattr(error, 'code', None)
                if code in {'FROZEN_INPUT_CHANGED', 'MODEL_RATE_LIMITED', 'MODEL_QUOTA_EXHAUSTED', 'MODEL_CAPACITY_TIMEOUT'}:
                    row['failure_code'] = code
                row['failure_category'] = content_failure or 'provider_budget_identity_or_unknown'
                if not (content_failure and plan.get('continue_content_failures', False)):
                    stopped = 'request_or_budget_failure'
                if code == 'FROZEN_INPUT_CHANGED':
                    stopped = 'evaluation_integrity_failure'
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    stopped = 'interrupted'
            row['failure_stage'] = 'extraction'
            row['diagnosis'] = diagnose(state=row['state'], stage='extraction',
                                       error_code=row.get('failure_code'), http_status=row.get('http_status'))
            row.update(elapsed_ms=round((clock() - began) * 1000),
                       response_checks=checks, provider_metrics=metrics)
            append(output / 'predictions.jsonl', row)
            rows.append(row)
            print(json.dumps({k: row[k] for k in ('trial_id', 'state', 'elapsed_ms')}), flush=True)
            if stopped:
                break
    finally:
        write(output / 'summary.json', dict(scheduled=len(plan['schedule']), attempted=len(rows),
              completed=sum(r['state'] == 'completed' for r in rows), stop_reason=stopped,
              **budget.snapshot(), quality_decision='pending scoring; no release acceptance'))
        write(output / 'capture-manifest.json', {p.name: digest(p) for p in output.iterdir() if p.is_file()})
    return json.loads((output / 'summary.json').read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--preflight', type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.prepared, args.output, json.loads(args.preflight.read_text()))
    raise SystemExit(0 if result['completed'] == result['scheduled'] else 2)
