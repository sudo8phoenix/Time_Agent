# Time Agent

Time Agent turns construction reports and supervisor conversations into
evidence-backed progress proposals. It imports schedules, extracts reported work,
matches activities and routes proposals to an authorized reviewer. Approval
updates a PostgreSQL progress ledger; an outbox delivers snapshots to
**MOCK PMIS — prototype**.

The stack is Python 3.12, FastAPI, PostgreSQL 16, LangGraph, React and Vite.
The selected local profile is the **V2 hierarchical, model-assisted orchestrator**:
Groq GPT-OSS 120B orchestrates and GPT-OSS 20B extracts and selects. Checked-in
rollout defaults remain off so a fresh checkout requires explicit configuration.

**Status:** public/synthetic local prototype; production acceptance is incomplete.
The latest recorded backend runs passed 1,455 unit and 263 PostgreSQL integration
tests. Those passes do not establish model accuracy or sustained capacity.
See [testing and measured results](docs/TESTING_AND_QUALITY.md).

## Features

- CSV and native schedule import with reviewed activation.
- Text, DOCX, PDF and mapped XLSX report intake with source evidence and transcription gates.
- Versioned report graphs and durable conversations with bounded recovery.
- Schedule-scoped matching, abstention, authorized approval and corrections.
- Progress history, CSV/JSON export and transactional mock-delivery outbox.

## Quick start

Requirements: Python 3.12, Node.js/npm (CI uses Node 20), Docker and Java for
native schedule parsing. Configure a supported model endpoint or provider key.

```sh
git clone https://github.com/sudo8phoenix/Time_Agent.git
cd Time_Agent
cp .env.example .env
make bootstrap
cd frontend && npm ci && cd ..
make db-up
make migrate
make build-web
make seed-demo
```

Set a random `SECRET_KEY` and your model configuration in `.env` before running.
`make seed-demo` prompts for a password for `demo-reviewer`. Start the API and
worker in separate terminals:

```sh
make serve PORT=8001
```

```sh
make worker
```

Open <http://127.0.0.1:8001/>. Follow the [local runbook](docs/local-run.md) for
orchestrator settings, development, diagnostics, mock delivery and backup.
Credentials, uploads and runtime databases stay local.

## Documentation

| Guide | What it covers |
|---|---|
| [System](docs/SYSTEM.md) | Architecture, versions, workflow and source map |
| [Local runbook](docs/local-run.md) | Setup, configuration, operation and recovery |
| [Testing and quality](docs/TESTING_AND_QUALITY.md) | Completed tests, model studies, limitations and reproduction |
| [Document support](docs/document-input-capabilities.md) | Supported formats, limits and security boundaries |
| [Provider capacity](docs/provider-capacity.md) | Admission, account scopes and rate limits |
| [Durable configuration](docs/durable-model-configuration.md) | Pinned builds and safe resumption |
| [Evaluation](evaluation/README.md) | Runner/scorer usage and acceptance contracts |

Historical handoffs, checklists, screenshots, raw evaluation runs and operator
notes are excluded from Git. Small regression fixtures remain versioned so a
fresh clone can run the test suite. The testing guide summarizes the retained
local evidence without treating incomplete studies as release approval.

## Development checks

```sh
make test-unit
make test-integration
cd frontend
npm run typecheck
npm run build
npm run test:e2e
```

Integration tests require an isolated local test database and block uninjected
hosted-provider HTTP. Live evaluation is separate and consumes provider quota.
Report bugs through the repository's GitHub Issues with reproduction steps and
sanitized logs; never include keys or private reports.
