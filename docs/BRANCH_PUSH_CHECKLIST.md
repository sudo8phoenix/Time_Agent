# Branch push checklist — 26 October 2026

The reviewed push set contains **56 files** for the current provider, recovery and four-model comparison work. The working branch is `main`. This audit has not staged, committed or pushed files. Existing uncommitted changes remain in place.

The exact machine-readable list is [`branch-push-files.txt`](../artifacts/gonka-model-comparison/branch-push-files.txt). Use this explicit list instead of staging the entire workspace. It includes the earlier uncommitted runtime/recovery work on which the comparison depends; it does not claim those changes were all authored in this audit.

## Why these files belong together

- `provider.py`, settings and the planner now reference the new Gonka adapter; `openrouter.py`, hosted admission and database capacity support it. Omitting `gonka.py` leaves that provider unusable.
- `ops/run_worker.py` imports the new `jobs/admission.py`; worker/service changes forward the pre-claim callback. These must travel together.
- Groq failure classes, shared transport diagnostics, metrics, agent tools/nodes/runtime, safe API messages and frontend messages implement the same recovery behavior. They share edits with the provider work, so this checklist treats the current runtime diff as one dependency-complete set.
- Tests accompany the behavior changes, including explicit 128-token planning, 8112-token Groq limits, truncation categorization and the existing bounded correction. The integration test belongs in the push even though it was not rerun during this audit.
- Reports, their generator, safe results and exact input travel together. The five-row schedule `data/review/gt10-five-entry/schedule.csv` is already tracked and unchanged. No migration or dependency-lockfile change is required by this diff.

## Runtime and operator entry points (19)

```text
backend/app/agent/hierarchy.py
backend/app/agent/nodes.py
backend/app/agent/planner.py
backend/app/agent/runtime.py
backend/app/agent/tools.py
backend/app/api/endpoints/agent_runs.py
backend/app/jobs/admission.py
backend/app/jobs/service.py
backend/app/jobs/worker.py
backend/app/llm/capacity.py
backend/app/llm/gonka.py
backend/app/llm/groq.py
backend/app/llm/hosted.py
backend/app/llm/metrics.py
backend/app/llm/openrouter.py
backend/app/llm/provider.py
backend/app/settings.py
frontend/src/main.tsx
ops/run_worker.py
```

## Regression tests (10)

```text
backend/tests/integration/agent/test_model_assisted_runtime.py
backend/tests/unit/agent/test_failure_categories.py
backend/tests/unit/agent/test_hierarchy.py
backend/tests/unit/agent/test_planner_config.py
backend/tests/unit/agent/test_worker_entry.py
backend/tests/unit/test_groq_adapter.py
backend/tests/unit/test_hosted_completion_boundaries.py
backend/tests/unit/test_provider_metrics.py
backend/tests/unit/test_provider_roles.py
backend/tests/unit/test_recorded_generation_settings.py
```

## Documentation and configuration (18)

```text
.env.example
.gitignore
CHANGELOG.md
README.md
docs/BRANCH_PUSH_CHECKLIST.md
docs/CONFIGURATION.md
docs/FOUR_MODEL_ROLE_COMPARISON.md
docs/INTEGRATIONS.md
docs/MODEL_AND_PROMPT_COMPARISON_REPORT.md
docs/MODEL_QUALITY_SUMMARY.md
docs/OBSERVABILITY.md
docs/README.md
docs/TESTING_AND_QUALITY.md
docs/TROUBLESHOOTING.md
docs/gonka-role-comparison.md
docs/local-run.md
docs/model-generation-settings.md
docs/provider-capacity.md
```

## Curated comparison evidence and runners (9)

```text
artifacts/gonka-model-comparison/branch-push-files.txt
artifacts/gonka-model-comparison/completion-manifest.json
artifacts/gonka-model-comparison/four-model-matrix.json
artifacts/gonka-model-comparison/four_model_matrix.py
artifacts/gonka-model-comparison/groq-planner-comparison.json
artifacts/gonka-model-comparison/input.txt
artifacts/gonka-model-comparison/ranked-assignments.json
artifacts/gonka-model-comparison/role-run-result.json
artifacts/gonka-model-comparison/summarize_matrix.py
```

## Leave out of this push

- Private `.env` files, keys, caches, generated frontend output and local databases.
- `artifacts/gonka-model-comparison/CONTINUE.md`, the historical `run.py`, `role_run.py`, `groq_planner_comparison.py` runners and the initial DeepSeek/MiniMax/GLM raw captures. The two historical safe result JSON files are included because the maintained Gonka report links to them.
- Other `artifacts/` content, including Cloudflare/NVIDIA experiments, local run/recovery notes and DOCX files.
- Untracked `evaluation/batch36_*`, `batch39_audit.py`, conversation/judge capture audits, retrieval/transcription studies, `screened_operation.py`, and their five untracked unit-test files. They are separate evaluation work and were not audited as part of this provider/comparison push. Preserve them locally for a separate review.

## Documentation audit

Updated the root README and local runbook to the inspected Qwen / GPT-OSS 120B / GPT-OSS 20B profile. Added Gonka variables to `.env.example` and the configuration reference. Updated integrations, capacity, observability, troubleshooting, generation settings, testing, model comparison summaries, index and changelog. The model report now explicitly records DeepSeek and GPT120 selection at 30/30 each, versus 29/30 for Qwen and GPT20. Historical workflow results retain their original scope.

Two implementation limits are explicitly documented: Gonka has shared transport admission but is absent from the report queue pre-check and numeric provider-metrics collector. The latter two currently cover Groq/OpenRouter. DeepSeek planner retesting remains 0/3 under the 128-token contract. A configuration allowlist is not a reliability certification.

## Verification

- 204 focused unit tests passed across planner/hierarchy, worker admission, failure categories, provider roles, Groq generation, provider metrics and hosted completion/refusal/capacity boundaries.
- `npm run typecheck` passed in `frontend`.
- Scoped Python lint, diff whitespace, documentation local links, completion hashes and the 64-assignment/120-selection coverage were checked.
- No live provider calls, database integration run, browser test or fresh production frontend build was performed in this audit. Prior integration/build results remain historical evidence, not a new release certification.
- Selected files were checked for configured private secret values and common credential-token patterns without printing the values. This is a targeted check, not an exhaustive security audit.

## Stage the reviewed set when ready

```sh
git add --pathspec-from-file=artifacts/gonka-model-comparison/branch-push-files.txt
git diff --cached --stat
git diff --cached --check
```

These commands are provided for the next commit step; they were not executed by this audit. Before pushing, review the staged diff and choose the intended target branch.
