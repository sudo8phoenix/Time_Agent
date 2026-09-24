# Architecture decisions

## O-01 record — 22 September 2026

### First-release scope

- Build the text-first, English-only workflow for fictional project `DEMO-UTILITY-01`.
- The first integrated dataset slice is the 12 activities and 20 observations C01–C20 defined in `progress-agent-plan/03_DATA_AND_EVALUATION.md`.
- A report produces reviewable proposals only. An approved immutable event is the sole path that may update progress.
- Original decision: OCR (W-16), native schedule adapters, overall project percentages, and remote/cloud model calls were out of the MVP path. The 23 September native-import amendment below supersedes only the native-adapter exclusion.

### Frozen implementation contract

- Contract source: `progress-agent-plan/04_TECHNICAL_SPEC.md`, version 1.0.
- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16.
- React + TypeScript + Vite served from FastAPI at the same origin in production.
- Every externally visible endpoint is rooted at `/api/v1`; `/api/v1/health/live` is public and minimal.
- PostgreSQL is the durable job store. One worker performs one local Ollama request at a time.
- The local-only runtime defaults and required environment names are those in technical specification §§1, 8, 12, and 13. Model availability remains unverified until W-08 records a real benchmark.

### Dependency and evidence policy

- Lock exact dependency versions in W-01 before dependent code uses them.
- Deterministic tests use fixtures/injected adapters. Any real Ollama result is separately recorded with model digest and machine data.
- Synthetic labels, public reference materials, and measured evaluation results must remain separately labelled.
- The working tree contains no existing application code or Git repository. New application code is created in `site-progress-agent/`; the planning package remains the contract and project tracker.

### Ownership for the first wave

| Task | Writable paths | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| O-01 | `site-progress-agent/docs/`; `progress-agent-plan/TASK_BOARD.md` | none | this decision record and live task state |
| W-01 | root manifests; `backend/app/main.py`; `backend/app/settings.py`; `frontend/`; W-01 tests | O-01 | bootstrap/API/web command transcript |
| W-02 | `backend/app/schemas/`; schema tests; API fixture | W-01 | strict-schema tests and OpenAPI fixture |
| W-03 | `data/`; dataset tests | W-02 | data integrity/split report |
| W-04 | `backend/app/db/`; auth endpoint; migrations; persistence tests | W-02 | PostgreSQL migration/auth transcript |
| W-08 | `backend/app/llm/`; `ops/model_smoke.py`; adapter tests | W-02 | fixture checks plus measured local call when hardware is available |

### Current blockers and assumptions

- The host, database runtime, and local Ollama model are not yet provisioned or measured. W-01 provides interfaces and local checks; W-04/W-08 must record unavailable prerequisites rather than claim completion.
- No authentication credentials, deployment account, or external model download is assumed.

## O-01 amendment — native schedule imports, 23 September 2026

- User-approved planning scope: add Primavera P6 XER/PMXML and Microsoft Project MSPDI/MPP ingestion. Current action is documentation only; implementation, installs, downloads and parser tests are future work.
- Contract advances to v1.1: `progress-agent-plan/04_TECHNICAL_SPEC.md` §14 and `progress-agent-plan/06_NATIVE_SCHEDULE_IMPORT.md`. Existing observation/progress enums remain frozen.
- Use local MPXJ with a tested pinned Java/Python bridge. O-02 resolves exact versions and field accessors in W-22, before giving those decisions to reader builders. No hosted file conversion or direct Primavera/Microsoft account access is added.
- Break implementation into W-21–W-30: fixtures/schema → runtime → separate P6 and Microsoft readers → reviewed normalization → provenance persistence → API → UI → verification. Synthetic DPR creation is W-29 with its own paths and human-review gate.
- Native source IDs, WBS and dependency metadata must survive import. Source percentages/labour durations do not become physical quantities. Unknown quantities remain unsupported until reviewed enrichment.
- Stage imports separately from explicit activation. Existing schedule-version, approval, audit and rebase safeguards apply. Native-system writeback remains outside this scope.
- Use the user's verbatim worker and orchestrator prompts from implementation plan §§7–8. One bounded card at a time per worker, at most three concurrent builders, exclusive shared-file ownership and evidence-based acceptance by O-02.
- Specific Oil & Gas XER source is still unidentified; DHTMLX/B4UBUILD are candidate download sources, not parsed fixtures or verified paired field data. Do not relabel other sources as Oil & Gas.
- Native-format support stays unclaimed until W-30 passes each format's actual parser/DB/browser checks. W-18 separately reports real local-model evaluation on reviewed W-29 synthetic DPRs. The original build-time estimate must be revisited after W-22.

## O-01 amendment — private remote inference, 23 September 2026

- The user chose to run the application and PostgreSQL locally on this Mac while Ollama runs on a friend's laptop on another network. Public application hosting is deferred.
- The two hosts will connect through a private Tailscale tailnet. Ollama is exposed only through Tailscale Serve or an authenticated private reverse proxy; public port forwarding and Tailscale Funnel are outside the approved design.
- `OLLAMA_BASE_URL`, the exact installed `OLLAMA_MODEL`, and any optional server-side bearer token remain deployment inputs. They are never supplied by the browser or uploaded report.
- Release claims requiring live inference, model digest, latency, held-out results, and the browser walkthrough remain pending until the user supplies that endpoint and model tag.

## O-04 record — bounded LangGraph compatibility freeze, 24 September 2026

- Contract source: technical specification v1.3 and `progress-agent-plan/07_AGENT_FRAMEWORK.md`. The graph remains a bounded `StateGraph` around the existing pipeline; it does not gain model-selected tools, approval authority, schedule activation, shell/SQL/filesystem/URL access, or a second job queue.
- Freeze `langgraph==1.2.12` and `langgraph-checkpoint-postgres==3.1.2` on Python 3.12.14 with the existing `psycopg[binary]==3.2.3`. The fallback pair using LangGraph 1.2.11 also passed, but is not selected. `pip check` reported no broken requirements.
- W-31 compiled and invoked a typed graph, resumed it through `InMemorySaver`, and resumed it through synchronous `PostgresSaver` against only the isolated `progress_test` PostgreSQL 16.6 database. The saver owns `checkpoint_migrations`, `checkpoints`, `checkpoint_blobs`, and `checkpoint_writes`; ordinary startup and workers must not call surprise setup DDL.
- Set `LANGGRAPH_STRICT_MSGPACK=true` before importing the saver (or supply an explicitly reviewed allowed-module list). Runtime code must use a processing-thread-owned synchronous psycopg connection; the heartbeat thread keeps its separate session and must not share the saver connection.
- Freeze initial public integration identifiers as `graph_version=report-analysis-v1`, `state_schema_version=agent-state-v1`, and `thread_id=str(agent_run.id)`. Use migration ID `0008_agent_runs` for W-32. Existing job leases remain authoritative over checkpoints.
- W-32 owns only the three sanitized trace models/schema and migration 0008. W-33 owns typed state/context/policy and may run independently after this freeze. Shared settings, worker/router wiring, dependency locks, and final rollout remain O-04-owned.
- Keep `agent_execution_mode=legacy` by default. This W-31 decision unblocks W-32/W-33 but does not enable graph mode; W-39 parity, restart, security, rollback, regression and private-Ollama evidence remain required.

## O-04 record — W-32/W-36 persistence and runtime acceptance, 24 September 2026

- Accept migration `0008_agent_runs` and its strict public schemas/three sanitized trace tables. They contain versions, states, counters, hashes, bounded metadata, stable errors and timing only; no checkpoint, prompt, hidden-reasoning or report-body columns exist.
- Accept separate migration `0009_langgraph_checkpoints`, which snapshots checkpoint-postgres 3.1.2 migrations 0–9 in final form. Alembic owns production setup; ordinary API/worker startup never calls `PostgresSaver.setup()`. The package's concurrent index statements are replaced by transactional indexes on new empty tables.
- Accept `process_job_with_graph` behind `agent_execution_mode=legacy`. Existing job leases remain authoritative. Runtime checks ownership/shutdown/schedule before and after each durable node, uses the existing heartbeat thread plus boundary renewals, validates checkpoint versions/size/identity and rehydrates evidence/candidate provenance from server-owned rows.
- Accept the idempotent domain transaction and ambiguous checkpoint-outcome recovery: restart after extraction or selection does not repeat completed model stages; a checkpoint failure after committed proposal persistence re-verifies exact rows and finalizes without duplicates.
- Accept local telemetry/pruning boundaries: traces contain sanitized counts/hashes/stable codes only; pruning is explicit-age, dry-run by default, exact-thread and transactional, and never removes retryable failed/stale runs or application/domain records.
- Evidence: 150 unit tests, 49 isolated-PostgreSQL integration tests, 10 focused W-36 runtime cases, clean `0009 → 0008 → 0009`, contiguous saver ledger 0–9 and valid thread indexes. These are deterministic/injected-model results, not a live Ollama quality claim.
- Graph mode remains disabled. W-37/W-38 and every W-39 parity, security, backup/restore, rollback and private-Ollama gate remain mandatory before an enablement decision.
