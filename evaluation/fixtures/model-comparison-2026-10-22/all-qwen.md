# All-Qwen two-account full-graph evaluation

22 October 2026. Qwen `qwen/qwen3.8-27b` handled orchestration, extraction, retrieval and selection. Planner and workers used distinct owner-confirmed accounts, then swapped keys, on the same two consumed synthetic reports as the mixed-model study. No active assignment changed.

**All four planned comparisons were attempted; 2/4 passed scoped full-report checks.** Both ambiguity cases passed; both unambiguous cases failed at final selection on HTTP200 responses that did not match the six-field application schema. One invalid response used a `suggested` wrapper; the other used `decision`, `candidate_id` and `evidence`. All 12 successful supervisor responses passed the real decision validator. The failure is downstream worker compatibility, not evidence that Qwen cannot confirm a supervisor stage.

The initial window stopped on selection HTTP503 after four earlier HTTP200s. After cooldown, one separately frozen same-key rerun attempted the four planned comparisons. It retained the HTTP503 and all original reservations. Five total report attempts: two successful ambiguity reports, two content/schema-failed unambiguous reports and the initial endpoint-failed report. No automatic key/model fallback, prompt tuning or acceptance of an alternate JSON shape occurred.

Across both windows: 27 HTTP attempts, 26 HTTP200s, 24 schema-valid responses; 20,151 known tokens; known list-price usage $0.02283120, one failed request's usage unknown. Cumulative conservative reservation $0.28566400 remains below the original $1 / 48-call ceiling. The new window deducts all prior reservations. These totals exclude earlier studies and are not verified billing.

All-Qwen success times: 324.806s and 341.412s, both above the 120-second readiness target under conservative pacing/shared provider admission. These do not measure intrinsic inference or sustained-load p95. Neither successful run wrote progress ledger entries; proposals stayed pending; terminal replay reused outcomes without duplicate proposals. Failed runs also made zero ledger writes.

Separate-role key/model checks, full response-schema rescoring, frozen source/capture/input checks and exact report rescoring pass. 28 focused planner/adapter/provider tests passed before this study; they are software controls, not model accuracy scores. The first offline rescore used a model-only lookup for supervisor requests, which incorrectly included same-model workers; it was corrected to select the action schema and rerun offline. Original live captures were unchanged.

The pre-20B-allowlist source build is archived under source-snapshot in both windows. Later adding 20B planner compatibility does not rewrite this experiment. No production `.env` edit, service restart, approval or PMIS delivery occurred.

**Decision:** All-Qwen is not a reliable drop-in for the current full selection contract. The earlier simplified selection 8/8 result does not establish current application compatibility. A full-object example, explicit root-field instruction, Qwen mode control or strict schema are potential separately controlled follow-ups, not measured fixes. Two repeated synthetic inputs do not establish a population ranking.

Evidence: [combined summary — local archive](README.md#local-archive-provenance), [schema diagnostics — local archive](README.md#local-archive-provenance), [initial plan — local archive](README.md#local-archive-provenance), [initial calls — local archive](README.md#local-archive-provenance), [initial stopped summary](summary.json), [rerun plan — local archive](README.md#local-archive-provenance), [rerun reports — local archive](README.md#local-archive-provenance), [rerun summary — local archive](README.md#local-archive-provenance).
