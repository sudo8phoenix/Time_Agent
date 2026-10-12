# Local prototype release evidence — updated 12 October 2026

This working tree implements the public/synthetic construction-progress prototype. It is not an independently validated release or owner-package acceptance. The completed implementation and remaining acceptance gates are recorded here; versioned task handoffs provide the supporting implementation evidence.

## Source and runtime

Base source revision: `ec9567d` (`Improve report extraction reliability and five-entry review workflow`), with parent `ef89995`. The graph-only update is published through the repository commit history; the source manifest identifies the tested application files. The October 10 release manifest and recovery evidence below document that earlier snapshot and remain historical; they do not identify the current source tree.

The [current source manifest](validation/graph-only-source-manifest-2026-10-12.json) hashes the application, migration, operations, test, frontend and dependency/configuration files. The [acceptance record](validation/graph-only-acceptance-2026-10-12.json) records the final checks, local deployment and remaining data gates. Private configuration and uploaded evidence are excluded from the source manifest.

Python 3.12.14; Node 26.0.0; npm 11.12.1; OpenJDK 25.0.1; PostgreSQL container 16.6. Python pins are in `pyproject.toml`/`uv.lock`; frontend pins are in `frontend/package-lock.json`. Lock hashes:

- `uv.lock`: `d9fc6a58f24fbf75fb9d99e5bed28e410ee3a9cde0e6ec9f0b306c3ca45269ce`
- `frontend/package-lock.json`: `438ccc28d5cbe697e5b8757c2569f8849f4204a8bea766c435601ca4e98ee96f`

LangGraph is the only supported execution runtime. The legacy job pipeline and rollback switch have been removed. Historical records remain readable. The API and worker were restarted on port 8001 with the graph-only code. The final model connectivity check timed out; the earlier successful live-model evidence remains dated evidence, not a claim of current model availability. Migration head is `0015_schedule_source_metadata`. The application database was migrated after a pre-deployment backup at `/private/tmp/time-agent-before-graph-20261012`; the separate project on port 8000 was left untouched.

The October 10 checks used injected fixture models for deterministic pipeline coverage; no model call was part of that verification. On October 11, the five-entry GT10 quantity workflow did call the authenticated live `gemma4:12b` API. Server-side configuration controls endpoint and model. Reanalysis records requested configuration separately from actual pipeline provenance and does not permit browser-supplied configuration overrides.

## Tested behavior

Quantity-free actual starts/finishes retain date/time precision, scope and source evidence. Authorized reviewers accept proposals; conversations alone do not authorize changes. Corrections/retractions preserve history and recompute current state. Report mapping and PDF transcription preserve original cell/page attribution. History/export separates event values from current state, and duration queries disclose unavailable calendar/labour inputs.

Explicit reanalysis creates a linked job with actor, reason, pinned schedule and configuration. Ordinary duplicate submission returns the original base job. Cross-run repeat application of accepted source work is blocked; accepted work changes through the existing correction workflow. Backup manifests verify row-content hashes for jobs, lifecycle state/events, observations/proposals/audit, graph records, conversations and outbox, plus original-file hashes.

The connector and receiver are labelled **MOCK PMIS — prototype**. Automatic outbox delivery, read-back, retry and correction ordering have fixture coverage. This is not a production PMIS integration.

## Historical verification — 10 October

211 unit tests, 102 isolated PostgreSQL integration tests and 33 browser fixtures passed. Final counts and command results are recorded in [E01–E03 verification](validation/e01-e03-verification-2026-10-10.json). Native smoke parsed all six required inputs, including XER, P6 XML, MSPDI and real MPP, and rejected the malformed XML fixture. Frontend type checking, production build and contract assertions passed.

A fresh source database `progress_recovery_e01_20261010` was migrated and seeded with explicitly synthetic data using `ops/seed_e01_recovery.py`. `ops/backup.py` created `/private/tmp/e01-recovery-20261010/backup-v2`; `ops/restore_verify.py` restored it into the new `progress_restore_e01_20261010` database and `/private/tmp/e01-recovery-20261010/restored-uploads`. Verification passed for two accepted events, one immutable original, three jobs, one graph operational record, one conversation/turn and one pending outbox record; state/event/lineage/payload content hashes matched. The restored pending outbox then delivered in one attempt to a separate loopback HTTP receiver, whose read-back matched revision 2 and 08:30 minute precision. The receiver's separate storage is outside this application-database backup. Temporary artifacts and both databases were left separate for inspection.

## Current verification — 12 October

Current working-tree checks on 2026-10-12: 233 unit tests, 124 full PostgreSQL integration tests, and 44 Playwright fixture/review-api browser tests passed. Frontend type checking, production build and frontend contract assertions passed. Native smoke parsed all six required sources and rejected malformed XML. These checks cover the graph-only source tree based on `ec9567d`; the final API/worker regression check also passed 11 tests.

The October 11 [GT10 five-entry live results](../data/review/gt10-five-entry/LIVE-RESULTS.md) record five synthetic quantity reports processed through authenticated API intake and the live `gemma4:12b` model. The fifth proposal was resolved and approved in the browser; progress, CSV export, mock-receiver read-backs and duplicate submission/approval idempotency were checked. Each of five activities has one approved quantity event. This is a bounded workflow demonstration: it does not establish quality on a full unseen evaluation, lifecycle/start-finish behavior, or duration acceptance. Delivery used the local **MOCK PMIS — prototype**, not a production connector.

The October 12 [graph smoke record](validation/graph-live-smoke-2026-10-12.json) shows a 179.396-second run using Ollama 0.40.0 and `gemma4:12b` digest `6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b`. It produced one extracted observation and one pending proposal, with zero approved events. This confirms one real-model graph path reached review; it does not measure quality or establish acceptance on unseen or lifecycle/duration cases.

The [live browser acceptance record](validation/graph-browser-live-2026-10-12.json) verifies the browser at `http://127.0.0.1:8001` submitted a synthetic report through the running API and normal graph worker, which called live Gemma and returned an agent run to `ready_for_review`. Job `80d12b86-a2fa-41a5-8971-99de3b2fe699` for project `a061ad38-0c67-4e89-8067-0a28a5593ec1` produced one pending matched 2 m proposal and zero approved events. The graph recorded eight successful steps: one extraction, one selection and no repair. Root inspected the [390 px](validation/graph-browser-ready-390.png) and [1440 px](validation/graph-browser-ready-1440.png) screenshots; both had no horizontal overflow or browser errors. The temporary reviewer was deactivated and its credentials removed; normal account access was preserved. The API and worker remain running as requested; process/log paths are recorded in `/private/tmp/time-agent-graph-runtime/processes.json`. This is end-to-end workflow acceptance for the local prototype, not unseen-quality, independent data or lifecycle/duration acceptance.

Graph recovery evidence uses `progress_recovery_graph_20261012` and restored database `progress_restore_graph_verified_20261012`, with restored uploads at `/private/tmp/graph-recovery-20261012/verified-restored-uploads`. Content hashes matched for 2 agent runs, 2 steps, 2 tool calls, 4 checkpoints (19 blobs/33 writes), 2 approved events and 1 preserved original. A restored interrupted graph resumed without re-extraction and retained one run, observation and proposal. The first restore attempt failed the approved-fragment subset check; the query was corrected and the subsequent clean restore passed. The literal subprocess kill test `test_killed_worker_resumes_from_postgres_checkpoint_without_repeating_extraction` passed: after `SIGKILL` following the persisted extract step, lease reclaim resumed the same checkpoint without repeating extraction, leaving one run, one observation, one proposal and zero progress events. Historical rollback-child checks belonged to the earlier dual-runtime snapshot. The graph-only suite now verifies that historical configuration cannot route jobs into another runtime. These are operational recovery results, not a production deployment rehearsal.

## Compact Gemma quality evidence — 12 October

The 12 October compact Gemma benchmark now has saved outputs for all 60 existing synthetic held-out cases after batches five and six were rerun. Activity choice was 44/45 (97.8%), quantity accuracy 36/36 (100%), precision across all selected activities 44/49 (89.8%), and unmatched-case safe abstention 10/15 (66.7%). Five unmatched fragments were falsely selected. This benchmark supplies the full schedule and does not complete independently reviewed, frozen-split UI-to-export acceptance.

The benchmark captures/scorer remain in the original local workspace; only documentation is published in this update. The [results report](../evaluation/RESULTS.md#gemma-4-12b-quality-evaluation--12-october-2026) and `../evaluation/results/gemma4-12b-2026-10-12/combined-after-retry/scored.json` record the fixed model digest, inputs, 12 source-locator corrections, raw captures and original crash-associated timeout. Combined ten-case request median was 206.3 seconds and p95/max 292.4 seconds. This is batch inference wall time, not UI proposal readiness. Atomic-event F1 and candidate Recall@8 are unavailable in this benchmark. Label review, calibration and release gates remain open.

The endpoint responded for the owner-requested rerun after the reported PC crash; both replacement batches completed. The earlier graph-only deployment connectivity timeout above remains historical evidence rather than the latest model availability observation.

## Remaining acceptance gates

- D04 independent event-label review/adjudication and D05 reviewed, frozen leakage-aware splits. The 2026-10-12 source-backed technical review covers 21 quality records and 16 labels and supplies separate suggestions; it does not claim human review or approval. Cambridge project 5060 is a bounded subset screen, not row-level proof for global aggregates.
- A02 calibrated thresholds from reviewed validation inputs; no fabricated threshold or confidence probability.
- E02 full unseen UI → live model → shortlist/match → reviewer acceptance → internal update → mock read-back → export evaluation, with agreed quality/latency targets and all failures included. The October 11 five-entry run is bounded workflow evidence, not this evaluation. [Proposed targets](evaluation-targets-draft.md) await agreement; they are not achieved results.
- Owner sample package remains `not_received`. Register/hash it when supplied, review mappings and calendar/timezone semantics, and repeat project-specific validation. Cambridge/GT10 and synthetic reports do not replace it.
- W-39/O-04 graph acceptance applies to this local prototype only. Freeze exact model digest/config and release artifacts, and rehearse on the intended laptop/network setup before any release claim.

E03 documentation reconciliation is implemented; its full release gate remains pending E02 and the independent data gates. Public/synthetic fixture verification must be reported separately from owner-package and live-model validation.
