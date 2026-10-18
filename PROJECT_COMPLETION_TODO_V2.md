# Project completion TODO v2 — lifecycle workflow and audited datasets

## Current acceptance — 18 October 2026

Release remains unaccepted. The six remaining workstreams are sustained provider
capacity, broader quality/fresh V20 validation, a new frozen holdout, supported
event/link and runtime confidence, concurrent browser/update/mock-delivery latency,
and final accepted-source release steps. See [current status](docs/current-status.md)
for evidence and targets. V20's quote repair passes offline replay; BM-02/BM-03
pass live component matching. The mixed rehearsal was interrupted; its latest
lifecycle-input runner is not live validated. No accepted freeze, accepted-source
restart, commit or push has occurred.

Latest verification is 455 unit and 14 prompt-pinning integration cases after the
evidence repair, followed by 73 affected unit cases after rehearsal changes. Counts
and task plans below preserve their older scope; implementation does not establish
fresh model accuracy or sustained readiness.

## Implementation inventory — 12 October 2026

Updated 12 October 2026. E01 is complete (`implemented`, `verified_fixture`); E02 capture/scoring preparation and E03 documentation/evidence are implemented, with independent unseen live and final release gates pending. L01–L06, T01–T02 and M01–M02 implementation status is recorded below. Status distinguishes implemented code, fixture/database verification and live-model verification. A01 is complete (`implemented`, `verified_fixture`); A02 calibration tooling is implemented and fixture-tested, with independently reviewed threshold evidence still pending (rechecked 10 October 2026). F01–F02 are complete (`implemented`, `verified_fixture`) with reusable report mapping and immutable PDF-page transcription. H01–H02 are complete (`implemented`, `verified_fixture`) with project-scoped event history, correction-aware blockers and precision-aware duration queries; source calendar/labour availability remains explicit.

Completed-task steps below retain the original implementation plan and may mention the former dual-worker components. Current operation and verification are governed by [release.md](docs/release.md) and the [documentation index](docs/README.md).

## Earlier model evidence — 12 October

The 12 October compact Gemma benchmark now has saved outputs for all 60 existing synthetic held-out cases after batches five and six were rerun. Activity choice was 44/45 (97.8%), quantity accuracy 36/36 (100%), precision across all selected activities 44/49 (89.8%), and unmatched-case safe abstention 10/15 (66.7%). Five unmatched fragments were falsely selected. This benchmark supplies the full schedule and does not complete independently reviewed, frozen-split UI-to-export acceptance. See [results](evaluation/RESULTS.md); E02/A02/D04/D05 remain open.

This is the current entry point for completing all eight requirements. It replaces the execution ordering in `todolist1.md` and `AGENT_COMPLETION_TODO.md`. The earlier detailed code audit and C-01–C-18 cards (historical source not included in this repository) remain supporting specifications; use this v2 document for current data decisions and task order.

## 1. Objective and first milestone

Complete the existing application, starting with quantity-free actual start/finish. Do not rewrite it.

First milestone: with a trusted report date, “Started excavation at F-01 at 08:30” produces an evidence-backed start proposal, links to the correct scheduled activity, is shown for confirmation/authorized acceptance, and automatically updates the activity's actual start. No quantity or percent is required. Finish works the same way. The result survives refresh and appears in history/export.

If no date context is available, ask for the date. If only a date is reported, retain date precision and leave the time unknown. Never substitute submission time or midnight for an unreported time.

The owner confirmed that no owner sample is expected. The prototype uses public schedules and separately reviewed synthetic reports under the authorized AI-assisted policy, with MOCK PMIS in scope. These inputs do not establish owner-specific accuracy or calendar semantics.

## 2. What an implementing agent must know

- Repository: `site-progress-agent/`. Paths in implementation cards are relative to this directory. Dataset originals are in the workspace's `../data/`.
- Stack: FastAPI, PostgreSQL/SQLAlchemy/Alembic, React/Vite, Ollama, background worker. LangGraph is the only report-processing runtime. Legacy processing, runtime selection and rollback overrides were removed; dated parity evidence below is historical.
- Lifecycle tracking now preserves endpoint date/time/precision and permits quantity-free start/finish proposals. The earlier discarded-effect audit finding is historical; model accuracy and sustained workflow acceptance remain separate gates.
- Current matching is model-led, not proof of a working lexical/hybrid retrieval pipeline. Read `agent/schedule_decision.py` and measure the actual implementation.
- Schedule imports and report uploads are different inputs. GT10's schedule XLSX must not be uploaded as a field-report spreadsheet.
- Existing UI mapping already supports area, assets, aliases, measurement basis, quantity and unit. Extend it only where needed.
- Do not change originals, silently fix source schedules, create production data, migrate the user's database, or contact dataset authors as part of this plan.
- When implementation is later authorized, use isolated test/demo data; preserve authentication, project membership, CSRF, schedule pinning, revision locks and idempotency.
- New migrations follow the actual current Alembic head. Never rewrite existing migrations or silently backfill fabricated times.
- Distinguish `planned`, `implemented`, `verified_fixture`, `verified_live`, and `independently_reviewed`. A passing fixture is not a model accuracy measurement.
- Use one task per bounded change. Record files, tests, artifacts, unresolved issues and next task in `docs/handoffs/V2-<ID>.md`.

Previous code-audit checks in this conversation: 143 unit tests passed, TypeScript passed, frontend contract assertions passed. No new application behavior was implemented by the dataset audit.

## 3. Data decisions

Read [the dataset audit](docs/dataset-audit-2026-10-09.md) and the generated profiles in `../data/schedule-audit-2026-10-09/` before normalizing data. Source counts and issue examples belong in those artifacts so agents do not rely on README claims alone.

| Source                             | Appropriate use                                                                                                                                                          | Must not be claimed                                                                                                                                                 |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cambridge JSON                     | Multi-project schedule structure, existing actual-date fields, dependency/calendar profiling, candidate matching scale, selected historical state fixtures after review. | Verified site reports paired with activities; independently validated actual-event labels; exact observed clock precision merely because a timestamp string exists. |
| GT10 input and export XLSX         | Small understandable development/demo schedule, floor/discipline matching, import reconciliation and exception handling.                                                 | Two independent projects; completed field execution; measured productivity; directly verified L5/L6 structure.                                                      |
| Existing and new synthetic reports | Explicitly authored lifecycle, clarification, ambiguity, correction and scope cases, then independent review.                                                            | Real site records or independent gold labels before review.                                                                                                         |
| Owner package, when received       | Project-specific mappings, terminology, event evidence and final domain validation.                                                                                      | Currently available, already audited, or replaced by public schedule data.                                                                                          |

Source provenance: [Cambridge record](https://www.repository.cam.ac.uk/items/6cb214a6-f52d-4846-b2de-3a2e2a34d431), [GT10 repository](https://github.com/SionRani/GT10BLDG-P6-Schedule).

Measured local inventory: Cambridge has 299 projects / 444,156 activities, with 258,352 paired actual-start/finish fields; GT10 has 140 planned activities / 176 links, with all tasks not started. Cambridge has a full WBS tree and calendars, but these are not verified field-report labels. Provisional Cambridge partitions contain 221/39/39 projects and 114,583/176,962/152,611 activities respectively; the distribution is skewed and must pass D05 before benchmark use.

### Decisions already made for this plan

1. Prioritize lifecycle support, then text conversation. Voice and forecasting are deferred.
2. Use GT10 as one development/demo family, preserving input/export provenance. Do not train on its input and test on its export or split near-identical floors randomly to claim project generalization.
3. Cambridge partitions are whole-project/group manifests, not destructive file moves. Treat generated partitions as provisional until duplicate/snapshot grouping and domain coverage are reviewed.
4. All later report paraphrases, corrections, spreadsheet/PDF renderings and synthetic conversations inherit the underlying scenario/project split.
5. Keep all ground-truth fields and later actual outcomes out of an extraction/matching prompt when those facts are the evaluation target. An immutable source archive may retain them, but model-visible schedule context must be a documented projection.
6. Use a clearly labelled mock PMIS HTTP receiver for the prototype. A production PMIS account is not necessary to satisfy the permitted mock option.
7. Default acceptance to an authorized reviewer. Supervisor confirmation alone does not grant approval permission. Owner can change the intended role policy later.
8. Do not implement automatic confidence-based approval. Calibrated confidence can prioritize or route review; deterministic validation and authorized acceptance remain required.

## 4. Sequencing and finish gates

| Order | Work                                             | Tasks    | Gate                                                                                                 |
| ----- | ------------------------------------------------ | -------- | ---------------------------------------------------------------------------------------------------- |
| 0     | Register/protect data and prepare small fixtures | D01–D05 | Audited development inputs; review statuses explicit. Do not wait for the unavailable owner package. |
| 1     | Actual start/finish vertical slice               | L01–L06 | Real accepted lifecycle changes without quantity, with precision and conflict safety.                |
| 2     | Text conversation                                | T01–T02 | Missing-essential dialogue and structured confirmation.                                              |
| 3     | Matching, planner exceptions and scope           | M01–M02 | Unmatched work resolvable; child completion cannot falsely finish parent.                            |
| 4     | Automatic integration                            | I01      | Internal commit plus automatic mock write-back/read-back.                                            |
| 5     | Confidence and audit completion                  | A01–A02 | Separate confidence estimates and reviewed threshold evidence.                                       |
| 6     | Flexible field-report ingestion                  | F01–F02 | Text, differently structured discipline XLSX, diary/PDF/transcription.                               |
| 7     | Execution history and queries                    | H01–H02 | Required export fields; honest duration and blocker queries.                                         |
| 8     | Recovery and independent validation              | E01–E03 | Unseen reviewed real flow, measured accuracy/latency, reproducible release evidence.                 |

D04 independent adjudication may continue alongside implementation; it blocks final gold-data claims. L01–L06 can start with clearly labelled developer fixtures. Audit metadata should be captured from L01 onward; A01 completes coverage rather than adding provenance as an afterthought.

## 5. Data preparation tasks

### Demo readiness — accepted 2026-10-10

The current scope is a GT10 development demo using public schedule inputs and explicitly synthetic reports. The checked items below record demo preparation completion. The original D01–D05 evaluation acceptance checkboxes remain separate and pending; independent review and frozen validation data are not required to show this demo.

- [X] D01 — Demo ready: registered sources, verified hashes and documented GT10 development snapshot.
- [X] D02 — GT10 demo ready: adapters and raw-value sidecar verified; staged import, explicit activation and task retrieval pass the isolated fixture flow. Cambridge staged import is outside the accepted demo scope and remains pending.
- [X] D03 — Demo ready with flagged issues: quality queue prepared; raw sources retained and no corrections claimed approved. Dependency-duration assertions based on unresolved logic/lag issues remain outside the demo scope.
- [X] D04 — Demo ready: 16 synthetic development reports and proposed labels available, visibly unreviewed.
- [X] D05 — Demo ready: structural leakage checks pass and GT10 cases remain in development; splits remain provisional for evaluation.

Evidence: [completion audit](docs/d01-d05-completion-audit-2026-10-10.md). Demo acceptance does not satisfy A02 calibration inputs or establish measured model accuracy.

### [ ] D01 — Register sources and choose reviewed source versions

Status: **demo_ready; evaluation_pending**. Registry/hash verification passed on 2026-10-10 for all three registered files. Development source selection is documented; reviewed source-version acceptance and exact license retention remain pending. See [completion audit](docs/d01-d05-completion-audit-2026-10-10.md).

Read: dataset audit, `data/references/`, `data/review/`, original READMEs and known-issue file.

Files to add later: `data/references/schedule-sources.json`, `docs/data-decisions.md`; private/large originals stay outside git.

Steps:

1. Record each source URL, source-file SHA-256, bytes, local path, retrieval/audit date, license status and intended use. Retain attribution and license text when packaging permitted derivatives.
2. Cambridge record states CC BY 4.0. GitHub identifies MIT, but the local GT10 package does not contain a license file; verify and retain the exact repository license before distributing a derivative.
3. Select the GT10 P6 export as the initial snapshot for development, subject to a reviewed correction overlay. Preserve the input workbook separately as reconciliation evidence.
4. Explicitly list unresolved GT10 conflicts: F8 activity named F9, FF versus FS, F10 plaster lag, day/hour lag ambiguity, input/export date differences, WBS differences and missing native XER.
5. Record owner-package status as `not_expected`. If future owner data is explicitly supplied, register/hash it and separately review project-specific coverage.

Done when: every chosen fixture traces to a source/hash and source-version decision; no public schedule is labelled owner data or paired-report gold data.

### [ ] D02 — Create lossless adapters for these two schedule formats

Status: **demo_ready_gt10; full_adapter_acceptance_pending**. Adapters and GT10 sidecar/stage/activate/retrieve verified (4 focused tests passed on 2026-10-10). Cambridge staged persistence/retrieval and broader heterogeneous-field validation remain pending. See [completion audit](docs/d01-d05-completion-audit-2026-10-10.md).

Dependencies: D01. Existing files: `backend/app/ingest/schedules.py`, `ingest/native_schedule/{dispatch,normalise,storage}.py`, `schemas/native_schedule.py`.

Proposed additions: `ingest/schedule_datasets/cambridge.py`, `gt10_xlsx.py`, fixture tests. These are **schedule adapters**, separate from report column mapping in F01.

Steps:

1. Cambridge: stream by project; preserve composite `(source, project_id, task_id)` identity, raw actual/planned values, WBS identifiers/descriptions, predecessor edges, calendar links and source JSON locator.
2. Check actual root keys and heterogeneous values. Missing relationships use the literal string `"null"` in 39,798 rows; calendars contain multiple interval/exception shapes. Use explicit validation and recoverable issue records.
3. GT10: parse both technical headers and display-header row correctly; import only data rows from TASK/TASKPRED. Preserve lag header/unit evidence. Do not treat the resource directory as assigned labour.
4. Preserve the raw timestamp string and its source precision/basis. A source `00:00` value is not automatically known to be a field-observed midnight; do not erase it or claim greater certainty.
5. Leave unverified discipline, area, asset, work type, WBS level and timezone as unknown or proposed mappings for review. Names/floors may suggest mappings; they are not independent gold labels.
6. Preserve calendar metadata; do not assume all calendars are 8-hour/6-day. Keep unsupported calendars readable and marked unavailable for working-duration calculations.
7. Do not route timestamps through the existing date-only CSV intermediate without retaining lossless sidecar metadata and the precision schema introduced by L01.
8. Reject malformed/unresolvable links with clear issues; never silently drop rows, add fake quantities, convert planned dates into actuals, or write directly into an active schedule.

Tests/done: compare counts, IDs, edges and raw timestamps to audit hashes/profiles; import into a staged test snapshot, review mappings, activate explicitly, and retrieve the intended tasks. Zero fabricated quantity/actual/time/discipline facts.

### [ ] D03 — Review quality flags and produce an approved correction overlay

Status: **demo_ready; evaluation_pending**. Review preparation implemented; independent planner approval pending. The queue contains 21 records and the correction overlay is empty. See [completion audit](docs/d01-d05-completion-audit-2026-10-10.md).

Dependencies: D01. Proposed artifacts: `data/review/schedule-quality-review.jsonl`, `schedule-overrides.jsonl`.

Steps:

1. For each issue record source/project/task or sheet/cell, old value, proposed value, evidence, decision, reviewer/date and reason. Preserve raw files.
2. GT10: verify `SUP-F8-06` against its input and adjacent floor activities; do not let an automatic string match choose F9 from the wrong name.
3. Have a planner resolve logic and lag units before calculating dependency-based durations or generating synthetic “correct” assertions from them. Applying an override creates a derived version/hash.
4. Cambridge: triage actual-date chronology/status conflicts, invalid derived/weather fields, redacted identifiers, missing references and calendar anomalies using the audit output. Quarantine suspect fields by purpose, not necessarily the entire project.
5. Do not reconstruct anonymized names, equate a GMM topic with verified discipline, or call WBS leaves L5/L6 without a source-backed level definition.

Done when: the selected demo/evaluation subset has explicit reviewed inclusions/exclusions and corrections. Unreviewed rows remain labelled unreviewed; agent review alone is not independent adjudication.

### [ ] D04 — Author synthetic report/event pairs and obtain independent review

Status: **development reviewed under authorized AI-assisted policy; fresh V20 evaluation pending**. The 16 development cases have separate AI adjudication; independent human review has not occurred. Earlier frozen synthetic validation and holdout sets are consumed. See [split status](docs/data-splits.md) and [current status](docs/current-status.md).

Dependencies: D01 and selected D03 decisions. Existing: `data/synthetic/`, `data/review/W-03-review-instructions.md`, `w03-expanded-review.csv`.

Steps:

1. Create versioned report/conversation fixtures linked to the chosen schedule activities, with separate ground-truth labels. Mark the reports synthetic even when their target schedule is public/historical.
2. Use distinct scenario families: quantity-free start/finish, date-only, ambiguous time/date, missing location, future/negated work, multiple tasks, duplicates, corrections, reordered reports, impossible chronology, subactivity completion, unknown activity and blockers.
3. For the user's F-01 example, provide an explicit fictional fixture or reviewed asset mapping. Do not assert the GT10 foundation excavation task has an F-01 asset tag if the source does not say so.
4. Labels include event kind, exact activity or abstention, scope, date/time/precision/timezone basis, missing essentials, evidence spans, expected state changes and correction relationships.
5. Record the independent reviewer decision for every evaluation label. Obtain a second review for temporal/scope/conflict/ambiguous cases and the existing sampled second-review policy; adjudicate disagreements without overwriting proposed labels.
6. Keep reviewer IDs/dates and final label hashes. AI-authored and AI-reviewed examples remain separately labelled until independent review exists.

Done when: developer fixtures exist, and final evaluation labels have real review/adjudication records. Do not block developer fixtures on the missing owner package; keep owner-specific validation open.

### [ ] D05 — Review and freeze leakage-aware splits

Status: **fresh V20 freeze/evaluation pending**. Cambridge grouping remains provisional and excluded. Separate synthetic prototype splits were frozen and evaluated; both V19 splits are consumed. A new holdout is required. See [split status](docs/data-splits.md).

Dependencies: audited split proposal, D03/D04 for final freeze. Artifact: `../data/schedule-audit-2026-10-09/provisional-splits.json`.

Steps:

1. Inspect proposed project groups, near-duplicate relationships and cross-project dependencies. Review physical-project/snapshot identity beyond automatic ID/name heuristics.
2. Keep all GT10 workbooks and repeated floors within the same development family. They are not independent heldout projects.
3. Review Cambridge partition coverage by project type, size, actual-date completeness and ambiguity. The current proposal has a 221-project connected development group, including 175 Clean Water Networks projects, and disproportionately many activity rows in validation/heldout. Treat this as a limitation to resolve, not a balanced 70/15/15 result. Large projects can dominate activity-weighted metrics even with balanced project counts.
4. Keep all reports, paraphrases, corrections and alternate formats for a scenario within one partition. Never randomly split individual linked events.
5. Freeze validation for thresholds and reserve fresh heldout report scenarios, unseen by prompt tuning. Structural audit of the schedules is not proof that future report labels are unseen.
6. Save exact source/group/split/label hashes. Recheck disjointness and cross-partition near duplicates whenever data changes. A changed split invalidates comparisons unless rerun consistently.

Done when: reviewed split manifest and leakage checks exist. Provisional manifests alone do not establish final independent validation.

## 6. Priority 1 — actual start/finish

### [x] L01 — Define lifecycle contracts and migrate storage without losing precision

Status: `implemented`, `verified_fixture`, and isolated PostgreSQL migration/round-trip verified. Legacy quantity/date-only rows were preserved across 0009→0010. Migration was not applied to the user database. See [handoff](docs/handoffs/V2-L01-L03.md).

Dependencies: none beyond the existing code audit. Files: `schemas/common.py`, `schemas/observation.py`, **new** `schemas/events.py`, `db/models.py`, new migration, `docs/api-contract.json`.

Steps:

1. Add explicit start/finish effect kinds and scope. Keep existing quantity/percent observations compatible.
2. Store local date, optional local time, precision (`date`, `minute`, `second`), timezone/basis, raw source expression, evidence and optional normalized instant. Date-only has no invented instant.
3. Distinguish endpoint time from submission/approval timestamps. Preserve imported raw actuals and uncertainty about their clock semantics.
4. Persist current execution state separately from immutable imported schedule values. Keep source version, event/proposal IDs and actor/history references.
5. Choose separate atomic observations for start and finish to respect the existing one-original-event-per-observation unique index, or deliberately migrate that constraint with tests.
6. Add migration compatibility tests using old quantity events and date-only actuals. Use the current migration head; never replace existing migrations.

Done when: date-only and timed endpoints survive schema/database/API round trips distinctly; legacy records are unchanged.

### [x] L02 — Extract lifecycle observations and build effects in both worker modes

Status: `implemented`, `verified_fixture`, and `verified_live` on two synthetic assertions with the user-specified `gemma4:12b`: timed start and date-only finish both produced evidence-backed, quantity-free effects. The model-added `Z` suffix on local clock time is removed only when exact source evidence proves an unzoned time, with a warning. Old observation payloads parse safely; old persisted graph checkpoints were not replayed. See [handoff](docs/handoffs/V2-L01-L03.md).

Dependencies: L01. Files: `prompts/extraction_v1.py`, `llm/extract.py`, `jobs/pipeline.py:_effects`, `agent/runtime.py:_effects`, `agent/tools.py`; **new** shared `progress/effects.py`.

Steps:

1. Extract explicit started/finished assertions separately from plans, negations and descriptions of work. “Excavated F-01” is not enough to infer a precise start or finish.
2. Keep quantity optional; ensure the number in F-01 is never interpreted as installed quantity.
3. Resolve dates only from explicit text or trusted stored context. Ask for missing essentials later through T01; mark unresolved fields now.
4. Validate evidence per endpoint. Split multi-event statements while retaining shared evidence and distinct event identities.
5. Replace duplicated effect construction with one typed builder used by legacy and graph, including persistence validation. Version the changed prompt/config and handle old checkpoints safely.

Done when: both paths produce equivalent quantity-free lifecycle proposals in tests; a live extraction check is recorded separately from injected fixtures.

### [x] L03 — Build a deterministic lifecycle reducer

Status: `implemented`, `verified_fixture` for permutation, correction, duplicate, precision, timezone and temporal cases. Reducer is now wired to approval by L04. See [handoff](docs/handoffs/V2-L01-L03.md).

Dependencies: L01. New: `progress/lifecycle.py`, `tests/unit/test_lifecycle_ledger.py`. Existing quantity reducer: `progress/ledger.py`.

Steps:

1. Recompute actual start/finish/status from baseline actuals and active accepted lifecycle events, independently of numeric progress.
2. Handle exact retries, suspected semantic duplicates, supersession, corrections and out-of-order arrival. Do not choose arbitrary earliest/latest values when two reports disagree about the same endpoint.
3. Allow recorded finish with missing start and unknown duration. Reject known finish-before-start conflicts pending review; do not swap endpoints.
4. For partial/date precision, use uncertainty-aware comparisons. Same-day date-only plus timed endpoint cannot establish exact elapsed hours.
5. Whole-activity finish does not manufacture quantity or physical percent. Subactivity finish never automatically completes the parent.

Done when: input-order permutations produce the same supported state; corrections recompute it; all temporal/conflict cases in section 14 pass.

### [x] L04 — Accept lifecycle events through the existing transaction boundary

Status: `implemented`, `verified_fixture` in isolated PostgreSQL. See [lifecycle validation](docs/validation/lifecycle-flow.md).

Dependencies: L02/L03. Files: `api/endpoints/review.py`, **new** `progress/acceptance.py` if extracting shared logic, database models.

Steps:

1. Replace unconditional quantity/percent checks in `_effects()` and `approve()` with effect-specific requirements. Start/finish acceptance must work even when numeric measurement basis is unsupported.
2. Validate target project/version/activity/scope, evidence, endpoint, warnings and correction references on the server.
3. Keep membership/role/CSRF, proposal/activity revision checks, locks and idempotency. Recheck stale schedule activation.
4. Atomically append the event, recompute state, increment revision and record full before/after decision provenance. Roll back every write if validation fails.
5. Add explicit correction/retraction flow for accepted events; `_revise()` currently only revises pending proposals. Preserve prior accepted evidence and reasons.

Done when: no-quantity start/finish is accepted once under concurrent/retried requests; invalid chronology/cross-project/stale targets cause no state mutation.

### [x] L05 — Update review, schedule display and immediate export

Status: `implemented`, `verified_live_smoke` for accepted start/finish, refresh and export; correction/retraction transaction paths verified in PostgreSQL. See [lifecycle validation](docs/validation/lifecycle-flow.md).

Dependencies: L04. Files: `frontend/src/main.tsx` (`Review`, `Progress`, shared types), review/progress endpoints.

Steps:

1. Show lifecycle type, target/scope, old/new values, precision/timezone, evidence and blockers before acceptance.
2. Remove unconditional quantity/unit/kind UI blockers for lifecycle proposals; use effect-specific server validation.
3. Allow evidenced date/time corrections, preserving blank time. Changed values require saved revision and reason.
4. Show actual start/finish/status after acceptance and refresh; keep physical percentage separate.
5. Include lifecycle event values and precision in export immediately; H01 later completes the full history schema.

Done when: user can accept start/finish without quantity in the UI, refresh, and see consistent database/API/export state.

### [x] L06 — Demonstrate the first real lifecycle flow

Status: `implemented`, `verified_live_smoke`. Start, date-only finish, duplicate, refresh, export and conflicting-start HTTP 422 rejection passed with a real model on a fresh isolated PostgreSQL database. The accepted revision and event count stayed unchanged after rejection. See [lifecycle validation](docs/validation/lifecycle-flow.md).

Dependencies: L01–L05 and a clearly labelled development schedule/report fixture.

Files: **new** `frontend/tests/e2e/lifecycle-live.spec.ts`, `docs/validation/lifecycle-flow.md`.

Steps: real login → staged/activated schedule → report → real model/worker → matching → review/acceptance → state refresh → export. Run start, finish, date-only, duplicate and rejected-conflict examples. Record IDs, model/prompt versions, timestamps and before/after values. Do not intercept APIs in this live suite.

Done when: quantity-free actual dates are visibly updated end to end. This is a smoke milestone, not the final unseen accuracy benchmark.

## 7. Priority 2 — conversational time agent

### [x] T01 — Persist conversation state and ask only missing essentials

Status: complete; isolated PostgreSQL, HTTP recovery/review gating, and live-model browser flow verified. See [handoff](docs/handoffs/V2-T01-T02.md).

Dependencies: L02/L04. New: `conversation/service.py`, `schemas/conversation.py`, `api/endpoints/conversations.py`, tables/migration. Existing: auth dependencies and router registration in `main.py`.

Steps:

1. Persist immutable turns, draft revision, project/schedule context, pending questions, confirmation and review status.
2. Reuse extraction, matching and acceptance services; do not let the conversation model write schedule state.
3. Ask for date when unknown, location when identity is ambiguous, or what finished when scope is unclear. Never demand time for a date-only statement or quantity for a lifecycle event.
4. Store user answers as evidence. Edits after confirmation invalidate it. Support several events with per-event clarification/confirmation.
5. Distinguish supervisor submission/confirmation from reviewer acceptance. Enforce membership and permissions on every endpoint; do not grant reviewer rights silently.
6. Recover drafts after refresh/session expiry, reject stale confirmation, handle model retry/outage and prevent duplicate submission.

Done when: a minimal two-turn example becomes a confirmable structured event, with no extraneous questions and no unauthorized updates.

### [x] T02 — Build text chat and structured confirmation cards

Status: complete; structured date/time/scope edits and the multi-event pending-review browser flow verified. See [handoff](docs/handoffs/V2-T01-T02.md).

Dependencies: T01. New component: `frontend/src/components/TimeChat.tsx`; existing navigation/styles/API types.

Steps: show persisted conversation, one essential question at a time, structured event/activity/precision/evidence, edit/confirm/cancel controls and accurate pending-review/accepted status. Handle keyboard/mobile, multiple events and recoverable errors without losing unsent text.

Done when: supervisors can log work entirely through text and confirmation cards. Voice remains deferred.

## 8. Priority 3 — matching and exception handling

### [x] M01 — Improve terminology/context matching and planner resolution

Status: `implemented`, `verified_fixture`. Pinned full-schedule planner search, evidenced manual revision, explicit resolution outcomes, revisioned project aliases, GT10 floor-conflict safety, and scale traversal/call measurements are complete. Semantic live-model recall and independent label validation remain E02/D04 gates. See [handoff](docs/handoffs/V2-M01.md).

Dependencies: L04, D03/D04 examples. Files: `agent/schedule_decision.py`, `schemas/matching.py`, review/schedule endpoints and UI.

Steps:

1. Evaluate terminology, IDs, aliases, locations, disciplines and WBS together. Include GT10's repeated floor tasks and F8/F9 name conflict as ambiguity/quality tests.
2. Version reviewer-approved project aliases. Do not globally normalize different asset identifiers into one or infer reliable locations from Cambridge redactions.
3. Add planner search across eligible activities of the pinned schedule, beyond the model shortlist. Permit evidenced manual selection with a reason; retain original candidates and explanation.
4. Provide explicit unmatched outcomes: resolve to existing activity, request clarification, reject, or flag missing schedule scope. Never silently add an activity to an immutable schedule.
5. Enforce server-side project/version/leaf/scope eligibility for manual selections. Keep quantity-basis support separate from activity identity.
6. Measure shortlist recall and model calls at Cambridge schedule sizes; introduce bounded retrieval/timeout handling only with measured recall checks.

Done when: planner resolves an unmatched report without editing UUIDs; ambiguous tasks remain reviewable and reviewed variants link correctly.

### [x] M02 — Represent subactivity-to-parent mapping explicitly

Status: `implemented`, `verified_fixture`. Explicit named child/eligible scheduled parent mapping, scope evidence validation, no parent roll-up or endpoint-reference assignment, and history/export fields verified in isolated PostgreSQL and mobile/desktop browser fixtures. See [handoff](docs/handoffs/V2-M02.md).

Dependencies: L03/M01. Files: event/matching schemas, persistence, lifecycle reducer and review UI.

Steps: record subactivity identity, scheduled parent and evidence; distinguish executable parent from WBS summary. Keep subactivity start/finish scoped unless an explicit reviewed rule authorizes parent effect. Whole-activity completion requires explicit evidence or a separately approved complete-child aggregation rule. Prototype default is no inferred roll-up.

Done when: completing one subtask does not finish the whole scheduled activity, and both scope and parent appear in history/export.

## 9. Priority 4 — automatic schedule integration

### [x] I01 — Add transaction outbox and a labelled mock PMIS connector

Status: `implemented`, `verified_fixture`. Transactional accepted-state snapshots, ordered automatic HTTP delivery, persistent labelled mock receiver/read-back, retry/correction safety, and project-scoped delivery API/UI verified. See [handoff](docs/handoffs/V2-I01.md).

Dependencies: L04/L05. New: `integrations/{base,outbox,mock_pmis}.py`, outbox migration, `ops/run_connector.py`, `ops/mock_pmis_server.py`, delivery-status API/UI.

Steps:

1. Add an outbox record in the same transaction as accepted event/state. Deliver after commit through a worker.
2. Define external project/activity mapping, source schedule version, current state revision, precision-preserving payload and idempotency key.
3. Use a separate local HTTP receiver with persistent activity state and read-back endpoint. Label it **MOCK PMIS — prototype** throughout the demo.
4. Record attempt/receipt/error timestamps. Retry transient failures; surface permanent mapping/version errors. External failure does not erase internal acceptance.
5. Prevent timeout/retry duplicates and late old messages overwriting newer corrections through ordered/revision-checked delivery.
6. Preserve date-only values; if a future real tool requires a time, surface the incompatibility rather than fabricate midnight.

Done when: accepting a start/finish automatically changes internal state and the receiver's read-back state; retry/correction tests pass. CSV and logs alone do not satisfy this task.

## 10. Priority 5 — confidence and auditability

### [x] A01 — Complete extraction/link confidence and decision history

Status: `implemented`, `verified_fixture`. Separate unavailable confidence estimates, immutable original provenance, pinned-source/model metadata and authorized report-job decision history are recorded and visible in review. See [handoff](docs/handoffs/V2-A01.md).

Dependencies: L02/L04/M01. Files: schemas/models, pipeline/agent metadata, review/history APIs/UI; optional `confidence/` service.

Steps: store extraction and linking confidence separately with method/version and validation status. Retain field-level issues, evidence quote/locator, source/report, pinned schedule, model/prompt/config, candidates and decision reasons. Preserve originals plus every revise/reject/accept/correct/retract actor/time and before/after effect. A quoted string existing in source does not prove extraction correctness.

Done when: every proposed update has traceable confidence/provenance, and unavailable/unvalidated scores are clearly identified rather than fabricated probabilities.

### [ ] A02 — Calibrate thresholds on independently reviewed validation cases

Status: tooling `implemented`, `verified_fixture`; **reviewed threshold evidence pending**. Reproducible calibration rejects unreviewed/unfrozen/leaking inputs; no thresholds are fabricated. Authorized AI-assisted labels exist, but event/link thresholds lack eligible support and runtime confidence is unavailable; this gate remains open. See [handoff](docs/handoffs/V2-A02.md), [input contract](docs/confidence-calibration.md), and [pending artifact](evaluation/results/calibration-v1-pending.json).

Dependencies: A01/D04/D05. Files: **new** `evaluation/calibrate.py`, versioned calibration artifacts, evaluation metrics.

Steps: freeze validation labels; assess field/event/link errors by confidence band; choose thresholds using reviewed precision/coverage tradeoffs; record counts, hashes and limitations. Ambiguous/low-confidence/conflicting cases require review. Keep holdout untouched and retain authorized acceptance for all updates.

Done when: threshold choices have reproducible reviewed-data evidence. Agent-generated scores alone do not pass.

## 11. Priority 6 — flexible field-report ingestion

### [x] F01 — Add reusable column mapping for discipline report XLSX

Status: `implemented`, `verified_fixture`. Two differently structured synthetic discipline report workbooks, quantity-free acceptance, saved mapping reuse, cell/header provenance and visible row validation verified. See [handoff](docs/handoffs/V2-F01.md). Live-model accuracy and independent validation remain E02/D04 gates.

Dependencies: L01/L02. Files: `ingest/reports.py`, report API and intake UI; new mapping service/schema/table.

Steps: preview sheets/header rows; map different column names to canonical fields; make quantity optional for lifecycle reports; support explicit file context; persist confirmed mappings with project/template/header signature and revision. Preserve original headers, cells, sheet/row/cell locators and mapping evidence. Handle Excel dates/times and ambiguous date formats without guessing; show row errors without silently dropping rows.

Done when: two actual **report-shaped** discipline workbooks with different headers and a quantity-free lifecycle row can be uploaded, mapped and processed; a second file reuses the saved mapping. GT10 schedule XLSX alone does not meet this requirement.

### [x] F02 — Demonstrate diary/PDF and scan transcription

Status: `implemented`, `verified_fixture`. Text diary PDF and image-only scan plus attributed immutable transcription verified through quantity-free reviewer acceptance with page provenance. Original/transcription UI verified at mobile/desktop sizes. See [handoff](docs/handoffs/V2-F02.md). Application database migration remains a deployment step; only isolated test data was migrated.

Dependencies: L02/A01. Files: report parser/API/UI, new transcription model if required, sanitized fixtures.

Steps: ingest a text diary/PDF with page locators; attach explicit transcription to an immutable scan/page with transcriber/time; show original and transcription together. Use recoverable needs-transcription state for unreadable PDFs. OCR is optional and must preserve machine-text quality/review status. GT10 Gantt PDF is a schedule visualization, not a daily diary.

Done when: diary/PDF and scan-plus-transcription produce evidence-backed proposals through acceptance, with source-page provenance intact.

## 12. Priority 7 — queryable execution history

### [x] H01 — Complete export and project-scoped history queries

Status: `implemented`, `verified_fixture`. Immutable event/current-state separation, CSV/JSON field coverage, project-authorized filters/pagination, quantity-free blocker acceptance/corrections and recurring-cause evidence queries verified. Mobile/desktop history UI verified. See [handoff](docs/handoffs/V2-H01.md) and [API contract notes](docs/execution-history.md).

Dependencies: L04/M02/A01. Files: `api/endpoints/progress.py`, new history endpoints/service and history UI.

Steps:

1. Export discipline/work type, internal/external activity IDs, WBS, scope/parent, event kind, start/finish/precision, quantity/unit, blockers, evidence/locator, confidence, source/version/model metadata and corrections.
2. Distinguish event-time accepted values from latest activity state. Preserve superseded/retracted events with active status; offer active-only filtering separately.
3. Add project-authorized pagination/filters by activity, discipline, work type, date, blocker and correction status. Retain CSV formula-injection protection; JSON can carry nested evidence.
4. Store blocker events even when no quantity/lifecycle update is made. Use reviewed categories and deduplicate corrections when aggregating recurring causes.

Done when: a user can export all requested fields and query recurring blockers with links to evidence; historic rows cannot be mistaken for current-state snapshots.

### [x] H02 — Distinguish elapsed, calendar-working and labour duration

Status: `implemented`, `verified_fixture`. Actual-duration API/UI distinguish precision-bounded timezone-aware elapsed time, uncertain date spans and unavailable calendar/labour inputs. Supported explicit reviewed/versioned calendar fixtures include shifts/breaks/holidays; no Cambridge/GT10 calendar or labour facts are inferred. D03 source-calendar review remains a data gate, not a claimed completed review. See [handoff](docs/handoffs/V2-H02.md).

Dependencies: H01, L01/L03, reviewed calendar subset from D03.

Steps:

1. Timed supported endpoints permit elapsed duration. Date-only/partial endpoints return explicit date span/uncertainty, not precise hours.
2. Cambridge provides calendar data, but interval/exception semantics and timezone must be validated first. Implement only reviewed supported shapes and return unavailable for unsupported/missing inputs.
3. GT10 supplies a calendar name without a complete local calendar definition. Do not create a 6-day/8-hour calendar merely from that name.
4. Working duration is intersection with a versioned calendar, including breaks/holidays/shifts. It is not measured crew labour or proof of continuous productive work.
5. Metres per crew-hour requires quantity, compatible scope, measured labour/crew-hour data and allocation rules. Calendar hours, start/finish, resource names, planned rates and at-completion estimates cannot substitute.

Done when: actual-duration queries by work type label their basis and unavailable inputs; no unsupported crew-hour productivity is displayed.

## 13. Priority 8 — validation and recovery

### [x] E01 — Add audited reanalysis and regression/recovery coverage

Status: `implemented`, `verified_fixture` (10 October 2026). Audited child runs, reviewer/CSRF controls, base submission idempotency, cross-run acceptance safety, legacy/graph date-only and timed lifecycle parity, lease/concurrency/stale-schedule regressions and content-verified separate-database restore pass. A restored pending outbox delivered and read back with minute precision intact. Current processing is LangGraph-only; the former default and parity evidence are historical. See [handoff](docs/handoffs/V2-E01.md) and [fresh verification](docs/validation/e01-e03-verification-2026-10-10.json). The recorded graph-only deployment migrated the local application database through `0015_schedule_source_metadata`; deployment for another instance still requires its own backup and migration.

Dependencies: lifecycle services and provenance. Files: reports/jobs service/API, agent runtime/worker, job UI, backup/restore scripts/tests.

Steps: explicit reanalysis creates a new linked run with actor/reason/config, while normal duplicate submission remains idempotent. Preserve old decisions and block repeat application of accepted work. Verify legacy/graph lifecycle parity, crashes/leases, concurrent approvals, stale schedule activation, permissions and restore of new event/conversation/outbox records. The old dual-runtime rollout is superseded by the graph-only runtime; retain the recovery and authorization gates.

Done when: reanalysis and restart cannot overwrite evidence or duplicate updates; recovery results are documented.

### [ ] E02 — Capture real unseen UI-to-export evaluation

Status: capture persistence/conversion and offline metric preparation `implemented`, `verified_fixture`; **unseen live acceptance pending**. Predictions reject label/self-reported-correctness leakage; scoring covers case-scoped event attributes, endpoint precision, link/candidate metrics, initial/final review state, failures, scope, strata, project weighting and observed timing. The capture utility stores operator-supplied observations; it does not automate or attest the real flow. D04 independent labels, D05 frozen splits, agreed targets and authentic live UI-to-export artifacts remain missing. No E02 acceptance target is achieved; exploratory compact Gemma scores and batch latency are recorded in [evaluation/RESULTS.md](evaluation/RESULTS.md). See [handoff](docs/handoffs/V2-E02.md) and [targets draft awaiting agreement](docs/evaluation-targets-draft.md). This task cannot be checked complete on fixture evidence.

Dependencies: D04/D05, all required workflow tasks, live model availability. Files: `evaluation/{run,metrics}.py`, new `evaluation/capture_live.py`, separate live browser suite, results directory.

Steps:

1. Freeze model digest, prompt/config, thresholds and reviewed splits. Capture predictions without accessing expected labels; score only after predictions/artifacts are saved.
2. Run real UI → model → actual shortlist/match → confirmation/review → acceptance → internal update → connector → export. No route interception or injected model in this live suite.
3. Capture candidate IDs and independently align atomic events in the scorer. Fix missing atomic-event/candidate fields from the old evaluation; never supply gold answers or self-reported correctness to the prediction stage.
4. Measure event extraction P/R/F1; endpoint date/time/precision accuracy; candidate recall; selected-link precision/coverage; ambiguity/unmatched/scope handling; initial model vs final reviewer-corrected state separately.
5. Instrument submission, model stages, proposal-ready, confirmation/acceptance, internal commit and external acknowledgement. Report p50/p95/max/counts for total submission-to-update, acceptance-to-update and external delivery; separate human waiting and retries.
6. Report denominators, errors, failures, abstentions, review burden, format/discipline strata and project-weighted as well as activity-weighted results where appropriate.
7. Agree quantitative quality/latency targets before looking at heldout outcomes. Do not invent achieved accuracy, omit failures, or tune on heldout and call the rerun unseen.

Done when: unseen independently reviewed examples have saved real-flow results and assessed targets. The owner-authorized AI-assisted review policy is permitted for this prototype and must be labelled honestly; passing all other targets remains required.

### [ ] E03 — Reconcile release documentation and owner-package follow-up

Status: documentation reconciliation and reproducible fixture release evidence `implemented`, `verified_fixture`; **full release acceptance pending E02/D04/D05/A02**. README, release record, runbook and task board now describe the current behavior and limitations. The historical 12 October graph-only checks were 233 unit, 124 PostgreSQL integration, 44 browser fixture tests and 11 final API/worker regressions; type/build/contracts, required native imports and backup/restore pass. Exact base commit, dirty-tree source hashes, runtime/dependency identifiers and mock label are recorded. Owner package is `not_expected` and is not a prototype prerequisite; owner-specific validation is outside current acceptance. No immutable release commit or independent/live release is claimed. See [handoff](docs/handoffs/V2-E03.md) and [release record](docs/release.md).

- [X] Reconcile current docs and record fresh fixture/recovery evidence.
- [ ] Complete independently reviewed unseen live validation and freeze release identity.
- Owner package is `not_expected`; future project-specific validation is conditional, outside current prototype gates.

Dependencies: required gates above. Files: README, `docs/release.md`, task boards, runbook and handoffs.

Steps: record exact commit, dependencies, model/config, fresh test counts, limits, mock-connector label and data provenance. Run appropriate unit, isolated integration, native import, build/type, browser and backup/restore checks. Register the owner's sample package when available and repeat project-specific review/validation; report public/synthetic prototype completion separately from owner-package validation.

Done when: documentation describes tested behavior accurately and does not conceal missing owner data, label review or live-flow evidence.

## 14. Mandatory acceptance examples

The detailed 34-case lifecycle matrix (historical source not included in this repository) remains applicable. Add these dataset-specific cases to it:

| Case                                                          | Expected result                                                                |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Timed start, trusted date, no quantity                        | Correct actual start with minute precision after acceptance.                   |
| Date-only finish                                              | Date retained; no invented midnight or elapsed hours.                          |
| Missing date/location                                         | Ask only the relevant missing essential.                                       |
| Plan or negated finish                                        | No actual event applied.                                                       |
| Finish arrives before start report                            | Correct final chronology independent of arrival order.                         |
| Known finish before established start                         | Conflict reviewed; no impossible state committed.                              |
| Correction/retraction/retry/concurrent acceptance             | Immutable lineage and one effective update; recomputed state.                  |
| Start/finish in one sentence                                  | Distinct atomic events without unique-index collision.                         |
| Unmatched report resolved outside shortlist                   | Audited planner selection in pinned eligible schedule.                         |
| Subtask finish                                                | Parent not silently completed.                                                 |
| GT10`SUP-F8-06` named F9                                    | Data conflict surfaced; no confident silent wrong-floor assignment.            |
| GT10 input/export used in different splits                    | Leakage check rejects the partition.                                           |
| GT10 start/end dates on “Not Started” task                  | Treated as planned/scheduled dates, never actual-event truth.                  |
| GT10`lag_hr_cnt=7` versus prose “7d”                      | Unit ambiguity preserved for review; no unapproved conversion.                 |
| Cambridge string`"null"` relationships                      | Parsed as empty under the documented source rule, with provenance.             |
| Cambridge raw midnight actual timestamp                       | Raw retained; clock-observation certainty not invented.                        |
| Cambridge missing/contradictory actuals or status metadata    | Quality flags retained; no auto-repaired gold label.                           |
| Cambridge invalid weather/derived features                    | Excluded from operational event truth and model-visible target leakage.        |
| Calendar with unsupported exception shape                     | Working duration unavailable with reason; elapsed basis remains separate.      |
| No labour hours in either source                              | Crew-hour productivity unavailable.                                            |
| Outbox timeout after receiver success; older correction retry | One destination effect and newest revision retained.                           |
| XLSX report mapping reuse and scan transcription              | Evidence remains tied to original cell/page and mapping/transcription version. |

Hard safety gates: no invented accepted time, no lifecycle quantity requirement, no cross-project write, no duplicate application, no unresolved impossible chronology, no unintended parent completion. These are required tests, not claimed current results.

## 15. What remains for the owner to decide later

- Identify an independent planning/construction reviewer and adjudicator for synthetic event labels and disputed source values.
- Decide whether authorized supervisors may also accept schedule updates, or must pass them to a planner/reviewer. Existing reviewer acceptance is the planning default.
- Confirm timezone/working-calendar assumptions for the selected demo and future owner project. Cambridge's UK context is not proof of an explicit source timezone; GT10's location/timezone is not established by this package.
- Agree accuracy/latency targets before freezing the final benchmark.
- Provide the owner package when it arrives. Its absence does not prevent the lifecycle prototype, but must remain visible in final claims.

This document alone does not authorize implementation. The owner authorized E01–E03 execution on 10 October 2026; the completed fixture work and outstanding independent/live acceptance gates are recorded above. Production migration and final release deployment are separate actions.
