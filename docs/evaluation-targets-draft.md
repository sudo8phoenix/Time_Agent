# E02 proposed acceptance targets — awaiting owner/reviewer agreement

These targets are a draft prepared before any new E02 held-out outcomes. They are not agreed, calibrated or achieved. Independent reviewers must confirm event alignment/labels, scope and temporal semantics; freeze the leakage-aware split and record approval before running unseen evaluation. Targets can be revised now, but must not be tuned against held-out outcomes afterward.

| Measure | Proposed target | Required denominator/basis |
| --- | --- | --- |
| Hard safety | Zero invented accepted times, cross-project writes, duplicate applications, impossible chronology or unintended parent completions | All safety cases including failures/retries/concurrent requests |
| Atomic event extraction | F1 ≥ 0.90 | Independently aligned atomic events; full failed/abstained case accounting |
| Selected activity links | Precision ≥ 0.98, coverage ≥ 0.80 | All initial model selections, including false matches on ambiguous/unmatched cases |
| Candidate recall at 8 | ≥ 0.95 | Independently matchable events with actual saved candidate IDs |
| Endpoint date/time/precision | Exact accuracy ≥ 0.95 per field | Date-only endpoints included; unknown fields excluded explicitly |
| Safe ambiguity/unmatched handling | ≥ 0.95 | Independently ambiguous/unmatched events |
| Model proposal readiness | p95 ≤ 120 seconds | Submission to proposal-ready, system time; count failed/timeouts separately |
| Acceptance to internal update | p95 ≤ 2 seconds | Authorization request to durable commit, no human review wait |
| Mock destination acknowledgement | p95 ≤ 10 seconds without retry | Durable acceptance to verified read-back; retry strata separately |

Report p50/p95/max/counts, all failure counts, source format/discipline strata, project-macro and activity/event-micro scores, reviewer corrections and review burden. Small denominators require disclosure; do not claim a target passed from a single smoke case. Report wall submission-to-update separately from system stages, human wait and retry delays. Final reviewer-corrected state must not be substituted for initial-model accuracy.

Pending agreement: named owner/reviewer, timestamp, approved targets hash, frozen model/config and split/label hashes. No agreement is inferred from this document or from elapsed time.
