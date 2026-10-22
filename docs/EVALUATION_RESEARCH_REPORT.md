# Prompting and bounded agents for construction progress reporting

Empirical development report, consolidated 23 October 2026. Scope: this repository's saved experiments and current offline verification. This is material for a paper's methods, results and limitations sections. It is not a systematic literature review or evidence of production acceptance.

## Abstract

We evaluated prompting, model roles, retrieval, safety controls and workflow execution for a construction progress assistant. The workflow converts reports into structured observations, retrieves schedule activities, proposes links and requires review before internal updates and MOCK PMIS delivery. Controlled development studies compared GPT-OSS 20B, GPT-OSS 120B and Qwen 27B, instruction variants, demonstrations and deterministic alternatives. On a six-case projected extraction task, plain 20B achieved 3/6 selected-field matches, tailored instructions 4/6, fixed and dynamic demonstrations 6/6, and plain 120B 6/6. A separate full workflow comparison on two consumed reports with inverse credential assignments yielded 4/4 exact scoped reports for all-20B and two mixed configurations, and 2/4 for all-Qwen. Full selection-schema failures explained the all-Qwen losses despite correct selected extraction facts. Every latest-cohort report missed the 120-second readiness target. A blind judge agreed with references on 21/24 decisions and required disagreement review. These findings support inexpensive baselines, schema-aware component evaluation and explicit stop conditions. Small correlated synthetic samples, AI-assisted reference review, missing telemetry and incomplete release gates prevent representative accuracy or superiority claims.

## Research questions and design

The evaluation asks whether demonstrations improve structured extraction, whether larger or mixed models improve assembled outcomes, whether simple retrieval alternatives can replace model calls, and whether failures remain visible through review and recovery. The unit of analysis differs by experiment: extraction case, retrieval context, scheduled report or judge decision. These denominators are reported separately.

The primary application is construction reporting, with literal quantities, units, dates, locations and asset IDs linked to a versioned schedule. Output contracts distinguish actual progress, planned work, material delivery, blockers, no work and corrections. Only measured actual progress supplies structured quantities under the current development contract; delivery/planning/correction amounts remain in summaries. Cumulative amounts are distinguished from deltas. Trusted report dates anchor relative expressions. Missing facts remain null, and source text cannot grant approval authority. See the development specification (local archive: `development-specification-v36.md`; not published) and scoring contract (local archive: `evaluation-scoring-contract.md`; not published).

Experiments retain prompt, schema, source and configuration identities, scheduled trials, requested/returned models, raw final outputs, usage and failure records. Synthetic authoring and AI-assisted review are explicitly distinguished from independent human adjudication. Consumed development families remain consumed; none of the comparisons below is a newly frozen acceptance holdout. No production model assignment was changed by this consolidation.

## Prompting and component results

| Six-case projected extraction arm | Selected-field exact matches |
|---|---:|
| Plain GPT-OSS 20B | 3/6 |
| GPT-OSS 20B with tailored instructions | 4/6 |
| GPT-OSS 20B with fixed demonstration | 6/6 |
| GPT-OSS 20B with training-only dynamic demonstration | 6/6 |
| Plain GPT-OSS 120B | 6/6 |

The arms used the same six inputs and compatible projected output contract. Two 120B review invocations agreed on those labels; this is correlated AI-assisted review. The 120B control was not independently optimized, so optimized configurations and equal model-tuning budgets must not be conflated. Dynamic examples provided no additional observed benefit over fixed examples. On a distinct eight-case full-schema metric, three demonstrations improved 1/8 to 3/8. The projected and full-schema scores measure different outcomes and must not be pooled. Batch 32 methods and retained outcomes (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-32/review.md`; not published); [complete prompting comparisons](MODEL_AND_PROMPT_COMPARISON_REPORT.md).

Earlier projected role studies recorded Qwen extraction 12/12 versus 20B 10/12, Qwen selection 8/8 successful outputs versus 20B 6/8, and supervisor-only Qwen and 120B 6/6 each. A retained HTTP503 sits outside the successful-output denominator. Earlier 20B selection followed injected source instructions on both credentials. These component results do not establish safe full-worker integration. Medium reasoning, one feedback repair and bounded consistency/critic studies did not establish a general improvement. Strict-output compatibility remained dependent on the actual schema. [Role and configuration evidence](MODEL_AND_PROMPT_COMPARISON_REPORT.md).

## Assembled model configurations, latency and cost

Each configuration's latest cohort contains the same two consumed synthetic reports, repeated under inverse credential assignments. One report is ordinary and one ambiguous. Thus four planned comparisons do not represent four independent source reports.

| Configuration | Exact scoped reports | Median completed report time | Known latest-cohort list-price estimate | Reports below 120 s |
|---|---:|---:|---:|---:|
| All GPT-OSS 20B | 4/4 | 324.594 s | $0.00265643 | 0/4 |
| 120B orchestration, 20B workers | 4/4 | 324.918 s | $0.00303638 | 0/4 |
| Qwen orchestration, 20B workers | 4/4 | 304.375 s | $0.00311070 | 0/4 |
| All Qwen | 2/4 | 333.109 s | $0.01913840 | 0/4 |

Costs include failures within the latest cohort; earlier failed/recovery attempts remain in separate accounting windows. They are historical list-price estimates, not current prices or provider billing totals. The all-Qwen median covers only its two successful ambiguous reports and is not directly comparable to four-completion medians. Conservative pacing and shared admission contribute to elapsed time; these measurements do not isolate provider transport speed. [Consolidated source table and accounting](MODEL_QUALITY_SUMMARY.md).

All-Qwen's two ordinary reports failed full selection-schema validation, while both ambiguity reports passed. A sealed stage/workflow audit retained extraction successes on failed assembled reports without giving those reports full-workflow credit. It preserved original failed/missing windows separately from recovery. This demonstrates why selected-field component accuracy cannot substitute for assembled contract compliance. Stage/workflow audit (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-36/stage-workflow-audit.json`; not published).

An earlier V2 graph comparison recorded one-account assisted reports at 182.738 and 166.131 seconds, and two-account assisted reports at 142.704 and 143.985 seconds. Both assisted arms achieved 2/2 scoped successes and missed readiness. The deterministic ordinary report took 97.580 seconds; the deterministic ambiguity control stopped at the original budget. Tiny samples, different windows and retained missing controls prohibit a causal account-policy speedup claim. Batch 32 graph evidence (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-32/review.md`; not published).

## Retrieval and document fidelity

A synthetic retrieval study ran 108 trials: nine cases, three schedule sizes and four methods. Each method had 18 matchable and nine unmatched trials. Macro Recall@8 was 0.333 for exact IDs, 0.667 for scoped aliases, and 0.833 for lexical retrieval and production discovery with an injected lexical ranker. All had zero unmatched false positives in these authored cases. The injected discovery path used 1,047 calls, which are scaffold invocations, not provider completions.

A separate comparison used five sealed historical model requests with identical saved observation/schedule context. Exact IDs had mean target Recall@8 of zero; aliases, lexical search and actual GPT-OSS 20B each reached one. Exact target sets were 0/5, 2/5, 2/5 and 5/5 respectively. Those five contexts derive from two related reports; the sixth planned control lacked a captured request after the original budget stop. This supports investigating cheap alternatives while retaining evidence that broader candidate sets can differ from model retrieval. It does not justify removing production calls. Retrieval methods, denominators and captures (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-35/review.md`; not published).

The real isolated TXT/DOCX/XLSX parser preserved all 15 critical annotated fields across three small fixtures. Controlled corruptions separately tested wrong values, missing outputs and displaced locators. Batch 36 additionally preserved authored text across 12 native-format fixtures, with associated schedules of 16, 256 or 1,000 rows. These are parser diagnostics; schedule size and site metadata do not establish large-schedule model accuracy or real contractor diversity. OCR is absent, so optical-quality testing is not applicable until that feature is added. Parser/scoring evidence (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-35/review.md`; not published); format coverage (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-36/review.md`; not published).

## Multi-turn behavior and judge fallibility

Batch 36 captured six actual model-assisted conversations through the local conversation consumer. A new read-only audit checks correction, conflicting instructions, pronouns, references, topic change and conflicting dates. Five unambiguous cases retain the expected activity, date and clock time. The date-conflict case retains both dates, an explicit warning and pending review. All six have zero ledger writes, no queued job and no proposal IDs. This completes a finite behavior test, with no claim of representative conversation reliability. Semantic and side-effect audit (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-37/conversation-audit.json`; not published).

The same study contains 12 AI-reviewed source annotations and 24 balanced blind judge decisions. Against source/contract-backed references the diagnostic confusion matrix is TP=10, TN=11, FP=1 and FN=2: agreement 21/24, or 87.5%, with no missing judgments. The three disagreements concern delivery, progress versus planning, and an injected approval directive. The secondary AI adjudication did not resolve the study successfully. Its original `ExperimentStop` and review requirement remain retained; post-stop engineering analysis is a labelled derivative, not acceptance of the stopped study. Forty recorded model calls, 338,506 reserved tokens and $0.0876399 of reserved list-price budget describe that window; reservations are not measured billable usage. Original summary (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-36/live/summary.json`; not published); post-stop findings (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-36/poststop-source-audit.json`; not published).

The evaluated guard wrapper blocks unsafe verdicts and required-check outages, malformed replies or overlong inputs. Optional outages are explicitly unscreened. Safeguard adoption is deferred because incremental guard benefit was not measured; no production guard was activated. Long-context tokenizer compatibility and wider runtime propagation remain open. Guard protocol and tests (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-36/review.md`; not published).

### Subsequent calibration verification and engineering adjudication

Batch 38 independently joined all 24 frozen judge inputs to actual wire requests and raw responses. Semantic request bodies contain only source, prediction and rubric; no target labels or evaluated-model identities occur in the inspected messages. The transport identifies the judge's own model. Exact requested/returned judge models and raw verdict/quote/reason fields match the saved decisions. The calibration therefore records actual blinded domain judgments, with the original stopped study still excluded from accepted quality scores.

| Diagnostic statistic | Result |
|---|---:|
| Agreement | 21/24 = 87.50% |
| Sensitivity to correct predictions | 10/12 = 83.33% |
| Specificity against incorrect predictions | 11/12 = 91.67% |
| Positive predictive value | 10/11 = 90.91% |
| Negative predictive value | 11/13 = 84.62% |

Codex recorded explicit AI-assisted engineering adjudications for all three actual disagreements using literal source and the stated contract: delivered pumps are material delivery, “40% done” is actual progress rather than planned work, and the embedded 400 m3 approval instruction does not invalidate the genuine 4 m3 excavation fact. All three reference judgments are retained and the blind judge decisions rejected. Evidence-bearing disagreement-gate records apply to this separate development derivative. The original unsuccessful secondary AI review, nonliteral secondary quote and study stop remain unchanged. Independent human adjudication remains pending for stronger claims.

SCORE-06 and SCORE-08 are complete as calibration/adjudication tasks, with **automated judge adoption deferred**. The requirement to measure judge errors can be completed even when the result does not support adoption. These synthetic paired correct/corrupted predictions are not a natural operational error distribution. Verified calibration, decisions and limitations (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-38/judge-audit.json`; not published); batch review (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-38/review.md`; not published).

## Verification, incidents and reproducibility

Latest focused verification: **115 tests passed**, including 12 new raw-judge audit regressions plus existing guard, study, conversation and evidence tests. Scoped Ruff passed. No new full-suite or provider run was made for batch 38. Latest verification (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-38/review.md`; not published).

Earlier verification: 1,653 full unit tests passed, one skipped; 42 focused tests passed, including three new regressions that reject stale conversation times, unauthorized side effects and tampered captures. The full suite preceded those three additions; the counts must not be added and described as a full-suite rerun. The initial sandbox run had 29 failures from blocked `/bin/ps` supervision, with 1,624 passes; the permitted rerun outside that restriction passed. Existing Starlette deprecation warnings remain. Historical PostgreSQL evidence is 263 passes in batch 32, not a fresh integration result. Earlier review and test logs (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-37/review.md`; not published).

An earlier misconfigured integration setup caused uncaptured provider traffic. Original records and the incident were retained, and subsequent test HTTP guards were strengthened. Total historical traffic and spend are unknown. The four dedicated cache probes lack cached-token telemetry, so their hit/miss status remains unknown. Batch 39 separately verifies three explicit positive records in other calls, as described below. Stable prefixes and lower latency alone remain insufficient evidence. Original manifests, failures, stopped budgets and consumed lineage must accompany any paper dataset export. Local evidence links are reproducible within this checkout but are not a public archival dataset; publication requires a redacted export and stable identifiers. Incident and preservation evidence (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-32/review.md`; not published).

### Fifteen-requirement continuation: observed caching and freshness controls

Batch 39 examined the next 15 outstanding requirements and completed **one (SPEC-16)**; 14 remain partial. Its new audit verifies original capture seals, joins requests to responses, checks stable-system placement before variable messages, and validates cache telemetry only on HTTP200 responses from the requested model. Across the batch-29 and batch-32 core windows, **three of 60 records contain explicit positive telemetry: 2,816 cached tokens out of 3,163 prompt tokens on those three calls**. The other **57 records have missing telemetry**. This is not a 3/60 hit-rate estimate, and the 89.03% cached-token fraction applies only to the explicitly reported subset. Repeated system-prefix hashes do not prove which prefix tokens were cached. No cache discount is applied to prior cost estimates or cold reservations. The four dedicated cache probes remain unknown, and independent parallel cold-start isolation is untested. Verified raw-cache audit (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-39/evidence/verified-cache-audit.json`; not published).

The current exposure inventory now retains unreadable UTF-8 captures as explicit hashed error records instead of aborting enumeration. It covers 188 capture files with 170 unique case IDs, 196 malformed/unidentified rows and 134 source-metadata files. Those row errors include valid records without recognized case-ID fields; counts are neither independent reports nor proof of 196 provider failures. Unknown history and unsupported containers remain quarantined.

The actual fresh-dataset preflight now uses bounded lexical fingerprints to flag cross-split near-duplicate candidates. Three-token shingle Jaccard similarity at a fixed 0.75 threshold is a conservative review rule; it preserves numeric values and IDs but can overflag common templates and miss semantic paraphrases. It does not certify ancestry or independence. A controlled renamed-holdout attempt performs 144 comparisons, identifies 12 candidate pairs and rejects all 12 reused consumed cases before inference. Active tuning and an unselected assembled configuration also reject. No new holdout is accepted. An initial 0.8 cutoff missed a controlled one-word variant; the lower final cutoff addresses that diagnostic without establishing a validated optimal threshold. Actual consumer rejection (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-39/evidence/holdout-rejection-audit.json`; not published).

Other checks re-executed 108 retrieval diagnostics, 12 injected-normalizer compatibility cases, 26 original Qwen HTTP200 schema validations (24 valid, two invalid), publication rescoring of all 18 attempts, native-source file hashes and five sealed stage/workflow windows. These are new offline analyses of consumed evidence, not new inference or independent quality samples. Slot-0 organization metadata, uncaptured historical billing, production evaluation-capacity reservations, representative projects and natural prevalence remain unresolved. All fifteen dispositions and results (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-39/review.md`; not published).

Verification for batch 39: full unit suite **1,687 passed / one skipped** before the final cache-response identity guard and two added tests; final focused suite **121 passed**, including **21 new regressions**, on the final source. Scoped Ruff passed. No new model, database, browser or release run was performed.

## Interpretation and limits for a paper

The strongest supported observations are that examples helped on a small projected task, full-schema integration reversed an encouraging component-only Qwen result, paced readiness missed its target, and judge disagreement remained material despite explicit instructions. All-20B is an economical development baseline among the fully passing configurations in the tiny latest cohort. No best general model or production-safe configuration is established.

The design has threats from authored synthetic data, consumed families, correlated model reviewers, limited independent projects, unequal tuning histories, repeated credentials, conservative pacing and incomplete usage records. Perfect 6/6 or 4/4 samples do not establish the owner targets of 0.98 selected-link precision or population p95 readiness. We do not pool heterogeneous experiments, treat repeated calls as independent reports, or report significance tests from these samples.

The governing targets (local archive: `evaluation-targets-approved-2026-10-16.json`; not published) remain unchanged. A representative reviewed corpus, resolved account map, frozen assembled candidate, fresh group-disjoint validation/holdout and explicit release review remain prerequisites for stronger claims. The owner deferred supplying those prerequisites on 23 October; they remain visible in the checklist (local archive: `PROMPTING_MODEL_AGENT_TESTING_CHECKLIST.md`; not published). The current inventory is **239 checked / 30 open**; every open requirement retains an explicit per-item disposition (local archive: `../evaluation/results/prompting-checklist-2026-10-20/batch-39/checklist-disposition.json`; not published).

For a literature paper, use these measurements as a bounded empirical case study. The existing checklist's research bibliography supplies leads for prompting, retrieval, agent design and evaluation; this consolidation does not reverify those external publications or claim an exhaustive literature search. A submission still needs a defined literature-search method, current primary-source review, independent references and an archival evidence package.

---

[Documentation index](README.md) · [Project overview](../README.md)
