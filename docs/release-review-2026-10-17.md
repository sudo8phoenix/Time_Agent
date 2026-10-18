# Final candidate review — 17 October 2026

> Historical record: statements and instructions below apply to the recorded stage.
> [Current status — 18 October](current-status.md) and the
> [latest V20 follow-up](release-followup-2026-10-18.md) supersede its operational
> status. Both V19 splits are consumed; release remains unaccepted.

This is a public/synthetic prototype using owner-authorized AI-assisted review
and **MOCK PMIS**. No owner package is expected. No independent human review or
owner-specific accuracy is claimed. The source remains uncommitted and unpushed.
Live captures identify Groq `openai/gpt-oss-20b`, key slot 0, pinned prompt hashes,
source hashes and request settings. A hosted immutable model-weights digest is
unavailable; the provider model name is not a weights hash.

## Frozen validation

The eight reports captured before truth scoring all reached review in
58.769–71.719 seconds (p50 68.318; p95 71.719). Initial and normalized atomic-event
F1 are 1.0; candidate recall is 7/7, selected-link precision/coverage are 7/7,
and safe ambiguity handling is 1/1. Initial fields are 32/37 correct, normalized
fields 34/37; endpoint fields are 3/6. Two reports require initial-model field
correction. One date-only start has an `actual_start` value without a lifecycle
endpoint object. This fails the approved 0.95 endpoint target. Successful event
and link scores do not make this a quality pass. No proposal was approved.

Evidence: `evaluation/results/release-completion-2026-10-17/validation-scored-v1/`.
Scoring verifies sealed capture, input, label and manifest hashes. Initial model
outputs are scored separately from normalized persisted proposals. Cases remain
in all denominators, including failures. The unchanged v18 candidate goes to
holdout without tuning against these results.

## Untouched holdout

All eight reports reached review, with no approved progress writes. Initial and
normalized event F1 are 0.9333 (seven correct, one missing event); project macro
F1 is 0.95. Selected-link precision is 5/6 (0.8333), coverage is 5/7 (0.7143),
and candidate recall is 5/7 (0.7143). These fail the frozen 0.98 / 0.80 / 0.95
matching targets. Endpoint fields are 6/6; safe ambiguity handling is 1/1.
Initial fields are 27/36, normalized fields 30/36. Five reports need initial
model field correction. Readiness p50 is 70.342 seconds and p95/max 111.298.

`H-ROAD-1` links its blocker to the progress activity HCE instead of HCF, with
the correct blocker activity absent from its shortlist. `H-ROAD-2` misses the
no-work event. The delivery ambiguity case safely abstains. These are retained
failures, not relabelled successes or evidence for tuning this candidate.

Evidence: `fresh-holdout-v1/` and `holdout-scored-v1/` under the same release
completion directory. Labels were opened for scoring only after the unchanged
candidate's predictions/calls were sealed. This holdout is now consumed for
evaluation; a later tuned candidate needs newly frozen unseen cases.

## Confidence study

Seven date-scored events are eligible under the policy frozen before scoring.
Event/link thresholds are unsupported (seven targets each). The field study's
support-index cutoff is 0.5 with 20/20 correct fields and 58.8% coverage across
34 field targets. These are clustered fields within seven synthetic events.
The index is not a probability and this finding does not establish deployment
calibration. Runtime confidence stays unavailable; no threshold is installed.
Holdout results must not tune the estimator or study policy.

## Verification and recovery

After the latest planner change: 435 unit tests, 197 PostgreSQL integration tests
and 48 browser fixture/review-API tests pass. Frontend type checking, production
build and contract wiring pass. Native smoke parses all six required sources;
an actual malformed-XML probe rejects the bad fixture with
`SCHEDULE_PARSE_FAILED`. Scoped source lint and diff checks pass.

Populated-state recovery evidence remains in
`evaluation/results/release-completion-2026-10-17/populated-recovery/`.
It covers restored conversation/provider journals and deterministic resume,
not sustained live-provider capacity. The earlier two-minute monitoring window
is retained as bounded baseline evidence.

## Incident disposition

The historical interruption's cause remains **unknown**. The original retrieval
failure's cause remains **unproven**. Fresh successful retrievals cannot establish
either historical cause. Earlier failed workload captures remain evidence.

## Operational scope

The mixed-workload runner uses two real worker processes, initially one report
and one conversation, then two of each every 150 seconds, with a ten-minute
budget. It stops new admissions for failed/cancelled work, readiness over 120
seconds, expired ownership, cooldown over 90 seconds, unexpected approved writes,
or worker exit. Shutdown sends SIGTERM, allows a shared 100-second drain, then
kills only the owned workers if needed. Checkpoints and queues are retained for
inspection; no automatic resume or rollout advancement occurs. An early stop
fails sustained workload acceptance. Both rollout flags remain disabled.

Browser acceptance-to-update and mock acknowledgement latency distributions are
not measured by the frozen report capture or this mixed-workload runner. Earlier
bounded browser/mock checks do not supply a sustained latency distribution.

## Development and monitoring attempts

The full known wording rerun passes 7/7 normalized component checks. In the new
five-case wording capture, B19-01 and B19-02 pass. B19-03 receives HTTP 429 with a
165-second cooldown (41.126 seconds in admission, 0.454 in transport); B19-04 and
B19-05 fail closed in admission. These three outcomes are provider-blocked checks,
not measured semantic failures or successes. The first delivery probe is likewise
capacity-blocked for all five cases. No credential/model/provider fallback occurs.

The first mixed stage observes cooldown over its 90-second stop threshold and
stops before either fixture is claimed. Both owned workers terminate; one report
and one conversation remain unclaimed. This proves the cooldown stop behavior,
not actual concurrency or sustained throughput. A separate post-stop disposition
cancels only those verified zero-attempt fixtures before the later capture; their
original failed attempt remains evidence.

The ten-minute monitor completes 121 samples in 600.022 seconds and records
`PROVIDER_COOLDOWN_EXCEEDS_CAPTURE_REQUEST_BUDGET`. This fails advancement rather
than certifying capacity. A separate five-minute monitor starts with the mixed
stage and records the stop/rollback period.

That second monitor completes 61 samples in 300.025 seconds. It records renewed
cooldown, a new failed report and conversation readiness exceeding 120 seconds.
The ten- and five-minute windows replace the earlier two-minute-only observation
as longer monitoring evidence; both observe stop conditions and fail advancement.

After the recorded cooldown expired, a separate mixed retry claimed both the
report and conversation once. The conversation reserved one model call, received
`MODEL_RATE_LIMITED`, and durably requeued for 07:51:16 UTC. The report's extraction
failed with `MODEL_CAPACITY_TIMEOUT`: 0.532 seconds in admission, no admission and
zero transport time. This instrumentation explains this new failure only; it
does not explain the original historical retrieval failure.

The controller stopped after 2.667 seconds with failed-work and renewed-cooldown
criteria. Both workers exited cleanly (code 0), flags stayed false and the ledger
remained at its pre-existing two events. The queued conversation is retained
with no worker running against this rehearsal database; inspect it explicitly
before any later resume. Further component retries were stopped after this
repeated rate limit. C06 and broader delivery identity remain unverified live;
three new wording cases remain provider-blocked. No sustained workload pass is
claimed, and no rejected capture is removed from totals.

## Source and running local prototype

`docs/validation/final-candidate-source-2026-10-17.json` freezes 322 source/test/
fixture/configuration files. Its SHA-256 is
`ff3f8243f786490619b86b420b2fa561cb47c66e94d41202c35b0c4132c3ca1d`.
All captured application source hashes still match validation and holdout.
The main API and worker were restarted after verifying the frozen hashes and
zero pending main jobs/conversations. Health returned HTTP 200; both processes
remain running. `final-runtime.json` records process identities and settings.
Migration is 0018; main timeouts remain 360/300 seconds, versus 90-second frozen
report/mixed request budgets and 60-second component budgets. Both rollout flags
remain false. This restart is not promotion of a passing release.

The machine-readable [final candidate record](../evaluation/results/release-completion-2026-10-17/final-release-record.json)
records gate comparisons, initial/retry captures, evidence/document hashes and
remaining unmeasured requirements. It freezes a failed candidate review, not an
approved release. The source manifest excludes secrets and mutable runtime state.

## Remaining gates

Endpoint accuracy on validation and link precision/coverage/recall on holdout
fail their frozen targets. Three broader wording cases and live C06/delivery
matching remain blocked by provider limits. The two mixed attempts exercise
stopping and rollback but do not establish sustained concurrency or readiness.
Runtime confidence and event/link thresholds remain unavailable; the field study
does not establish deployment calibration. Sustained approval/update and mock
acknowledgement distributions remain unmeasured. These gates require new scored
evidence before rollout advancement; a tuned candidate needs a fresh holdout.
