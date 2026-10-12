# Local runbook

This profile runs the application and PostgreSQL on this Mac. Ollama may run on a friend's laptop through a private Tailscale connection; public hosting is intentionally deferred. Report processing uses the LangGraph worker. This local checkout is running on port 8001; the separate project on port 8000 is untouched.

## One-time setup

Requirements: Python 3.12, Node.js/npm, Docker Desktop, and Java. From `site-progress-agent/`:

```sh
cp .env.example .env
make bootstrap
cd frontend && npm ci && cd ..
make db-up
make migrate
make build-web
```

Edit `.env` before creating real data. Replace `SECRET_KEY` with a long random value. Keep `ENVIRONMENT=development` for plain `http://127.0.0.1`; production cookies require HTTPS.

Create the local reviewer and demo schedule without resetting existing data:

```sh
DEMO_PASSWORD='choose-at-least-12-characters' make seed-demo
```

The username is `demo-reviewer`. Do not commit `.env` or share the password.

## Remote Ollama configuration

After the friend-host endpoint is ready, put its private Tailscale HTTPS URL and exact installed tag in `.env`:

```dotenv
OLLAMA_BASE_URL=https://model-host.example.ts.net
OLLAMA_MODEL=exact-installed-tag
OLLAMA_API_KEY=
```

Then run the non-generating readiness check:

```sh
make remote-check
```

This check has a 10-second timeout, does not send report content, and does not print the endpoint or token. See [remote-ollama.md](remote-ollama.md) for the friend-host setup and network restrictions.

## Start the app

Use two terminals from the project directory:

```sh
make serve
```

```sh
make worker
```

The API serves the already-built frontend from `frontend/dist`; rerun `make build-web` after frontend changes. The ordinary `make serve` command uses port 8000. For a second local instance, run `make serve PORT=8001` and open `http://127.0.0.1:8001`.

The worker is deliberately single-process for the laptop profile. Stop it with Ctrl-C; durable graph jobs may be reclaimed after their lease expires and resumed from checkpoint.

## Report processing and recovery

The report processor uses the bounded LangGraph workflow. There is no selectable alternate processor or runtime-mode setting. `.env` contains server-side model settings; do not copy the private endpoint or credentials into reports or browser settings. The local database was migrated to `0015_schedule_source_metadata` after a backup at `/private/tmp/time-agent-before-graph-20261012`. The live browser-to-API/worker/model run and one-observation smoke are recorded in [release evidence](release.md); each produced a pending proposal and no approved progress update. The local API and worker are running on port 8001. These are bounded workflow checks, not an unseen quality evaluation.

To recover from an interrupted worker, stop or restart the worker and allow its lease to expire; the durable graph run resumes from its PostgreSQL checkpoint. For database recovery, use the separate restore verification procedure below. Do not delete run traces, checkpoints, proposals, or requested snapshots as part of recovery. Earlier dated W-39 verification records describe a rollback path that has since been removed; that path is not available in the current runtime.

Report model calls allow one bounded request with `REPORT_MODEL_TIMEOUT_SECONDS`
(default 360 seconds, configurable from 30 to 900). A reachable model inventory
does not guarantee generation will finish within that limit. Model connection,
timeout, and invalid-response failures appear on the job page.

If a model assigns a report-context date without a trusted reviewer-entered report
date, extraction keeps the evidence-backed observation for clarification and
removes the unsupported dates and lifecycle effects. It cannot apply progress
until the reviewer resolves the date. If all items fail evidence validation, the
job reports an extraction failure instead of an empty successful review.

Hybrid retrieval uses the optional local `sentence-transformers/all-MiniLM-L6-v2` adapter only when its pinned runtime and weights have already been provisioned on this Mac. It never downloads weights while processing a job. Until those assets are installed, the worker reports the limitation and safely uses lexical retrieval; do not describe that fallback as a measured hybrid-model result.

## Checks

```sh
make doctor
make test-unit
make test-integration
make native-smoke
cd frontend && npm run build && node tests/frontend-contracts.test.mjs
```

`make doctor` checks the model endpoint and exact model tag configured for this local profile.

## Backup and restore drill

Stop intake and the worker before the backup:

```sh
make backup ARGS="--output /absolute/new/backup-directory --quiesced"
make restore-verify ARGS="/absolute/backup-directory --database progress_restore_example --uploads /absolute/new/restore-uploads"
```

Restore verification refuses to replace an existing database and leaves the separate restored database available for inspection.

## Still requires a person

- Independently review and adjudicate W-03/W-29 and the technical review suggestions before they become evaluation truth.
- Rehearse the demo on the intended laptop/network and record its conditions.
- Decide on hosting later; no public exposure is part of this runbook.

## Audited reanalysis and prototype connector

For a terminal report job, an authorized reviewer can open **Report reanalysis**, enter a reason, and create a linked run. Normal resubmission of identical report/date/mapping inputs reuses the base job. Reanalysis preserves prior decisions and cannot apply already accepted source work again; use the accepted event's correction controls to change it. The API is `POST /api/v1/projects/{project_id}/reports/{report_id}/reanalysis` with `reason` and `idempotency_key`. `GET .../reports/{report_id}/runs` lists run lineage. The worker uses the snapshotted model/mode; arbitrary browser configuration overrides are rejected. Migration `0014` downgrade refuses while child runs exist.

Run the explicitly labelled local mock receiver and connector in separate terminals:

```sh
PYTHONPATH=backend .venv/bin/python ops/mock_pmis_server.py --db /absolute/path/mock-pmis.sqlite3 --port 8091
PYTHONPATH=backend .venv/bin/python ops/run_connector.py --url http://127.0.0.1:8091
```

For a test restricted to one project, append `--project-id <project-UUID>` to the
connector command. Other projects' pending deliveries remain queued. Without
that option, the connector processes pending deliveries across all projects.

Choose a writable persistent receiver database path before starting it. The outbox is part of the application backup; the receiver's separate persistent store must be backed up separately when preserving destination read-back state.

Backup/restore now verifies content hashes for lifecycle state/events, report-job lineage, conversations, graph records and outbox payloads. Use a new restore database and upload directory. The synthetic recovery fixture script refuses nonlocal/non-`progress_recovery_*` databases; see [release evidence](release.md) for the completed isolated drill.

The E02 capture utility stores operator-supplied observations and can emit prediction JSONL. It does not drive or attest a real browser/model workflow. Keep reference labels out of observed capture files and score only after saving and hashing predictions. Independent review, split freeze and target agreement are prerequisites to an unseen evaluation claim.
