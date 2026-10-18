# V20 follow-up — acceptance remains open

Use [current status](current-status.md) for the consolidated model, latency,
runtime and six-workstream summary. Configured extraction is Groq
`openai/gpt-oss-20b`; the default prompt remains V12 and V20 remains opt-in.
The homepage and liveness check on port 8001 passed on 18 October; no
accepted-source restart is implied by that reachability check.

The release gates remain the owner-approved targets in
`evaluation-targets-approved-2026-10-16.json`. Regression tests do not establish
capacity, accuracy, calibration, sustained latency or acceptance.

## Evidence quote repair

V20 now removes a repeated initial source heading only when the remaining quote
is a unique exact substring in the same identified fragment. Another intervening
non-clock colon, altered source words, an unknown heading or an ambiguous span
prevents repair. Observation and lifecycle evidence follow the same rule and
repaired observations carry a warning. V19 and earlier versions retain their
existing behavior; the runtime default remains unchanged.

Offline replay of the already-consumed V19 reservoir validation response retains
three observations under the new V20 source, versus one under V19. This is a
development diagnostic, not a fresh accuracy result. No holdout labels were used.
See `../evaluation/results/release-completion-2026-10-18/quote-repair-offline-v1/replay.json`.

The affected checks passed: 455 unit tests, 14 PostgreSQL prompt-pinning integration
cases, scoped Ruff and `git diff --check`.

## Blocker components

Fresh V20 short-ID matching passed BM-02 and BM-03 in 25.685 and 25.385 seconds.
BM-02 selected `CIV-A-REBAR-01`; BM-03 abstained as ambiguous. Both proposals remain
pending with no progress effects. There were four successful hosted calls and no
429s in this two-case capture. Groups contained one case with a 60-second pause.
These are supplied-observation matching checks, not extraction or sustained
acceptance. See `../evaluation/results/release-completion-2026-10-18/v20-blocker-matching-v1/`.

## Rehearsal integrity

The retained conversation `22d2b979-b4ce-44bc-833e-b31cad4f22da` was inspected and
expired through normal runtime claim handling. It failed with
`CONVERSATION_BUDGET_EXHAUSTED`, preserving one attempt, one model-call reservation
and its original deadline; no inference was made. Its disposition is retained.

The first new mixed-workload attempt was interrupted after finding that the runner
pinned report prompts but left conversation prompts at application defaults.
Its two owned workers exited with code zero. Its report was left queued for
inspection, preserving checkpoints; no automatic resume was performed. That
attempt cannot certify V20 sustained operation.

The runner now explicitly pins conversation prompts and extraction/selection
assignments to the same V20/Groq candidate as report workers. The second attempt
uses the previously idle evaluation rehearsal database; a persisted configuration
audit confirms the assignments. Delivery-only conversation inputs produce no
lifecycle confirmation cards in the current conversation flow, so their task
completion cannot establish lifecycle conversation matching coverage.

The corrected second attempt reached report review in 115.757 seconds, with
111.316 seconds of admission and 2.842 seconds of transport across three calls.
Extraction accounted for 47.134 seconds: 46.312 seconds of admission and
0.806 seconds of request/response transport. These timings identify quota pacing
as this sample's dominant delay; they do not isolate model generation time or
establish sustained p95. See
[the saved tool metrics](../evaluation/results/release-completion-2026-10-18/v20-mixed-workload-v2/initial-report-provider-metrics.json).
It stopped in its second stage on `EXPIRED_WORK_OWNERSHIP`. Adjacent samples
show a roughly ten-minute wall-clock discontinuity while monotonic time advanced
about two seconds. Its cause is unproven; this is not evidence of a new 429 or
successful sustained capacity. Both owned workers exited with code zero. Two
reports and two conversations remain retained in running/queued states; inspect
`v20-mixed-workload-v2/post-stop-runtime.json` before any explicit resume.
The first interrupted attempt's separate queued report is also retained.

The runner now submits lifecycle-start conversation messages and treats a
succeeded task with no event cards or model calls as a failed measurement.
This latest harness revision has not been live validated. Its affected 73 unit
checks, scoped Ruff and diff checks passed after the change.

`v20-candidate-source-v5.json` is an unaccepted candidate snapshot. It supersedes
the older candidate hash inventory for this source; it is not an accepted freeze.
All new evidence paths are under
`../evaluation/results/release-completion-2026-10-18/`.

## Remaining gates

Sustained full-report and lifecycle-conversation capacity is unproven. Fresh V20
validation against every approved target, a newly frozen holdout, supported
event/link confidence thresholds and runtime confidence validation remain open.
The consumed V19 holdout must not be reused as unseen acceptance. Browser update
and mock-delivery latency still require measurements during concurrent model
work. Accepted-source freeze, restart, commit and push remain gated on acceptance.
