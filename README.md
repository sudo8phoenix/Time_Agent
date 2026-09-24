# Time Agent

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/UI-React-61DAFB?logo=react&logoColor=111111)](https://react.dev/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%2016-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![LangGraph](https://img.shields.io/badge/Agent%20runtime-LangGraph-1C3C3C)](https://langchain-ai.github.io/langgraph/)

Time Agent is a local-first construction progress assistant. It imports schedules and daily reports, extracts evidence-backed observations with a private Ollama model, retrieves supported schedule candidates, and creates proposals for human review. Approval remains the only path that can change the deterministic progress ledger.

The project is designed for a laptop-hosted FastAPI/PostgreSQL application with optional private Ollama access over a Tailscale network. It preserves source evidence, schedule versions, review history, rollback safety, and explicit abstention when the evidence is ambiguous or unsupported.

## Current status

The accepted local release candidate includes:

- CSV and native schedule import foundations with provenance-preserving storage.
- Authenticated report intake, proposal review, correction, approval, progress history, and CSV export.
- A bounded LangGraph workflow behind the default-off `AGENT_EXECUTION_MODE=legacy` switch.
- PostgreSQL checkpoints, lease-aware resume, sanitized agent traces, idempotent proposal persistence, and exact checkpoint pruning.
- 150 unit tests and 49 PostgreSQL integration tests passing locally.

Graph mode is intentionally not enabled yet. W-37/W-38 status visibility, W-39 legacy parity and rollback checks, a real private-Ollama smoke test, human label review, browser walkthrough, and demo rehearsal remain release gates. Fixture and injected-model results are not model-quality benchmarks.

## Architecture

```text
report API → PostgreSQL job + lease → legacy or bounded graph worker
                                      ├─ load context
                                      ├─ extract observations
                                      ├─ validate evidence
                                      ├─ retrieve schedule candidates
                                      ├─ select supported matches
                                      ├─ validate proposals
                                      └─ save pending review proposals

reviewer approval → deterministic progress ledger → history/export
```

The graph cannot approve proposals, activate schedules, write progress events, select arbitrary tools, access the shell/filesystem/URLs, or receive credentials from the browser. Checkpoints are internal resume data; public traces contain only bounded stage, count, hash, timing, and stable-error metadata.

## Repository structure

```text
site-progress-agent/
├── backend/app/                 # FastAPI application, services, schemas, agent runtime
├── backend/migrations/          # Alembic database migrations (0001–0009)
├── backend/tests/               # Unit and PostgreSQL integration coverage
├── frontend/                    # React/Vite production UI
├── data/                        # Synthetic fixtures and reference manifests
├── docs/                        # Runbook, decisions, release gates, task handoffs
├── evaluation/                  # Evaluation scripts and result records
├── ops/                         # Worker, backup/restore, smoke, and pruning commands
├── compose.yaml                 # Local PostgreSQL 16.6 service
├── Makefile                     # Bootstrap, migration, test, worker, and build commands
└── pyproject.toml               # Python 3.12 dependencies and tooling
```

## Requirements

- Python 3.12
- Node.js/npm
- Docker Desktop with PostgreSQL 16.6
- Java for native schedule parsing
- Ollama locally or at a private, authenticated Tailscale endpoint when live inference is configured

## Quick start

From the repository root:

```sh
cp .env.example .env
# Set a strong SECRET_KEY before using real data.
make bootstrap
cd frontend && npm ci && cd ..
make db-up
make migrate
make build-web
```

Create the demo reviewer and seed data without resetting existing records:

```sh
DEMO_PASSWORD='choose-at-least-12-characters' make seed-demo
```

Start the API and worker in separate terminals:

```sh
make serve
make worker
```

Open <http://127.0.0.1:8000>. The default worker uses the accepted legacy pipeline. Keep `AGENT_EXECUTION_MODE=legacy` until the documented W-39 and O-04 gates pass.

## Configuration

Copy `.env.example` to `.env`. Important settings include:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy PostgreSQL URL |
| `OLLAMA_BASE_URL` | Private/loopback Ollama endpoint only |
| `OLLAMA_MODEL` | Exact server-side model tag |
| `OLLAMA_API_KEY` | Optional server-side bearer token |
| `AGENT_EXECUTION_MODE` | `legacy` by default; `graph` remains gated |
| `SECRET_KEY` | Application signing key; never commit it |

The browser cannot change model, endpoint, prompt, execution mode, checkpoint, or approval settings.

## Verification

```sh
make test-unit
make test-integration
make native-smoke
make build-web
cd frontend && node tests/frontend-contracts.test.mjs
make doctor
```

The integration suite expects the isolated `progress_test` database. The graph checkpoint schema is installed by Alembic migration `0009_langgraph_checkpoints`; ordinary application startup does not execute checkpoint DDL.

For backups and restore verification:

```sh
make backup ARGS="--output /absolute/backup-directory --quiesced"
make restore-verify ARGS="/absolute/backup-directory --database progress_restore_example --uploads /absolute/restore-uploads"
```

See [`docs/local-run.md`](docs/local-run.md), [`docs/release.md`](docs/release.md), and [`docs/handoffs/W-36.md`](docs/handoffs/W-36.md) for the complete local runbook and acceptance evidence.

## Security and data handling

Do not commit `.env`, model credentials, uploaded reports, model weights, PostgreSQL volumes, or generated frontend/build artifacts. Report text is treated as untrusted input. Exact source evidence stays in the existing application records and is not copied into public agent telemetry. Human approval is required before progress changes.

## Contributing

1. Create a focused branch for one bounded task.
2. Read the relevant task card and contract before editing.
3. Add or update tests for the behavior being changed.
4. Run the focused checks and relevant regression suite.
5. Document limitations and unrun live/browser gates honestly in the handoff.

Please open an issue or pull request with reproduction steps, expected behavior, actual behavior, and environment details. Do not include secrets or private report contents.

## License

No license has been declared for this repository yet. Add an explicit license before distributing the project outside the intended repository access controls.

## Acknowledgements

This project builds on FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, React, Vite, Ollama, LangGraph, and the open-source Python and Java ecosystems.

## Contact

Open an issue in [sudo8phoenix/Time_Agent](https://github.com/sudo8phoenix/Time_Agent/issues) for project questions, defects, or collaboration requests.
