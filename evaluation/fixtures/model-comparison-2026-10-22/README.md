# Published model-comparison evidence — 22 October 2026

This is a curated public/synthetic evidence bundle, exported from retained local studies. It contains no API keys, authorization headers, account identifiers, database URLs or private host paths. Synthetic internal UUIDs in persisted outcomes are replaced with placeholders. It is not the raw transport capture or a new holdout.

- `cases.json`, `labels.json`, `schedule.csv`: consumed AI-authored inputs and frozen expected scoped fields; both key assignments reuse the same two cases.
- `outcomes.json`: all 18 report attempts, including the original mixed-model network failure and original all-Qwen HTTP503. Independent full-report rescoring uses the app's scorer. Failed reports retain failure credit; successful reruns do not erase them.
- `summary.json`: four-configuration scorecard; latest planned comparison and all-attempt denominators are separate. Costs are known list-price estimates, not verified billing.
- `all-qwen-summary.json`, `all-20b-summary.json`, `mixed-summary.json`: detailed component/graph counts, budgets, safety boundaries and limitations.
- `all-qwen-schema-diagnostics.json`: two HTTP200 ordinary-selection replies omit the required six-field object. The simplified array test did not cover this contract.
- `prompt-catalog.json`: exact trusted system prompts and SHA256 digests. Schemas and report/schedule inputs were supplied separately.
- `prompt-evidence.json`: preserved batch-30 ablation records. Their `grounded_exact` metric is not the projected task or latest graph metric.
- `retained-transport-failures.json`: one owner-attributed network interruption and a separate HTTP503, both of unknown usage. They are not interchangeable causes.
- `public-pricing.json`: checked official source URLs/rates; no cache discount assumed.
- `checklist-inventory.json`: 269 local requirements, 231 checked/38 open; Qwen is uniquely MODEL-11. This inventory correction is not a new closure.

## Offline reproduction

From the repository root, after installing Python dependencies:

```sh
PYTHONPATH=backend:. .venv/bin/python -m evaluation.published_model_comparison
```

This makes no model/network/database calls. It verifies the publication manifest and prompt digests and re-evaluates every persisted report using `full_case_score`. It does not independently verify provider usage or recreate omitted raw transport requests. Those measurements are retained summaries, not newly measured data.

## Local archive provenance

`local-archive-hashes.json` identifies the original plan, capture manifest and reports by digest. Full transport bodies, request journals, frozen source snapshots, complete historical checklist and execution logs remain local under ignored paths. Public outcomes are intentionally sanitized derivatives; their bytes differ from the originals. The local source paths inside historical records are provenance labels, not files required in a fresh checkout.

Live study runners require explicit credentials, a fresh isolated local rehearsal database and a new output directory/budget. Their publication copies were made portable after the studies; they are not the original captured source hashes. Historical continuation/recovery modules preserve old schedules and require their local archives; they are not generic fresh-study commands. No production configuration was activated.

## Historical evidence

The [consolidated report](../../../docs/MODEL_AND_PROMPT_COMPARISON_REPORT.md) states the earlier prompt, model and planner results with their original caveats. Historical raw reviews, pilot scorecards and screenshots are not included here. They must not be presented as fresh holdout evidence or pooled into one model leaderboard. The full local checklist remains private; the maintained [comparison checklist](../../../docs/MODEL_COMPARISON_CHECKLIST.md) publishes the relevant dispositions.
