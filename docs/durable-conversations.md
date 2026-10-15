# Durable conversation analysis

Implemented 16 October 2026 behind the existing, disabled-by-default hierarchy flag. Human confirmation still creates pending proposals; authorized reviewer approval remains the only path to ledger effects.

## Dispatch and operation

Apply additive migration `0017_conversation_tasks` before running the updated API or worker. It adds private `conversation_tasks` and `conversation_task_calls` tables. Only the isolated local test database was migrated during implementation.

New conversations created with `AGENT_HIERARCHY_ENABLED=true` pin `conversation-analysis-v1` in their server-owned draft. Older conversations retain the synchronous path. The flag does not reinterpret existing durable conversations: they continue to accept turns and resume with their stored version after a rollback. `ORCHESTRATOR_MODEL_ASSISTED` does not control this deterministic conversation scheduler.

The message transaction commits the immutable user turn and queued task together, then returns `status=analyzing`. No provider is invoked from that HTTP transaction. The UI polls saved conversation status, handles temporary polling failures, restores analysis after refresh, and offers cancellation. Edit, retry and confirmation requests are rejected while analysis is active. Cancellation uses the current optimistic revision and prevents late output from being published.

Use the existing `python ops/run_worker.py`. Its polling loop processes one report and one conversation task per cycle, sequentially. `--once` processes at most one task, preferring an available report. Multiple worker processes claim tasks with `FOR UPDATE SKIP LOCKED`. A running worker independently renews its conversation lease every 40 seconds; user clarification and confirmation waits retain no lease.

## State, budgets and retry policy

Each analysis task pins its conversation, schedule, input revision, contract version, source fingerprint, provider/model/key-slot assignments and timeout. Provider credentials are read at execution and never saved in task configuration. Public conversation responses contain no journal output, fingerprints, provider configuration or lease tokens.

Limits for this runtime version:

| Limit | Value |
| --- | --- |
| Task ownership lease | 120 seconds, independently renewed |
| Attempts per task, including restart claims | 3 |
| Model-call reservations per task | 806 |
| Model-call reservations across a conversation | 1,600 |
| User turns per conversation analysis | 100 |
| Analysis tasks per conversation | 200 |
| Task deadline from enqueue, including queue wait and retries | 1,800 seconds |
| One saved model response | 1 MiB |
| Saved responses per task | 16 MiB |

Model-call reservations commit before inference. Failed calls and calls interrupted before their response is saved consume budget. Successful model responses are checkpointed by call ordinal, role and complete request fingerprint, then revalidated by the existing extraction and selection contracts on replay. A restart repeats deterministic draft construction while reusing completed model calls; it does not rerun those calls. A crash after provider completion but before response checkpoint commit can repeat inference, with both reservations charged.

Transport failures automatically requeue with bounded 2/4-second delays until the attempt limit. Adapter transport retries remain zero. Invalid responses and other analysis failures stop safely and require explicit retry. Explicit retry reuses the failed task, original deadline, counters and journal while advancing the public conversation revision. Exhausted or incompatible tasks reject retry; a new user turn starts a new task while retaining the aggregate conversation call limit. Existing semantic repair allowances remain unchanged. A subsequent [hosted-provider admission guard](provider-capacity.md) now shares PostgreSQL-backed concurrency and observed quota cooldowns across roles/keys. Conversation retries persist the provider cooldown; daily quota exhaustion does not auto-retry. No cross-provider fallback is configured.

The worker checks ownership, input fingerprint, cancellation, deadline and active schedule before calls, after calls and before publication. Publication locks and refreshes the conversation and project rows. Stale schedules discard draft events. Task completion and the resulting draft/question/revision commit together. An old lease cannot publish after replacement, and a terminal task cannot be claimed again. Checkpoint storage contains private source-derived output, as existing conversation drafts do; it is not included in public traces. Backup/restore manifests now verify both conversation journal tables and report agent tasks.

## Rollback and verification

Set `AGENT_HIERARCHY_ENABLED=false` to stop creating durable conversations and new v2 reports. Keep the updated worker, both runtime versions and additive tables until existing durable work is drained or explicitly cancelled. Do not downgrade the migration or remove journal data while durable conversations exist. Both rollout flags remain false in this workspace.

PostgreSQL tests in `backend/tests/integration/test_durable_conversations.py` cover committed turns before inference, missing-date follow-up, corrections and repeated confirmation through HTTP, pending-review boundaries, extraction and selection replay, actual subprocess SIGKILL recovery, attempt and call budgets, bounded response storage, manual retry revision conservation, heartbeat renewal, stale schedules during inference and at confirmation, cancellation, and mismatched checkpoint rejection. The browser fixture checks 390px and 1440px refresh, polling failure/reconnection, clarification and disabled confirmation. These are deterministic checks, not live provider-capacity or independently adjudicated report-quality acceptance.

## Validation record — 16 October 2026

- 311 backend unit tests passed.
- 152 PostgreSQL integration tests passed across the full backend suite, including 17 durable-conversation scenarios.
- Two conversation browser scenarios passed at 390px and 1440px; saved screenshots were inspected.
- Frontend TypeScript, production build and contract assertions passed.
- Ruff for changed runtime/API/storage/worker/test/backup files and `git diff --check` passed.
- Effective local hierarchy and model-assisted flags were checked again and both were false.

An initial test run exposed a test cleanup ordering issue and an incorrect ledger-column assertion in the new fixtures; both were corrected. A broader run also exposed an existing native MPP import test double that returned a candidate outside the byte-bounded supplied schedule batch. The test double now returns the target only when present in that batch; production matching rules were not changed. An initial browser run used the wrong mocked account response on refresh; correcting the fixture made both browser scenarios pass. No live inference, provider-load run, production migration or rollout was performed.

## Extraction prompt compatibility

New tasks now pin `extraction_prompt_version=extraction-v11-exact-evidence-coverage`
in their saved configuration. Old tasks without that field retain the exact v9
prompt and v9 normalization during retries and saved-call replay. Previously pinned v10 tasks retain their exact v10 prompt and processing; v11 evidence repair is not applied to their saved outputs. New report
runs use the same pinning rule in `AgentRun.config_metadata`. Do not replace or
remove a registered historical prompt while resumable work still references it.
Changing the default affects newly created tasks/runs only. The v10 follow-up
and its remaining quality failures are recorded in the
[quality report](../evaluation/results/quality-gap-fixes-2026-10-16/REPORT.md).
