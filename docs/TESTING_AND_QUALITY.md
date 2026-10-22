# Testing and measured quality

Maintained testing record, updated 22 October 2026. Results below distinguish
software regression checks, small model studies and incomplete release acceptance.
Full raw captures, execution logs, screenshots, handoffs and the detailed historical
checklist remain local under ignored paths. Small consumed regression fixtures and
the executable evaluation contracts remain in Git.

## Recorded software verification

| Check | Most recent recorded result | Scope |
|---|---|---|
| Backend unit suite | 1,467 passed, one skipped | Full Mac and Linux suites after bounded exit confirmation |
| PostgreSQL integration suite | 263 passed | Isolated rehearsal DB, injected models; last full batch-32 run |
| Final batch-32 controls | 26 passed | Source fingerprints, scopes, journals and test execution guards after final source-contract expansion |
| Scoped Python lint | Passed | New evaluation, admission, source-contract and guard modules; no repository-wide lint claim |
| Native import suite | Six passed | Earlier recorded native-reader verification; not repeated in batch 32 |
| Frontend typecheck/build | Previously passed | Publication verification is recorded below |
| Mocked browser checks | 50 passed plus two hostile-link checks | Historical batch 16; later browser changes require current verification |

The unit suite covers schema/evidence validation, schedule-scoped retrieval and
selection, graph/role contracts, model budgets, hosted capacity, source identity,
annotation/scoring integrity, native parser controls and security boundaries.
Integration coverage exercises authenticated APIs, review and ledger behavior,
durable reports/conversations, recovery/cancellation, outbox delivery and isolated
quota-policy activation. These use deterministic/injected responses; passing them
does not measure a live model's accuracy.

## Model and prompt studies

The latest bounded study used consumed public/synthetic development examples.
Its six-case component task used a projected event schema, not the complete
production ObservationBatch contract:

| Arm | Exact scoped case matches |
|---|---:|
| GPT-OSS 20B baseline | 3/6 |
| GPT-OSS 120B baseline, same inputs/settings | 6/6 |
| Tailored 20B instruction | 4/6 |
| Fixed examples with 20B | 6/6 |
| Dynamic training-only examples with 20B | 6/6 |

There is no demonstrated benefit from dynamic examples in this tiny sample.
Two 120B annotation-review calls agreed on all six cases across the two accounts;
using the same model is correlated AI review, not independent human adjudication.
Earlier development work also retained schema failures, HTTP400s, incomplete
comparisons and original consumed labels. None is promoted into fresh holdout truth.

## Actual V2 graph study

The study seeded reports directly in an isolated database, bypassing upload/OCR.
It exercised extraction, schedule matching, planner calls and the pending-review
boundary. It did not execute user approval or delivery.

| Routing/account arrangement | Readiness | Outcome |
|---|---|---|
| Deterministic routing | 97.580 s on ordinary case | One completed case; ambiguity case stopped at original budget |
| Assisted, one account | 182.738 s / 166.131 s | Two scoped cases passed |
| Assisted, orchestrator key_1 and workers key_2 | 142.704 s / 143.985 s | Two scoped cases passed |

All four assisted runs exceeded the 120-second target. Two correlated examples,
prior shared admission and the study's own pacing do not establish p95, sustained
capacity, a causal benefit from independent admission or a production winner.
The independent account-scope policy was implemented and tested offline later;
these older live measurements do not validate that later source revision.

There were 64 tracked HTTP200 completions across the core and graph study,
with 55,550 reported tokens, plus two read-only catalog requests. The original
64-call cap stopped the final deterministic ambiguity case before another HTTP
request. Graph attempts and actual HTTP counts differ at that budget boundary.
Missing cache telemetry remains unknown; no cache hit/miss or true independent
cold-start claim is made. Synthetic retrieval diagnostics covered 54 comparisons
at 8, 1,000 and 10,000 rows without model calls; those are component diagnostics.

## Test-execution incident and safeguards

An initial integration invocation omitted the isolated database setting. A new
synthetic fixture project was created in the main database; cleanup targeted only
that verified fixture and its owned rows. The final main inventory matched the
original 56 jobs, 10 runs and zero conversation tasks. Existing run metadata,
configuration, counters and deadlines were preserved.

A subsequent isolated run reused cached settings before pytest disabled rollout
flags. Real Groq orchestration occurred outside the frozen study. The run was
interrupted; its exact extra call/token/spend totals were not captured. Therefore
64 is the tracked study count, not a total for all traffic or a billing guarantee.
The corrected study-only list-price estimate is $0.007057; an older cost summary
misclassified 120B as 20B by suffix matching and was superseded locally. Total
billing including the incident remains unknown.

Integration setup now validates an explicitly isolated local database, rejects
an already-imported engine pointing elsewhere, clears cached settings, disables
hierarchy/model assistance by default, and blocks uninjected hosted-provider
HTTP. Four guard regressions and the full 263-case integration suite passed after
these changes. This Python-level transport guard is not an OS-wide network sandbox.
The main account-scope flag remains false and the activation marker is absent.

## Acceptance status

The historical checklist ends at 231 checked scopes and 37 open items out of 268.
The last requested 25-item batch closed 12 scoped items; 13 remain partial.
This status is retained here without publishing the large checklist archive.

Owner-approved thresholds are frozen in
[approved-targets.json](../evaluation/contracts/approved-targets.json): event
F1 ≥ 0.90, selected-link precision ≥ 0.98 and coverage ≥ 0.80, candidate recall@8
≥ 0.95, endpoint accuracy ≥ 0.95, safe ambiguity handling ≥ 0.95, readiness p95
≤ 120 seconds, accept-to-internal ≤ 2 seconds, mock acknowledgement ≤ 10 seconds,
and zero hard safety violations. Passing regression suites cannot replace these.

Open acceptance work includes selecting and freezing an assembled configuration,
reviewed representative data, complete lineage/group-disjoint splits, fresh
validation and holdout, representative extraction/retrieval/evidence quality,
confidence calibration, broader adversarial coverage, sustained mixed-workload
capacity and an explicit release review. Historical V19 validation/holdout and
other exposed development inputs remain consumed. No production acceptance,
service restart or main-database scope activation is asserted.

## Reproduce software checks

From the repository root after [setup](local-run.md):

```sh
make test-unit
.venv/bin/python -m pytest backend/tests/native_import -q
make test-integration
cd frontend
npm run typecheck
npm run build
npm run test:e2e
```

`make test-integration` prepares and migrates `progress_test`. Use an isolated
local `progress_test` or `progress_rehearsal_*` database, never the main application
database. Set DATABASE_URL before importing application code. Special account-scope
integration tests also require `BATCH32_SCOPE_TEST_DATABASE_URL` when invoked alone.
Browser tests use the fixture runner. Keep real credentials out of test transports.

[Regression fixtures](../evaluation/fixtures/regression/README.md) are small,
consumed historical inputs retained specifically for offline checks. Fresh-clone
verification must not depend on ignored local archives. Live generation is a
separate operation: freeze inputs, source/configuration, budgets and stop criteria,
retain failures and unattempted outcomes, and score sealed captures offline.
See the [evaluation guide](../evaluation/README.md).

## Publication verification

The documentation cleanup relocates required fixture inputs without changing
sealed capture bytes. Verification of the publication candidate:

- Working-tree unit suite: **1,455 passed**.
- Fresh staged checkout, without private `.env` or ignored archives: **1,454
  passed, one skipped**. The skip is the optional workspace `PROJECT.xer` fixture.
- Isolated PostgreSQL integration suite: **263 passed**, including account-scope
  policy tests in dedicated schemas.
- Native import suite: **six passed**.
- Frontend TypeScript check and production build: **passed**.
- Browser suite: **60 passed, three live-model checks skipped**.
- Tracked-file scan: no configured local secrets or common credential patterns
  found; no uploads, environment files, raw results, handoffs or validation
  archives staged. Maintained Markdown links resolve within the tracked checkout.

The restricted unit attempt initially failed process-monitor tests because the
sandbox blocked `/bin/ps`; rerunning with process inspection enabled passed.
No new live-model evaluation was run for this publication.

## Linux parser exit-race correction

A subsequent GitHub Linux unit run reported four parser failures: an exiting
child could retain `/proc/<pid>/status` after its `VmRSS` field disappeared.
The memory sampler treated this normal exit transition as unavailable supervision,
masking document validation errors and rejecting valid schedule/spreadsheet parses.

The shared sampler now returns an unavailable sample when `VmRSS` is absent.
Both report and native callers recheck child liveness; a live child without
telemetry still fails closed. No memory limit or validation check was removed.
Added regressions cover missing RSS, live missing telemetry, RSS byte conversion
and an actual unreaped Linux child (Linux-only test).

Verification: the full Mac unit suite passed **1,460 tests** before the final
Linux-only regression was added. A network-disabled Linux Python 3.12 container
passed **200 unreaped-child exit checks and two live-memory checks** using the
shared report/native samplers. The final affected parser suite passed **44 tests**,
with the Linux-only test skipped on Mac; scoped Ruff also passed. This is targeted Linux verification, not a claim
that the full Linux CI suite has passed. See the next CI run for that result.

## Linux exit-transition follow-up

The next GitHub run still failed five parser tests. The first fix covered an
already-exited zombie but missed the interval after Linux removes `VmRSS` and
before `waitpid` can report termination. An immediate second poll was insufficient.

Both parser paths now share a bounded exit confirmation: a missing sample waits
up to 250 ms for termination, capped by the original parser deadline. Completed
output and validation errors are then processed normally. A child that remains
alive fails supervision and is terminated; no missing sample is treated as a
successful memory measurement. The original memory and output limits remain.

New regressions simulate that delayed exit in report/native paths, preserve both
successful output and document-validation errors, reject a persistently live
unmonitored child, and verify that the grace interval cannot extend the original
deadline. The Mac full unit suite passed **1,467 tests**, with the Linux-only
regression skipped. Scoped Ruff passed. Linux verification is recorded below.

Linux verification used Python 3.12.13 on ARM64 with Java 17, the project-pinned
requirements and working-environment transitive constraints, in a clean container
without private `.env` or ignored archives. The complete unit suite passed
**1,467 tests**, with the optional workspace `PROJECT.xer` fixture skipped.
The initial container lacked Java and reported two dependency-unavailable failures;
a rerun with Java resolved them. Two earlier PyPI download timeouts occurred
before tests started and are not counted as test outcomes. GitHub's Ubuntu x86
runner/Python patch version remains a separate verification environment.

The affected Linux parser suite then passed **61 tests in each of five consecutive
runs** (305 additional test executions), including native schedule normalization,
report ingestion, mapping, delayed-exit handling and fail-closed supervision.
Scoped Ruff, whitespace checks, tracked Markdown links and the tracked-file secret
scan passed. No live model evaluation was run for this correction.
