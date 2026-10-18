# Paused completion work — 16 October 2026

> Historical record: statements and instructions below apply to the recorded stage.
> [Current status — 18 October](current-status.md) and the
> [latest V20 follow-up](release-followup-2026-10-18.md) supersede its operational
> status. Both V19 splits are consumed; release remains unaccepted.

Resumed by the owner on 17 October. See
[retrieval resumption evidence](retrieval-resumption-2026-10-17.md) for inspection,
recovery and fresh diagnostics. The pause instruction below records historical
state and no longer prohibits the authorized continuation.

Paused at the owner's request: “lets stop over here”. This is the resume entry
point. No additional inference or deployment work should start until resumed.

## Current operational state

- Normal local API remains running at `http://127.0.0.1:8001` (PID 43045), with
  its normal worker (PID 43046). Process/log record:
  `/private/tmp/progress-completion-20261016-runtime/processes.json`.
- The configured application database was upgraded from 0015 through 0016/0017
  to **0018_hosted_admission**. Both rollout flags remain **false**.
- The temporary API on 8002, mock receiver on 8092, connector and rehearsal
  workers have stopped. The PostgreSQL container remains running.
- Isolated live/rehearsal database: `progress_rehearsal_20261016`. Its data and
  checkpoints remain available. It contains two interrupted diagnostic jobs;
  inspect them before running any worker against this database again. Their
  ownership/provider leases can expire normally. This does not affect the normal
  application database, which uses a separate coordinator.
- Source changes are uncommitted. The normal processes were started before the
  final settings/diagnostic edits; restart them on resumption after final checks
  if the latest complete source is to be loaded. No release commit/source
  manifest was frozen and no push was performed.

## Completed and observed

### Migration, backup and recovery

The backup tool now supports a valid database before migrations 0016–0018. It
allows only the tables legitimately absent before their introducing migration;
unexpected missing required tables fail. Manifests record migration identity,
and restore verifies it and the expected absent-table inventory.

1. Quiesced the normal API/worker, with zero queued/running jobs.
2. Backed up 0015 to `/private/tmp/progress-completion-20261016-before-0018`.
3. Restored and verified it in `progress_restore_completion_pre_20261016`, with
   originals under `/private/tmp/progress-completion-20261016-pre-restored-uploads`.
4. Rehearsed 0016–0018 on that restored copy, then applied them to the application.
   The pre-named restore database is consequently now migrated; its original
   backup remains an unchanged 0015 recovery point.
5. Backed up 0018 to `/private/tmp/progress-completion-20261016-after-0018` and
   restored/verified it in `progress_restore_completion_post_20261016`, with
   originals under `/private/tmp/progress-completion-20261016-post-restored-uploads`.
6. Verified all prior tracked recovery-row hashes, checkpoint hashes and file
   manifests stayed equal across migration: **54 originals and 17 approved
   events** preserved. Restarted the normal API/worker and checked HTTP health.

The new operational tables were empty in the application snapshot. Recovery of
populated provider/conversation-task state remains an additional useful rehearsal.

### Extraction and semantic quality

- Added versioned `extraction-v12-source-clause-check`, preserving exact v9/v10/v11
  prompts and processing compatibility. New runs pin v12; saved runs retain their
  pinned version. Tests cover report/conversation replay after default changes.
- All seven live component wording checks passed in
  `evaluation/results/quality-gap-fixes-2026-10-16/v12-wording-09/`.
- Q07 now has a successful live conflicting-date result: delivery retained,
  date cleared, blocking clarification warning, no quantity/lifecycle effects.
- **7/7 does not mean all fields are correct.** The separate AI technical review
  flags Q01's dropped Zone C/testing scope, Q02's unsupported cross-clause Bay D
  association, and Q04's location classified as an asset. Resolve these and add
  field/scope checks before claiming extraction quality is complete.
- The component evaluator now saves synthetic structured model outputs and safe
  schema error paths, allowing failed observations to be investigated.

### Live browser workflow and frontend regression

The real browser → live Groq → pending proposal → authorized synthetic reviewer
acceptance → automatic mock delivery/read-back → refresh/export test passed in
the isolated database. It verified a quantity-free 08:30 minute-precision start,
a date-only finish with no invented clock, duplicate intake, and rejection of a
conflicting start with unchanged revision/event count. Duration returned a
one-day span, no invented elapsed hours, and unavailable calendar/labour metrics.

Proposal readiness was 74.105 / 91.784 / 90.865 seconds for three synthetic reports.
Successful approval response-header timings were 29.126 / 39.145 ms; these are
browser response timings, not isolated database commit measurements. Mock read-back
was asserted, but a full delivery-latency distribution was not captured.

Evidence is under `/private/tmp/progress-completion-20261016-live/evidence/`:
`lifecycle-live-run.json` and `lifecycle-live.png`. Screenshot was inspected.
This is a known synthetic workflow demonstration, not an unseen benchmark.

The browser regression originally failed because its mocked `/auth/me` kept
returning 401 after login; focus changes during parallel tests logged it out.
The fixture now preserves authentication and explicitly exercises focus restore.
The complete fixture/review API suite then passed **48/48**. Initial failed runs
remain part of the investigation; they are not omitted.

### Actual two-worker workload and rollback

`evaluation/results/release-completion-2026-10-16/two-worker-rollback-02/` ran four
seed reports through two real worker processes. Maximum observed running jobs was
two. C01/C02 were pinned v2 with the free OpenRouter planner before workers started
with both flags false; C03/C18 used v1. Saved version/configuration was honored.

| Case | Runtime | Result | Terminal observation from enqueue |
| --- | --- | --- | --- |
| C01 | v2 | Failed at retrieval, `AGENT_TOOL_FAILED` | 168.495 s |
| C02 | v2 | Ready for review; ambiguous selection abstained | 150.622 s |
| C03 | v1 | Failed at retrieval, `AGENT_TOOL_FAILED` | 220.108 s |
| C18 | v1 | Ready for review with date conflict handling | 305.652 s |

The run took 306.373 seconds. Both workers exited cleanly; zero approved progress
events were created. **This fails workload readiness**, and the observed ready
latencies exceed the approved 120-second target. It proves bounded live behavior
and pinned rollback execution, not sustained acceptable capacity.

The first attempt, `two-worker-rollback/`, made no inference: string key-slot
environment variables were rejected by Pydantic integer literals. It is retained
with `abort-review.json`, which explicitly rejects its misleading interrupted
controller `status=completed`. Its four never-claimed fixture jobs were cancelled.
Settings now parse only documented 0/1/2 strings, and the controller fails promptly
on child exit or incomplete work.

The completed workload retained only generic errors. New private telemetry now
records a closed, sanitized failure category (capacity/rate/quota, transport,
response, decision, extraction validation) while preserving public error contracts.
No provider body, source text or arbitrary exception attributes are copied.

`retrieval-diagnostic-03/` repeated only C01/C03 with that instrumentation but was
**interrupted at the owner's pause request**, after about 40.8 seconds. Its two
workers were killed after bounded shutdown, have exited, and wrote zero approved
events. Its nonzero/failed result is operator interruption, not a measured new
provider failure. Preserve its checkpoint/ownership evidence when deciding resume
versus a separate new capture.

### Review authorization and prepared data review

The owner approved using the proposed targets and authorized AI-assisted review
instead of naming a human reviewer. Recorded policy:
`docs/evaluation-targets-approved-2026-10-16.json`. Do not ask for that approval again.
AI review must not be represented as independent human adjudication.

Prepared artifacts:

- `data/review/v2-ai-adjudication-2026-10-16.json`: all 16 development cases,
  suggested corrections and unresolved/clarification concerns; originals unchanged.
- `data/review/schedule-split-ai-review-2026-10-16.json`: all 21 quality queue
  records and structural grouping assessment. Aggregate Cambridge findings remain
  distinct from the bounded project-5060 screen.
- `docs/review-handoff-2026-10-16.md` and
  `data/review/release-readiness-2026-10-16.json`: exact sources/hashes and next work.
- Existing structural split check passed: 299 Cambridge projects in 221/39/39
  provisional partitions, 54 groups; 16 GT10 scenarios remain development.
- GT10's MIT notice and both workbook identities are already retained/verified.
  Cambridge upstream byte identity/attribution remains unresolved.

Some AI review comments need final adjudication rather than blind promotion:
planned-versus-actual schedule variance alone does not invalidate a source date;
planned dependency links do not prove actual chronology; missing/ambiguous source
facts can be valid clarification-case labels. Duplicate/correction/reordered cases
need explicit workflow setup rather than universal standalone extraction labels.

## Verification boundary

- Latest full backend run: **397 unit / 191 integration passed**, after the
  settings fix and before the final telemetry-category patch.
- After the telemetry patch: **26 targeted unit / 22 targeted integration passed**.
  A final full combined regression remains to be run on the complete source.
- Frontend type checking, production build and **48 browser regression tests** passed.
- Native smoke: all six required inputs parsed; malformed XML rejected.
- Structural split checker and scoped Ruff/diff checks passed at their recorded
  stages. Run final scoped lint/diff after any remaining edits.
- JUnit artifacts: `/private/tmp/progress-completion-20261016-unit-final.xml` and
  `/private/tmp/progress-completion-20261016-integration-final.xml`.

## Work remaining, in recommended order

1. **Finish live failure diagnosis.** Read the interrupted diagnostic record and
   decide whether to resume its isolated jobs or capture new ones. Identify why
   retrieval failed in the completed two-worker run. Keep all failures in totals;
   do not add unapproved key/model/provider fallback.
2. **Fix semantic field/scope gaps.** Resolve the location and blocker-scope errors,
   delivery association (including whether C06 should abstain), and strengthen
   metrics beyond event/quantity checks. Repeat known and fresh wording plus full
   reports with all rejected outputs retained.
3. **Finalize AI-assisted adjudication and freeze evaluation inputs.** Resolve
   proposed label/workflow corrections in separate derived artifacts, review group
   identity/coverage, and freeze versioned splits. Current development examples
   cannot become unseen evaluation by renaming them.
4. **Complete unseen acceptance against approved targets.** Capture initial model
   outputs before scoring; independently account for atomic events, candidates,
   links, endpoint precision, abstentions, corrections, failures and stage latency.
   The successful single-workflow browser test is insufficient for these metrics.
5. **Confidence calibration.** Runtime scores are currently deliberately null.
   Do not invent probabilities or thresholds. A versioned scored estimator and
   eligible validation evidence are required for operational thresholds. Existing
   `evaluation/calibrate.py` still enforces independent-human attestations; it has
   not been changed to an explicit owner-authorized AI-review policy. If adapting
   that policy, preserve an honest AI review status and the strict default.
6. **Provider/deployment acceptance.** Resolve failed multi-worker requests, measure
   sustained report/conversation mixes and latency/error/cooldown behavior on the
   intended deployment. Current results do not support scaling or enabling flags.
7. **Finish staged monitoring/rollback acceptance.** The read-only monitor is
   `ops/runtime_status.py`; pinned v2 execution after flag rollback was observed.
   Full staged report/conversation monitoring and agreed stop criteria remain.
   Consider restoring populated admission/conversation-task state and resuming
   interrupted work, not only empty new tables.
8. **Historical interruption.** The old transport-plus-lease root cause remains
   unproven because original ownership transitions/logs were not captured. New
   diagnostics cannot retroactively establish it. Close only with recovered
   evidence, or explicitly retain it as an unattributed historical incident.
9. **Finalize source/release record.** Run final full checks, hash/freeze exact
   source/model/configuration and evidence, reconcile current release/runbook
   entries with this migration, then restart the main app on the final source.
   Enable either flag only after its failed acceptance gates are resolved.

Owner sample package remains `not_received`; register and validate it when supplied.
The agreed prototype permits **MOCK PMIS**. A production PMIS connector is outside
that scope, not an additional requirement for this prototype's completion.

The system still has one active schedule per project/job. Simultaneous matching
across two independent schedules is unsupported; it was discussed, not implemented
or added to the authorized completion scope.
