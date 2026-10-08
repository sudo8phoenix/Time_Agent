# Report processing and review diagnosis

Investigated on 2026-09-25 using the source, recent local PostgreSQL records,
typed extraction and adapter tests, PostgreSQL integration tests, and browser tests.

## Findings and changes

| Symptom | Cause established by evidence | Change |
| --- | --- | --- |
| Worker says it is using lexical retrieval | `sentence_transformers` is not installed in the project environment. The worker intentionally falls back to lexical retrieval when its optional local embedding model is unavailable. | Retained the supported fallback. Embedding availability does not determine whether the selection model runs. |
| No candidate selection in legacy mode | Extraction returns `WorkType` enums. Selection compared `str(enum)` with database strings, so `WorkType.pipe_spool_erection` did not equal `pipe_spool_erection`. It excluded otherwise valid candidates and bypassed the model. | Normalize enum values before comparing work types. Added a regression using the real enum type. |
| Model request would fail once candidates survived filtering | Selection supplied a dictionary as Ollama message content. Ollama expects text. Typed observation fields also needed JSON serialization. | Serialize structured context at the adapter boundary and dump observations in JSON mode. Verified the actual adapter request payload. |
| Report date did not influence extraction | The UI sent `report_date`, but the worker trusts it only when `report_date_evidence` is present. The form also defaulted to a fixed date. | Start with an empty date and record an explicitly entered date with a reviewer-entered context marker, for both text and uploads. |
| Completed work appeared as planned/no work | Recent stored outputs misclassified completed work, invented area values, and sometimes used the wrong work type. Those values then legitimately caused filtering or removal of numeric effects. | Updated the versioned prompt to distinguish performed, planned, and absent work; keep asset tags separate from areas; and avoid inventing quantities from completion language. Live model improvement remains unverified. |
| Approval failed even for otherwise valid numeric observations | Both worker modes omitted `quantity_semantics` from persisted effects, although approval requires it. Legacy mode also wrote units such as `Unit.spool` instead of `spool`. | Persist canonical units, event type, and delta/cumulative semantics in both modes. Verified that a typed extracted observation can proceed to a real ledger approval. |
| Reject appeared ineffective | Recent records contain successful rejections. The client retained old proposal IDs after rejection and revision, so returning to the queue could reopen a rejected or superseded record. | Refresh pending IDs from the backend, update revised IDs, and reset the review component for each proposal. |
| Next Proposal returned to the previous page | On the last entry the button deliberately returned to the job page, but that page still offered the stale review queue. Between entries the component retained local form state. | Use Next Proposal only when another entry remains, Finish Review on the last entry, and an explicit completed-queue state. Reload pending proposals and reset form state on navigation. |
| Revision accepted invalid quantity text | Stored revisions included `yes` and `done`. The API accepted arbitrary effect strings and rejected them only at approval. | Validate finite, non-negative quantities in the UI and API before superseding a proposal. Validate revised calendar dates on the API. |
| The UI did not explain why a match was absent | Selection explanations and missing-information results were discarded when proposals were persisted. | Preserve that metadata in observation evidence records and expose the agent assessment in the review response and UI. Graph resume verification checks the same persisted metadata. |

## What the stored reports showed

The last five jobs included three with one observation each and two with no
observations. Their review records included rejected and superseded proposals,
not merely unrecorded button clicks. No recent proposal had a candidate list.

One stored observation summarized completion of line 24-XX spool erection, but
had `event_type=planned_work`, `quantity=null`, and `area=line_24`. Another used
`area=spool` with `work_type=structural_erection`. A task-completion observation
was classified as `no_work`. These are extraction-quality problems in addition
to the deterministic enum comparison bug.

An exact evidence quote is not enough to prove that every extracted field is
correct. The current validation checks schema and quote membership; it does not
independently establish the semantics of the model's event classification.
The prompt update addresses the observed mistakes, but requires live evaluation
before making any model-quality claim.

## How the flow now behaves

1. The authenticated form sends the actual report text or file and any explicitly
   entered report date. Original fragments remain the evidence source.
2. The worker extracts typed observations and retrieves eligible schedule leaves
   from the job's pinned schedule. Lexical retrieval remains usable alone.
3. Selection compares canonical values and sends the surviving candidates to the
   model as structured JSON text. Contradictory facts still exclude candidates.
4. The worker stores the match explanation and canonical numeric effects as a
   pending proposal. Processing itself never updates the progress ledger.
5. A reviewer saves candidate or field changes with Revise. The new proposal ID
   replaces the superseded ID in the client queue.
6. Reject requires a nonblank reason. Approve requires a saved candidate and
   resolved warnings; the UI also explains missing work dates, quantities, and
   quantity semantics. Backend ledger validation remains authoritative.
7. Next reloads pending proposals. The last decision leads to Finish Review and
   a completed queue, rather than offering the same old proposals again.

## Verification

- The targeted selection, adapter, and retrieval tests passed: 37 tests.
- Focused PostgreSQL coverage verifies real typed extraction through the real
  Ollama adapter with an injected transport, candidate selection, persisted
  numeric effects, and approval into the real ledger. It also covers revision,
  rejection, pending-queue updates, warning resolution, and concurrency.
- Graph tests cover persistence and recovery after a domain commit followed by
  checkpoint failure. The added explanation metadata is included in resume checks.
- Browser tests passed at 390px and 1440px: text/date submission, invalid-quantity
  feedback, warning resolution, revision, reopening the latest revision, rejection,
  next-proposal state reset, approval, and queue completion. These browser tests
  intercept API responses; PostgreSQL and adapter integration are tested separately.
- The existing fixture approval and schedule-import browser tests passed. The
  schedule test needed an unambiguous heading selector.
- Captured review screenshots were inspected at both widths. No page errors were
  reported in the new browser flow tests.
- Production Vite build and frontend contract checks passed. The backend/frontend
  diff whitespace check passed.

The full unit run produced 152 passes and one pre-existing failure:
`test_w03_expansion_is_complete_isolated_and_pending_human_review` expects
`pending_human_review`, while the already-modified dataset manifest says
`ai_assisted_review`. That dataset was not changed by this repair.

Standalone TypeScript checking is blocked by existing missing React declaration
packages and Vite environment declarations. The production build succeeds, but
that does not establish a clean strict type check.

The installed Playwright 1.52 ESM loader stalled with the current Node runtimes.
The successful browser run used the bundled Node 24 runtime with
`PW_DISABLE_TS_ESM=1` to use native TypeScript loading. No Playwright or Node
dependency upgrade was made.

## Remaining runtime limits

The configured private Ollama endpoint timed out during an 8-second health
check outside the sandbox. Live extraction and selection, including the revised
prompt's accuracy on the reported examples, could not be verified. The endpoint
must be reachable before new reports can complete model processing.

The application is configured for `AGENT_EXECUTION_MODE=legacy`. This repair
does not enable graph mode or install embedding packages/model weights.

Existing rejected, approved, and superseded records were inspected read-only.
They were not rewritten or automatically reprocessed. Re-submitting identical
report bytes reuses the existing report/job under the current idempotency rule;
it does not rerun extraction with the new prompt. Historical reanalysis needs an
explicit, audited workflow rather than resetting those records.

A report that only says "completed" still cannot establish installed quantity,
unit, delta versus cumulative semantics, or a supported quantity-ratio baseline.
Those missing facts should remain visible blockers to a numeric progress update.
Improved matching must not manufacture them.
