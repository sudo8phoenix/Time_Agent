"""Measure synthetic server acceptance/update and real HTTP MOCK PMIS delivery.

Rollback-only rehearsal transaction; no model calls or browser timing. Uses the
existing developer lifecycle fixture. This is bounded component evidence, not a
sustained concurrent workload or a browser-to-update acceptance result.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import perf_counter

from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from app.api.endpoints.review import ApprovalRequest, approve
from app.db.models import ActivityState, IntegrationOutbox, User
from app.db.session import engine
from app.integrations.mock_pmis import MockPMISConnector
from app.integrations.outbox import run_once
from app.settings import get_settings
from backend.tests.integration.test_lifecycle_acceptance import _lifecycle
from evaluation.deployment_rehearsal import _validate_target
from evaluation.score_frozen_acceptance import percentile
from ops.mock_pmis_server import create_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=20)
    args = parser.parse_args()
    _validate_target(get_settings().database_url)
    if args.output_dir.exists() or not 20 <= args.samples <= 100:
        parser.error('Use a new directory and 20–100 samples')
    args.output_dir.mkdir(parents=True)
    rows = []
    with TemporaryDirectory(prefix='progress-latency-') as directory:
        server = create_server(str(Path(directory)/'mock.sqlite3'), 0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connector = MockPMISConnector(f'http://127.0.0.1:{server.server_port}')
        connection = engine.connect()
        transaction = connection.begin()
        factory = sessionmaker(bind=connection, expire_on_commit=False,
            join_transaction_mode='create_savepoint')
        try:
            # Hide prior outbox rows only within this rollback-only transaction.
            connection.execute(delete(IntegrationOutbox))
            for index in range(args.samples):
                user, proposal, activity, _ = _lifecycle(factory, 'actual_start',
                    '2027-02-01', time='08:15:00')
                began = perf_counter()
                with factory() as db:
                    approve(proposal, ApprovalRequest(expected_proposal_revision=1,
                        expected_activity_revision=0, idempotency_key=f'latency-{index}'),
                        db.get(User, user), db)
                    db.commit()
                with factory() as db:
                    state = db.get(ActivityState, activity)
                    assert state.actual_start.isoformat() == '2027-02-01'
                    assert state.actual_start_time.isoformat() == '08:15:00'
                    assert state.revision == 1
                update = perf_counter()-began
                assert run_once(factory, connector)
                with factory() as db:
                    from sqlalchemy import select
                    delivery = db.scalar(select(IntegrationOutbox).where(
                        IntegrationOutbox.activity_id == activity))
                    assert delivery.attempts == 1 and delivery.receipt['verified']
                row = {'sample': index+1, 'server_acceptance_to_update_seconds': update,
                    'server_acceptance_to_mock_verified_seconds': perf_counter()-began,
                    'attempts': 1}
                rows.append(row)
                with (args.output_dir/'samples.jsonl').open('a') as stream:
                    stream.write(json.dumps(row)+'\n')
        finally:
            transaction.rollback()
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join()
    summary = {'recorded_at': datetime.now(timezone.utc).isoformat(),
        'scope': __doc__, 'samples': len(rows), 'persistent_database_writes': 0,
        'browser_timing_measured': False, 'sustained_concurrency_measured': False,
        'ordinary_database_commit_measured': False,
        'limitations': ['Savepoint commits occur within a rolled-back outer transaction; durable commit cost is excluded.',
            'Direct endpoint invocation excludes HTTP, auth, UI, worker polling and model contention.'],
        'metrics': {key: {'p50': percentile([r[key] for r in rows], .5),
                         'p95': percentile([r[key] for r in rows], .95),
                         'max': max(r[key] for r in rows)} for key in
            ('server_acceptance_to_update_seconds', 'server_acceptance_to_mock_verified_seconds')},
        'source_sha256': {str(p): sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__), Path('backend/app/api/endpoints/review.py'),
             Path('backend/app/integrations/outbox.py'))}}
    (args.output_dir/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    (args.output_dir/'capture-manifest.json').write_text(json.dumps({'hashes': {
        p.name: sha256(p.read_bytes()).hexdigest() for p in args.output_dir.iterdir()
        if p.is_file()}}, indent=2)+'\n')
    print(json.dumps(summary['metrics']))


if __name__ == '__main__':
    main()
