# Remaining work audit — 15 October 2026

Follow-up, 16 October: durable conversation orchestration has since been implemented and locally verified. See [the current conversation guide](durable-conversations.md). Findings below retain the original audit state; provider-capacity and broader report-evaluation gates remain open. A subsequent [report investigation](../evaluation/results/report-evaluation-2026-10-16/REPORT.md) and [capacity guide](provider-capacity.md) record implemented fixes, new evidence and the remaining limits.

Decision: keep both rollout flags disabled. This audit checked current code, retained evaluation captures and fresh deterministic tests. It did not implement the remaining orchestration, make live provider requests or deploy anything.

| Area | Finding | Remaining gate |
| --- | --- | --- |
| Durable conversations | Incomplete. Messages and retries call `analyze()` synchronously inside the request transaction. Drafts and `hierarchy_waiting` references persist, but there is no conversation task runner, checkpoint resume, conserved root budget or automatic restart recovery. | Persist input before inference; add versioned tasks, ownership, budgets, bounded retries and restart recovery. Waiting for users must release execution ownership. |
| Conversation verification | Partial. Unit tests exercise missing-date clarification, corrections, repeat service confirmation and stale draft invalidation with hierarchy on/off. PostgreSQL HTTP coverage exercises partial-scope clarification, corrections, refresh, duplicate confirmation rejection, pending review, reviewer acceptance and model-outage retry. | Complete the matrix through HTTP/browser with hierarchy enabled, including stale schedules, missing-date follow-ups, concurrent/repeated confirmation and real process interruption. The existing live browser test is opt-in and was not run in this audit. |
| Broader report evaluation | Partial. Six synthetic scenarios and an independent live pair are retained. Controlled candidate specialists replay baseline payloads; these are compatibility evidence, not independent candidate accuracy measurements. | Independently adjudicate ambiguous matches, semantic evidence, dates and units; broaden representative samples. |
| Provider capacity | Incomplete. Role selection and bounded adapter requests exist; application construction sets transport retries to zero. Evaluation pacing observes quota headers, but does not establish application capacity. No application-wide provider semaphore, quota scheduler or configured cross-provider fallback was found in the inspected execution path. | Measure sustained throughput, concurrency, timeout/429/5xx handling and explicit fallback policy for each selected provider/model. Additional keys do not establish independent quotas. |
| Controlled rollout | Prepared in part, not executed. Defaults and effective local flags are false. Tests cover version-pinned report resume across flag changes, stale schedules, lease reclaim, checkpoint recovery and pending proposals. | Review final combined changes after remaining work; stage new-run enablement, monitor failure/latency/budget metrics and exercise operational rollback. |

## Specific evaluation defects

`evaluation/report_planner_eval.py:score_case` compares every non-null label quantity against the normalized observation. `backend/app/llm/extract.py` intentionally clears quantities for planned work, no-work and material-delivery observations. Thus the planned-work case remains a label/measurement contract mismatch, not a resolved scoring implementation. Define separate source/planned-quantity and actual-progress expectations, retain the original raw score/captures, and add a versioned normalization-aware metric. Do not change labels silently to improve results.

The original controlled `C01` capture records successful extraction, followed by a retrieval `OllamaTransportError` after 52,290 ms including 22,578 ms of pacing. The v1 run subsequently reports `JOB_LEASE_LOST` from the post-node ownership check at about 53.5 seconds. V2 replays that failed specialist response as HTTP 599 and returns `AGENT_INTERNAL_ERROR`; this is not a second independent provider outage. A separately retained retry succeeds in both arms without duplicate proposals or ledger writes.

The evaluation calls `process_job_with_graph` directly with a 15-minute initial lease and without the production worker's heartbeat callback/thread. The observed short elapsed time alone does not explain the lease-loss signal. The retained sanitized capture lacks the ownership/state transitions needed to establish the cause. Reproduce with controlled transport failure and record safe job-state/lease-time transitions around node completion, then repeat through the production worker path. Successful retry does not close this investigation.

Evidence substring checks establish quote presence only. They do not establish that the cited quote supports the event, date, unit or quantity claimed. Independent semantic review remains open.

## Fresh validation

- 311 unit tests passed.
- 51 PostgreSQL integration tests passed: all agent integration tests plus conversation HTTP coverage, using isolated `progress_test`.
- Frontend TypeScript and frontend contract assertions passed.
- Ruff passed for inspected agent, conversation, provider and report-evaluation code; `git diff --check` passed before this audit document was added.
- Effective local settings: `agent_hierarchy_enabled=False`, `orchestrator_model_assisted=False`. No settings or credentials changed.

The initial sandboxed PostgreSQL run could not connect. The same suite passed with approved access to the local test database. No current browser run, live quota/load test, production monitoring or deployment rollback drill is claimed.
