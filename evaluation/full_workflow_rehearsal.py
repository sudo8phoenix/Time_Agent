"""Complete real browser/API/worker/DB/MOCK flow using injected synthetic AI.

Requires a fresh local progress_rehearsal_* database. Retains all test records;
never calls a provider, approves production work or claims live model quality.
"""
from datetime import date
from decimal import Decimal
from hashlib import sha256
import argparse
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from threading import Event, Thread
import time
from urllib.request import urlopen
from uuid import uuid4

from sqlalchemy import func, select

from app.agent.runtime import process_job_with_graph
from app.db.models import (Activity, ActivityState, Fragment, IntegrationOutbox, Job,
                           ProgressEvent, Project, ProjectMembership, Proposal, ScheduleVersion, User)
from app.db.passwords import hash_password
from app.db.session import engine, session_factory as sessions
from app.jobs.service import heartbeat
from app.jobs.worker import run_once
from app.settings import get_settings
from evaluation.deployment_rehearsal import _ensure_migrated, _validate_target
from evaluation.repeated_development import write
from ops.mock_pmis_server import create_server


def run(output):
    settings = get_settings()
    _validate_target(settings.database_url)
    _ensure_migrated(engine)
    if settings.agent_hierarchy_enabled or settings.orchestrator_model_assisted:
        raise ValueError('Use deterministic flags for the injected-model rehearsal')
    with sessions() as db:
        if db.scalar(select(func.count()).select_from(Project)):
            raise ValueError('Use a fresh rehearsal database')
    output.mkdir(parents=True, exist_ok=False)
    password = secrets.token_urlsafe(32)
    with sessions.begin() as db:
        user = User(username='checklist-flow-'+uuid4().hex, password_hash=hash_password(password), role='reviewer')
        project = Project(name='Synthetic checklist full workflow', timezone='UTC')
        db.add_all([user, project])
        db.flush()
        schedule = ScheduleVersion(project_id=project.id, version_number=1, content_sha256='0'*64, state='active')
        db.add(schedule)
        db.flush()
        project.active_schedule_version_id = schedule.id
        activity = Activity(schedule_version_id=schedule.id, external_id='CABLE-001', name='Install cable',
                            wbs='1', discipline='electrical', work_type='cable_laying', area=None,
                            is_leaf=True, measurement_basis='quantity_ratio', unit='m',
                            planned_quantity=Decimal(10), baseline_quantity=Decimal(0), baseline_date=date(2026, 9, 23))
        db.add(activity)
        db.add(ProjectMembership(project_id=project.id, user_id=user.id))
        db.flush()
        db.add(ActivityState(activity_id=activity.id, revision=0, completed_quantity=Decimal(0)))
        fixture = dict(username=user.username, user_id=str(user.id), project_id=str(project.id),
                       schedule_id=str(schedule.id), activity_id=str(activity.id))
    write(output / 'fixture.json', fixture)
    # This test double is already exercised by the PostgreSQL runtime suite.
    # It returns a declared fixture LLMResult, not a real provider response.
    sys.path.insert(0, str(Path('backend/tests/integration/agent').resolve()))
    from test_agent_runtime import RuntimeFixture
    model = object.__new__(RuntimeFixture)
    model.activity_id, model.lifecycle, model.calls = fixture['activity_id'], False, []
    stop = Event()
    failures = []

    def pipeline(db, job, *, token, should_stop, heartbeat_callback):
        fragment = db.scalar(select(Fragment).where(Fragment.report_id == job.report_id))
        model.fragment_id = fragment.id
        return process_job_with_graph(db, job, token=token, session_factory=sessions,
            database_url=settings.database_url, should_stop=should_stop,
            heartbeat_callback=heartbeat_callback, model_callable=model.model)

    def beat(job, token):
        with sessions.begin() as db:
            return heartbeat(db, job.id, token)

    def worker():
        try:
            while not stop.is_set():
                with sessions() as db:
                    worked = run_once(db, pipeline, should_stop=stop.is_set, heartbeat_callback=beat)
                if not worked:
                    stop.wait(.1)
        except Exception as error:
            failures.append(type(error).__name__)
            stop.set()

    receiver = create_server(str(output / 'mock.sqlite3'), 0)
    receiver_thread = Thread(target=receiver.serve_forever, daemon=True)
    receiver_thread.start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base, mock = f'http://127.0.0.1:{port}', f'http://127.0.0.1:{receiver.server_port}'
    env = {**os.environ, 'DATABASE_URL': settings.database_url, 'PYTHONPATH': 'backend',
           'CHECKLIST_API_URL': base, 'CHECKLIST_MOCK_URL': mock, 'CHECKLIST_PASSWORD': password}
    processes, streams = [], []
    worker_thread = Thread(target=worker, daemon=True)
    browser_code = None
    try:
        for name, command in [('api', [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)]),
                              ('connector', [sys.executable, 'ops/run_connector.py', '--url', mock])]:
            stream = (output / f'{name}.log').open('w')
            streams.append(stream)
            processes.append(subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT))
        deadline = time.monotonic()+20
        while True:
            try:
                with urlopen(base+'/api/v1/health/live', timeout=1) as response:
                    assert response.status == 200
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Rehearsal API startup failed') from None
                time.sleep(.1)
        worker_thread.start()
        browser_code = subprocess.run(['node', 'evaluation/browser_full_workflow.mjs',
            str(output / 'fixture.json'), str(output / 'browser.json')], env=env, timeout=120).returncode
    finally:
        stop.set()
        if worker_thread.ident:
            worker_thread.join(timeout=10)
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in streams:
            stream.close()
        receiver.shutdown()
        receiver.server_close()
        receiver_thread.join(timeout=5)
        with sessions.begin() as db:
            user = db.scalar(select(User).where(User.username == fixture['username']))
            user.is_active = False
    with sessions() as db:
        jobs = list(db.scalars(select(Job)))
        events = int(db.scalar(select(func.count()).select_from(ProgressEvent)))
        proposals = list(db.scalars(select(Proposal)))
        deliveries = list(db.scalars(select(IntegrationOutbox)))
        passed = (browser_code == 0 and not failures and len(jobs) == 1 and jobs[0].state == 'ready_for_review'
                  and model.calls == ['extraction', 'schedule', 'selection'] and events == 1
                  and len(proposals) == 1 and proposals[0].review_state == 'approved'
                  and len(deliveries) == 1 and deliveries[0].status == 'delivered'
                  and deliveries[0].attempts == 1 and (deliveries[0].receipt or {}).get('verified') is True)
        result = dict(scope=__doc__, passed=passed, browser_exit_code=browser_code,
                      worker_error_types=failures, injected_model_stages=model.calls,
                      jobs=len(jobs), proposals=len(proposals), approved_events=events,
                      mock_deliveries=len(deliveries), no_live_model_calls=True,
                      fixture_user_deactivated=True, release_accepted=False)
    result['source_sha256'] = {str(p): sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__), Path('evaluation/browser_full_workflow.mjs'),
         Path('backend/tests/integration/agent/test_agent_runtime.py'), Path('backend/app/agent/runtime.py')]}
    write(output / 'summary.json', result)
    write(output / 'capture-manifest.json', {p.name: sha256(p.read_bytes()).hexdigest() for p in output.iterdir()
                                           if p.is_file() and p.suffix not in {'.log', '.sqlite3'}})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.output)['passed'] else 1)
