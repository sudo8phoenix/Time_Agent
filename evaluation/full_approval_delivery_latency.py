"""Browser click through authenticated HTTP, durable commit and automatic MOCK delivery.

Synthetic proposals are seeded explicitly in a local rehearsal database and retained.
No model is called. Results do not certify concurrent model workloads.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from threading import Thread
import time
from urllib.request import urlopen

from sqlalchemy import func, select

from app.db.models import Activity, ConversationTask, IntegrationOutbox, Job, Observation, Proposal, User
from app.db.passwords import hash_password
from app.db.session import engine, session_factory
from app.settings import get_settings
from backend.tests.integration.test_lifecycle_acceptance import _lifecycle
from evaluation.deployment_rehearsal import _ensure_migrated, _validate_target
from evaluation.score_frozen_acceptance import percentile
from ops.mock_pmis_server import create_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=20)
    parser.add_argument('--interval-seconds', type=float, default=0)
    args = parser.parse_args()
    settings = get_settings()
    _validate_target(settings.database_url)
    _ensure_migrated(engine)
    if args.output_dir.exists() or not 1 <= args.samples <= 100 or not 0 <= args.interval_seconds <= 60:
        parser.error('Use a new output directory, 1–100 samples and a 0–60 second interval')
    with session_factory() as db:
        for model in (Job, ConversationTask):
            if db.scalar(select(func.count()).select_from(model).where(model.state.in_(('queued', 'running')))):
                parser.error('Inspect pending rehearsal work before measuring latency')
        if db.scalar(select(func.count()).select_from(IntegrationOutbox).where(
                IntegrationOutbox.status.in_(('pending', 'retry')))):
            parser.error('Use a rehearsal database without pre-existing pending deliveries')
    args.output_dir.mkdir(parents=True)
    password = secrets.token_urlsafe(32)
    fixtures = []
    for _ in range(args.samples):
        user_id, proposal_id, activity_id, project_id = _lifecycle(
            session_factory, 'actual_start', '2027-02-01', time='08:15:00')
        with session_factory.begin() as db:
            user = db.get(User, user_id)
            user.password_hash = hash_password(password)
            proposal = db.get(Proposal, proposal_id)
            job = db.get(Job, db.get(Observation, proposal.observation_id).job_id)
            job.state, job.stage, job.proposal_count = 'ready_for_review', 'persist', 1
            fixtures.append({'user_id': str(user_id), 'username': user.username,
                'proposal_id': str(proposal_id), 'activity_id': str(activity_id),
                'project_id': str(project_id), 'schedule_id': str(db.get(Activity, activity_id).schedule_version_id)})
    fixture_path = args.output_dir / 'fixtures.json'
    fixture_path.write_text(json.dumps(fixtures, indent=2) + '\n')
    server = create_server(str(args.output_dir / 'mock.sqlite3'), 0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    mock = f'http://127.0.0.1:{server.server_port}'
    env = {**os.environ, 'DATABASE_URL': settings.database_url, 'PYTHONPATH': 'backend',
        'LATENCY_API_URL': base, 'LATENCY_MOCK_URL': mock, 'LATENCY_PASSWORD': password,
        'LATENCY_SAMPLE_INTERVAL_MS': str(int(args.interval_seconds * 1000))}
    processes, streams = [], []
    browser_code = None
    measurement_started_at = None
    measurement_seconds = None
    try:
        for name, command in [('api', [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)]),
                              ('connector', [sys.executable, 'ops/run_connector.py', '--url', mock])]:
            stream = (args.output_dir / f'{name}.log').open('w')
            streams.append(stream)
            processes.append(subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT))
        deadline = time.monotonic() + 20
        while True:
            try:
                with urlopen(base + '/api/v1/health/live', timeout=1) as response:
                    assert response.status == 200
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Isolated API startup failed') from None
                time.sleep(.1)
        measurement_started_at = datetime.now(timezone.utc).isoformat()
        measurement_started = time.monotonic()
        browser_code = subprocess.run(['node', 'evaluation/browser_delivery_latency.mjs',
            str(fixture_path), str(args.output_dir / 'samples.jsonl')], env=env,
            timeout=args.samples * (90 + args.interval_seconds)).returncode
        measurement_seconds = time.monotonic() - measurement_started
    finally:
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
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        with session_factory.begin() as db:
            for fixture in fixtures:
                db.get(User, fixture['user_id']).is_active = False
    rows_path = args.output_dir / 'samples.jsonl'
    rows = [json.loads(line) for line in rows_path.read_text().splitlines()] if rows_path.exists() else []
    with session_factory() as db:
        deliveries = [dict(zip(('activity_id', 'status', 'attempts', 'verified'),
            (str(row.activity_id), row.status, row.attempts, bool((row.receipt or {}).get('verified')))))
            for row in db.scalars(select(IntegrationOutbox).where(
                IntegrationOutbox.project_id.in_([fixture['project_id'] for fixture in fixtures])))]
    keys = ('browser_click_to_approval_response_seconds',
        'browser_click_to_verified_internal_update_seconds', 'browser_click_to_verified_mock_seconds')
    complete = browser_code == 0 and len(rows) == args.samples and all(row['passed'] for row in rows)
    verified = len(deliveries) == args.samples and all(row['status'] == 'delivered' and row['attempts'] == 1 and row['verified'] for row in deliveries)
    summary = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'scope': __doc__,
        'requested_samples': args.samples, 'samples': len(rows), 'all_samples_verified': complete and verified,
        'measurement_started_at': measurement_started_at, 'measurement_seconds': measurement_seconds,
        'sample_interval_seconds': args.interval_seconds,
        'durable_commits': True, 'browser_and_auth_measured': True, 'automatic_connector_polling': True,
        'concurrent_model_workload_measured': False, 'fixture_users_deactivated': True,
        'deliveries': deliveries, 'metrics': {}, 'release_gate_passed': False}
    for key in keys:
        values = [row[key] for row in rows if key in row]
        summary['metrics'][key] = {'support': len(values), 'p95': percentile(values, .95) if values else None,
                                  'max': max(values) if values else None}
    summary['source_sha256'] = {str(p): sha256(p.read_bytes()).hexdigest() for p in
        (Path(__file__), Path('evaluation/browser_delivery_latency.mjs'),
         Path('backend/app/api/endpoints/review.py'), Path('backend/app/integrations/outbox.py'))}
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (args.output_dir / 'capture-manifest.json').write_text(json.dumps({'hashes': {
        p.name: sha256(p.read_bytes()).hexdigest() for p in args.output_dir.iterdir() if p.is_file()
        and p.name not in {'api.log', 'connector.log', 'mock.sqlite3'}}}, indent=2) + '\n')
    print(json.dumps({key: summary[key] for key in ('samples', 'all_samples_verified', 'metrics')}))
    return 0 if complete and verified else 1


if __name__ == '__main__':
    raise SystemExit(main())
