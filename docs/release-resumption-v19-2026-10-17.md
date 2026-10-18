# V19 release resumption — incomplete acceptance

> Historical record: statements and instructions below apply to the recorded stage.
> [Current status — 18 October](current-status.md) and the
> [latest V20 follow-up](release-followup-2026-10-18.md) supersede its operational
> status. Both V19 splits are consumed; release remains unaccepted.

The accepted release has **not** been finalized. V19 is an explicit opt-in
candidate, not the runtime default. Earlier candidate records and consumed holdout
captures remain unchanged. The historical interruption cause remains unknown;
the original retrieval failure cause remains unproven.

V19 adds explicit extraction instructions for date-only lifecycle endpoint
objects, separate no-work assertions, and blocker work identity. Both schedule
discovery and selection now distinguish prevented work from adjacent progress.
These are candidate fixes; their semantic effectiveness is not yet established
by passing live acceptance. V18 and older prompt identities remain replayable.
V19 retains nullable-field, exact-evidence and clause normalization behavior.
Durable prompt-pinning tests cover V18 and V19 under both execution modes.

The mixed workload runner now accepts `--prompt-version` and pins it on report
jobs, recording its prompt and source hashes. Conversation orchestration retains
its own existing contract. A future sustained run must explicitly select V19;
a run using another extraction version cannot certify V19 report quality.

## Verification and live outcomes

436 unit tests and 199 PostgreSQL integration tests pass. Scoped Ruff and diff
checks pass. An initial sandboxed integration invocation could not connect to
PostgreSQL; the subsequent permitted invocation passed. Logs are retained in
`evaluation/results/release-completion-2026-10-17/v19-resumption/`.

The three provider-blocked wording cases were rerun with V19 in
`v19-wording-retry-v1/`. B19-03 passed. B19-04 received MODEL_RATE_LIMITED after
44.987 seconds of admission and 0.307 seconds of transport; provider retry-after
was approximately 673 seconds. B19-05 failed closed in admission with
MODEL_CAPACITY_TIMEOUT. These last two cases remain unverified semantically.

C06 and four other delivery matching cases were rerun in
`v19-delivery-retry-v1/`; all five were blocked in admission. No successful
matching result is claimed. No alternate provider, model or credential was used.
The retained queued conversation `244eab13-3d21-4ce6-acd5-d455e1492454` still
requires explicit inspection before another mixed rehearsal. It was not resumed
or cancelled by this work. No new sustained workload pass is claimed.

## Fresh cases and calibration

`data/evaluation/prototype-v19-v2/manifest.json` freezes eight validation and eight
holdout reports, each containing three events. Each split has eight disjoint
synthetic project groups, 24 events, one delivery and one ambiguity case, and
lifecycle endpoints with date/minute precision. Labels declare the same-session
AI authorship/review honestly. Scenario structures overlap across projects, so
this does not establish out-of-distribution or independent-review performance.
The earlier unsubmitted V19-v1 manifest remains as a superseded preparation
artifact; use V19-v2 only. Neither V19 split has been sent to the provider or
scored. The consumed original holdout is not new validation evidence.

The existing label-free estimator is unchanged and its hash is frozen with the
new inputs. The predeclared calibration policy remains precision 0.98, minimum
support 20. The new validation has enough potential atomic targets for event/link
support; missing predictions, mistakes, or cutoff selection may still leave
thresholds unsupported. No new scored evidence or usable thresholds are claimed.
Runtime confidence remains unavailable; neither calibration nor runtime score
validation is complete.

## Bounded component timings

`evaluation/approval_delivery_latency.py` measured 20 synthetic server endpoint
approvals, state reads and real HTTP MOCK PMIS deliveries, with one attempt and
verified receipts for every sample. Update p95 was 0.016826 seconds; verified
mock receipt p95 was 0.021234 seconds. The outer database transaction was rolled
back; savepoint commits exclude durable commit cost. Direct endpoint invocation
excludes browser/HTTP/auth, worker polling, and concurrent model workloads.
Consequently these measurements **do not meet or substitute for** the required
sustained acceptance/update or mock acknowledgement acceptance distributions.
The full raw samples, scope and source hashes are in `v19-component-latency-v1/`.

## Remaining release sequence

After provider capacity is available, rerun the remaining wording and delivery
checks in new directories. Capture and seal V19 validation before scoring it;
derive calibration only from validation. Keep the source and estimator fixed
before capturing holdout, then score it without tuning on its outcomes. A tuned
candidate needs another fresh holdout. Compare all approved quality targets,
including ambiguity and readiness; missing cases remain in denominators.

Inspect retained rehearsal work before starting the explicitly pinned V19 mixed
run. Measure successful sustained reports/conversations and full approval/update
and mock-delivery latency. Validate runtime confidence against the frozen study
before installing any review-priority thresholds. All proposals still require
authorized acceptance. Repeat affected checks, freeze accepted source/evidence
hashes and restart only after all required acceptance gates pass, then commit and
push the accepted release. None of those release completion actions is claimed
here. The original final-candidate source manifest describes an earlier snapshot;
use the separate V19 candidate source manifest for the new working tree.
