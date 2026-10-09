# Time Agent

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/UI-React-61DAFB?logo=react&logoColor=111111)](https://react.dev/)
[![PostgreSQL 16](https://img.shields.io/badge/Database-PostgreSQL%2016-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![LangGraph](https://img.shields.io/badge/Agent%20runtime-LangGraph-1C3C3C)](https://langchain-ai.github.io/langgraph/)

Time Agent is a local-first construction progress assistant. It imports project schedules and daily reports, extracts evidence-backed observations, matches them to schedule activities, and prepares proposals for human review. A reviewer must approve a proposal before it can change the deterministic progress ledger.

The application is intended to run on a laptop with FastAPI, PostgreSQL, and a React frontend. Model inference can remain local or use a private, authenticated Ollama endpoint over Tailscale. The system preserves source provenance, schedule versions, review history, corrections, approval effects, and rollback information so progress changes remain explainable.

## What it does

- Imports CSV and native schedule formats through provenance-preserving staging and activation flows.
- Accepts authenticated daily reports and processes them through a bounded extraction and matching pipeline.
- Stores observations, evidence references, schedule candidates, and proposed progress changes for review.
- Supports corrections, approval, progress history, lifecycle events, conflict handling, and safe CSV export.
- Offers a legacy pipeline and a gated LangGraph runtime with PostgreSQL checkpoints, leases, resume support, sanitized traces, and idempotent persistence.
- Restricts model configuration to server-side settings; the browser cannot select arbitrary endpoints, prompts, tools, or checkpoints.
- Keeps ambiguous or unsupported evidence from silently changing the ledger.

## Current status

The repository contains the accepted local release candidate plus ongoing lifecycle and schedule-data work. The default execution mode remains `legacy` while the graph path and live model workflow complete their release gates.

The documented baseline includes 150 unit tests, 49 PostgreSQL integration tests, native schedule smoke coverage, frontend build and contract checks, approval safety, rollback, backup and restore verification, and private Ollama readiness checks. The current working tree also includes lifecycle acceptance flows, expanded schedule datasets, review artifacts, and browser coverage that are still being consolidated into the next release record.

Fixture-only retrieval, injected-model tests, and synthetic labels do not measure live model accuracy. A release still requires real private-Ollama evaluation, human label review, a browser walkthrough, and a two-laptop demo rehearsal. See [`docs/release.md`](docs/release.md) for the evidence and remaining gates.

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

reviewer approval → lifecycle/progress ledger → history and export
```

The agent may create pending proposals, but it cannot approve them, activate schedules, write progress events directly, select arbitrary tools, access the shell or filesystem, or receive browser credentials. Checkpoints are internal resume data. Public traces expose only bounded stage, count, hash, timing, and stable-error metadata.

## Repository layout

```text
site-progress-agent/
├── backend/app/                 # FastAPI app, services, schemas, jobs, agent runtime
├── backend/migrations/          # Alembic migrations
├── backend/tests/               # Unit and PostgreSQL integration tests
├── frontend/                    # React/Vite production UI and browser tests
├── data/                        # Synthetic fixtures, schedule sources, and review records
├── docs/                        # Runbooks, decisions, release gates, and handoffs
├── evaluation/                  # Evaluation scripts and result records
├── ops/                         # Worker, backup/restore, smoke, and diagnostic commands
├── compose.yaml                 # Local PostgreSQL service
├── Makefile                     # Setup, migration, test, worker, and build commands
└── pyproject.toml               # Python package metadata and tooling
```

## Requirements

- Python 3.12
- Node.js and npm
- Docker Desktop with PostgreSQL 16.6
- Java for native schedule parsing
- Ollama locally, or a private authenticated Ollama endpoint when live inference is enabled

## Quick start

From the repository root:

```sh
cp .env.example .env
make bootstrap
cd frontend && npm ci && cd ..
make db-up
make migrate
make build-web
```

Set a long random `SECRET_KEY` in `.env` before using real data. Create a demo reviewer and schedule without resetting existing records:

```sh
DEMO_PASSWORD='choose-at-least-12-characters' make seed-demo
```

Start the API and worker in separate terminals:

```sh
make serve
make worker
```

Open <http://127.0.0.1:8000>. The default worker uses the accepted legacy pipeline. Keep `AGENT_EXECUTION_MODE=legacy` until the graph parity, security, rollback, and live-model gates are complete.

For the complete setup, private Ollama configuration, backup drill, and known limitations, read [`docs/local-run.md`](docs/local-run.md).

## Configuration

Copy `.env.example` to `.env`. The main settings are:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy PostgreSQL connection URL |
| `OLLAMA_BASE_URL` | Loopback or private Ollama endpoint |
| `OLLAMA_MODEL` | Exact server-side model tag |
| `OLLAMA_API_KEY` | Optional server-side bearer token |
| `AGENT_EXECUTION_MODE` | `legacy` by default; `graph` remains gated |
| `SECRET_KEY` | Application signing key; never commit it |

The browser cannot change model, endpoint, prompt, execution mode, checkpoint, or approval settings.

## Verification

Run the focused checks from the repository root:

```sh
make test-unit
make test-integration
make native-smoke
make build-web
cd frontend && node tests/frontend-contracts.test.mjs
make doctor
```

The integration suite uses the isolated `progress_test` database. The graph checkpoint schema is installed by Alembic; ordinary application startup does not execute checkpoint DDL.

For backup and restore verification:

```sh
make backup ARGS="--output /absolute/backup-directory --quiesced"
make restore-verify ARGS="/absolute/backup-directory --database progress_restore_example --uploads /absolute/restore-uploads"
```

## Security and data handling

Do not commit `.env`, model credentials, uploaded reports, model weights, PostgreSQL volumes, or generated build artifacts. Report text is treated as untrusted input. Source evidence stays in application records and is not copied into public agent telemetry. Human approval is required before progress changes. Restore verification uses a separate database and refuses to replace an existing one.

## Documentation

- [`docs/local-run.md`](docs/local-run.md) — laptop setup, Ollama configuration, checks, and backup drill
- [`docs/release.md`](docs/release.md) — verified evidence and remaining release gates
- [`docs/decisions.md`](docs/decisions.md) — architectural decisions
- [`docs/data-decisions.md`](docs/data-decisions.md) — schedule and dataset decisions
- [`docs/data-splits.md`](docs/data-splits.md) — dataset split definitions
- [`evaluation/RESULTS.md`](evaluation/RESULTS.md) — evaluation records

## Contributing

1. Create a focused branch for one bounded task.
2. Read the relevant task card, contract, and runbook before editing.
3. Add or update coverage for changed behavior.
4. Run the focused checks and relevant regression suite.
5. Record limitations and any unrun live or browser gates in the handoff.

Open an issue or pull request in [sudo8phoenix/Time_Agent](https://github.com/sudo8phoenix/Time_Agent) with reproduction steps, expected behavior, actual behavior, and environment details. Do not include secrets or private report contents.

## License

No license has been declared for this repository. Add an explicit license before distributing the project outside its intended repository access controls.

## Acknowledgements

Time Agent uses FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, React, Vite, Ollama, LangGraph, and open-source Python and Java tooling.
