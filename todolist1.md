# Time Agent — to-do list

Updated 7 October 2026. This is the practical work list for making the agent understand schedules and field reports, then proving that it works with a real model. `[x]` means implemented and locally verified; `[ ]` means work or acceptance evidence is still needed. Keep the detailed task IDs in [`../progress-agent-plan/TASK_BOARD.md`](../progress-agent-plan/TASK_BOARD.md).

8 October update: the private `gemma4:12b` endpoint passed health and structured JSON checks, plus one live extraction and one corrected selection case. The import UI now exposes the remaining task mapping fields. Real schedule/report walkthroughs, independent evaluation, and PostgreSQL integration remain open; the Docker daemon was unavailable in this session. Details are in [`docs/current-audit-2026-10-07.md`](docs/current-audit-2026-10-07.md).

## 1. Understand the schedule and its tasks

- [x] Detect and parse canonical CSV, P6 XER/PMXML, and Microsoft MSPDI/MPP; retain source file, project identity, task IDs, WBS, dates, and relationships. Parser fixtures and four-format PostgreSQL flows pass.
- [x] Require a reviewer to select a project in a multi-project source, review mapping, stage a version, and activate it explicitly.
- [x] Show all parsed leaf activities in a searchable import screen; let a reviewer enter discipline and work type. Unknown work type no longer falsely contradicts a report observation.
- [ ] Complete the import mapping UI for area, asset tags, aliases, measurement basis, planned quantity, unit, and baseline quantity. Show which tasks still have unsupported measurement. **Done when** a reviewer can map every relevant task without editing JSON or CSV by hand, and invalid combinations are rejected with clear feedback.
- [ ] Show a useful schedule-version comparison before activation: added/removed/changed tasks, dates, WBS, quantities, and dependencies. Preserve the approved baseline separately from later status updates. **Done when** a reviewer can see what changed and activation does not silently rebase approved progress.
- [ ] Run a real project schedule through upload → preview → mapping → staging → activation → task retrieval in the browser. Include a multi-project file if that is part of the actual workflow. **Done when** source IDs and selected project remain correct in the database and UI.

## 2. Read reports and understand what happened

- [x] Accept pasted text, TXT, DOCX, text PDF, and structured XLSX; preserve the original and exact fragment locators. Image-only PDFs require transcription.
- [x] Extract typed observations, validate quoted evidence, distinguish actual work from planned/no work, retrieve candidate activities, and save review proposals. Both legacy and bounded LangGraph processing paths are wired; current configured mode is `legacy`.
- [ ] Validate extraction on representative real field reports: actual versus planned work, dates, quantities, units, asset tags, corrections, delays, and missing facts. **Done when** saved predictions can be checked against independently reviewed examples and serious errors are visible, not silently accepted.
- [ ] Verify that reports with multiple activities produce separate observations and that duplicates/corrections do not double-count work. Include conflicting dates and cumulative-versus-delta quantities. **Done when** each accepted proposal has traceable evidence and ledger totals match reviewed facts.
- [ ] Provide an explicit, audited way to reanalyse a previously submitted report after a prompt/model fix. Current duplicate-byte intake reuses the earlier job. **Done when** old decisions remain intact and a new run is clearly linked to its source and model version.

## 3. Match, explain, and propose progress

- [x] Match only against eligible leaf tasks from the job's pinned schedule, require source evidence, and abstain when a match is unsupported or ambiguous. Approval is separate from agent processing.
- [ ] Measure task matching on real schedule/report pairs, including exact IDs, names, WBS, aliases, similar tasks, wrong project, and ambiguous references. **Done when** candidate recall, selected precision, and abstention are recorded with examples of failures.
- [ ] Calculate quantity or physical progress only for tasks with a reviewed measurement basis and a supported report amount. Show missing unit, date, baseline, or delta/cumulative meaning as blockers. **Done when** an unsupported “completed” statement cannot create an invented percentage.
- [ ] Surface blockers, delays, and possible downstream effects as evidence-backed review items. Treat forecasts as a later feature after actual dates and dependencies are reliable. **Done when** each alert names the source statement and affected schedule task; no automatic schedule change occurs.
- [ ] Make the review queue clearly show the proposed task, evidence, confidence/ambiguity reason, numeric effect, required corrections, and what approval will change. **Done when** a reviewer can revise, reject, approve, and revisit the latest state without stale proposal IDs.

## 4. Finish the agent framework rollout

- [ ] W-37: add authenticated, read-only agent-run status with sanitized stage, count, retry, and timing data. Never expose prompts, report bodies, checkpoints, endpoint, token, or hidden reasoning.
- [ ] W-38: show those stages and retry/failure states in the job UI while preserving a clear legacy-mode view.
- [ ] W-39: prove legacy/graph proposal parity, crash recovery, lease and schedule-change behavior, concurrency, security, backup/restore, and rollback. Run one real private-model graph smoke. **Only then** decide whether to change `AGENT_EXECUTION_MODE` from `legacy` to `graph`.

## 5. Connect and evaluate Gemma 4 12B later

- [ ] Connect the two machines privately with Tailscale; keep model URL, exact installed tag, and optional token in server configuration. Do not expose Ollama publicly or pass model settings from the browser.
- [ ] Check Ollama runtime, installed tag and digest, model metadata, structured JSON response, extraction, selection, timeouts, and latency. Confirm that the current bounded context/output settings suit the exact installed model.
- [ ] Review/adjudicate the synthetic W-03 and W-29 labels independently before treating them as a gold set. Keep AI-assisted review and unreviewed labels marked as such.
- [ ] Re-run seed and held-out evaluation through the **assembled** parser → extraction → retrieval → selection path. Save predictions before scoring held-out labels. Fix the evaluator's missing candidate-ID and `atomic_event_keys` inputs so tag/selection/F1 metrics are meaningful. Compare Gemma with the saved Qwen run and a lexical baseline without overstating synthetic-data quality.
- [ ] If lexical retrieval misses real tasks, provision and pin local embedding weights, then measure whether hybrid retrieval actually improves recall. Lexical fallback must remain usable.

## 6. Verify the real user flow and release readiness

- [ ] Walk through real login → project/schedule import → report intake → worker processing → review/revise/reject/approve → progress history → CSV export in a browser with PostgreSQL and the connected model. Current Playwright tests use fixtures or intercepted API responses.
- [ ] Test model outage, malformed model output, duplicate submission, worker restart, stale schedule, unauthorized access, and a second reviewer racing an approval. Record what the user sees as well as the database result.
- [ ] Run `make doctor`, unit/integration/native/browser/type checks, a backup and separate-database restore, then rehearse the demo on the actual two-machine network. Update the release record with exact versions, model digest, timings, accuracy, and limitations.
- [x] Add `npm run typecheck` to CI; the local strict check passes.
- [ ] Review the five reported development-dependency npm audit findings and upgrade only with passing build/browser checks; the production dependency audit currently reports zero findings.
- [ ] Bring the README, release notes, and both task boards up to date after the evidence above is accepted. Older documents still describe earlier test counts and pending checks.

## Optional, after the text workflow is reliable

- [ ] Add local OCR for scanned PDFs and evaluate transcription accuracy before using OCR text for progress proposals.
- [ ] Add trend/forecast views for late or blocked activities only after actual dates, task relationships, and schedule status dates are trustworthy.
- [ ] Decide separately whether public hosting or native Primavera/Microsoft writeback is needed. Neither is part of the current local-first release.

## Current verification snapshot

On 7 October 2026: 154 backend unit tests, six native parser tests, 57 isolated PostgreSQL integration tests, four Playwright browser tests, frontend production build, and strict TypeScript check passed. Native parser smoke passed the checked fixture manifest. This proves the local implementation paths, **not** Gemma model accuracy or a real two-machine run. See [`docs/current-audit-2026-10-07.md`](docs/current-audit-2026-10-07.md) for the audit and [`docs/report-review-diagnosis.md`](docs/report-review-diagnosis.md) for the earlier report/review defects.
