# Graph-only report runtime (2026-10-12)

The report processor now uses LangGraph as its only execution path. The former pipeline, execution-mode setting, and worker rollback override were removed. Existing database records and their provenance are retained as historical records; they are not rewritten to imply they were created by the current runtime.

The authenticated job status response omits execution-mode metadata and exposes `agent_run_available`. It is true when a persisted graph run exists. The frontend shows bounded public run details only for available traces, waits on active jobs while the parent job status is polled for trace creation, and hides the status section for terminal historical jobs with no trace. Fixture mode disables the status request. Public stage labels and bounded counters, attempts, durations, and ordered steps remain allow-listed; raw server errors and unknown labels are not rendered.

The 2026-10-12 graph acceptance evidence records the live local browser-to-API/worker/model path, SIGKILL checkpoint resume, backup/restore verification, and the pre-removal regression totals. The [final graph-only acceptance record](../validation/graph-only-acceptance-2026-10-12.json) records 233 unit tests, 124 PostgreSQL integration tests, 44 browser fixtures and 11 final API/worker regression tests. These are recorded checks, not newly rerun by this documentation reconciliation. The live prototype workflow produced a pending proposal and no approved progress event. These checks do not establish independent label review, calibration, frozen splits, owner-data coverage, unseen quality, or lifecycle/duration acceptance.

Earlier dated task-board and W-38/W-39 handoff notes are retained as historical evidence. Their references to an alternate processor, execution-mode selection, or rollback behavior describe the earlier implementation and are superseded for current operation.

## Frontend verification

- `npm run typecheck` — passed.
- `npm run build` — passed.
- `npm run test:e2e -- --project=review-api --grep='agent|historical terminal|queued graph'` — 11 passed.
- `npm run test:e2e -- --project=fixtures --project=review-api --workers=3` — 44 passed, including fixture flow, strict API mocks, historical jobs without traces, pending graph trace availability, running/terminal states, stale-response cancellation, retry behavior, and mobile/desktop layouts.

One initial parallel full-suite attempt had a single setup timeout; the affected test passed in isolation, and the complete rerun passed. Tests use intercepted API fixtures; they do not call a live model.

## Later compact quality evidence

The [12 October Gemma benchmark](../../evaluation/RESULTS.md) completed 60 synthetic cases using a compact prompt and full schedule context, with five unmatched false matches. It bypasses the production graph's separate extraction and shortlist stages; it does not establish complete graph-runtime quality or close independent review/freeze/calibration gates.
