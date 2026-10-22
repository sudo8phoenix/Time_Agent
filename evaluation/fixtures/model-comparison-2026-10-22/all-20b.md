# All-GPT-OSS 20B two-account full-graph study

22 October 2026. All model roles use `openai/gpt-oss-20b`; orchestration on key1/workers on key2, then reversed. Same two consumed synthetic cases, schedule, V12 prompt, application schemas and pacing as the Qwen studies. Fresh isolated local `progress_rehearsal_gpt20_all_roles_20261022` PostgreSQL database at 0018.

**4/4 exact scoped full reports; 4/4 ready for review.** See the [combined summary — local archive](README.md#local-archive-provenance), [reports — local archive](README.md#local-archive-provenance), [HTTP captures — local archive](README.md#local-archive-provenance), [frozen plan — local archive](README.md#local-archive-provenance) and [schema diagnostics — local archive](README.md#local-archive-provenance). All captured roles/model IDs and distinct credential slots were independently verified; supervisor responses were run through the real decision validator. Failed attempts, if any, remain in the capture. No prompt tuning, model/key fallback or accepted alternate JSON shape.

Known usage: 26,515 tokens, estimated $0.00265643 list price; 0 unknown-usage calls. Conservative reservation $0.02035950 under $0.25 / 48 calls. No complete-billing or overall-project budget claim. No production assignment, approval, delivery or service restart. App compatibility changed only by adding exact 20B planner ID and tests; this build difference is archived.

226 focused agent/adapter/provider/configuration tests passed after that change. Scoped lint and capture/source/input/schema/output/accounting checks pass. These software tests are not model-quality trials. All relevant source and request settings remain retained. Successful terminal replay and ledger/review boundaries are in the machine-readable summary.

Timing includes conservative reservation waits and shared provider admission. 0/4 met the 120-second readiness target; two repeated cases cannot establish p95, representative accuracy or independent-account throughput. See the [complete comparison report — local archive](README.md#local-archive-provenance) for all models, prompting evidence and recommendations.
