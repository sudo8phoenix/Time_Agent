"""Frozen synthetic live hierarchy comparison; never approves or changes defaults.

Pipeline state is isolated in a fresh progress_rehearsal_* database. Provider
admission deliberately uses the normal application's database and shared scope.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import time

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Project
from app.llm import provider
from app.llm.hosted import request
from app.llm.metrics import capture_provider_metrics
from app.llm.openrouter import _matches_schema
from app.prompts.extraction_v1 import V12_PROMPT_VERSION, get_extraction_prompt
from app.settings import get_settings
from evaluation.deployment_rehearsal import _ensure_migrated, _validate_target
from evaluation.paired_pilot import CLAUSE_COVERAGE_SUFFIX, QUANTITY_SUFFIX
from evaluation.prompt_ablation import COMPLETENESS_SUFFIX, CORRECTION_SUFFIX, DATE_BASIS_SUFFIX
from evaluation.repeated_development import ExperimentStop, TrialBudget, append, digest, write
from evaluation.report_planner_eval import run_case, seed
from evaluation.strict_schema import build_wire_schema
from evaluation.experiment_guard import FrozenExperimentGuard
from evaluation.error_taxonomy import diagnose

FIXTURE = Path('evaluation/fixtures/paired-development-v2/inputs.json')
MODEL = 'openai/gpt-oss-120b'
PRICES = {'input': .15, 'output': .60}
ARMS = ('deterministic', 'model_assisted')


def candidate_prompt():
    return get_extraction_prompt(V12_PROMPT_VERSION)[1] + CLAUSE_COVERAGE_SUFFIX + QUANTITY_SUFFIX + CORRECTION_SUFFIX + DATE_BASIS_SUFFIX + COMPLETENESS_SUFFIX


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    inputs = [r for r in json.loads(FIXTURE.read_text()) if r['case_id'] in {'DEV-20261020-01', 'DEV-20261020-08'}]
    write(output / 'inputs.json', inputs)
    labels = {
        'DEV-20261020-01': dict(expected_activity_ids=['EXC-CEDAR'], expected_mapping_state='suggested',
                                expected_event_type='actual_progress', expected_quantity='5',
                                expected_quantity_kind='delta', expected_unit='m3',
                                expected_area='Zone Cedar', expected_asset_tags=['TR-030']),
        'DEV-20261020-08': dict(expected_activity_ids=[], expected_mapping_state='ambiguous',
                                expected_event_type='actual_progress', expected_quantity='2',
                                expected_quantity_kind='delta', expected_unit='m3',
                                expected_area=None, expected_asset_tags=[]),
    }
    write(output / 'labels.json', dict(status='AI-authored consumed development; independent review pending', cases=labels))
    (output / 'schedule.csv').write_text(
        'activity_id,activity_name,wbs_path,discipline,work_type,area,asset_tags,is_leaf,measurement_basis,planned_quantity,unit,planned_start,planned_finish,aliases\n'
        'EXC-CEDAR,Excavation Zone Cedar TR-030,1.1,civil,excavation,Zone Cedar,TR-030,true,quantity_ratio,100,m3,2026-10-01,2026-11-30,excavation\n'
        'EXC-OAK,Excavation Zone Oak TR-021,1.2,civil,excavation,Zone Oak,TR-021,true,quantity_ratio,100,m3,2026-10-01,2026-11-30,excavation\n')
    sources = sorted(set(Path('backend/app').rglob('*.py')) | {
        Path(__file__), Path('evaluation/report_planner_eval.py'), Path('evaluation/report_scoring.py'),
        Path('evaluation/runtime_probe.py'), Path('evaluation/strict_schema.py'),
        Path('evaluation/repeated_development.py'), Path('evaluation/prompt_ablation.py'),
        Path('evaluation/paired_pilot.py'), Path('evaluation/deployment_rehearsal.py'),
        Path('ops/runtime_status.py'), Path('evaluation/experiment_guard.py'),
        Path('evaluation/error_taxonomy.py')})
    plan = dict(scope='Consumed AI-authored development; no acceptance or unseen-data claim',
                model=MODEL, key_slot=2, prices_per_million=PRICES,
                price_checked='2026-10-20', price_source='https://console.groq.com/docs/model/' + MODEL,
                roles={r: dict(provider='groq', model=MODEL, key_slot=2) for r in ('orchestrator', 'extraction', 'selection')},
                arms=list(ARMS), hierarchy_enabled=True, extraction_prompt_version=V12_PROMPT_VERSION,
                extraction_prompt=candidate_prompt(), native_strict=True, reasoning_effort='low',
                schedule=[dict(trial_id=cid+'-'+arm, case_id=cid, arm=arm)
                          for index, cid in enumerate(r['case_id'] for r in inputs)
                          for arm in (ARMS if index % 2 == 0 else tuple(reversed(ARMS)))],
                budget=dict(calls=24, reserved_tokens=1000000, list_price_usd=.50, wall_seconds=3600,
                            request_seconds=180, output_tokens_per_call=3072, retries=0, repairs=0, concurrency=1),
                admission='Normal main-database provider coordinator; never isolated to bypass shared limits',
                pipeline_storage='Fresh local progress_rehearsal_* database; all fixture/checkpoint records retained',
                labels_in_requests=False, review='AI-authored provisional engineering labels, not independent human review',
                application_retry_policy='Existing bounded retrieval reconsideration and selection/graph repairs stay active and count toward the cumulative call ceiling; transport retries and evaluation repairs are zero',
                metric_scope='Selected normalized event/date/quantity/unit/location/asset fields, exact mapping and approval boundary; semantic summary/evidence entailment not independently reviewed',
                stop_conditions=['Any provider/transport/identity/schema failure', 'Budget exhausted', 'Approval/ledger mutation'],
                file_sha256={name: digest(output/name) for name in ('inputs.json', 'labels.json', 'schedule.csv')},
                source_sha256={str(p): digest(p) for p in sources})
    write(output / 'plan.json', plan)
    return plan


def verify(prepared):
    plan = json.loads((prepared / 'plan.json').read_text())
    for name, expected in plan['source_sha256'].items():
        if digest(Path(name)) != expected:
            raise ExperimentStop('Frozen source changed: ' + name)
    for name, expected in plan['file_sha256'].items():
        if digest(prepared/name) != expected:
            raise ExperimentStop('Frozen fixture changed')
    if (plan['model'] != MODEL or plan['key_slot'] != 2 or plan['prices_per_million'] != PRICES or
            plan['extraction_prompt'] != candidate_prompt() or plan['arms'] != list(ARMS) or
            plan['roles'] != {r: dict(provider='groq', model=MODEL, key_slot=2) for r in ('orchestrator', 'extraction', 'selection')} or
            plan['extraction_prompt_version'] != V12_PROMPT_VERSION or
            plan['budget'] != dict(calls=24, reserved_tokens=1000000, list_price_usd=.50, wall_seconds=3600,
                                   request_seconds=180, output_tokens_per_call=3072, retries=0, repairs=0, concurrency=1)):
        raise ExperimentStop('Unsupported assembled study settings')
    inputs = json.loads((prepared/'inputs.json').read_text())
    if len(inputs) != 2 or any(set(r) != {'case_id', 'report_date', 'text'} for r in inputs):
        raise ExperimentStop('Inputs must contain only frozen synthetic input fields')
    expected = {(r['case_id'], arm) for r in inputs for arm in ARMS}
    if (len(plan['schedule']) != 4 or
            {(r['case_id'], r['arm']) for r in plan['schedule']} != expected or
            len({r['trial_id'] for r in plan['schedule']}) != 4):
        raise ExperimentStop('Invalid assembled trial schedule')
    return plan, inputs


def full_case_score(row, label, report_date):
    observations = row.get('observations', [])
    ready = row.get('state') == 'ready_for_review'
    try:
        quantity = len(observations) == 1 and Decimal(str(observations[0].get('quantity'))) == Decimal(label['expected_quantity'])
    except (InvalidOperation, TypeError, ValueError):
        quantity = False
    facts = (ready and len(observations) == 1 and
             observations[0].get('event_type') == 'actual_progress' and
             quantity and
             observations[0].get('unit') == 'm3' and observations[0].get('quantity_kind') == 'delta' and
             observations[0].get('area') == label['expected_area'] and
             observations[0].get('asset_tags') == label['expected_asset_tags'] and
             observations[0].get('work_date') == report_date)
    mapping = (ready and row.get('mapping_states') == [label['expected_mapping_state']] and
               sorted(row.get('selected_activity_ids', [])) == sorted(label['expected_activity_ids']))
    safety = row.get('ledger_writes') == 0 and all(r == 'pending' for r in row.get('review_states', []))
    return dict(facts_exact=facts, mapping_exact=mapping, approval_boundary_intact=safety,
                full_report_exact=facts and mapping and safety,
                ambiguity_success=mapping and facts if label['expected_mapping_state'] == 'ambiguous' else None)


class Recorder:
    """One cumulative ceiling across all stage calls and all four reports."""
    replay_specialists = False
    replay_queue = ()

    def __init__(self, plan, output, *, transport=request, secrets=(), integrity=None):
        self.plan, self.output, self.transport, self.secrets = plan, output, transport, secrets
        self.integrity = integrity
        self.stop_reason = None
        self.factory = provider.create_adapter
        self.budget = TrialBudget(plan['budget'], plan['prices_per_million'])
        self.calls, self.arm, self.case_id, self.stopped = [], None, None, False

    def create(self, settings, **options):
        adapter = self.factory(settings, **options)
        recorder = self
        role = options.get('role')
        if adapter.model != MODEL or role not in self.plan['roles']:
            raise ExperimentStop('Unexpected provider role/model')

        class RecordedAdapter:
            def chat(self, **kwargs):
                if recorder.stopped:
                    raise ExperimentStop('Study already stopped')
                kwargs = deepcopy(kwargs)
                properties = kwargs['schema'].get('properties', {})
                stage = ('planner' if role == 'orchestrator' else 'extraction' if 'observations' in properties
                         else 'retrieval' if 'candidate_ids' in properties else 'selection')
                if stage == 'extraction':
                    kwargs['system'] = recorder.plan['extraction_prompt']
                kwargs['schema'] = build_wire_schema(kwargs['schema'])[0]
                call = dict(stage=stage, model=MODEL, ok=False, replayed=False)
                original = adapter._transport
                began = time.monotonic()

                def transport(method, url, payload, timeout, headers):
                    payload['max_completion_tokens'] = recorder.plan['budget']['output_tokens_per_call']
                    payload['response_format']['json_schema']['strict'] = True
                    payload['reasoning_effort'] = 'low'
                    encoded = json.dumps(payload, sort_keys=True)
                    if any(secret and secret in encoded for secret in recorder.secrets):
                        raise ExperimentStop('Configured secret found in model payload')
                    if recorder.integrity is not None:
                        recorder.integrity.check()
                    allowed = recorder.budget.reserve(payload)
                    call['payload_sha256'] = sha256(encoded.encode()).hexdigest()
                    append(recorder.output/'reservations.jsonl', dict(case_id=recorder.case_id, arm=recorder.arm,
                           stage=stage, **recorder.budget.snapshot()))
                    status, body = recorder.transport('groq', method, url, payload, min(allowed, timeout), headers)
                    call['http_status'] = status
                    call['usage'] = {k: v for k, v in body.get('usage', {}).items()
                                     if type(v) is int and v >= 0}
                    if status != 200 or body.get('model') != MODEL:
                        raise ExperimentStop('Provider rejection or model mismatch')
                    return status, body

                adapter._transport = transport
                try:
                    with capture_provider_metrics() as metrics:
                        result = adapter.chat(**kwargs)
                    if recorder.integrity is not None:
                        recorder.integrity.check()
                    if not _matches_schema(result.value, kwargs['schema']):
                        raise ExperimentStop('Native schema mismatch')
                    call.update(ok=True, output=result.value, settings_hash=result.settings_hash, prompt_hash=result.prompt_hash)
                    return result
                except BaseException as error:
                    recorder.stopped = True
                    call['error_type'] = type(error).__name__
                    code = getattr(error, 'code', None)
                    if code in {'FROZEN_INPUT_CHANGED', 'MODEL_RATE_LIMITED', 'MODEL_QUOTA_EXHAUSTED', 'MODEL_CAPACITY_TIMEOUT'}:
                        call['failure_code'] = code
                    recorder.stop_reason = code if code == 'FROZEN_INPUT_CHANGED' else 'stage_failure'
                    raise
                finally:
                    adapter._transport = original
                    call.update(elapsed_ms=round((time.monotonic()-began)*1000), provider_metrics=metrics)
                    call['diagnosis'] = diagnose(state='completed' if call['ok'] else 'failed',
                                                 stage=stage, error_code=call.get('failure_code'),
                                                 http_status=call.get('http_status'))
                    recorder.calls.append(call)
                    append(recorder.output/'calls.jsonl', dict(case_id=recorder.case_id, arm=recorder.arm, **call))
        return RecordedAdapter()


    def observe_report(self, row):
        """Stop after an observed approval violation; incomplete checks also stop.

        This harness never approves, so any ledger write/approved proposal is a
        hard violation. Other authorization/effect checks require their own evidence.
        """
        writes, reviews = row.get('ledger_writes'), row.get('review_states')
        complete = (type(writes) is int and writes >= 0 and isinstance(reviews, list)
                    and all(isinstance(value, str) for value in reviews))
        violation = ((type(writes) is int and writes > 0) or
                     (isinstance(reviews, list) and 'approved' in reviews))
        if violation or not complete or any(value != 'pending' for value in reviews):
            self.stopped = True
            self.stop_reason = 'hard_safety_violation' if violation else 'safety_check_incomplete'
            write(self.output / 'stop-assessment.json', dict(
                reason=self.stop_reason, hard_safety_violation=bool(violation),
                ledger_writes=writes if type(writes) is int else None,
                assessment='Affected results require review; no quality promotion',
                preserved_artifacts=['reports.jsonl', 'calls.jsonl', 'reservations.jsonl'],
                release_accepted=False))


def run(prepared, output, database_url, preflight_path, *, transport=None):
    plan, inputs = verify(prepared)
    _validate_target(database_url)
    # Global app.db.session remains the main database for hosted admission.
    settings = get_settings()
    if settings.database_url == database_url:
        raise ExperimentStop('Pipeline database must differ from normal admission database')
    from evaluation.repeated_development import validate_preflight
    preflight = json.loads(preflight_path.read_text())
    validate_preflight(preflight, {**plan, 'schedule': [{}] * plan['budget']['calls']})
    engine = create_engine(database_url)
    _ensure_migrated(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        if db.scalar(select(func.count()).select_from(Project)):
            raise ExperimentStop('Use a fresh isolated database')
    output.mkdir(parents=True, exist_ok=False)
    from pydantic import SecretStr
    secrets = [v.get_secret_value() for v in settings.__dict__.values() if isinstance(v, SecretStr)]
    mode = 'injected_transport' if transport is not None else 'live_groq'
    recorder = Recorder(plan, output, secrets=secrets, transport=transport or request,
                        integrity=FrozenExperimentGuard(prepared, plan))
    write(output/'config.json', {**plan, 'execution_mode': mode,
                               'started_at': datetime.now(timezone.utc).isoformat(),
                               'isolated_database': engine.url.database,
                               'prepared_plan_sha256': digest(prepared/'plan.json')})
    write(output/'preflight.json', preflight)
    # Read labels for post-call scoring only; seed persists the explicit input fields.
    labels = json.loads((prepared/'labels.json').read_text())['cases']
    cases_by_arm = {}
    scopes = {}
    for arm in ARMS:
        cases = [dict(**row, locator='synthetic:1', family='unambiguous' if row['case_id'].endswith('01') else 'ambiguous',
                      schedule_path=str(prepared/'schedule.csv'), label=labels[row['case_id']]) for row in inputs]
        scopes[arm] = seed(sessions, cases)
        cases_by_arm[arm] = {r['case_id']: r for r in cases}
    original_factory = provider.create_adapter
    provider.create_adapter = recorder.create
    rows = []
    try:
        for trial in plan['schedule']:
            arm, cid = trial['arm'], trial['case_id']
            recorder.arm, recorder.case_id = arm, cid
            candidate = settings.model_copy(update={
                'database_url': database_url, 'agent_hierarchy_enabled': True,
                'orchestrator_model_assisted': arm == 'model_assisted',
                'llm_provider': 'groq', 'groq_model': MODEL, 'report_model_timeout_seconds': 180,
                **{f'{role}_{key}': value for role, assignment in plan['roles'].items() for key, value in assignment.items()}})
            case = cases_by_arm[arm][cid]
            _, row = run_case(sessions, *scopes[arm], case, candidate, recorder)
            row.update(trial_id=trial['trial_id'], execution_mode=mode,
                       full_case_score=full_case_score(row, labels[cid], case['report_date']))
            append(output/'reports.jsonl', row)
            rows.append(row)
            recorder.observe_report(row)
            print(json.dumps({k: row[k] for k in ('trial_id', 'state', 'full_case_score')}), flush=True)
            if recorder.stopped or not row['full_case_score']['approval_boundary_intact']:
                break
    finally:
        provider.create_adapter = original_factory
        write(output/'summary.json', dict(scheduled=len(plan['schedule']), attempted=len(rows),
              ready=sum(r['state'] == 'ready_for_review' for r in rows),
              unattempted=[t['trial_id'] for t in plan['schedule'] if t['trial_id'] not in {r['trial_id'] for r in rows}],
              full_report_exact=sum(r['full_case_score']['full_report_exact'] for r in rows),
              **recorder.budget.snapshot(), stopped=recorder.stopped, stop_reason=recorder.stop_reason,
              metric_scope=plan['metric_scope'],
              release_accepted=False, limitation='Two consumed synthetic cases; no p95, confidence, representative or release claim'))
        write(output/'capture-manifest.json', {p.name: digest(p) for p in output.iterdir() if p.is_file()})
        engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--database-url')
    parser.add_argument('--preflight', type=Path)
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare)
    elif all([args.prepared, args.output, args.database_url, args.preflight]):
        run(args.prepared, args.output, args.database_url, args.preflight)
    else:
        parser.error('Use --prepare or all execution arguments')
