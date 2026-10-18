# V19 live acceptance follow-up — 17 October 2026

> Historical record: statements and instructions below apply to the recorded stage.
> [Current status — 18 October](current-status.md) and the
> [latest V20 follow-up](release-followup-2026-10-18.md) supersede its operational
> status. Both V19 splits are consumed; release remains unaccepted.

Release acceptance remains incomplete. The current provider/model is retained
at the user's request. Waiting out cooldowns has permitted more live checks but
has not established sustained capacity. Earlier failed captures remain intact.
All 98 application-source files matched the V19 candidate manifest during V19
capture and scoring. An opt-in V20 matching candidate was prepared afterward;
the runtime default and rollout flags have not changed.

## Component checks

B19-04 passed in `v19-wording-retry-v3/`; B19-05 passed in
`v19-wording-retry-v4/`. Earlier rate-limited attempts remain failures in their
captures. C06, DM-03, DM-04 and DM-05 passed in `v19-delivery-retry-v2/`.
The ambiguous DM-04/DM-05 cases abstained without progress effects.
DM-02 failed there and in separate diagnostic retries. Its diagnostic response
was HTTP 200 but combined pieces of different supplied UUIDs; local schema
validation rejected the invented ID. This is a response-validity failure,
not a rate limit or a successful match. No validation guard was relaxed.

## Fresh validation

`v19-validation-v1/` captured all eight frozen V19-v2 validation reports before
labels were scored. `v19-validation-scored-v1/` verifies capture/input/label
hashes and retains every case in denominators. Three reports reached review;
five failed following a renewed 429 and admission blocks. No proposal was approved.

| Metric | Result | Approved minimum/maximum |
|---|---:|---:|
| Initial atomic-event F1 | 0.667 | ≥0.90 |
| Normalized atomic-event F1 | 0.452 | ≥0.90 |
| Selected-link precision | 1.000 (6/6) | ≥0.98 |
| Selected-link coverage | 0.261 (6/23) | ≥0.80 |
| Candidate Recall@8 | 0.348 (8/23) | ≥0.95 |
| Initial endpoint field accuracy | 0.500 (12/24) | ≥0.95 |
| Normalized endpoint field accuracy | 0.375 (9/24) | ≥0.95 |
| Safe ambiguity handling | 0/1 | ≥0.95 |
| Readiness p95 among completed reports | 143.892 seconds | ≤120 seconds |

Failed reports remain explicit failures; their short fail-closed timings are
not successful readiness samples. The reservoir report loses two observations
because their evidence adds a repeated location prefix absent from the quoted
source substring. The tramway report retains its no-work event and all three
correct links but takes 143.892 seconds. Grain-terminal retains three events
and all candidates, selects two correct links, and takes 127.531 seconds.
These bounded successes do not establish a passing quality/readiness result.

## Calibration and runtime confidence

The unchanged predeclared policy is precision 0.98 and minimum support 20.
Scoring supplies 24 atomic validation targets but only seven emitted event
predictions and six selected-link predictions. Event/link thresholds remain
null. The field study has 21 correct emitted field targets at cutoff 0.5 and
17.5% coverage of 120 field targets. These fields are clustered within seven
events; this does not establish probability or deployment calibration.

`v19-capacity-resumption-v2/runtime-confidence-audit.json` inspects all seven
persisted observations. Extraction/link scores are null and unavailable in
every case. This confirms the absent runtime estimator; it does not validate
non-null runtime confidence. No threshold was installed.

## Untouched V19 holdout

After the validation cooldown expired, `v19-holdout-v1/` submitted the unchanged
V19 application and estimator against the eight frozen holdout reports. The
first request received HTTP 429; seven subsequent reports failed in admission.
The capture was sealed before `v19-holdout-scored-v1/` opened labels. There are
zero ready reports and 24 missing events: initial/normalized F1, link coverage,
candidate recall, endpoint accuracy and ambiguity handling are all zero.
Selected-link precision and readiness p95 are unavailable because no prediction
or ready report exists. These are retained failed acceptance outcomes; there is
no successful holdout semantic evidence. The holdout is now consumed for
evaluation, and its labels must not tune a later candidate.

## Full browser and mock-delivery measurement

The new `evaluation/full_approval_delivery_latency.py` and
`evaluation/browser_delivery_latency.mjs` seed synthetic pending lifecycle
proposals, drive actual browser login and approval clicks, verify state through
authenticated HTTP after durable commits, and wait for automatic connector
polling and real HTTP MOCK PMIS read-back. Fixture users are deactivated after
each run. Seeded proposals do not demonstrate live extraction accuracy.

The 20 samples in `v19-browser-latency-v1/`, spaced 15 seconds apart, all passed
with verified one-attempt deliveries: update p95 0.115462 seconds and mock
read-back p95 0.571742 seconds. Unlike the earlier component timing, this includes
browser/HTTP/authentication, ordinary commit and automatic connector polling.
After adding pending-work guards and timestamps, a second 20-sample verification
in `v19-browser-latency-verification-v2/` also passed: update p95 0.106806 seconds
and mock read-back p95 0.417908 seconds. The repeat is a short burst.

These measurements satisfy the numerical 2-second / 10-second limits for the
isolated synthetic approval workload. They do not certify latency with reports
and conversations sharing the same application database and API under sustained
model load. They cannot clear the overall sustained-operation gate.

## Retained work and release disposition

The retained conversation `244eab13-3d21-4ce6-acd5-d455e1492454` was inspected.
After its original deadline elapsed, normal runtime `claim` marked it failed
with `CONVERSATION_BUDGET_EXHAUSTED`, preserving one attempt and one model call.
No inference, budget reset or checkpoint deletion occurred. The disposition
is recorded in `v19-capacity-resumption-v2/retained-task-disposition.json`.

After the next cooldown expired, the explicitly pinned V20 two-worker mixed
attempt stopped after 2.820 seconds on failed work and renewed provider cooldown
above 90 seconds. The report failed; conversation
`22d2b979-b4ce-44bc-833e-b31cad4f22da` remains queued with one attempt and one
model-call reservation, no successful checkpoint, no lease, next attempt at
15:44:37 UTC and original deadline 16:03:50 UTC. Both workers exited code 0.
The ledger retained its two pre-existing events and rollout flags stayed false.
`v20-mixed-workload-v1/final-inspection-v2.json` records the inspected state;
it corrects a SQL-null versus JSON-null completion predicate in the first
inspection without changing any row. Inspect this retained task before any
explicit resume. No worker was left running against the rehearsal database.

This is another failed sustained-operation attempt. No accepted-source freeze,
accepted restart, commit or push is claimed. V20 needs fresh quality/readiness
and calibration evidence; a later candidate needs a fresh holdout after the
current V19 holdout has been evaluated.

## Opt-in V20 matching candidate

The DM-02 response-validity failure motivated a separate request-local short-ID
contract. V20 keeps V19 extraction instructions and normalization, but sends
`row1`, `row2`, etc. as structured schedule IDs during discovery and selection.
Exact validated lookup maps these back to the loaded pinned activity UUIDs.
External activity IDs, source quotes, observation facts and evidence IDs remain
unchanged. Unknown IDs still fail closed. Schema limits and the discovery byte
bound remain enforced. A later selection repair reuses the same alias mapping.

V18/V19 retain their original wire requests. V20 is explicit opt-in under
`extraction-v20-short-schedule-ids`, with selection provenance
`agent-schedule-v3-short-ids`. Its source snapshot is a candidate record, not an
accepted release freeze. Tests cover round trips, source/evidence preservation,
invalid IDs, discovery batching and selection repair. Current checks pass 444
unit tests, 14 prompt-pinning integration cases across both execution modes,
and the full 201-case PostgreSQL integration suite. V19 evaluation
does not certify V20. Its confidence, quality, readiness and sustained-operation
gates remain open.

After waiting out the holdout's approximately 17-minute provider cooldown,
`v20-delivery-dm02-v1/` passed DM-02 in 26.027 seconds, with two successful
Groq calls, exact short-ID lookup back to `PIP-B-ERECT-024`, pending review
and no progress effects. Immediately afterward, BM-01 received HTTP 429 with
a 412-second retry delay; BM-02/BM-03 failed in admission. The three supplied
blocker observations remain semantically unverified in
`v20-blocker-matching-v1/`. The monitored cooldown expired before the DM-02
attempt; waiting did not establish sustained capacity. No alternative model,
provider or key slot was used.

The user subsequently authorized all three configured Groq keys if needed and
confirmed that they belong to the same organization. Read-only model-listing
checks authenticated all three distinct keys with HTTP 200 and the configured
model present. [Groq rate limits](https://console.groq.com/docs/rate-limits)
apply at organization level; these keys do not supply three independent quotas.
Shared admission/cooldown enforcement is retained. No rate-limit fallback to
another key is introduced. `v19-capacity-resumption-v2/three-key-preflight.json`
and `v19-capacity-resumption-v2/three-key-scope.json`
record authentication and scope separately without storing credentials.

## Smaller live groups

The user subsequently requested groups of at most five live tests. The live
extraction, matching and frozen-report capture runners now default to five cases
per group, wait at least 60 seconds between groups, and check the shared provider
cooldown before every case, including the first. New requests wait out an
observed 429 instead of immediately failing the remaining cases in admission.
Requests retain their existing finite timeouts, zero transport retries and key
assignments. A pacing wait beyond 1800 seconds fails closed with a partial
capture; incomplete coverage cannot pass the sealed scorer.

`pacing.jsonl` records scheduled pre-submission waits separately from component
or enqueue-to-review timings. Deliberately spaced submissions do not certify
concurrent throughput. Six new pacing tests and the seven targeted capture/scoring
tests pass. `v20-candidate-source-v3.json` records the executable source including
this evaluation policy; it is not an accepted release manifest.

A single-case BM-01 retry in `v20-blocker-paced-bm01-v1/` waited 373.726 seconds
before submission and then passed in 25.340 seconds. It selected hydrotesting,
not adjacent spool erection, with pending review and no progress effects.
After a pause longer than 60 seconds, BM-02 received another HTTP 429 in
`v20-blocker-paced-bm02-bm03-v1/`, imposing a 615-second delay. BM-03 waited
614.975 seconds, completed retrieval, and then received HTTP 429 at selection
with a further 328-second retry delay. It has no successful matching outcome.
The paced capture records both BM-02 and BM-03 as failures. Smaller groups
have not established sufficient organization quota or sustained capacity.

Earlier failed batch captures and both consumed V19 split results remain
unchanged. Offline unit tests make no provider calls and do not consume quota.

## Current release decision

The release remains incomplete and unaccepted. Known wording B19-04/B19-05,
four V19 delivery cases including C06, DM-02 on opt-in V20 and the paced BM-01
blocker component have successful bounded live evidence. Broader blocker
matching remains provider-blocked. V19 fresh validation fails quality and
readiness; its holdout is consumed with eight provider-blocked failures.
V20 has no passing fresh validation/holdout or runtime confidence study.
The mixed workload fails sustained acceptance. Full isolated browser timings
meet numerical latency limits but have not been repeated under sustained
reports/conversations sharing the application database and API.

All failed captures remain retained. The historical interruption cause remains
unknown; the original historical retrieval failure remains unproven. No
accepted-source hash freeze, accepted-source restart, commit or push was done.

All capture directory references above are relative to
`evaluation/results/release-completion-2026-10-17/`.
