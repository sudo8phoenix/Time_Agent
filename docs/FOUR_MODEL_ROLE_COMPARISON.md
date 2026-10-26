# Four-model role comparison — 26 October 2026

GPT-OSS 20B extraction is the most compact candidate that preserves all eight core facts in this one report. Qwen is the fastest observed legal planner. Under the disclosed compactness-first rubric, Qwen planning / GPT-OSS 20B extraction / Qwen selection ranks first; GPT-OSS 120B selection is effectively tied on elapsed time and handles DeepSeek’s extra records better. DeepSeek and GPT-OSS 120B selection each scored 30/30 across all extractor outputs; Qwen and GPT-OSS 20B each scored 29/30. DeepSeek extraction preserves more inspection and blocker detail, at the cost of ten selection calls rather than GPT20’s six. These are trial recommendations, not a production acceptance or a universal model ranking.

## Scope and reproducibility

Four planners × four extractors × four selectors produce 64 **composed** assignments. We measured three legal planner transitions per model, one extraction per model and every extractor–selector pair. We did not execute 64 independent graphs. Planner decisions merely confirm one supplied legal next stage and do not inspect report text. The fixed five-row candidate pool includes explicit source activity identifiers, making this an easy mapping task; it does not measure retrieval quality.

The source is `artifacts/gonka-model-comparison/input.txt`; schedule: `data/review/gt10-five-entry/schedule.csv`. Full validated observations, per-observation selection results, errors, timestamps and safe usage metadata are in `artifacts/gonka-model-comparison/four-model-matrix.json`. Selection explanations and reason codes were not retained by this runner; the saved selection outputs are activity, state, event/quantity, error and elapsed time. Failed raw generations were not retained; an invalid-JSON category does not establish whether syntax or local schema validation failed. Earlier six-event DeepSeek extraction and MiniMax trials are separate evidence.

PostgreSQL `progress_test` and Docker were unavailable during the original setup. No durable graph, retrieval, persistence, approval, ledger update or PMIS delivery was tested. No active model assignment or private key was changed. Gonka transport admission is supported, but its queue pre-claim check and numeric provider-metrics collection are not yet covered; those currently cover Groq/OpenRouter. Standalone call diagnostics here are separate from durable metrics.

Resume: `.venv/bin/python artifacts/gonka-model-comparison/four_model_matrix.py --retest-deepseek-planner --retry-transport-failures`. Completed work is skipped; the versioned planner retest preserves the initial results. Only explicit transport-failure rows are archived and retried with the flag; schema failures remain in the matrix. Calls retain all attempts and interruptions. Rebuild this report with `.venv/bin/python artifacts/gonka-model-comparison/summarize_matrix.py`.

Groq uses planner slot 1 and worker slot 2, with account scopes disabled. Shared header-aware admission and the 10.5-second Gonka gate apply. Calls use temperature zero, zero automatic retries and no fallback. Planner output budget is 128; extraction requests 4096; compact selection requests 768. Groq GPT-OSS reasoning is low; no explicit Gonka reasoning switch is sent. Gonka accepts a complete JSON fence and still enforces the requested schema. Its 4096 cap does not increase the planner’s explicit 128-token request.

Model identities: `qwen` = `groq` / `qwen/qwen3.8-27b`; `gpt120` = `groq` / `openai/gpt-oss-120b`; `gpt20` = `groq` / `openai/gpt-oss-20b`; `deepseek` = `gonka` / `deepseek-ai/DeepSeek-V4-Flash-0731`.

## Planner results

| Model | Legal stages | Intake / analysis / review (seconds) | Trial |
|---|---:|---|---|
| qwen | 3/3 | 0.16 / 0.323 / 0.38 | Original matrix |
| gpt120 | 3/3 | 2.883 / 2.569 / 2.678 | Original matrix |
| gpt20 | 3/3 | 2.531 / 2.589 / 2.472 | Original matrix |
| deepseek | 0/3 | 2.586 / 8.605 / 12.126 | Updated fence adapter |

DeepSeek’s initial planner trial passed 0/3 (two invalid JSON, one incomplete response). The updated-adapter retest is independently retained under `planner_retest_fenced_json_v1`; its failures must not be replaced by the successful extraction result. A planner failure makes the composed assignment unusable under this model-assisted contract. A larger planner budget would be a separate experiment, not a correction to this result.

## Extraction semantics

Eight core checks: (1) exactly 300 kg installed column reinforcement as a delta, (2) exactly 60 m² installed shuttering as a delta, (3) no column concrete placed, (4) no slab concrete placed, (5) staged 800 kg not counted as installed slab reinforcement, (6) no first-floor actual progress, (7) no whole-activity finish inferred, and (8) final inspection represented as inspection. All four outputs pass schema validation with no extraction validation errors. These are application-normalized observations, not raw generations: validators clear installed quantities on no-work, blocker, material-delivery and planned-work records and can clear unsupported dates. Core scores describe the combined extraction contract, not unaided model ability. Schema validity alone does not establish semantic correctness.

| Extractor | Rows | Core checks | Elapsed seconds | Review finding |
|---|---:|---:|---:|---|
| qwen | 6 | 7/8 | 3.953 | Final inspection is actual_progress/other; quantities and no-work facts are correct. Date guesses were removed by validation; warnings remain. |
| gpt120 | 8 | 8/8 | 78.224 | Inspection preserved; separate blocker rows retain both causes. Column-concrete blocker carries rebar_installation despite identifying SUP-GF-02, a work-type mismatch. |
| gpt20 | 6 | 8/8 | 70.905 | Six compact core events, inspection preserved. Blocker causes remain in text/evidence but structured blocker fields are null; column cause requires reading the quote. |
| deepseek | 10 | 8/8 | 49.361 | Three inspection rows, no-work rows and planned first-floor statement remain separate. Internal bar relocation is labeled material_delivery; column checks and final inspection may overlap. No installed 800 kg or first-floor progress is invented. |

Inspection/material/planned-work observed_status=completed refers to the event, not completion of a schedule activity. Every saved actual_finish and lifecycle_effects field is empty. DeepSeek material movement quantity was normalized to null; its 800 kg remains in the summary and evidence. GPT-OSS outputs use civil discipline where the schedule uses structural; successful mapping here does not certify discipline normalization.

## All 16 worker pairs

A correct identity is the source activity suffix shown in the observation appendix. DeepSeek observation 10 has no first-floor candidate and must abstain (null candidate with unmatched). Selecting a no-work activity identifies context; it does not approve installed progress. Pair scores therefore include this negative control.

| Extractor | Selector | Rows saved / expected | Valid proposals | Correct identities or abstentions | Selection seconds |
|---|---|---:|---:|---:|---:|
| qwen | qwen | 6/6 | 6 | 6/6 | 111.517 |
| qwen | gpt120 | 6/6 | 6 | 6/6 | 133.827 |
| qwen | gpt20 | 6/6 | 6 | 6/6 | 133.557 |
| qwen | deepseek | 6/6 | 6 | 6/6 | 165.844 |
| gpt120 | qwen | 8/8 | 8 | 8/8 | 156.784 |
| gpt120 | gpt120 | 8/8 | 8 | 8/8 | 177.249 |
| gpt120 | gpt20 | 8/8 | 8 | 8/8 | 177.936 |
| gpt120 | deepseek | 8/8 | 8 | 8/8 | 185.833 |
| gpt20 | qwen | 6/6 | 6 | 6/6 | 106.868 |
| gpt20 | gpt120 | 6/6 | 6 | 6/6 | 106.947 |
| gpt20 | gpt20 | 6/6 | 6 | 6/6 | 128.365 |
| gpt20 | deepseek | 6/6 | 6 | 6/6 | 125.058 |
| deepseek | qwen | 10/10 | 10 | 9/10 | 198.904 |
| deepseek | gpt120 | 10/10 | 10 | 10/10 | 221.318 |
| deepseek | gpt20 | 10/10 | 10 | 9/10 | 220.839 |
| deepseek | deepseek | 10/10 | 10 | 10/10 | 207.124 |

First-floor negative control (DeepSeek observation 10):

| Selector | Saved activity | State | Correct abstention |
|---|---|---|---|
| qwen | SUP-GF-01 | suggested | No |
| gpt120 | None | unmatched | Yes |
| gpt20 | None | unmatched | Yes |
| deepseek | None | unmatched | Yes |

Qwen’s suggested SUP-GF-01 for the first-floor statement is schema-valid but semantically wrong: no first-floor row exists in this pool. GPT-OSS 120B, 20B and DeepSeek correctly return unmatched. Separately, GPT-OSS 20B returns unmatched on DeepSeek observation 7 (bar relocation) instead of SUP-GF-04, giving that pair 9/10 overall. This is a conservative loss of identity recall, not an invented installation; the exact-identity scoring rule still counts it as a miss. GPT-OSS 120B and DeepSeek selection score 10/10 on DeepSeek extraction. This observation demonstrates why all proposals passing validation is insufficient for declaring a pair correct.


## Ranking all 64 composed assignments

Descriptive lexicographic ranking: complete legal planner and complete correct pair first; among nonpassing rows, legal planners precede failed planners; then higher core-check count; then fewer manually flagged secondary issues; then fewer extracted rows; then lower sum of planner + extraction + selection elapsed seconds; finally lower recorded token count. Secondary issue counts are Qwen 1 (inspection), GPT120 1 (blocker type), GPT20 1 (structured blocker loss), DeepSeek 2 (relocation label and potential inspection overlap). These subjective counts are disclosed rather than treated as calibrated accuracy. Latency is only a tie-breaker. Different priorities, especially structured blocker retention, can favor GPT120 or DeepSeek instead.

Each row reuses measured components; time and tokens are **composed totals**, not a fresh end-to-end measurement. Elapsed includes admission and cross-provider call order. Many Groq worker calls wait about 22 seconds; this cannot establish pure inference speed. Tokens are reported without prices or a dollar-cost ranking. Failed attempts and interruptions are excluded from successful-path token totals but remain in the call audit.

| Rank | Planner | Extractor | Selector | Contract/pair | Core | Secondary issues | Rows | Composed seconds | Successful-path tokens |
|---:|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | qwen | gpt20 | qwen | legal; 6/6 | 8/8 | 1 | 6 | 178.636 | 13503 |
| 2 | qwen | gpt20 | gpt120 | legal; 6/6 | 8/8 | 1 | 6 | 178.715 | 14703 |
| 3 | gpt20 | gpt20 | qwen | legal; 6/6 | 8/8 | 1 | 6 | 185.365 | 13947 |
| 4 | gpt20 | gpt20 | gpt120 | legal; 6/6 | 8/8 | 1 | 6 | 185.444 | 15147 |
| 5 | gpt120 | gpt20 | qwen | legal; 6/6 | 8/8 | 1 | 6 | 185.903 | 13993 |
| 6 | gpt120 | gpt20 | gpt120 | legal; 6/6 | 8/8 | 1 | 6 | 185.982 | 15193 |
| 7 | qwen | gpt20 | deepseek | legal; 6/6 | 8/8 | 1 | 6 | 196.826 | 14630 |
| 8 | qwen | gpt20 | gpt20 | legal; 6/6 | 8/8 | 1 | 6 | 200.133 | 14646 |
| 9 | gpt20 | gpt20 | deepseek | legal; 6/6 | 8/8 | 1 | 6 | 203.555 | 15074 |
| 10 | gpt120 | gpt20 | deepseek | legal; 6/6 | 8/8 | 1 | 6 | 204.093 | 15120 |
| 11 | gpt20 | gpt20 | gpt20 | legal; 6/6 | 8/8 | 1 | 6 | 206.862 | 15090 |
| 12 | gpt120 | gpt20 | gpt20 | legal; 6/6 | 8/8 | 1 | 6 | 207.400 | 15136 |
| 13 | qwen | gpt120 | qwen | legal; 8/8 | 8/8 | 1 | 8 | 235.871 | 18550 |
| 14 | gpt20 | gpt120 | qwen | legal; 8/8 | 8/8 | 1 | 8 | 242.600 | 18994 |
| 15 | gpt120 | gpt120 | qwen | legal; 8/8 | 8/8 | 1 | 8 | 243.138 | 19040 |
| 16 | qwen | gpt120 | gpt120 | legal; 8/8 | 8/8 | 1 | 8 | 256.336 | 20087 |
| 17 | qwen | gpt120 | gpt20 | legal; 8/8 | 8/8 | 1 | 8 | 257.023 | 19860 |
| 18 | gpt20 | gpt120 | gpt120 | legal; 8/8 | 8/8 | 1 | 8 | 263.065 | 20531 |
| 19 | gpt120 | gpt120 | gpt120 | legal; 8/8 | 8/8 | 1 | 8 | 263.603 | 20577 |
| 20 | gpt20 | gpt120 | gpt20 | legal; 8/8 | 8/8 | 1 | 8 | 263.752 | 20304 |
| 21 | gpt120 | gpt120 | gpt20 | legal; 8/8 | 8/8 | 1 | 8 | 264.290 | 20350 |
| 22 | qwen | gpt120 | deepseek | legal; 8/8 | 8/8 | 1 | 8 | 264.920 | 19910 |
| 23 | gpt20 | gpt120 | deepseek | legal; 8/8 | 8/8 | 1 | 8 | 271.649 | 20354 |
| 24 | gpt120 | gpt120 | deepseek | legal; 8/8 | 8/8 | 1 | 8 | 272.187 | 20400 |
| 25 | qwen | deepseek | deepseek | legal; 10/10 | 8/8 | 2 | 10 | 257.348 | 24034 |
| 26 | gpt20 | deepseek | deepseek | legal; 10/10 | 8/8 | 2 | 10 | 264.077 | 24478 |
| 27 | gpt120 | deepseek | deepseek | legal; 10/10 | 8/8 | 2 | 10 | 264.615 | 24524 |
| 28 | qwen | deepseek | gpt120 | legal; 10/10 | 8/8 | 2 | 10 | 271.542 | 24275 |
| 29 | gpt20 | deepseek | gpt120 | legal; 10/10 | 8/8 | 2 | 10 | 278.271 | 24719 |
| 30 | gpt120 | deepseek | gpt120 | legal; 10/10 | 8/8 | 2 | 10 | 278.809 | 24765 |
| 31 | qwen | qwen | qwen | legal; 6/6 | 7/8 | 1 | 6 | 116.333 | 13043 |
| 32 | gpt20 | qwen | qwen | legal; 6/6 | 7/8 | 1 | 6 | 123.062 | 13487 |
| 33 | gpt120 | qwen | qwen | legal; 6/6 | 7/8 | 1 | 6 | 123.600 | 13533 |
| 34 | qwen | qwen | gpt20 | legal; 6/6 | 7/8 | 1 | 6 | 138.373 | 14172 |
| 35 | qwen | qwen | gpt120 | legal; 6/6 | 7/8 | 1 | 6 | 138.643 | 14269 |
| 36 | gpt20 | qwen | gpt20 | legal; 6/6 | 7/8 | 1 | 6 | 145.102 | 14616 |
| 37 | gpt20 | qwen | gpt120 | legal; 6/6 | 7/8 | 1 | 6 | 145.372 | 14713 |
| 38 | gpt120 | qwen | gpt20 | legal; 6/6 | 7/8 | 1 | 6 | 145.640 | 14662 |
| 39 | gpt120 | qwen | gpt120 | legal; 6/6 | 7/8 | 1 | 6 | 145.910 | 14759 |
| 40 | qwen | qwen | deepseek | legal; 6/6 | 7/8 | 1 | 6 | 170.660 | 14143 |
| 41 | gpt20 | qwen | deepseek | legal; 6/6 | 7/8 | 1 | 6 | 177.389 | 14587 |
| 42 | gpt120 | qwen | deepseek | legal; 6/6 | 7/8 | 1 | 6 | 177.927 | 14633 |
| 43 | qwen | deepseek | qwen | legal; 9/10 | 8/8 | 2 | 10 | 249.128 | 22201 |
| 44 | gpt20 | deepseek | qwen | legal; 9/10 | 8/8 | 2 | 10 | 255.857 | 22645 |
| 45 | gpt120 | deepseek | qwen | legal; 9/10 | 8/8 | 2 | 10 | 256.395 | 22691 |
| 46 | qwen | deepseek | gpt20 | legal; 9/10 | 8/8 | 2 | 10 | 271.063 | 24020 |
| 47 | gpt20 | deepseek | gpt20 | legal; 9/10 | 8/8 | 2 | 10 | 277.792 | 24464 |
| 48 | gpt120 | deepseek | gpt20 | legal; 9/10 | 8/8 | 2 | 10 | 278.330 | 24510 |
| 49 | deepseek | gpt20 | qwen | planner failed; 6/6 | 8/8 | 1 | 6 | 201.090 | 13366 |
| 50 | deepseek | gpt20 | gpt120 | planner failed; 6/6 | 8/8 | 1 | 6 | 201.169 | 14566 |
| 51 | deepseek | gpt20 | deepseek | planner failed; 6/6 | 8/8 | 1 | 6 | 219.280 | 14493 |
| 52 | deepseek | gpt20 | gpt20 | planner failed; 6/6 | 8/8 | 1 | 6 | 222.587 | 14509 |
| 53 | deepseek | gpt120 | qwen | planner failed; 8/8 | 8/8 | 1 | 8 | 258.325 | 18413 |
| 54 | deepseek | gpt120 | gpt120 | planner failed; 8/8 | 8/8 | 1 | 8 | 278.790 | 19950 |
| 55 | deepseek | gpt120 | gpt20 | planner failed; 8/8 | 8/8 | 1 | 8 | 279.477 | 19723 |
| 56 | deepseek | gpt120 | deepseek | planner failed; 8/8 | 8/8 | 1 | 8 | 287.374 | 19773 |
| 57 | deepseek | deepseek | qwen | planner failed; 9/10 | 8/8 | 2 | 10 | 271.582 | 22064 |
| 58 | deepseek | deepseek | deepseek | planner failed; 10/10 | 8/8 | 2 | 10 | 279.802 | 23897 |
| 59 | deepseek | deepseek | gpt20 | planner failed; 9/10 | 8/8 | 2 | 10 | 293.517 | 23883 |
| 60 | deepseek | deepseek | gpt120 | planner failed; 10/10 | 8/8 | 2 | 10 | 293.996 | 24138 |
| 61 | deepseek | qwen | qwen | planner failed; 6/6 | 7/8 | 1 | 6 | 138.787 | 12906 |
| 62 | deepseek | qwen | gpt20 | planner failed; 6/6 | 7/8 | 1 | 6 | 160.827 | 14035 |
| 63 | deepseek | qwen | gpt120 | planner failed; 6/6 | 7/8 | 1 | 6 | 161.097 | 14132 |
| 64 | deepseek | qwen | deepseek | planner failed; 6/6 | 7/8 | 1 | 6 | 193.114 | 14006 |

## Successful-call latency and token summary

These aggregates include admission and are grouped across different inputs. Counts are operations; an operation may contain more than one provider attempt if the selector asks for a consistency correction. Failed operations are excluded here and retained in the audit.

| Model | Role | Successful operations | Median seconds | Total seconds | Prompt / completion / total tokens |
|---|---|---:|---:|---:|---|
| qwen | orchestrator | 3 | 0.323 | 0.863 | 112 / 25 / 137 |
| qwen | extraction | 1 | 3.953 | 3.953 | 2384 / 1602 / 3986 |
| qwen | selection | 30 | 21.925 | 574.073 | 41021 / 3019 / 44040 |
| gpt120 | orchestrator | 3 | 2.678 | 8.130 | 457 / 170 / 627 |
| gpt120 | extraction | 1 | 78.224 | 78.224 | 3422 / 2998 / 6420 |
| gpt120 | selection | 30 | 22.155 | 639.341 | 45215 / 4862 / 50077 |
| gpt20 | orchestrator | 3 | 2.531 | 7.592 | 457 / 124 / 581 |
| gpt20 | extraction | 1 | 70.905 | 70.905 | 3422 / 1505 / 4927 |
| gpt20 | selection | 30 | 22.259 | 660.697 | 45215 / 4226 / 49441 |
| deepseek | orchestrator | 0 | — | — | — |
| deepseek | extraction | 1 | 49.361 | 49.361 | 4463 / 2913 / 7376 |
| deepseek | selection | 30 | 19.430 | 683.859 | 46103 / 3357 / 49460 |

## Recommendation and limits

Use the first fully passing row above as the trial candidate under this explicit rubric. Treat near-identical composed times as ties in practice: the GPT20-extraction pairs using Qwen and GPT120 selection differ by only 0.079 seconds, far below what this single paced trial can resolve. Qwen planning with GPT-OSS 20B extraction is the compact candidate; choose the selector using the measured pair result. GPT120 extraction retains structured blockers at the expense of two extra rows and a blocker work-type error. DeepSeek extraction preserves more ancillary events but increases selection calls from six to ten, including a necessary first-floor abstention. Qwen extraction needs correction of the inspection event. DeepSeek model-assisted planning is not recommended under the tested 128-token contract.

The privately configured profile checked on 26 October is Qwen orchestrator (Groq slot 1), GPT-OSS 120B extractor (Groq slot 2), GPT-OSS 20B selector (Groq slot 2), V2/model-assisted enabled and account scopes disabled. This report does not change it. Trial recommendations require repeated reports, ambiguous identifiers, missing candidates, full retrieval, database-backed graph execution and human review before deployment selection.

One report, one extraction per model and one completed trial per pair cannot establish significance, robustness, stable latency or universal superiority. Eight to ten correlated rows from one report are not independent evaluation samples. There was no randomized call order or frozen preregistered scoring rubric. Changes to the adapter occurred between initial and retest planner trials. Raw wire payloads and call-time source hashes were not saved, limiting exact reproduction. `artifacts/gonka-model-comparison/completion-manifest.json` fingerprints the source, schedule, runner, adapters and result at report generation only; it does not attest earlier call-time code. No provider price assumptions are made.

## Full validated observation summaries and selections

The JSON artifact retains every observation field and evidence quote. Below are all event summaries and every saved selection as activity / state / error; safe call diagnostics follow. This is not a dump of failed raw model generations.

### qwen

1. `actual_progress` / `rebar_installation` / `in_progress`; quantity `300` `kg`, kind `delta`; expected `01`. Installed 300 kg of column reinforcement at SUP-GF-01; activity remains in progress.

   - qwen: `SUP-GF-01` / `suggested` / `None` (0.504s)
   - gpt120: `SUP-GF-01` / `suggested` / `None` (22.456s)
   - gpt20: `SUP-GF-01` / `suggested` / `None` (21.931s)
   - deepseek: `SUP-GF-01` / `suggested` / `None` (2.839s)

2. `actual_progress` / `formwork` / `in_progress`; quantity `60` `m2`, kind `delta`; expected `03`. Installed 60 m2 of slab shuttering at SUP-GF-03; activity remains in progress.

   - qwen: `SUP-GF-03` / `suggested` / `None` (22.518s)
   - gpt120: `SUP-GF-03` / `suggested` / `None` (22.425s)
   - gpt20: `SUP-GF-03` / `suggested` / `None` (22.241s)
   - deepseek: `SUP-GF-03` / `suggested` / `None` (43.937s)

3. `no_work` / `concrete_pour` / `not_started`; quantity `None` `None`, kind `none`; expected `02`. No column concrete placed at SUP-GF-02; pour postponed due to reinforcement and formwork not ready for inspection.

   - qwen: `SUP-GF-02` / `suggested` / `None` (22.04s)
   - gpt120: `SUP-GF-02` / `suggested` / `None` (22.156s)
   - gpt20: `SUP-GF-02` / `suggested` / `None` (22.363s)
   - deepseek: `SUP-GF-02` / `suggested` / `None` (2.336s)

4. `no_work` / `rebar_installation` / `not_started`; quantity `None` `None`, kind `none`; expected `04`. Slab reinforcement installation at SUP-GF-04 has not started; 800 kg of bars moved to staging area but not installed.

   - qwen: `SUP-GF-04` / `suggested` / `None` (22.301s)
   - gpt120: `SUP-GF-04` / `suggested` / `None` (22.451s)
   - gpt20: `SUP-GF-04` / `suggested` / `None` (22.435s)
   - deepseek: `SUP-GF-04` / `suggested` / `None` (37.125s)

5. `no_work` / `concrete_pour` / `not_started`; quantity `None` `None`, kind `none`; expected `05`. No slab concrete placed at SUP-GF-05; pour prevented by waterlogged access path.

   - qwen: `SUP-GF-05` / `suggested` / `None` (22.002s)
   - gpt120: `SUP-GF-05` / `suggested` / `None` (22.185s)
   - gpt20: `SUP-GF-05` / `suggested` / `None` (22.309s)
   - deepseek: `SUP-GF-05` / `suggested` / `None` (33.007s)

6. `actual_progress` / `other` / `in_progress`; quantity `None` `None`, kind `none`; expected `01`. Engineer inspected column reinforcement at SUP-GF-01; no first-floor work performed.

   - qwen: `SUP-GF-01` / `suggested` / `None` (22.152s)
   - gpt120: `SUP-GF-01` / `suggested` / `None` (22.154s)
   - gpt20: `SUP-GF-01` / `suggested` / `None` (22.278s)
   - deepseek: `SUP-GF-01` / `suggested` / `None` (46.6s)

### gpt120

1. `actual_progress` / `rebar_installation` / `in_progress`; quantity `300` `kg`, kind `delta`; expected `01`. The steel fixing crew installed an additional 300 kg of column reinforcement today. This is today's quantity, not the cumulative total. Bar spacing and concrete cover were checked by the site engineer. Column reinforcement remains in progress; the entire activity is not complete.

   - qwen: `SUP-GF-01` / `suggested` / `None` (0.615s)
   - gpt120: `SUP-GF-01` / `suggested` / `None` (21.382s)
   - gpt20: `SUP-GF-01` / `suggested` / `None` (21.985s)
   - deepseek: `SUP-GF-01` / `suggested` / `None` (3.185s)

2. `actual_progress` / `formwork` / `in_progress`; quantity `60` `m2`, kind `delta`; expected `03`. 2. Slab Shuttering — SUP-GF-03: The formwork crew installed an additional 60 m2 of ground-floor slab shuttering today. This is today's installed area. The crew checked panel alignment and support stability in the completed portion. Shuttering remains in progress, with further areas pending installation.

   - qwen: `SUP-GF-03` / `suggested` / `None` (22.153s)
   - gpt120: `SUP-GF-03` / `suggested` / `None` (23.06s)
   - gpt20: `SUP-GF-03` / `suggested` / `None` (22.107s)
   - deepseek: `SUP-GF-03` / `suggested` / `None` (10.288s)

3. `no_work` / `concrete_pour` / `not_started`; quantity `None` `None`, kind `none`; expected `02`. 3. Column Concreting — SUP-GF-02: No column concrete was placed today. The planned pour was postponed because the remaining column reinforcement and formwork were not ready for inspection. No actual start or finish is reported for column concreting.

   - qwen: `SUP-GF-02` / `suggested` / `None` (21.907s)
   - gpt120: `SUP-GF-02` / `suggested` / `None` (21.486s)
   - gpt20: `SUP-GF-02` / `suggested` / `None` (22.226s)
   - deepseek: `SUP-GF-02` / `suggested` / `None` (11.362s)

4. `blocker` / `rebar_installation` / `blocked`; quantity `None` `None`, kind `none`; expected `02`. 3. Column Concreting — SUP-GF-02: No column concrete was placed today. The planned pour was postponed because the remaining column reinforcement and formwork were not ready for inspection. No actual start or finish is reported for column concreting.

   - qwen: `SUP-GF-02` / `suggested` / `None` (21.876s)
   - gpt120: `SUP-GF-02` / `suggested` / `None` (21.744s)
   - gpt20: `SUP-GF-02` / `suggested` / `None` (22.004s)
   - deepseek: `SUP-GF-02` / `suggested` / `None` (39.082s)

5. `no_work` / `rebar_installation` / `not_started`; quantity `None` `None`, kind `none`; expected `04`. 4. Slab Reinforcement — SUP-GF-04: Slab reinforcement installation has not started. Workers moved 800 kg of reinforcement bars from the laydown yard to a temporary staging area near the ground floor. These bars have not been fixed in the slab and must not be counted as installed reinforcement.

   - qwen: `SUP-GF-04` / `suggested` / `None` (23.055s)
   - gpt120: `SUP-GF-04` / `suggested` / `None` (22.998s)
   - gpt20: `SUP-GF-04` / `suggested` / `None` (22.931s)
   - deepseek: `SUP-GF-04` / `suggested` / `None` (36.686s)

6. `no_work` / `concrete_pour` / `not_started`; quantity `None` `None`, kind `none`; expected `05`. 5. Slab Concreting — SUP-GF-05: The transit mixer access path remained waterlogged throughout the shift. This prevented the planned ground-floor slab concrete pour. No slab concrete was placed today.

   - qwen: `SUP-GF-05` / `suggested` / `None` (22.172s)
   - gpt120: `SUP-GF-05` / `suggested` / `None` (22.181s)
   - gpt20: `SUP-GF-05` / `suggested` / `None` (22.749s)
   - deepseek: `SUP-GF-05` / `suggested` / `None` (39.582s)

7. `blocker` / `concrete_pour` / `blocked`; quantity `None` `None`, kind `none`; expected `05`. 5. Slab Concreting — SUP-GF-05: The transit mixer access path remained waterlogged throughout the shift. This prevented the planned ground-floor slab concrete pour. No slab concrete was placed today.

   - qwen: `SUP-GF-05` / `suggested` / `None` (21.214s)
   - gpt120: `SUP-GF-05` / `suggested` / `None` (21.479s)
   - gpt20: `SUP-GF-05` / `suggested` / `None` (20.75s)
   - deepseek: `SUP-GF-05` / `suggested` / `None` (43.474s)

8. `inspection` / `other` / `completed`; quantity `None` `None`, kind `none`; expected `01`. 6. Inspection and Handover: The engineer inspected the column reinforcement installed during today's shift. This inspection does not establish completion of the whole column reinforcement activity. A subcontractor verbally suggested that first-floor work could begin tomorrow, but no first-floor work was performed or measured today.

   - qwen: `SUP-GF-01` / `suggested` / `None` (23.792s)
   - gpt120: `SUP-GF-01` / `suggested` / `None` (22.919s)
   - gpt20: `SUP-GF-01` / `suggested` / `None` (23.184s)
   - deepseek: `SUP-GF-01` / `suggested` / `None` (2.174s)

### gpt20

1. `actual_progress` / `rebar_installation` / `in_progress`; quantity `300` `kg`, kind `delta`; expected `01`. Column reinforcement installed 300 kg today

   - qwen: `SUP-GF-01` / `suggested` / `None` (0.426s)
   - gpt120: `SUP-GF-01` / `suggested` / `None` (22.067s)
   - gpt20: `SUP-GF-01` / `suggested` / `None` (22.286s)
   - deepseek: `SUP-GF-01` / `suggested` / `None` (27.498s)

2. `actual_progress` / `formwork` / `in_progress`; quantity `60` `m2`, kind `delta`; expected `03`. Shuttering installed 60 m2 today

   - qwen: `SUP-GF-03` / `suggested` / `None` (21.376s)
   - gpt120: `SUP-GF-03` / `suggested` / `None` (21.45s)
   - gpt20: `SUP-GF-03` / `suggested` / `None` (20.464s)
   - deepseek: `SUP-GF-03` / `suggested` / `None` (2.435s)

3. `no_work` / `concrete_pour` / `not_started`; quantity `None` `None`, kind `none`; expected `02`. No column concrete placed today; planned pour postponed

   - qwen: `SUP-GF-02` / `suggested` / `None` (21.341s)
   - gpt120: `SUP-GF-02` / `suggested` / `None` (20.294s)
   - gpt20: `SUP-GF-02` / `suggested` / `None` (22.82s)
   - deepseek: `SUP-GF-02` / `suggested` / `None` (47.723s)

4. `no_work` / `rebar_installation` / `not_started`; quantity `None` `None`, kind `none`; expected `04`. Slab reinforcement not started; bars moved but not fixed

   - qwen: `SUP-GF-04` / `suggested` / `None` (21.121s)
   - gpt120: `SUP-GF-04` / `suggested` / `None` (21.278s)
   - gpt20: `SUP-GF-04` / `suggested` / `None` (19.555s)
   - deepseek: `SUP-GF-04` / `suggested` / `None` (2.672s)

5. `no_work` / `concrete_pour` / `not_started`; quantity `None` `None`, kind `none`; expected `05`. No slab concrete placed due to waterlogged path

   - qwen: `SUP-GF-05` / `suggested` / `None` (21.733s)
   - gpt120: `SUP-GF-05` / `suggested` / `None` (0.701s)
   - gpt20: `SUP-GF-05` / `suggested` / `None` (22.566s)
   - deepseek: `SUP-GF-05` / `suggested` / `None` (42.015s)

6. `inspection` / `other` / `completed`; quantity `None` `None`, kind `none`; expected `01`. Engineer inspected column reinforcement installed today

   - qwen: `SUP-GF-01` / `suggested` / `None` (20.871s)
   - gpt120: `SUP-GF-01` / `suggested` / `None` (21.157s)
   - gpt20: `SUP-GF-01` / `suggested` / `None` (20.674s)
   - deepseek: `SUP-GF-01` / `suggested` / `None` (2.715s)

### deepseek

1. `actual_progress` / `rebar_installation` / `in_progress`; quantity `300` `kg`, kind `delta`; expected `01`. The steel fixing crew installed an additional 300 kg of column reinforcement today. Column reinforcement remains in progress; the entire activity is not complete.

   - qwen: `SUP-GF-01` / `suggested` / `None` (0.839s)
   - gpt120: `SUP-GF-01` / `suggested` / `None` (22.34s)
   - gpt20: `SUP-GF-01` / `suggested` / `None` (21.942s)
   - deepseek: `SUP-GF-01` / `suggested` / `None` (2.453s)

2. `inspection` / `rebar_installation` / `completed`; quantity `None` `None`, kind `none`; expected `01`. Bar spacing and concrete cover were checked by the site engineer.

   - qwen: `SUP-GF-01` / `suggested` / `None` (21.942s)
   - gpt120: `SUP-GF-01` / `suggested` / `None` (22.384s)
   - gpt20: `SUP-GF-01` / `suggested` / `None` (22.703s)
   - deepseek: `SUP-GF-01` / `suggested` / `None` (57.961s)

3. `actual_progress` / `formwork` / `in_progress`; quantity `60` `m2`, kind `delta`; expected `03`. The formwork crew installed an additional 60 m2 of ground-floor slab shuttering today. Shuttering remains in progress, with further areas pending installation.

   - qwen: `SUP-GF-03` / `suggested` / `None` (21.896s)
   - gpt120: `SUP-GF-03` / `suggested` / `None` (21.9s)
   - gpt20: `SUP-GF-03` / `suggested` / `None` (21.277s)
   - deepseek: `SUP-GF-03` / `suggested` / `None` (32.55s)

4. `inspection` / `formwork` / `completed`; quantity `None` `None`, kind `none`; expected `03`. The crew checked panel alignment and support stability in the completed portion.

   - qwen: `SUP-GF-03` / `suggested` / `None` (22.201s)
   - gpt120: `SUP-GF-03` / `suggested` / `None` (22.263s)
   - gpt20: `SUP-GF-03` / `suggested` / `None` (22.369s)
   - deepseek: `SUP-GF-03` / `suggested` / `None` (2.228s)

5. `no_work` / `concrete_pour` / `not_started`; quantity `None` `None`, kind `none`; expected `02`. No column concrete was placed today. The planned pour was postponed because the remaining column reinforcement and formwork were not ready for inspection.

   - qwen: `SUP-GF-02` / `suggested` / `None` (21.809s)
   - gpt120: `SUP-GF-02` / `suggested` / `None` (21.698s)
   - gpt20: `SUP-GF-02` / `suggested` / `None` (21.46s)
   - deepseek: `SUP-GF-02` / `suggested` / `None` (10.602s)

6. `no_work` / `rebar_installation` / `not_started`; quantity `None` `None`, kind `none`; expected `04`. Slab reinforcement installation has not started. Workers moved 800 kg of reinforcement bars from the laydown yard to a temporary staging area near the ground floor. These bars have not been fixed in the slab and must not be counted as installed reinforcement.

   - qwen: `SUP-GF-04` / `suggested` / `None` (22.001s)
   - gpt120: `SUP-GF-04` / `suggested` / `None` (22.128s)
   - gpt20: `SUP-GF-04` / `suggested` / `None` (22.401s)
   - deepseek: `SUP-GF-04` / `suggested` / `None` (47.803s)

7. `material_delivery` / `rebar_installation` / `completed`; quantity `None` `None`, kind `none`; expected `04`. Workers moved 800 kg of reinforcement bars from the laydown yard to a temporary staging area near the ground floor.

   - qwen: `SUP-GF-04` / `suggested` / `None` (22.225s)
   - gpt120: `SUP-GF-04` / `suggested` / `None` (22.286s)
   - gpt20: `None` / `unmatched` / `None` (23.068s)
   - deepseek: `SUP-GF-04` / `suggested` / `None` (2.892s)

8. `no_work` / `concrete_pour` / `not_started`; quantity `None` `None`, kind `none`; expected `05`. The transit mixer access path remained waterlogged throughout the shift. This prevented the planned ground-floor slab concrete pour. No slab concrete was placed today.

   - qwen: `SUP-GF-05` / `suggested` / `None` (22.125s)
   - gpt120: `SUP-GF-05` / `suggested` / `None` (22.235s)
   - gpt20: `SUP-GF-05` / `suggested` / `None` (21.552s)
   - deepseek: `SUP-GF-05` / `suggested` / `None` (9.948s)

9. `inspection` / `rebar_installation` / `completed`; quantity `None` `None`, kind `none`; expected `01`. The engineer inspected the column reinforcement installed during today's shift. This inspection does not establish completion of the whole column reinforcement activity.

   - qwen: `SUP-GF-01` / `suggested` / `None` (21.828s)
   - gpt120: `SUP-GF-01` / `suggested` / `None` (21.871s)
   - gpt20: `SUP-GF-01` / `suggested` / `None` (22.971s)
   - deepseek: `SUP-GF-01` / `suggested` / `None` (9.942s)

10. `planned_work` / `other` / `unknown`; quantity `None` `None`, kind `none`; expected `abstain`. A subcontractor verbally suggested that first-floor work could begin tomorrow, but no first-floor work was performed or measured today.

   - qwen: `SUP-GF-01` / `suggested` / `None` (22.038s)
   - gpt120: `None` / `unmatched` / `None` (22.213s)
   - gpt20: `None` / `unmatched` / `None` (21.096s)
   - deepseek: `None` / `unmatched` / `None` (30.745s)

## Complete safe call audit

| # | Role | Model | Label | Result | Seconds | HTTP / finish / tokens |
|---:|---|---|---|---|---:|---|
| 1 | orchestrator | qwen/qwen3.8-27b | intake | OK | 0.16 | 200 / stop / 47 |
| 2 | orchestrator | openai/gpt-oss-120b | intake | OK | 2.883 | 200 / stop / 210 |
| 3 | orchestrator | openai/gpt-oss-20b | intake | OK | 2.531 | 200 / stop / 202 |
| 4 | orchestrator | deepseek-ai/DeepSeek-V4-Flash-0731 | intake | OllamaResponseError: Gonka returned an invalid JSON response | 2.094 | 200 / stop / 176 |
| 5 | orchestrator | qwen/qwen3.8-27b | analysis | OK | 0.323 | 200 / stop / 45 |
| 6 | orchestrator | openai/gpt-oss-120b | analysis | OK | 2.569 | 200 / stop / 211 |
| 7 | orchestrator | openai/gpt-oss-20b | analysis | OK | 2.589 | 200 / stop / 179 |
| 8 | orchestrator | deepseek-ai/DeepSeek-V4-Flash-0731 | analysis | OllamaResponseError: Gonka response was incomplete | 6.965 | 200 / length / 219 |
| 9 | orchestrator | qwen/qwen3.8-27b | review | OK | 0.38 | 200 / stop / 45 |
| 10 | orchestrator | openai/gpt-oss-120b | review | OK | 2.678 | 200 / stop / 206 |
| 11 | orchestrator | openai/gpt-oss-20b | review | OK | 2.472 | 200 / stop / 200 |
| 12 | orchestrator | deepseek-ai/DeepSeek-V4-Flash-0731 | review | OllamaResponseError: Gonka returned an invalid JSON response | 2.964 | 200 / stop / 168 |
| 13 | extraction | qwen/qwen3.8-27b | full site update | OK | 3.953 | 200 / stop / 3986 |
| 14 | extraction | openai/gpt-oss-120b | full site update | OK | 78.224 | 200 / stop / 6420 |
| 15 | extraction | openai/gpt-oss-20b | full site update | OK | 70.905 | 200 / stop / 4927 |
| 16 | extraction | deepseek-ai/DeepSeek-V4-Flash-0731 | full site update | OllamaResponseError: Gonka returned an invalid JSON response | 39.525 | 200 / stop / 7596 |
| 17 | selection | qwen/qwen3.8-27b | qwen observation 1 | Interrupted before transport | 10.043 | No HTTP response |
| 18 | extraction | deepseek-ai/DeepSeek-V4-Flash-0731 | full site update | OK | 49.361 | 200 / stop / 7376 |
| 19 | selection | qwen/qwen3.8-27b | qwen observation 1 | OK | 0.504 | 200 / stop / 1509 |
| 20 | selection | qwen/qwen3.8-27b | qwen observation 2 | OK | 22.518 | 200 / stop / 1499 |
| 21 | selection | qwen/qwen3.8-27b | qwen observation 3 | OK | 22.04 | 200 / stop / 1487 |
| 22 | selection | qwen/qwen3.8-27b | qwen observation 4 | OK | 22.301 | 200 / stop / 1501 |
| 23 | selection | qwen/qwen3.8-27b | qwen observation 5 | OK | 22.002 | 200 / stop / 1467 |
| 24 | selection | qwen/qwen3.8-27b | qwen observation 6 | OK | 22.152 | 200 / stop / 1457 |
| 25 | selection | openai/gpt-oss-120b | qwen observation 1 | OK | 22.456 | 200 / stop / 1696 |
| 26 | selection | openai/gpt-oss-120b | qwen observation 2 | OK | 22.425 | 200 / stop / 1714 |
| 27 | selection | openai/gpt-oss-120b | qwen observation 3 | OK | 22.156 | 200 / stop / 1682 |
| 28 | selection | openai/gpt-oss-120b | qwen observation 4 | OK | 22.451 | 200 / stop / 1678 |
| 29 | selection | openai/gpt-oss-120b | qwen observation 5 | OK | 22.185 | 200 / stop / 1696 |
| 30 | selection | openai/gpt-oss-120b | qwen observation 6 | OK | 22.154 | 200 / stop / 1680 |
| 31 | selection | openai/gpt-oss-20b | qwen observation 1 | OK | 21.931 | 200 / stop / 1672 |
| 32 | selection | openai/gpt-oss-20b | qwen observation 2 | OK | 22.241 | 200 / stop / 1692 |
| 33 | selection | openai/gpt-oss-20b | qwen observation 3 | OK | 22.363 | 200 / stop / 1666 |
| 34 | selection | openai/gpt-oss-20b | qwen observation 4 | OK | 22.435 | 200 / stop / 1668 |
| 35 | selection | openai/gpt-oss-20b | qwen observation 5 | OK | 22.309 | 200 / stop / 1640 |
| 36 | selection | openai/gpt-oss-20b | qwen observation 6 | OK | 22.278 | 200 / stop / 1711 |
| 37 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | qwen observation 1 | OK | 2.839 | 200 / stop / 1683 |
| 38 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | qwen observation 2 | OK | 43.937 | 200 / stop / 1682 |
| 39 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | qwen observation 3 | OK | 2.336 | 200 / stop / 1679 |
| 40 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | qwen observation 4 | OK | 37.125 | 200 / stop / 1657 |
| 41 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | qwen observation 5 | OK | 33.007 | 200 / stop / 1655 |
| 42 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | qwen observation 6 | OK | 46.6 | 200 / stop / 1664 |
| 43 | selection | qwen/qwen3.8-27b | gpt120 observation 1 | OK | 0.615 | 200 / stop / 1488 |
| 44 | selection | qwen/qwen3.8-27b | gpt120 observation 2 | OK | 22.153 | 200 / stop / 1522 |
| 45 | selection | qwen/qwen3.8-27b | gpt120 observation 3 | OK | 21.907 | 200 / stop / 1465 |
| 46 | selection | qwen/qwen3.8-27b | gpt120 observation 4 | OK | 21.876 | 200 / stop / 1562 |
| 47 | selection | qwen/qwen3.8-27b | gpt120 observation 5 | OK | 23.055 | 200 / stop / 1502 |
| 48 | selection | qwen/qwen3.8-27b | gpt120 observation 6 | OK | 22.172 | 200 / stop / 1478 |
| 49 | selection | qwen/qwen3.8-27b | gpt120 observation 7 | OK | 21.214 | 200 / stop / 1525 |
| 50 | selection | qwen/qwen3.8-27b | gpt120 observation 8 | OK | 23.792 | 200 / stop / 1451 |
| 51 | selection | openai/gpt-oss-120b | gpt120 observation 1 | OK | 21.382 | 200 / stop / 1684 |
| 52 | selection | openai/gpt-oss-120b | gpt120 observation 2 | OK | 23.06 | 200 / stop / 1708 |
| 53 | selection | openai/gpt-oss-120b | gpt120 observation 3 | OK | 21.486 | 200 / stop / 1662 |
| 54 | selection | openai/gpt-oss-120b | gpt120 observation 4 | OK | 21.744 | 200 / stop / 1777 |
| 55 | selection | openai/gpt-oss-120b | gpt120 observation 5 | OK | 22.998 | 200 / stop / 1699 |
| 56 | selection | openai/gpt-oss-120b | gpt120 observation 6 | OK | 22.181 | 200 / stop / 1639 |
| 57 | selection | openai/gpt-oss-120b | gpt120 observation 7 | OK | 21.479 | 200 / stop / 1727 |
| 58 | selection | openai/gpt-oss-120b | gpt120 observation 8 | OK | 22.919 | 200 / stop / 1634 |
| 59 | selection | openai/gpt-oss-20b | gpt120 observation 1 | OK | 21.985 | 200 / stop / 1649 |
| 60 | selection | openai/gpt-oss-20b | gpt120 observation 2 | OK | 22.107 | 200 / stop / 1630 |
| 61 | selection | openai/gpt-oss-20b | gpt120 observation 3 | OK | 22.226 | 200 / stop / 1670 |
| 62 | selection | openai/gpt-oss-20b | gpt120 observation 4 | OK | 22.004 | 200 / stop / 1735 |
| 63 | selection | openai/gpt-oss-20b | gpt120 observation 5 | OK | 22.931 | 200 / stop / 1650 |
| 64 | selection | openai/gpt-oss-20b | gpt120 observation 6 | OK | 22.749 | 200 / stop / 1638 |
| 65 | selection | openai/gpt-oss-20b | gpt120 observation 7 | OK | 20.75 | 200 / stop / 1720 |
| 66 | selection | openai/gpt-oss-20b | gpt120 observation 8 | OK | 23.184 | 200 / stop / 1611 |
| 67 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt120 observation 1 | OK | 3.185 | 200 / stop / 1648 |
| 68 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt120 observation 2 | OK | 10.288 | 200 / stop / 1679 |
| 69 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt120 observation 3 | OK | 11.362 | 200 / stop / 1641 |
| 70 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt120 observation 4 | OK | 39.082 | 200 / stop / 1745 |
| 71 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt120 observation 5 | OK | 36.686 | 200 / stop / 1667 |
| 72 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt120 observation 6 | OK | 39.582 | 200 / stop / 1614 |
| 73 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt120 observation 7 | OK | 43.474 | 200 / stop / 1717 |
| 74 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt120 observation 8 | OK | 2.174 | 200 / stop / 1642 |
| 75 | selection | qwen/qwen3.8-27b | gpt20 observation 1 | OK | 0.426 | 200 / stop / 1418 |
| 76 | selection | qwen/qwen3.8-27b | gpt20 observation 2 | OK | 21.376 | 200 / stop / 1416 |
| 77 | selection | qwen/qwen3.8-27b | gpt20 observation 3 | OK | 21.341 | 200 / stop / 1401 |
| 78 | selection | qwen/qwen3.8-27b | gpt20 observation 4 | OK | 21.121 | 200 / stop / 1416 |
| 79 | selection | qwen/qwen3.8-27b | gpt20 observation 5 | OK | 21.733 | 200 / stop / 1403 |
| 80 | selection | qwen/qwen3.8-27b | gpt20 observation 6 | OK | 20.871 | 200 / stop / 1385 |
| 81 | selection | openai/gpt-oss-120b | gpt20 observation 1 | OK | 22.067 | 200 / stop / 1644 |
| 82 | selection | openai/gpt-oss-120b | gpt20 observation 2 | OK | 21.45 | 200 / stop / 1655 |
| 83 | selection | openai/gpt-oss-120b | gpt20 observation 3 | OK | 20.294 | 200 / stop / 1589 |
| 84 | selection | openai/gpt-oss-120b | gpt20 observation 4 | OK | 21.278 | 200 / stop / 1605 |
| 85 | selection | openai/gpt-oss-120b | gpt20 observation 5 | Interrupted | 6.021 | No HTTP response |
| 86 | selection | openai/gpt-oss-120b | gpt20 observation 5 | OllamaTransportError: Groq request timed out or failed | 0.013 | No HTTP response |
| 87 | selection | openai/gpt-oss-120b | gpt20 observation 6 | OllamaTransportError: Groq request timed out or failed | 2.093 | No HTTP response |
| 88 | selection | openai/gpt-oss-20b | gpt20 observation 1 | Interrupted | 1.697 | No HTTP response |
| 89 | orchestrator | deepseek-ai/DeepSeek-V4-Flash-0731 | intake | OllamaResponseError: Gonka returned an invalid JSON response | 2.586 | 200 / stop / 202 |
| 90 | orchestrator | deepseek-ai/DeepSeek-V4-Flash-0731 | analysis | OllamaResponseError: Gonka response was incomplete | 8.605 | 200 / length / 219 |
| 91 | orchestrator | deepseek-ai/DeepSeek-V4-Flash-0731 | review | OllamaResponseError: Gonka returned an invalid JSON response | 12.126 | 200 / stop / 172 |
| 92 | selection | openai/gpt-oss-120b | gpt20 observation 5 | OK | 0.701 | 200 / stop / 1593 |
| 93 | selection | openai/gpt-oss-120b | gpt20 observation 6 | OK | 21.157 | 200 / stop / 1553 |
| 94 | selection | openai/gpt-oss-20b | gpt20 observation 1 | OK | 22.286 | 200 / stop / 1628 |
| 95 | selection | openai/gpt-oss-20b | gpt20 observation 2 | OK | 20.464 | 200 / stop / 1607 |
| 96 | selection | openai/gpt-oss-20b | gpt20 observation 3 | OK | 22.82 | 200 / stop / 1623 |
| 97 | selection | openai/gpt-oss-20b | gpt20 observation 4 | OK | 19.555 | 200 / stop / 1600 |
| 98 | selection | openai/gpt-oss-20b | gpt20 observation 5 | OK | 22.566 | 200 / stop / 1562 |
| 99 | selection | openai/gpt-oss-20b | gpt20 observation 6 | OK | 20.674 | 200 / stop / 1562 |
| 100 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt20 observation 1 | OK | 27.498 | 200 / stop / 1617 |
| 101 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt20 observation 2 | OK | 2.435 | 200 / stop / 1603 |
| 102 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt20 observation 3 | OK | 47.723 | 200 / stop / 1584 |
| 103 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt20 observation 4 | OK | 2.672 | 200 / stop / 1610 |
| 104 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt20 observation 5 | OK | 42.015 | 200 / stop / 1578 |
| 105 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | gpt20 observation 6 | OK | 2.715 | 200 / stop / 1574 |
| 106 | selection | qwen/qwen3.8-27b | deepseek observation 1 | OK | 0.839 | 200 / stop / 1506 |
| 107 | selection | qwen/qwen3.8-27b | deepseek observation 2 | OK | 21.942 | 200 / stop / 1440 |
| 108 | selection | qwen/qwen3.8-27b | deepseek observation 3 | OK | 21.896 | 200 / stop / 1496 |
| 109 | selection | qwen/qwen3.8-27b | deepseek observation 4 | OK | 22.201 | 200 / stop / 1450 |
| 110 | selection | qwen/qwen3.8-27b | deepseek observation 5 | OK | 21.809 | 200 / stop / 1470 |
| 111 | selection | qwen/qwen3.8-27b | deepseek observation 6 | OK | 22.001 | 200 / stop / 1484 |
| 112 | selection | qwen/qwen3.8-27b | deepseek observation 7 | OK | 22.225 | 200 / stop / 1473 |
| 113 | selection | qwen/qwen3.8-27b | deepseek observation 8 | OK | 22.125 | 200 / stop / 1480 |
| 114 | selection | qwen/qwen3.8-27b | deepseek observation 9 | OK | 21.828 | 200 / stop / 1452 |
| 115 | selection | qwen/qwen3.8-27b | deepseek observation 10 | OK | 22.038 | 200 / stop / 1437 |
| 116 | selection | openai/gpt-oss-120b | deepseek observation 1 | OK | 22.34 | 200 / stop / 1721 |
| 117 | selection | openai/gpt-oss-120b | deepseek observation 2 | OK | 22.384 | 200 / stop / 1662 |
| 118 | selection | openai/gpt-oss-120b | deepseek observation 3 | OK | 21.9 | 200 / stop / 1711 |
| 119 | selection | openai/gpt-oss-120b | deepseek observation 4 | OK | 22.263 | 200 / stop / 1682 |
| 120 | selection | openai/gpt-oss-120b | deepseek observation 5 | OK | 21.698 | 200 / stop / 1657 |
| 121 | selection | openai/gpt-oss-120b | deepseek observation 6 | OK | 22.128 | 200 / stop / 1667 |
| 122 | selection | openai/gpt-oss-120b | deepseek observation 7 | OK | 22.286 | 200 / stop / 1691 |
| 123 | selection | openai/gpt-oss-120b | deepseek observation 8 | OK | 22.235 | 200 / stop / 1668 |
| 124 | selection | openai/gpt-oss-120b | deepseek observation 9 | OK | 21.871 | 200 / stop / 1655 |
| 125 | selection | openai/gpt-oss-120b | deepseek observation 10 | OK | 22.213 | 200 / stop / 1648 |
| 126 | selection | openai/gpt-oss-20b | deepseek observation 1 | OK | 21.942 | 200 / stop / 1686 |
| 127 | selection | openai/gpt-oss-20b | deepseek observation 2 | OK | 22.703 | 200 / stop / 1627 |
| 128 | selection | openai/gpt-oss-20b | deepseek observation 3 | OK | 21.277 | 200 / stop / 1681 |
| 129 | selection | openai/gpt-oss-20b | deepseek observation 4 | OK | 22.369 | 200 / stop / 1641 |
| 130 | selection | openai/gpt-oss-20b | deepseek observation 5 | OK | 21.46 | 200 / stop / 1644 |
| 131 | selection | openai/gpt-oss-20b | deepseek observation 6 | OK | 22.401 | 200 / stop / 1647 |
| 132 | selection | openai/gpt-oss-20b | deepseek observation 7 | OK | 23.068 | 200 / stop / 1668 |
| 133 | selection | openai/gpt-oss-20b | deepseek observation 8 | OK | 21.552 | 200 / stop / 1661 |
| 134 | selection | openai/gpt-oss-20b | deepseek observation 9 | OK | 22.971 | 200 / stop / 1666 |
| 135 | selection | openai/gpt-oss-20b | deepseek observation 10 | OK | 21.096 | 200 / stop / 1586 |
| 136 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | deepseek observation 1 | OK | 2.453 | 200 / stop / 1686 |
| 137 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | deepseek observation 2 | OK | 57.961 | 200 / stop / 1620 |
| 138 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | deepseek observation 3 | OK | 32.55 | 200 / stop / 1684 |
| 139 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | deepseek observation 4 | OK | 2.228 | 200 / stop / 1624 |
| 140 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | deepseek observation 5 | OK | 10.602 | 200 / stop / 1649 |
| 141 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | deepseek observation 6 | OK | 47.803 | 200 / stop / 1682 |
| 142 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | deepseek observation 7 | OK | 2.892 | 200 / stop / 1683 |
| 143 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | deepseek observation 8 | OK | 9.948 | 200 / stop / 1654 |
| 144 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | deepseek observation 9 | OK | 9.942 | 200 / stop / 1649 |
| 145 | selection | deepseek-ai/DeepSeek-V4-Flash-0731 | deepseek observation 10 | OK | 30.745 | 200 / stop / 1590 |
