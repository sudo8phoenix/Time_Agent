# Hierarchical runtime rollout

For the latest model, evidence, retained work and six open release workstreams,
see [current status](current-status.md). Both rollout flags remain false. V20 is
opt-in; the default extraction prompt remains V12. The historical implementation
and measurements below do not establish current acceptance.

Implemented 15 October 2026. Both runtime generations remain available. Human approval remains the only path to ledger effects.

`AGENT_HIERARCHY_ENABLED=false` is the default. It controls creation of report runs and use of shared conversation specialists. Existing report runs dispatch from their stored graph/state versions, independently of the current flag. v1 checkpoints retain their original graph. v2 uses `report-analysis-v2` / `agent-state-v2`, nested intake, analysis, matching and review graphs, and additive `agent_tasks` storage (migration `0016_agent_tasks`). Execution is sequential.

Apply migrations through the existing Alembic workflow before enabling new v2 runs. No production migration or deployment was performed for this implementation. Local durability tests use the isolated `progress_test` database.

## Configuration

Extraction, selection (including candidate shortlisting), and orchestration each accept `<ROLE>_PROVIDER`, `<ROLE>_MODEL`, and `<ROLE>_KEY_SLOT`. Providers are `ollama`, `groq`, and `openrouter`; Groq slots are `0` (original `GROQ_API_KEY`), `1`, and `2`. Assignments and model-assisted mode are pinned to the run when it is created. Credentials remain ephemeral and are never checkpointed. Defaults retain the configured baseline: Groq `openai/gpt-oss-20b` in this workspace. Multiple keys do not imply separate quotas, and there is no key rotation or quota bypass.

`ORCHESTRATOR_MODEL_ASSISTED=false` retains deterministic root routing. The optional planner requires explicit `ORCHESTRATOR_PROVIDER=openrouter` and an allowlisted free model ID: `nvidia/nemotron-3.5-super-vl:free`, `nvidia/nemotron-3-super-120b-a12b:free`, or `nvidia/nemotron-3-ultra-550b-a55b:free`. Super VL is the current evaluation candidate. Paid IDs, automatic routers, and unknown models are rejected before adapter construction. It receives only the next legal supervisor action, with no source bodies or arbitrary tool access. Python validates its JSON and the exact legal action; invalid decisions terminate safely. It cannot approve proposals.

The exact ID and zero prompt/completion prices were verified against [OpenRouter's official endpoint catalog](https://openrouter.ai/api/v1/models/nvidia/nemotron-3-ultra-550b-a55b:free/endpoints) and [model listing](https://openrouter.ai/nvidia/nemotron-3-ultra-550b-a55b%3Afree/pricing). The catalog advertises tools/tool choice, but not `response_format`. The adapter requests JSON in its prompt and validates locally; downstream Pydantic contracts remain authoritative. At verification the endpoint reported `status=-5` and zero uptime over the preceding 5/30 minutes. Availability therefore blocks a meaningful live planner smoke test; deterministic orchestration remains the rollout configuration. No alternate paid model or free router was selected.

## Ownership, budgets and recovery

Task envelopes pin run, project, source, schedule, contract, parent, observation key and attempt. The registry permits root → intake/analysis/review, analysis → extraction/matching/evidence, and matching → selection. Tool views expose only the responsible role's capabilities. Deterministic evidence/date/scope validation, arithmetic and pending proposal persistence remain tools.

The root reserves usage in a locked, short database transaction before work. Limits are 12 supervisor transitions, 806 actual model calls, 1,010 tool calls, 1,300 delegations and 1,800 seconds from original run creation. Limits are shared across children, failed calls and restarts. The model allowance covers two extraction attempts, candidate decisions and two selection attempts for up to 200 observations, plus three optional planner calls, with a hard shared cap for extraction batching and crash replays. Existing extraction/selection semantic repair limits remain one each; hosted adapters perform no transport retries in the worker. The inherited domain-node guard remains as an additional invariant; it does not count supervisor nesting.

Nested LangGraph checkpoints use the pinned installed versions (`langgraph==1.2.12`, checkpoint-postgres `3.1.2`). Durable successful child state resumes through those checkpoints. Task fingerprints reject changed scope/input, and sanitized task IDs link tool and supervisor traces. A provider response before its checkpoint may be repeated following a crash; reservations persist and domain writes remain idempotent. A checkpoint infrastructure failure leaves unfinished task records resumable. Ordinary terminal outcomes reconcile unfinished tasks. Lease loss and shutdown propagate out of nested graphs; stale schedules prevent persistence.

Conversation analysis shares extraction and selection specialist contracts, preserves quoted exact-match shortcuts and immutable user turns, and stores source-turn/schedule references while awaiting clarification or confirmation. It does not create a worker lease while waiting. New turns recompute the draft; a changed schedule invalidates it. Confirmation is idempotent and creates pending review proposals, never ledger entries. New conversations created with the hierarchy enabled now use the [durable conversation runtime](durable-conversations.md), with leased worker tasks, model-call checkpoints and conserved budgets. Existing conversations retain their original synchronous path. The flag controls creation; stored conversation versions survive rollback.

## Verification and rollback

`backend/tests/integration/agent/test_hierarchical_runtime.py` covers PostgreSQL task lineage, approval boundaries, both versions resuming after a flag change, interruption after extraction without repeated extraction, stale schedules, lease reclaim and the persistence/checkpoint crash boundary with exactly one proposal set. Unit tests cover scope denial, contract identities, budgets, bounded repairs, invalid planner actions and non-writing shadow comparison. Public API tests verify that raw task summaries, references, error text and private configuration are excluded.

`agent.shadow.compare_report` executes each generation with fresh tools and intercepts persistence. Synthetic matched and unmatched comparisons are recorded in `evaluation/results/hierarchy-baseline-2026-10-15/comparison.json`. They have identical observations, selections, terminal outcomes and domain counters; writes are zero. These small deterministic fixtures are a compatibility baseline, not a live quality or latency benchmark. Provider accuracy and production latency thresholds still require a representative authorized evaluation before enabling v2 broadly.

Rollback sets `AGENT_HIERARCHY_ENABLED=false` for subsequent jobs. Existing v2 runs continue through v2. Keep additive task tables and checkpoints; do not downgrade migrations or delete checkpoints while either version is active. To abandon a run, use the existing cancellation/retry policy under operator control rather than changing its stored version.

## Local validation record

Final backend validation: 279 unit tests passed; 47 PostgreSQL agent integration tests passed, including seven v2 durability tests. Ruff and `git diff --check` passed. Migration 0016 was applied only to the isolated local test database.

Frontend TypeScript checking, Vite build and `node frontend/tests/frontend-contracts.test.mjs` passed. The two new hierarchy browser scenarios passed at 390px and 1440px. The existing status browser file initially had eight passes and three failures; offline recovery passed on an isolated rerun. The bounded-404 and unknown-label scenarios fail before `.job-header` appears, and both failures were reproduced with the original HEAD frontend in an isolated temporary directory. These legacy fixture failures remain outside the migration changes; the whole browser suite is not being reported as green.

A read-only OpenRouter `/api/v1/key` authentication request returned HTTP 200 using the existing credential. No credential or account detail was printed or persisted. This confirms key authentication, separately from the free model endpoint's availability. No inference was submitted to a paid fallback.


## Resumed evaluation work

Schedule discovery now partitions the entire pinned schedule by an 8,000-byte logical request budget (system, user context and schema), with the original 48-row limit as a second guard. It preserves schedule fields and source quotes, reserves room for empty-result reconsideration, and rejects a single oversized row before making a model call. Candidate merges must strictly reduce their input count. These changes apply equally to the retained and hierarchical graphs; the original failed captures remain available for comparison.

The evaluation-only transport uses the same HTTP User-Agent as the production adapters. It reads only allowlisted numeric quota headers, observes token reset times and `Retry-After`, and paces the same credential without rotation. Daily or excessive retry delays stop traffic. Provider error bodies remain discarded. This pacing is an evaluation mechanism; application rollout still requires capacity planning for the selected provider. See [Groq's rate-limit documentation](https://console.groq.com/docs/rate-limits).

The full agent PostgreSQL regression suite passed 50 tests after these changes. The browser status suite passed all 13 scenarios on two later full runs; earlier job-screen startup timeouts were intermittent and did not reproduce reliably, so no speculative product or test changes were made.


The completed [report evaluation](../evaluation/results/report-planner-super-vl-2026-10-15/REPORT.md) includes an independent live 60-activity pair, a six-fixture controlled specialist replay with live planners, and a separately retained retry of the interrupted clear-match fixture. Domain outputs matched across each controlled pair; all persisted proposals stayed pending, successful terminal replays created no duplicates, and ledger writes were zero. The six-fixture first pass had five successful cases and one transport/lease interruption; its retry later succeeded without replacing the original result. Small synthetic samples and unadjudicated labels remain insufficient for broad rollout.

At that resumed stage, 311 unit tests, 50 PostgreSQL agent integration tests and 13 browser status scenarios passed; these are historical totals. The evaluation preserves distinct diagnostic attempts and explains the planned-quantity label mismatch. Conversation task durability was subsequently implemented; see [its guide](durable-conversations.md). The [provider capacity implementation](provider-capacity.md) now uses PostgreSQL admission across processes sharing one database. Sustained representative capacity remains unproven; cross-provider fallback remains unconfigured and fails closed. Current verification scope is recorded in [current status](current-status.md).
