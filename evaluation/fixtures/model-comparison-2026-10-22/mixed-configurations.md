# Qwen 3.8 27B — actual orchestration workflow results

22 October 2026. Completed under the owner's request to test actual orchestration and explicit instruction to rerun after an owner-reported network issue.

**All eight planned comparisons completed:** Qwen and GPT-OSS 120B each produced exact outcomes in 4/4 full V2 graph reports. Each model ran the same unambiguous and ambiguous synthetic reports with orchestration on key1/workers on key2, then the inverse assignment. Workers remained live GPT-OSS 20B throughout. This supersedes the earlier supervisor-only limitation; it does not retroactively change the prior frozen role-contract study.

| Measure | Qwen 3.8 27B | GPT-OSS 120B |
|---|---:|---:|
| Completed unique full-report comparisons | 4/4 | 4/4 |
| Exact report facts + mapping + approval boundary | 4/4 | 4/4 |
| Key1 exact completed reports | 2/2 | 2/2 |
| Key2 exact completed reports | 2/2 | 2/2 |
| Valid successful planner responses, including retained failed run's first response | 13 | 12 |
| Total planner attempts, including original network timeout | 14 | 12 |
| Median successful planner transport request | 0.324 s | 0.786 s |
| Reports meeting 120-second readiness target | 0/4 | 0/4 |

Qwen completed report times: 298.752, 298.384, 311.156, 309.997 seconds. 120B: 312.302, 337.533, 311.138, 340.781 seconds. Report time includes conservative pacing, provider admission, live worker calls and PostgreSQL/checkpoint work. Planner transport timing excludes the evaluator's pacing wait but includes provider admission. These are not pure inference or sustained-load p95 measurements; different arm positions and remaining quota also affect waits.

Both models preserved the unambiguous report's quantity, date, area, asset tag and correct activity. Both kept the under-specified report ambiguous with no selected activity. All completed reports reached `ready_for_review`, proposals remained pending, no progress-ledger writes occurred, and all eight terminal replays reused the result without duplicate proposals.

## Retained failure and owner-authorized rerun

The first window completed three reports, then Qwen/key2's second planner request raised `URLError` after approximately 75 seconds. That job failed safely as `AGENT_PLANNER_FAILED`; no final answer/usage is available for the interrupted request. The owner stated the failure was due to an issue on their side and explicitly requested a rerun. That attribution is owner supplied, not independently diagnosed as a provider or model fault.

A separately frozen rerun in a second fresh database completed the failed report on the same key plus the four previously unattempted comparisons. The original failed job, reservation, partial successful planner response and stopped capture remain retained. There were **nine attempted graph reports: eight successes and one retained network-failed attempt**. Qwen is 4/4 on completed unique comparisons and 4/5 across all report attempts; 120B is 4/4 across all attempts. No failure was redirected to another credential/model. Successful earlier reports were not rerun.

## Budget, isolation and implementation

Across both windows: **50 reserved HTTP attempts, 49 HTTP200 responses, 1 unknown-usage interruption; 51,369 known tokens**. Known list-price usage is **$0.00621347**, excluding unknown interrupted usage. Cumulative conservative cold reservation is **$0.50794880**, below the original **$1 / 96-call ceiling**. The rerun deducts the first window's entire reserved token/cost/call usage; its new 2,400-second window was explicitly authorized by the owner's rerun request. Prior role-study and batch32 unknown traffic are separate windows and are not included in this cost total. No complete-billing claim is made.

Fresh local databases: `progress_rehearsal_qwen_orchestrator_20261022` and `progress_rehearsal_qwen_orchestrator_rerun_20261022`; migrations at 0018. Test jobs and durable checkpoints remain in those databases. No approval, PMIS delivery, deletion of original work, service restart, `.env` edit or active role reassignment occurred. Shared application admission remained in effect, with additional cold-reservation pacing at 6,000 TPM/22 RPM per key.

`backend/app/agent/planner.py` now explicitly allows exact Groq model ID `qwen/qwen3.8-27b` alongside 120B. Tests verify both key slots preserve their configured model and reject malformed/unknown IDs and unsupported provider/model pairs. Enabling compatibility does not select Qwen in active settings. Existing source-pinned work continues to follow the repository's source-change/revalidation rules.

Verification: **224 focused agent/adapter/provider/configuration tests pass**; scoped Ruff passes. The initial unit command referenced a nonexistent test directory and ran no tests; that log and the corrected passing run are retained. Independent offline rescoring checks every saved report against frozen labels and every successful planner response through the actual `validated_decision` validator. Original capture manifests, source/input hashes, cumulative limits and duplicate-free completed comparisons are verified. Credentials are excluded from captured headers and checked against artifacts before delivery.

## Decision and limits

**Qwen works as an orchestrator in the actual bounded V2 graph on these cases and keys. It matches 120B's observed correctness.** Both miss the 120-second readiness target under this pacing regime; no model selection or production activation follows. The graph's planner confirms one supplied legal next supervisor; this is not autonomous multi-action planning, agentic coding or general tool-use evaluation. Two consumed AI-authored reports repeated across keys are not eight independent cases. Representative reports, independent human gold, fresh validation/holdout, repeated load, strict/tool capabilities and broader worker comparisons remain open.

Evidence: [combined quality summary — local archive](README.md#local-archive-provenance), [initial frozen plan — local archive](README.md#local-archive-provenance), [initial stopped summary](summary.json), [initial reports — local archive](README.md#local-archive-provenance), [initial HTTP calls — local archive](README.md#local-archive-provenance), [rerun frozen plan — local archive](README.md#local-archive-provenance), [rerun reports — local archive](README.md#local-archive-provenance), [rerun summary — local archive](README.md#local-archive-provenance). The [earlier role-contract evidence — local archive](README.md#local-archive-provenance) is unchanged.
