# Super VL report runtime evaluation

Rollout decision: keep disabled. This is local synthetic evidence with unadjudicated labels, not production acceptance.

| Check | Evidence |
| --- | --- |
| Independent live 60-activity report | Both arms ready for review; expected activity and quantity; zero ledger writes |
| Six-fixture controlled parity | Same terminal state, observations, chosen activities and effects on all six cases |
| Successful controlled cases | Five of six in both arms; first clear-match case had a transport/lease interruption |
| Ambiguous / unmatched / injection | Three of three safely abstained in both arms |
| Source-quote support | Zero unsupported persisted evidence quotes; this is not a semantic claim audit |
| Human approval | Every persisted proposal stayed pending; no ledger writes |
| Terminal replay | All ten successful controlled arm executions reused outputs without model calls or duplicate proposals |
| Baseline provider behavior | One transport failure retained in the six-fixture capture |

The larger independent live pair used 11 Groq requests for v1 and 11 Groq plus 3 Super VL planner requests for v2. Wall times were 202.487s and 221.691s. Explicit pacing waits were 193.174s and 210.182s, so these times primarily measure quota constraints. The two live specialist executions are separate samples, and one case cannot establish a quality or latency ranking.

The controlled fixture matrix uses the full original 12-activity schedule. Its candidate Groq calls are replayed only after exact full-payload fingerprint matching; Super VL planner calls are live. Candidate wall time is therefore excluded from comparative latency summaries. Failure category codes differed for the interrupted case (v1 lease-loss signal, v2 safe failure from replayed transport error), although both stopped with no proposals or ledger writes.

| Case | Scenario | V1 | V2 | Same domain outputs |
| --- | --- | --- | --- | --- |
| C01 | unambiguous_actual | failed | failed | True |
| C02 | ambiguous_match | ready_for_review | ready_for_review | True |
| C03 | future_plan_or_no_work | ready_for_review | ready_for_review | True |
| C16 | unmatched | ready_for_review | ready_for_review | True |
| C18 | messy_date_unit | ready_for_review | ready_for_review | True |
| C19 | injection_or_unreadable | ready_for_review | ready_for_review | True |

Label limitations: the raw quantity score is 2/4 in each controlled arm. One failure is the interrupted clear-match case. The other is planned work: the label retains a planned quantity, while the production extraction normalizer intentionally clears non-actual quantities and proposal effects remain empty. Empty extraction for injection and different event typing for unmatched work also make literal event-label scores unsuitable as an independently adjudicated acceptance gate. Dates and semantic field support need separate human review.

Captures are preserved separately; see README.md for diagnostics, original attempts and exact scopes. No failed first attempt has been silently replaced with a retry.

A separately preserved retry of the interrupted `C01` fixture (`seed-c01-retry-07/`) succeeded in both arms with the expected activity/quantity, no new model calls on terminal replay, no duplicate proposals, and zero ledger writes. The original six-fixture result remains five successes plus one failure; the retry is not substituted into that denominator. This establishes successful coverage of every selected scenario at least once, while retaining the observed interruption.

Local checks: 311 unit tests passed; 50 PostgreSQL agent integration tests passed; the browser status file passed 13 scenarios on later complete runs. Ruff and `git diff --check` passed. Browser startup timing was intermittently flaky in an initial run, and no speculative product fix was applied.

Next gates: independently review label conventions and semantic/date handling, complete durable conversation orchestration, and evaluate application-level provider capacity/retry policy before any controlled rollout. Both rollout flags remain false.
