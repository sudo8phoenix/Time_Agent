"""Bounded live report/conversation rehearsal, with fail-closed staged admission.

Uses only an idle local rehearsal database. No approvals or rollout flag changes.
Initial stage admits one report and one conversation; subsequent stages admit two
of each. Stops new admission on any failure, expired ownership, >120s readiness,
unexpected ledger writes, worker death, or excessive cooldown. Retains fixtures.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from sqlalchemy import func, select

from app.conversation import runtime as conversation_runtime
from app.conversation.service import add_turn
from app.db.models import Activity, Conversation, ConversationTask, Job, Observation, ProgressEvent, Project, Proposal, Report, User
from app.db.passwords import hash_password
from app.db.session import session_factory as sessions
from app.jobs.service import enqueue_job
from app.settings import get_settings
from app.prompts.extraction_v1 import PROMPT_VERSION, get_extraction_prompt
from evaluation.deployment_rehearsal import _ensure_migrated, _validate_target, _worker_environment, _settings_for_rehearsal
from evaluation.report_planner_eval import load_cases, seed
from ops.runtime_status import build_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--prompt-version', default=PROMPT_VERSION)
    args = parser.parse_args()
    prompt_version, prompt = get_extraction_prompt(args.prompt_version)
    settings = get_settings()
    _validate_target(settings.database_url)
    if args.output_dir.exists() or not 120 <= args.seconds <= 1800:
        parser.error('Use a new directory and a 120–1800 second window')
    if settings.agent_hierarchy_enabled or settings.orchestrator_model_assisted:
        parser.error('Both rollout flags must be false')
    settings = _settings_for_rehearsal(settings.database_url)
    from app.db.session import engine
    _ensure_migrated(engine)
    with sessions() as db:
        for model in (Job, ConversationTask):
            if db.scalar(select(func.count()).select_from(model).where(model.state.in_(['queued', 'running']))):
                parser.error('Inspect pending rehearsal work first')
        baseline = db.scalar(select(func.count()).select_from(ProgressEvent))
    args.output_dir.mkdir(parents=True)
    env, secrets = _worker_environment(settings.database_url, settings)
    env['CONVERSATION_MODEL_TIMEOUT_SECONDS'] = '90'
    started = time.monotonic()
    records, processes, streams, reasons = [], [], [], set()
    config = {'started_at': datetime.now(timezone.utc).isoformat(), 'duration_budget_seconds': args.seconds,
              'stage_interval_seconds': 150, 'worker_count': 2, 'initial_stage': {'reports': 1, 'conversations': 1},
              'later_stages': {'reports': 2, 'conversations': 2}, 'readiness_stop_seconds': 120,
              'cooldown_stop_seconds': 90, 'automatic_acceptance': False, 'rollout_flags': False,
              'provider': 'groq', 'model': settings.groq_model, 'retains_fixtures': True,
              'extraction_prompt_version': prompt_version,
              'extraction_prompt_sha256': sha256(prompt.encode()).hexdigest(),
              'source_sha256': {str(p): sha256(p.read_bytes()).hexdigest() for p in
                  (Path(__file__), Path('backend/app/agent/schedule_decision.py'),
                   Path('backend/app/llm/extract.py'), Path('backend/app/prompts/extraction_v1.py'))},
              'rollback': 'Stop new admission; SIGTERM owned workers, allow 100s drain, then kill if needed. Preserve checkpoints and queued work for inspection. Never resume automatically.'}
    (args.output_dir/'config.json').write_text(json.dumps(config, indent=2)+'\n')

    def admit(stage):
        cases = load_cases(case_ids=('C01', 'C06') if stage else ('C06',), dataset='seed')
        project_id, schedule_id = seed(sessions, cases)
        with sessions.begin() as db:
            user = User(username='mixed-'+uuid4().hex, password_hash=hash_password(uuid4().hex), role='viewer')
            db.add(user)
            db.flush()
            for case in cases:
                job, existed = enqueue_job(db, db.get(Project, project_id), db.get(Report, case['report_id']))
                assert not existed
                job.config_snapshot = {**(job.config_snapshot or {}),
                    'provider': 'groq', 'model': settings.groq_model,
                    'extraction_prompt_version': prompt_version}
                records.append({'kind': 'report', 'id': str(job.id), 'case_id': case['case_id'], 'admitted': time.monotonic()-started})
                conversation = Conversation(project_id=project_id, creator_id=user.id, schedule_version_id=schedule_id,
                    revision=0, status='draft', draft={'orchestration_version': conversation_runtime.VERSION, 'report_date': case['report_date']})
                db.add(conversation)
                db.flush()
                # Conversations support lifecycle confirmations; a delivery or
                # incremental-progress message can complete with zero cards.
                # Exercise a real lifecycle extraction and matching path.
                conversation_text = (f"Area A, line 24-XX: Spool erection started on "
                                     f"{case['report_date']} at 08:15.")
                add_turn(db, conversation, 'user', conversation_text, user.id)
                task = conversation_runtime.enqueue(db, conversation)
                # enqueue snapshots application defaults. This rehearsal must
                # exercise the same explicit candidate and hosted assignments
                # as its report workers, rather than those defaults.
                task.config = {**task.config, 'extraction_prompt_version': prompt_version,
                    'timeout': 90, 'roles': {
                        role: {'provider': 'groq', 'model': settings.groq_model, 'key_slot': 0}
                        for role in ('extraction', 'selection')}}
                records.append({'kind': 'conversation', 'id': str(task.id), 'case_id': case['case_id'],
                    'scenario': 'lifecycle_start', 'admitted': time.monotonic()-started})
        (args.output_dir/'fixtures.json').write_text(json.dumps(records, indent=2)+'\n')

    stage = 0
    try:
        admit(stage)
        for index in range(2):
            stream = (args.output_dir/f'worker-{index+1}.log').open('w')
            streams.append(stream)
            processes.append(subprocess.Popen([sys.executable, 'ops/run_worker.py', '--poll-seconds', '0.5'],
                env=env, stdout=stream, stderr=stream))
        while True:
            elapsed = time.monotonic()-started
            with sessions() as db:
                status = build_report(db, settings)
                events = db.scalar(select(func.count()).select_from(ProgressEvent))
                for record in records:
                    from uuid import UUID
                    row = db.get(Job if record['kind'] == 'report' else ConversationTask, UUID(record['id']))
                    record['state'] = row.state
                    terminal = row.state not in ('queued', 'running')
                    if terminal and 'terminal_seconds' not in record:
                        record['terminal_seconds'] = round(elapsed-record['admitted'], 3)
                    if row.state in ('failed', 'cancelled'):
                        reasons.add('FAILED_OR_CANCELLED_WORK')
                    if record['kind'] == 'conversation' and row.state == 'succeeded':
                        conversation = db.get(Conversation, row.conversation_id)
                        cards = (conversation.draft or {}).get('events', []) if conversation else []
                        record['model_calls'] = row.model_calls
                        record['event_cards'] = len(cards)
                        if not cards or not row.model_calls:
                            reasons.add('EMPTY_CONVERSATION_RESULT')
                    if row.state == 'running' and row.lease_expires_at and row.lease_expires_at < datetime.now(timezone.utc):
                        reasons.add('EXPIRED_WORK_OWNERSHIP')
                    age = record.get('terminal_seconds', elapsed-record['admitted'])
                    if age > 120:
                        reasons.add('READINESS_EXCEEDS_120_SECONDS')
                if events != baseline:
                    reasons.add('UNEXPECTED_APPROVED_PROGRESS_WRITE')
                if status['jobs']['expired_running_ownership_count']:
                    reasons.add('EXPIRED_REPORT_OWNERSHIP')
                if any((r.get('cooldown_remaining_seconds') or 0) > 90 for r in status['hosted_provider_admission'].values()):
                    reasons.add('PROVIDER_COOLDOWN_EXCEEDS_90_SECONDS')
            if any(p.poll() is not None for p in processes):
                reasons.add('WORKER_EXIT')
            sample = {'elapsed_seconds': round(elapsed, 3), 'records': records, 'runtime': status, 'stop_reasons': sorted(reasons)}
            with (args.output_dir/'samples.jsonl').open('a') as stream:
                stream.write(json.dumps(sample)+'\n')
            if reasons or elapsed >= args.seconds:
                break
            if elapsed >= (stage+1)*150:
                stage += 1
                admit(stage)
            time.sleep(2)
    except BaseException:
        reasons.add('CONTROLLER_INTERRUPTED_OR_FAILED')
        raise
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic()+100
        for process in processes:
            try:
                process.wait(timeout=max(.1, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                reasons.add('WORKER_REQUIRED_KILL')
                process.kill()
                process.wait()
        for stream in streams:
            stream.close()
        for log in args.output_dir.glob('worker-*.log'):
            value = log.read_text()
            for secret in secrets:
                value = value.replace(secret, '[REDACTED]')
            log.write_text(value)
        with sessions() as db:
            for record in records:
                from uuid import UUID
                row = db.get(Job if record['kind'] == 'report' else ConversationTask, UUID(record['id']))
                record['state_after_shutdown'] = row.state if row else 'missing'
                if record['kind'] == 'report' and row:
                    captured = []
                    for observation in db.scalars(select(Observation).where(Observation.job_id == row.id)):
                        proposal = db.scalar(select(Proposal).where(Proposal.observation_id == observation.id))
                        activity = db.get(Activity, proposal.chosen_activity_id) if proposal and proposal.chosen_activity_id else None
                        captured.append({'fields': observation.fields,
                            'selected_activity': activity.external_id if activity else None,
                            'mapping_state': proposal.mapping_state if proposal else None,
                            'effects': proposal.proposed_effects if proposal else {},
                            'review_state': proposal.review_state if proposal else None})
                    record['captured_events'] = captured
        result = {'status': 'stop_criteria_observed' if reasons else 'bounded_window_completed',
                  'duration_seconds': round(time.monotonic()-started, 3), 'stages_admitted': stage+1,
                  'stop_reasons': sorted(reasons), 'records': records, 'worker_exit_codes': [p.returncode for p in processes],
                  'rollback_applied': 'Owned workers stopped; flags remain disabled; queued/checkpoint state retained for inspection',
                  'limitations': ['Local synthetic mixed workload only; no UI, approvals or connector latency.',
                                  'An early stop fails sustained workload acceptance.', 'No automatic resume or rollout advancement.']}
        (args.output_dir/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result))


if __name__ == '__main__':
    main()
