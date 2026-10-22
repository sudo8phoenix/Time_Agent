# Local runbook

## Setup

Use Python 3.12, Node.js/npm, Docker with PostgreSQL 16, and Java for native
schedule parsing. Run the [README quick start](../README.md#quick-start), edit
`.env`, and apply all migrations before starting a worker. Keep `.env` private.
`ENVIRONMENT=development` permits local HTTP; production cookies require HTTPS.

The default example uses Ollama. The owner-selected orchestrator profile is:

```dotenv
LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-20b
AGENT_HIERARCHY_ENABLED=true
ORCHESTRATOR_MODEL_ASSISTED=true
ORCHESTRATOR_PROVIDER=groq
ORCHESTRATOR_MODEL=openai/gpt-oss-120b
ORCHESTRATOR_KEY_SLOT=1
EXTRACTION_PROVIDER=groq
EXTRACTION_MODEL=openai/gpt-oss-20b
EXTRACTION_KEY_SLOT=2
SELECTION_PROVIDER=groq
SELECTION_MODEL=openai/gpt-oss-20b
SELECTION_KEY_SLOT=2
GROQ_ACCOUNT_SCOPES_ENABLED=false
```

Set `GROQ_API_KEY_1` and `GROQ_API_KEY_2` privately. Do not put secrets in commands,
commits, browser configuration or screenshots. Slot 0 (`GROQ_API_KEY`) is optional
for this profile and its account mapping is unverified. The API and workers read
settings at startup. Flags affect new work; retained runs use pinned configuration.
Do not enable account scopes without the explicit procedure in
[provider capacity](provider-capacity.md).

`AGENT_HIERARCHY_ENABLED=false` selects the V1 report graph and synchronous new
conversations. With hierarchy enabled, `ORCHESTRATOR_MODEL_ASSISTED=false` uses
deterministic V2 routing. The model-assisted planner validates legal next actions;
it cannot approve progress. The default extraction prompt is V12; V20 is opt-in.

## Development and diagnostics

The API serves the built frontend. Rebuild after UI changes with `make build-web`.
For hot reload, run `make dev-api PORT=8001` and `make dev-web`; inspect the Vite
configuration for its API proxy. Keep a worker running with `make worker`.

```sh
curl --fail http://127.0.0.1:8001/api/v1/health/live
make doctor
PYTHONPATH=backend .venv/bin/python ops/runtime_status.py
```

Liveness does not certify model quality or database readiness. There is no
`/api/v1/health/ready` endpoint. Admission waits count toward model-request budgets.
The report timeout defaults to 360 seconds; inspect `.env.example` for all settings.
For Ollama, set `OLLAMA_BASE_URL`, the exact installed `OLLAMA_MODEL` and optional
`OLLAMA_API_KEY`; `make remote-check` checks readiness without inference.

## Recovery and cancellation

Stop workers with Ctrl-C. Ownership leases and PostgreSQL checkpoints support
bounded recovery. Inspect queued work, original budgets and retained journals
before restarting. The [durable configuration contract](durable-model-configuration.md)
rejects source/dependency drift and unpinned legacy work before new model calls.
Do not reset counters, deadlines or checkpoints to force a resume.

An authorized reviewer can POST `/api/v1/jobs/{job_id}/cancel` using normal session
and CSRF protections. Cancellation fences late publication. Terminal report
reanalysis uses `POST /api/v1/projects/{project_id}/reports/{report_id}/reanalysis`
with a reason and idempotency key, retaining prior decisions and lineage.
Already accepted work must be corrected through audited correction controls.

## Mock delivery

Run these in separate terminals with a writable persistent receiver path:

```sh
PYTHONPATH=backend .venv/bin/python ops/mock_pmis_server.py --db /absolute/path/mock-pmis.sqlite3 --port 8091
PYTHONPATH=backend .venv/bin/python ops/run_connector.py --url http://127.0.0.1:8091
```

Append `--project-id <project-UUID>` to restrict the connector to one project.
Without it, the connector processes pending deliveries across projects.
This receiver is explicitly a mock integration. Back up its SQLite state separately.

## Backup and restore

Stop intake and the worker, then use a new backup directory:

```sh
make backup ARGS="--output /absolute/new/backup-directory --quiesced"
make restore-verify ARGS="/absolute/backup-directory --database progress_restore_example --uploads /absolute/new/restore-uploads"
```

Restore verification refuses an existing destination database and retains the
restored copy for inspection. Preserve uploads alongside application state.
See [testing](TESTING_AND_QUALITY.md) before running any evaluation or DB tests.

---

[Documentation index](README.md) · [Project overview](../README.md)
