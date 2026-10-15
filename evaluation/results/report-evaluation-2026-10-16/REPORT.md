# Report evaluation and interruption investigation — 16 October 2026

Decision: keep hierarchy and model-assisted rollout disabled. Local fixes and controlled evidence are complete for this slice; independent semantic adjudication, extraction completeness and deployment-wide provider capacity remain acceptance gates.

## Scoring corrections without rewriting evidence

The original six-case capture remains unchanged. Its raw quantity score is still 2/4 per arm: one interrupted case and one planned amount cleared intentionally by normalization. Separate rescoring gives normalized quantity/effect safety 3/4; it does not erase the interrupted case or relabel the source planned quantity as actual work.

The new twelve-case capture initially used `report-scoring-v2`, which required literal quantity and unit equality after non-actual normalization. It exposed a second scoring mismatch: `0.5 t` is the same supported mass as the label's `500 kg`. `report-scoring-v3` now uses the existing production reducer's documented unit conversion rules. It still requires the correct event and delta/cumulative semantics, and rejects unsupported mass/volume conversions. Original v2 scores remain in the capture; v3 review output is stored separately.

No original labels were changed. Source notes in `evaluation/reviews/seed-source-review-2026-10-16.json` are explicitly technical review, not independent human adjudication. Event-unknown labels and operational reupload/correction/obsolete-schedule instructions are not treated as universal literal extraction truth. Prior lineage, accepted test records and real schedule changes require separate workflow tests.

## Broader paired runtime evidence

`live-paired-01/` contains C01, C03, C04, C05, C06, C07, C08, C12, C13, C14, C17 and C18 with the full twelve-activity seed schedule. Baseline Groq requests were live. V2 used deterministic orchestration and replayed specialist responses only after exact complete-payload fingerprint matching. There were no OpenRouter planner calls in this run. This measures runtime parity; it is not an independent v2 model-quality or comparative latency ranking.

| Check | Result in each arm |
| --- | --- |
| Ready for human review | 12/12 |
| Exact domain-output parity | 12/12 pairs |
| Legacy subset-based mapping metric | 12/12 |
| Exact activity-set and atomic-event coverage | 11/12 |
| Historical raw quantity score | 7/10 |
| Normalized quantity/effect score, v3 | 11/11 |
| Technically reviewed work dates | 7/9 |
| Unsupported persisted quote substrings | 0 |
| Terminal replay reuses outputs without duplicates | 24/24 executions |
| Ledger writes | 0 |
| Observed ownership-check failures | 0 |

All persisted proposals stayed pending. Baseline used 37 live requests; v2 replayed those 37 responses. No live request failed. Baseline median case time was 51.525 seconds, with 571.060 seconds of explicit quota pacing across the full baseline run. The sample is synthetic, already inspected and unadjudicated; it does not establish unseen quality or a latency service objective.

The stricter metrics expose remaining defects:

- **C05:** the model returned erected spools but omitted the separate welding/rain blocker. The old subset-based mapping score hid this incomplete extraction. Quantity correctness alone does not establish event completeness.
- **C03/C06:** planned work and material delivery correctly have no progress quantity/effect, but their normalized observations omit the source-supported future/report date. These are technical date-recall gaps, not evidence of unintended ledger effects.
- Quote-presence checks are not semantic support checks. Independent reviewers still need to adjudicate field support and scope.

## Date-safety fix

The old C18 capture accepted the body's 23 September date even though the trusted/header date was 21 September, without a warning. Extraction now removes conflicting current-day dates and lifecycle endpoints, preserves the physical assertion and quantity, and adds a reviewer-clarification warning. A `report_context` date must equal the trusted report date. Explicit historical work dates remain supported; arbitrary different dates in a fragment are not automatically treated as conflicts.

The new live C18 pair has `work_date=null`, no `effective_date` in its proposed quantity effect, and a blocking warning. PostgreSQL tests cover both graph versions and verify approval rejects the unresolved warning with zero ledger writes. Additional tests cover two contradictory source anchors without trusted metadata and model-declared conflicting dates. These narrow deterministic checks do not resolve every natural-language date ambiguity.

## Transport/lease investigation

The old C01 record shows a retrieval transport error after 52.290 seconds, including 22.578 seconds of pacing, followed by v1 `JOB_LEASE_LOST`. The original harness assigned a fifteen-minute lease but had no production heartbeat or ownership snapshots. Its short elapsed time does not establish ordinary expiry; the precise historical state/token change remains unproven.

The harness now uses the production heartbeat primitive in an independent thread and retains safe ownership snapshots: state, stage, attempts, token-match booleans and remaining lease seconds. Tokens and source bodies are not included. Exact replay of a transport failure now preserves its type instead of fabricating HTTP 599.

The investigation also found that v1's fixed `retrieve -> select` edge could overwrite a retrieval error with a missing-candidate `KeyError`/`AGENT_INTERNAL_ERROR`. Selection now carries the typed failure forward without invoking a model. Graph layout and stored version identities remain unchanged.

`lease-faults-01/` saves eight deterministic scenarios across v1/v2, direct execution with heartbeats and the actual worker. All four transport-only scenarios return `AGENT_TOOL_FAILED` with valid ownership through the checks. All four deliberate lease replacements return `JOB_LEASE_LOST` and cannot publish. None creates proposals or ledger entries. This separates the failure modes and improves future diagnosis; it does not retroactively prove the old interruption's cause.

## Evidence directories

- `original-capture-review-01/`: initial normalized v2 rescoring, retained.
- `original-capture-review-v3-02/`: current rescoring of the unchanged six-case capture.
- `live-paired-01/`: original live/replayed twelve-case capture, including original v2 scores and cleanup record.
- `live-paired-review-v3-01/`: current technical review, v3 scores and input/reference hashes.
- `lease-faults-01/`: controlled fault snapshots and summary.

The live capture began before the final error-preservation patch and the extra non-trusted/model-declared date guards were added. It exercises the earlier current-day conflict guard. Final regression tests exercise those later changes. No failed capture has been replaced, no source/label has been tuned to hide failures, and no production settings, migration or deployment was changed in this slice.

## Final validation

337 backend unit tests and 165 full PostgreSQL integration tests passed after the final changes. Ruff for changed runtime/provider/evaluation/tests and `git diff --check` passed. Both effective rollout flags were re-read as false. A scan of the 23 generated report/capacity artifact files found none of the configured credential values. No frontend implementation changed in this slice, so no new browser validation is claimed.
