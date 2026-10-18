# Local runbook

This profile runs the application and PostgreSQL on this Mac. Current extraction is configured for Groq `openai/gpt-oss-20b`. Private Ollama remains a separately configured option; public hosting is deferred. Report processing uses the LangGraph worker. The local homepage on port 8001 returned HTTP 200 and liveness returned `status=ok` on 18 October. Reachability does not certify source freshness or model quality. See [current status](current-status.md).

The default extraction prompt is V12; V20 remains an explicit, unaccepted candidate.
The latest measured extraction spent 46.312 seconds waiting for admission and
0.806 seconds in request/response transport. Waiting in the UI may reflect shared
quota pacing. All three Groq keys share one organization quota. See
[provider capacity](provider-capacity.md) for bounded failures and retry policy.

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

The normal laptop profile uses one worker process. Stop it with Ctrl-C; durable graph jobs may be reclaimed after their lease expires and resumed from checkpoint. Rehearsal workers and retained tasks are separate from normal app operation; inspect them explicitly before resume.

Verify the local app after startup:

```sh
curl --fail http://127.0.0.1:8001/api/v1/health/live
```

The homepage is `http://127.0.0.1:8001/`. There is no `/api/v1/health/ready`
endpoint. Liveness does not exercise extraction, database health or approval.
Read-only database/queue/cooldown inspection is available with
`PYTHONPATH=backend .venv/bin/python ops/runtime_status.py`.

## Report processing and recovery

The report processor uses bounded LangGraph. There is no alternate processor or runtime-mode switch; the hierarchy flag selects versions within LangGraph. `.env` contains server-side model settings; keep endpoints and credentials out of reports and browser settings. The application database was inspected at `0018_hosted_admission`; the earlier 0015 backup is historical. Apply migrations through 0018 before using current hosted transports. The [release record](release.md) preserves dated browser/model smokes; these are bounded workflow checks, not unseen quality acceptance.

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

Candidate discovery uses the configured model to shortlist rows from the pinned schedule through `backend/app/agent/schedule_decision.py`, then selects or abstains from the supplied candidates. It traverses leaf activities in batches of up to 48 and retains at most eight candidates. The current worker does not use the former hybrid/lexical embedding retrieval path. Historical W-10 evidence describes the earlier implementation.

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

For a terminal report job, an authorized reviewer can open **Report reanalysis**, enter a reason, and create a linked run. Normal resubmission of identical report/date/mapping inputs reuses the base job. Reanalysis preserves prior decisions and cannot apply already accepted source work again; use the accepted event's correction controls to change it. The API is `POST /api/v1/projects/{project_id}/reports/{report_id}/reanalysis` with `reason` and `idempotency_key`. `GET .../reports/{report_id}/runs` lists run lineage. The worker uses the snapshotted model and the only supported LangGraph runtime; historical execution-mode metadata cannot switch processors. Arbitrary browser configuration overrides are rejected. Migration `0014` downgrade refuses while child runs exist.

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

The older E02 manual capture utility stores operator-supplied observations and does not attest a browser/model workflow. The current frozen-report runner drives real worker capture and seals it before separate scoring; browser approval/delivery has its own runner. See [the evaluation guide](../evaluation/README.md). Keep labels out of inference, retain failures, use the approved review policy and freeze before capture. Both V19 splits are consumed.

## Reproduce the compact model benchmark

The [60-case Gemma record](../evaluation/RESULTS.md#gemma-4-12b-quality-evaluation--12-october-2026) and [evaluation guide](../evaluation/README.md) describe historical inputs, corrected table locators, draft prompt, failures and reruns. Runners and saved captures are included in the candidate publication; local databases, logs and imported schedule copies are excluded. Scoring saved captures does not contact Ollama:

```sh
.venv/bin/python -m evaluation.summarize_gemma \
  --capture-dir evaluation/results/gemma4-12b-2026-10-12/combined-after-retry
```

Live generation is a separate explicit command in that guide. The benchmark's 300-second timeout differs from the report worker's default 360 seconds. A reachable inventory is readiness evidence only; a request interrupted by a host crash must remain in the original record, with replacement captures and denominators identified.

## 17 October candidate operation and rollback

See [current status](current-status.md) before advancing
either rollout flag. Both flags remain false. New work uses the current prompt;
previous report/conversation runs retain their pinned versions and journals.
Changing flags does not rewrite an existing run or change the only supported
LangGraph execution runtime.

`evaluation/mixed_workload.py` is restricted to an idle local
`progress_rehearsal_*` database. It runs two real workers with a staged synthetic
report/conversation mix and refuses automatic acceptance. Its predeclared stop
criteria include failed work, readiness over 120 seconds, expired ownership,
cooldown over 90 seconds, unexpected approved writes and worker exit. A stop
prevents further admission and terminates only its own worker processes with a
bounded drain, preserving pending work and checkpoints for explicit inspection.
Do not restart a worker against retained queued work without reviewing that state.

The latest runner explicitly pins conversation V20/provider assignments, supplies
lifecycle-start messages and rejects empty-card/model-free task completions.
That revision has not been live validated. Retained work from interrupted attempts
exists in both `progress_rehearsal_20261016` and
`progress_rehearsal_eval_20261017`; see [the follow-up](release-followup-2026-10-18.md).

`evaluation/monitor_window.py --seconds 600 --output-dir <new-directory>` supplies
a separate read-only monitoring window on the rehearsal database. It records
stop conditions and does not kill workers, reset leases or change flags.
Read-only monitor success alone does not certify sustained workload capacity.

The main local prototype and isolated captures have separate configuration
records. Main timeouts are preserved at restart; frozen report and mixed workload
captures use 90-second request budgets, while component probes use 60 seconds.
A source hash does not make those configurations
equivalent. Restoring data requires a fresh database/upload destination and a
verified backup manifest; disabling rollout flags is not a database rollback.
