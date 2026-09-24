# Implementation task state

This is the execution record for the application. The user-facing checklist remains at `progress-agent-plan/TASK_BOARD.md` and is updated when a task has passed its acceptance evidence.

| Task | Status | Owner | Dependencies | Next acceptance evidence |
| --- | --- | --- | --- | --- |
| O-01 | complete | orchestrator | — | recorded decisions and assigned scopes |
| W-01 | complete | builder agent | O-01 | completed: bootstrap, lockfiles, PostgreSQL startup, liveness, and web build |
| W-02 | unit validated | builder agent | W-01 interface | generated OpenAPI comparison |
| W-03 | 60/300 expansion validated; human review pending | builder agent | W-02 interface | user review of seed, expanded and native-linked labels |
| W-04 | complete | builder agent | W-02 interface | expiry/revocation/roles/CSRF/cross-project acceptance passed |
| W-08 | remote-private adapter complete; benchmark blocked | builder agent | friend-host endpoint/model | live readiness, digest and measured benchmark |
| W-05 | complete | builder agent | W-03/W-04 interfaces | CSV and activation safety integrated with native flows |
| W-06 | complete | builder agent | W-04/W-05 interfaces | PostgreSQL constraint rollback and file cleanup passed |
| W-07 | runtime complete; live model pending | builder agent | W-04/W-06 interfaces | run CLI worker against friend-hosted Ollama |
| W-09 | extraction fixtures validated; real-model evaluation pending | builder agent | W-03/W-06/W-08 interfaces | 20 seed-case results from an actual local model |
| W-10 | persisted hybrid retrieval validated; live model pending | builder agent | W-02/W-03/W-05 interfaces | provision pinned local embedding weights and evaluate reviewed labels |
| W-11 | deterministic and persistence integration validated | builder agent | W-09/W-10 interfaces | live-model selection evaluation |
| W-12 | unit validated | builder agent | W-02/W-03/W-04 interfaces | database-backed approval integration |
| W-13 | complete | builder agent | W-07/W-11/W-12 interfaces | real two-session race and correction/supersession passed |
| W-14 | build/API contract validated | builder agent | W-01/W-02 interfaces | browser walkthrough with provisioned demo account |
| W-15 | build/API contract validated | builder agent | W-13/W-14 interfaces | browser walkthrough of review/revise/reject/approve |
| W-17 | PostgreSQL/API/export validated | builder agent | W-12/W-13/W-14 interfaces | browser walkthrough of approved progress and CSV download |
| W-18 | implementation complete; real evaluation blocked | builder agent | W-03/W-09/W-10/W-11/W-12 interfaces | saved predictions from real local model |
| W-21 | complete | builder agent | O-02, W-02 | required hash/provenance fixtures include real MPP |
| W-22 | complete | builder agent | W-21, W-01 | all required bounded MPXJ smoke fixtures pass |
| W-23 | complete | builder agent | W-21/W-22 | XER, PMXML and multi-project selection pass |
| W-24 | complete | builder agent | W-21/W-22 | MSPDI and real MPP pass |
| W-25 | complete | builder agent | W-23/W-24, W-05 | four-format normalization preserves unknown quantities |
| W-26 | complete | builder agent | W-25, W-04/W-05 | provenance persistence passes assembled flow |
| W-27 | complete | builder agent | W-26, auth dependencies | all four authenticated API flows pass |
| W-28 | production UI build validated; browser walkthrough pending | builder agent | W-27, W-14 | real browser import/mapping/activation walkthrough |
| W-29 | integrity complete; human review pending | builder agent | W-25, W-03/W-21 | review the 40 native-linked synthetic labels |
| W-30 | backend accepted; browser pending | orchestrator | W-23–W-28, W-10; W-29 paired cases | 7 real parser/API/DB/retrieval cases passed; browser walkthrough pending |
| O-04 | active; persistence/runtime accepted, rollout still disabled | lead orchestrator | W-31–W-36 acceptance evidence | complete W-37/W-38/W-39; keep graph mode disabled |
| W-31 | complete | Luna low-reasoning builder; accepted by O-04 | O-04 compatibility shortlist | LangGraph 1.2.12/checkpointer 3.1.2 locked; memory and PostgreSQL 16.6 resume pass |
| W-32 | complete | builder agent; accepted by O-04 | W-31 | strict schemas, three trace tables and migration `0008_agent_runs`; 11 unit + 9 PostgreSQL tests pass |
| W-33 | complete | Luna low-reasoning builder; accepted by O-04 | W-31 | 21 strict state/context/policy tests and Ruff pass; W-34 unblocked |
| W-34 | complete | Luna low-reasoning builder; accepted by O-04 | W-33 | 19 typed-tool cases cover metadata and safe retry classification; W-35 accepted |
| W-35 | complete | Luna low-reasoning builder; accepted by O-04 | W-31/W-33/W-34 | exact 11-node/edge manifest, 8 route/limit/atomicity tests and Ruff pass; consumed by accepted W-36 runtime |
| W-36 | complete | O-04 integration | W-32/W-35/W-07 | PostgreSQL saver, provenance rehydration, leases/heartbeats, idempotent finalization, sanitized telemetry and exact pruning; 10 focused cases pass |

## Native-import assignment rules

Use `progress-agent-plan/06_NATIVE_SCHEDULE_IMPORT.md` (contract v1.1) and W-21–W-30 cards in the implementation plan. Paste the user's exact worker prompt into each assignment; specify prerequisite files/revisions and only the card's writable paths. No more than three concurrent workers, no overlapping shared-file ownership. O-02 supplies dependency pins, actual parser field-accessor examples and API payloads before assigning dependent low-reasoning builders.

The native-import implementation is integrated and its four-format backend acceptance passes. Future W-18 evaluation consumes W-29 after human review; W-20 still requires live browser and model evidence. The planning viewer now derives counts dynamically and includes contract v1.2/native-import material.

## Completed evidence

- O-01 (2026-09-22): froze v1 contract references, first data slice, initial path ownership, and known infrastructure assumptions in `docs/decisions.md`.
- W-03 (2026-09-22): dependency-free integrity validation passes for the synthetic 12-activity/20-case seed slice. The source manifest records `pending_human_review`.
- W-01/W-02/W-04/W-08: static source/JSON checks pass where applicable. Their required live checks remain blocked by host Python 3.9.6, missing dependencies, unavailable PostgreSQL, and unavailable local model respectively.
- W-13 repair (2026-09-22): approval now uses the canonical proposal route, idempotency/revision checks, project membership, locked activity state, and the deterministic ledger before committing an event/audit/state update. PostgreSQL transaction tests remain required.
- W-09 fixture validation (2026-09-23): 10 deterministic extraction tests pass for batching, atomic observations, evidence validation, date trust and non-progress quantity removal. This does not measure a local model.
- W-10 fixture validation (2026-09-23): 7 deterministic retrieval tests pass. Eligible explicit activity IDs survive without rank evidence and remain first; synthetic seed Recall@8 is 1.0 over 17 labelled suggested cases. This is not an embedding/model benchmark.
- W-10 persistence (2026-09-23): migration `0007` stores activity vectors by activity/model revision with a composed-description hash. The worker reuses valid vectors, refreshes stale text, embeds only each query during retrieval, and falls back to lexical ranking if the optional local embedding model is unavailable. No embedding weights were provisioned, so model quality remains unmeasured.
- W-21 schema/fixture validation (2026-09-23): four strict-schema tests pass; authored XER, P6 XML and MSPDI fixtures have recorded hashes and hand-checked counts. A real MPP fixture and all native parser reads remain pending.
- W-07 lifecycle validation (2026-09-23): four PostgreSQL job-lifecycle tests and the full six-test integration suite pass. Lease replacement, retry bounds, terminal jobs and stale schedule versions are covered; the real processing pipeline is still unassembled.
- W-11 selection validation (2026-09-23): 11 injected-model tests pass for dynamic candidate IDs, abstention, contradictions and evidence membership. No model/database integration result exists.
- W-06 recovery validation (2026-09-23): 7 unit tests pass for multipart validation, locators, duplicate preservation, storage cleanup and flush compensation. PostgreSQL constraint-failure recovery remains untested.
- W-13 approval-lock validation (2026-09-23): 8 PostgreSQL integration tests pass, including idempotent retry, stale second approval, row locking, cross-project rejection and rollback. The evidence uses sequential independent sessions, not a simultaneous-request race.
- W-05 schedule-safety validation (2026-09-23): 3 PostgreSQL API tests pass for no partial invalid staging, duplicate-byte idempotency/leading-zero IDs, activation conflict and post-approval rebase restriction. Canonical CSV only; native conversion is separate.
- W-07 assembled-pipeline validation (2026-09-23): PostgreSQL tests cover persisted fragment evidence, pinned-version candidates, pending proposals, injected failure rollback and retry idempotence. No local model was called and the CLI worker runner remains unimplemented.
- Runtime setup (2026-09-23): Python 3.12.14 installed; `uv.lock` and `frontend/package-lock.json` generated; `make bootstrap`, `make db-up`, `make migrate`, `make test-unit` (29 passed), `npm run build`, API liveness, and `make doctor` completed successfully.
- PostgreSQL workflow (2026-09-23): `make test-integration` passes two tests using rollback-isolated PostgreSQL transactions. Coverage includes reviewer login/CSRF, project membership, schedule import/activation, report idempotency, job lookup, viewer denial, proposal evidence retrieval, an approved progress event, and repeat approval idempotency.
- W-17 progress/export validation (2026-09-23): authenticated PostgreSQL integration coverage verifies per-activity approved state, pending-review count, source locator history and approved-event CSV. Unit coverage verifies spreadsheet-formula neutralization without altering normal leading-zero-style IDs. Browser walkthrough remains pending.
- W-22 runtime validation (2026-09-23): the existing pinned Python bridge (`JPype1 1.5.2`, `mpxj 14.0.0`) now runs in a bounded child process with unit checks; host OpenJDK 25.0.1 reads workspace `PROJECT.xer` (24 tasks). The corrected MSPDI fixture now reads; unavailable/corrupted authored fixtures are explicitly marked non-required, so no unsupported format claim is made.
- W-23 Primavera validation (2026-09-23): the bounded reader preserves P6 XER project/task identity, WBS/outline/calendar metadata, dates and three FS relationships from hash-verified workspace `PROJECT.xer`. PMXML and multi-project cases remain unverified.
- W-24 Microsoft validation (2026-09-23): after correcting the MSPDI namespace, the bounded reader preserves UID separately from display ID, summary hierarchy and an FS relationship in a four-task MPXJ-read fixture. Real MPP evidence remains pending.
- W-25 dispatch/normalization validation (2026-09-23): strict reviewer mapping produces canonical CSV through the existing validator, keeps unknown leaf quantities unsupported, preserves metadata and rejects unknown IDs/DTD XML. P6 XER and MSPDI dispatch checks pass; PMXML/MPP source evidence remains pending.
- W-26 native-import storage validation (2026-09-23): migration `0006` and PostgreSQL coverage verify original source storage, duplicate-byte reuse, reviewed mapping staging, normalized schedule linkage and immutable source metadata for the inspected P6 XER.
- W-27 native-import API validation (2026-09-23): reviewer/CSRF-protected P6 XER upload, mapping and explicit staging pass through PostgreSQL; read access remains membership-scoped. PMXML/MPP and browser evidence remain pending.
- W-28 native-import UI validation (2026-09-23): the workspace now supplies upload, source ID/WBS/dependency preview, reviewer mapping, explicit staging and activation controls; production build passes. A real browser walkthrough remains pending.
- W-03 expansion (2026-09-23): 60 executable activities, 100 synthetic reports and exactly 300 atomic proposed labels pass count, reference, 180/60/60 family-split and hash checks. Review sheets are ready; human review remains pending.
- W-04/W-06/W-13 closure (2026-09-23): eight focused PostgreSQL safety checks pass for session expiry/revocation, project isolation, a real two-session approval race, correction/supersession, warning resolution, pinned schedules, transaction rollback and stored-artifact cleanup.
- Private inference amendment (2026-09-23): the worker accepts only loopback/private/link-local/Tailscale model endpoints, supports optional server-side bearer authentication, hides endpoint/token from output, and passes 12 adapter checks. Live friend-host readiness remains pending.
- W-21–W-27/W-30 backend acceptance (2026-09-23): bounded MPXJ reads all required fixtures including real MPP; seven isolated-PostgreSQL flows cover four formats through preview, reviewed mapping, staging, activation and version-scoped retrieval. Full integration result after W-10 persistence: 30 passed.
- W-34 typed agent tools (2026-09-24): the six server-scoped adapters enforce job/lease/schedule ownership, exact fragment and candidate membership, observation/candidate limits, bounded model calls, safe abstention, strict validation and an idempotent persistence callback. Nineteen focused cases also cover server-owned report metadata and fail-closed retry classification.
- W-35 bounded graph (2026-09-24): the exact 11-node LangGraph manifest passes eight focused happy/repair/abstention/stale/failure/limit/atomicity cases and Ruff. The complete backend unit suite passes 139 tests. Graph mode remains disabled; W-36 must add validated checkpoint provenance rehydration and runtime integration after W-32.
- W-32 trace persistence (2026-09-24): strict public status schemas and the `agent_runs`, `agent_steps` and `agent_tool_calls` records/constraints pass 11 schema and 9 isolated-PostgreSQL cases, including clean `0008` downgrade/re-upgrade. No checkpoint/prompt/report-body columns were added.
- W-36 durable runtime (2026-09-24): migration `0009` installs the pinned saver schema without startup DDL; ten focused PostgreSQL cases cover durable provenance resume, duplicate prevention after ambiguous checkpoint failure, persistence rollback, replacement leases, boundary heartbeats, schedule staleness, version rejection, sanitized traces and exact dry-run pruning. Full regressions pass at 150 unit and 49 integration tests. `agent_execution_mode` remains `legacy`.
- W-29 integrity (2026-09-23): 40 native-linked synthetic observations preserve real P6 source IDs/Microsoft UIDs, exact case allocation, source hashes and 24/8/8 family splits. Human review remains pending.
- W-14/W-15/W-17/W-28 frontend integration (2026-09-23): production build and source-contract checks pass for real logout, full proposal queue, correction/warning resolution, retry, CSV/native import, source-project selection and explicit activation. Browser visual evidence remains pending because no browser surface was available.
- G-07 (2026-09-23): backup and restore were verified against a separate database containing one approved event and one linked source evidence fragment. The restored database was left separate for inspection.
