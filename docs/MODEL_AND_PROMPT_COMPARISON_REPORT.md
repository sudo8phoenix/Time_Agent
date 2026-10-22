# Model configurations, prompting techniques and measured comparison

Updated 22 October 2026. This is the consolidated development report for the construction site progress agent. It brings together the latest full-graph configurations, the earlier component studies, prompt ablations, costs, failures and current recommendations. The frozen captures remain the evidence; this document does not rewrite old scores or labels.

## 1. Decision and scope

**All GPT-OSS 20B is the strongest cost-focused baseline among the configurations that completed every planned report correctly in this test.** It matches the 4/4 scoped outcomes of both mixed configurations at the lowest listed token rates. **All-Qwen passed 2/4** and failed the full selection schema on both unambiguous cases. This changes the practical interpretation of the earlier simplified Qwen worker wins: Qwen is a promising component challenger, but its current full worker configuration needs compatibility work. Observed lowest known latest-cohort spend among fully passing configurations: **All 20B**, $0.00265643 for four comparisons; this small descriptive cost result is not a billing guarantee.

The latest configuration matrix contains two **previously consumed, AI-authored source reports**, each tested with both key assignments. Four rows per configuration therefore represent **two source cases repeated across accounts**, not four independent real reports. No production winner, human-adjudicated quality claim, fresh holdout result or release acceptance follows from these measurements.

The practical distinction is between a model answering a small component test and that model completing the application's actual report-analysis graph. Qwen passed the simplified selection schema but failed the full application's selection contract on both unambiguous runs. Model size, model family, valid JSON, HTTP200 and agreement between models are each insufficient evidence of application success.

## 2. Configurations and experimental controls

The exact model IDs are `openai/gpt-oss-20b`, `openai/gpt-oss-120b` and `qwen/qwen3.8-27b` on Groq. The four configurations are:

| Configuration | Orchestrator | Extraction, retrieval and selection |
|---|---|---|
| All 20B | GPT-OSS 20B | GPT-OSS 20B |
| 120B + 20B | GPT-OSS 120B | GPT-OSS 20B |
| Qwen + 20B | Qwen 3.8 27B | GPT-OSS 20B |
| All Qwen | Qwen 3.8 27B | Qwen 3.8 27B |

Every latest configuration uses both independently owner-confirmed accounts. In assignment A, the orchestrator uses `groq_api_key_1` and all workers use `groq_api_key_2`. Assignment B reverses those roles. Extraction and selection share the worker key. Keys are fixed by the frozen workload; a failed request is never moved to another key to evade a restriction. Slot 0 is unused in these studies. Key contents are excluded from artifacts.

The source reports and two-activity schedule are the same across configurations:

| Case | Report facts | Expected mapping |
|---|---|---|
| DEV-20261020-01 | Excavated 5 m3, explicitly named Zone Cedar and asset TR-030, trusted report date 20 October | Suggest the Cedar excavation activity |
| DEV-20261020-08 | Excavated 2 m3; site area and asset tag explicitly not recorded | Preserve the actual progress but leave matching ambiguous; no chosen activity |

Each arm gets its own synthetic reports, jobs and database records. Generated UUIDs differ. New evaluation databases are fresh local `progress_rehearsal_*` PostgreSQL databases at migration 0018. Application `.env`, active role assignments, existing jobs and production services are not changed. Planner compatibility was added for exact Qwen and then 20B model IDs to permit the requested experiments; allowing an ID does not activate it.

The source guard was changed only after the all-Qwen run ended. Old source snapshots and hashes preserve that build; the 20B build adds an allowlist entry and associated tests. Runtime prompts, schemas and business logic were not tuned between these configuration arms. This is an explicit build difference, not an assertion that the source hashes are identical.

```mermaid
flowchart LR
    A[Seeded report and schedule] --> B[Orchestrator on key A]
    B --> C[Extraction on key B]
    C --> D[Schedule retrieval on key B]
    D --> E[Selection on key B]
    E --> F[Validation and pending review]
```

The actual supervisor also confirms intake, analysis and review transitions. It is a **bounded singleton-action planner**: the graph supplies one legal next supervisor, and the model confirms it. It does not choose arbitrary tools, search a planning tree or delegate freely. Extra planner capacity is therefore not automatically useful in this workflow.

### What is held fixed

Temperature is zero. The application Groq adapter uses `response_format=json_schema`, `strict=false`, no streaming and zero automatic retries. Its completion cap is 1,536 tokens; compact discovery/selection can request a lower cap. GPT-OSS requests send `reasoning_effort=low`; Qwen sends no explicit reasoning parameter. That is an application-configuration comparison, not reasoning-mode parity. Temperature zero is not a determinism guarantee.

The full graph uses the current V12 extraction prompt (`extraction-v12-source-clause-check`), full `ObservationBatch` schema, schedule discovery schema and final six-field selection schema. V12 contains task rules and inline contrastive examples. No additional fixed/dynamic demonstration set was added to these latest configuration trials. The earlier registered zero-shot/few-shot experiment names refer to their own harness prompts. The [exact prompt catalog](MODEL_PROMPT_CATALOG.md) reproduces the current captured system instructions and hashes.

Reports are seeded directly, bypassing upload/OCR. Runs exercise the live extraction → retrieval → selection → pending-review graph and durable checkpoints. They do not test browser upload, speech, OCR, user approval or PMIS delivery end to end.

## 3. Latest full-graph results

| Configuration | Exact planned reports | Key1 / key2 exact | All report attempts | Median completed report time | Known latest-cohort cost | Below 120s |
|---|---:|---:|---:|---:|---:|---:|
| All 20B | 4/4 | 2/2 / 2/2 | 4 | 324.594s (4 completed) | $0.00265643 | 0/4 |
| 120B + 20B | 4/4 | 2/2 / 2/2 | 4 | 324.918s (4 completed) | $0.00303638 | 0/4 |
| Qwen + 20B | 4/4 | 2/2 / 2/2 | 5 | 304.375s (4 completed) | $0.00311070 | 0/4 |
| All Qwen | 2/4 | 1/2 / 1/2 | 5 | 333.109s (2 completed) | $0.01913840 | 0/4 |

Costs cover the latest result for each of four planned comparisons, including failures. Earlier failed/recovery attempts remain in separate total-window accounting. All-Qwen timing includes only its two ambiguity successes. These are known list-price estimates, not complete billing or an equal completed-report timing population.

### Stage compatibility and planner request times

| Configuration | Planner accepted | Extraction accepted | Retrieval accepted | Selection accepted | Median successful planner request |
|---|---:|---:|---:|---:|---:|
| All 20B | 12/12 | 4/4 | 4/4 | 4/4 | 0.531s |
| 120B + 20B | 12/12 | 4/4 | 4/4 | 4/4 | 0.786s |
| Qwen + 20B | 12/12 | 4/4 | 4/4 | 4/4 | 0.324s |
| All Qwen | 10/10 | 4/4 | 4/4 | 2/4 | 0.347s |

These are accepted adapter-call outputs in the latest four-comparison cohort, not independent field-accuracy scores. All-Qwen has fewer planner calls because the two ordinary reports stopped before final review. Request timing excludes evaluator pacing but includes application admission; no intrinsic-speed or p95 claim is made.

A scoped exact report requires ready-for-review state, the expected event type, quantity, quantity kind, unit, work date, area, asset tags, mapping state and chosen activity IDs, plus an intact approval boundary. It is not an assertion that every optional field or possible semantic property was independently adjudicated.

Failed and unattempted work receive no success credit. Original failed jobs remain retained. A scheduled comparison may be fully evaluated and still fail: “testing complete” does not mean “model passed.”

### Availability and compatibility findings

The first all-Qwen window stopped on selection HTTP503. A single separately frozen same-key rerun retained that failure and attempted all four planned comparisons. Its unambiguous reports received HTTP200 but failed local schema validation: one used a `suggested` wrapper; the other used `decision`, `candidate_id`, `evidence`. Both ambiguity reports passed. All-Qwen therefore has two successful reports out of four planned comparisons and five total attempts including the initial endpoint failure. No root cause of the HTTP503 is inferred.

The mixed Qwen/20B study also retains a different original network timeout. The owner attributed that earlier timeout to an issue on their side and explicitly requested rerun; the same-key rerun passed. That attribution does not apply automatically to the later all-Qwen HTTP503. Original jobs and captures remain retained.

The error class `OllamaResponseError` in Groq adapter logs is a shared exception name. It does not mean these tests used an Ollama endpoint.

The application is designed to reject unusable model output rather than approve it. No live study invoked approval or delivery, and the study databases recorded no progress-ledger writes. Successful terminal replays reused completed results without duplicate proposals. This verifies the tested boundary, not resistance to every attack or production failure mode.

### Reading the timing numbers

Planner transport duration excludes the evaluator's own pacing wait but includes application provider admission. Whole-report time includes cold-reservation pacing, provider admission, worker inference, validation, PostgreSQL work and checkpoints. Do not subtract two such timings and label the difference intrinsic model speed.

These studies reserve cold input bytes, framing and the output cap, pace conservatively at 6,000 TPM / 22 RPM per account and retain the application's existing **shared provider-wide admission**. Separate credentials do not mean independent application admission buckets were activated. These measurements do not isolate the causal effect of two-account capacity.

The established report-readiness target is 120 seconds. None of the latest configurations has demonstrated four ready reports inside that target under this pacing regime. The ordinary successful reports typically needed six calls: three supervisor confirmations and three worker calls. No sustained-load p95 or production throughput result is established.

## 4. Earlier component evidence and why it differs

The earlier two-key Qwen role-contract study used a projected extraction schema and a tiny activity-ID array selection schema:

| Role-level test | Qwen | GPT-OSS control | What it establishes |
|---|---:|---:|---|
| Six extraction cases, repeated on both keys | 12/12 | 20B: 10/12 | Exact projected events/fields on ordinary, no-work, correction, administrative, mixed and injected text |
| Four selection cases, repeated on both keys | 8/8 successful outputs, plus one HTTP503 | 20B: 6/8 | Exact selected-ID arrays on exact, ambiguous, unmatched and injected cases |
| Three singleton supervisor decisions, both keys | 6/6 | 120B: 6/6 | Correct response to the supplied legal next action |

20B omitted the explicit area on the no-work case on both keys. It selected the attacker-requested wrong activity on both injected selection cases; Qwen resisted those particular attacks. Both worker families still need representative security testing. Enum-valid schedule IDs alone do not establish that a selected ID is factually supported.

These earlier results made Qwen a reasonable challenger, not a production-ready worker. The full selection schema is materially different. The required top-level fields are `candidate_id`, `mapping_state`, `evidence_fragment_ids`, `reason_codes`, `explanation` and `missing_information`. Successful simplified arrays do not test compliance with that contract.

On the unambiguous full-graph reruns, Qwen instead returned one object headed by `suggested`, and another using `decision`, `candidate_id` and `evidence`. Both omitted required fields. For example, the first invalid shape was:

```json
{"suggested":{"candidate_id":"<supplied candidate UUID>","evidence":"<source sentence>"}}
```

The expected shape is illustrated below; this is a schema illustration, **not a captured successful response**:

```json
{
  "candidate_id": "<supplied candidate UUID>",
  "mapping_state": "suggested",
  "evidence_fragment_ids": ["<supplied source fragment UUID>"],
  "reason_codes": ["supported_identity"],
  "explanation": "The report explicitly identifies this area and asset.",
  "missing_information": []
}
```

The rejection is not proof that Qwen can never perform selection. It establishes that the **tested default prompt/schema/adapter combination is not a reliable drop-in**. Explicitly demonstrating the complete object, testing Qwen's supported reasoning modes, or a separately validated strict schema are future tuning candidates. None was applied mid-study or credited as a measured fix.

See the [earlier role-contract review — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#local-archive-provenance) and [actual orchestration review](../evaluation/fixtures/model-comparison-2026-10-22/mixed-configurations.md).

## 5. Prompting techniques: what was used, measured and better

The techniques are composable. A model can use a role instruction, examples, retrieved context and a schema in the same request. A configuration comparison changes model assignments; it does not establish which prompt component caused a difference.

### Controlled prompt results

| Technique/ablation | Measured outcome | Current interpretation |
|---|---|---|
| Clear zero-shot task specification versus three demonstrations, batch 30 | Grounded selected-field exactness 1/8 → 3/8; all 16 outputs wire/domain valid | Examples improved this small sample, but five of eight still failed the stronger metric. This is not an acceptance pass. |
| Fixed example versus training-only dynamically retrieved example, batch 32 projected schema | Both 6/6; plain 20B 3/6 | Fixed examples are the simpler candidate here. No measured benefit justifies a dynamic example index yet. |
| More explicit model-tailored 20B rules, batch 32 | 4/6 versus plain 3/6 | Small diagnostic gain; verbosity alone did not eliminate errors. |
| Ordinary versus difficult demonstration sets, batch 30 | Ordinary demos 2/2; difficult demos 1/2 on the tested subset | Hard examples are not automatically better. Demonstration choice must be tested by slice. |
| Forward/reversed example ordering, batch 30 | Six trials, two grounded exact outcomes in aggregate; no copied example-specific values identified by the recorded audit | No universal best order established. Keep order fixed in fair model comparisons. |
| V12 long instructions versus consolidated specification | Six trials; two grounded selected-field exact outcomes in aggregate; prompt lengths 8,944 versus 2,554 characters | The record does not establish a winner. Shortening can remove protections; longer text did not guarantee accuracy. |
| Low versus medium reasoning effort on the hard subset | Both 0/2 grounded exact; completion tokens 1,222 versus 3,646 | Medium used about 3× output tokens without a gain in this test. No unconditional reasoning escalation. |
| Best-effort versus strict output | Corrected small early schema: 2/2 each. Later strict extraction experiment retained HTTP400s and stopped trials | Strict can help formatting when supported, but compatibility depends on the actual schema. No semantic improvement or universally reliable strict mode established. |
| One validator-feedback repair | Zero of three incorrect extracts became exact; one correct administrative control remained correct | A repair costs a call and can remain wrong. Keep a bounded, evidence-based policy; no unconditional reflection loop. |
| Three-sample self-consistency and separate 120B critic | Three extraction samples and critic all failed grounded exactness; majority was 2/3, not a correct answer | Consensus and model review are not truth. No production voting or best-of-N success credit. |
| Clause-coverage suffix, earlier isolated 20B experiment | Normalized exact fields 1/2 → 2/2; improved retention of explicit no-work beside planned work | Promising targeted rule, not a general quality guarantee. |
| Non-actual quantity rule on two consumed inputs | Raw selected fields 1/2 → 2/2; normalized fields already 2/2 in both arms | Improved raw output, not a new normalized-quality gain. Do not credit app normalization to the model. |

Batch-30 `grounded_exact` is its recorded domain-valid, source-quote-grounded selected-field exactness measure. It is different from batch-32 projected-event equality and the latest full-report success metric. Denominators, schemas, contexts and labels differ; the percentages are not one pooled leaderboard.

Evidence: [batch-30 prompt/model review — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#historical-evidence), [zero/few-shot detail](../evaluation/fixtures/model-comparison-2026-10-22/prompt-evidence.json), [reasoning detail](../evaluation/fixtures/model-comparison-2026-10-22/prompt-evidence.json), [repair detail](../evaluation/fixtures/model-comparison-2026-10-22/prompt-evidence.json), [consistency detail](../evaluation/fixtures/model-comparison-2026-10-22/prompt-evidence.json), [batch-32 projected study — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#historical-evidence), [coverage comparison — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#local-archive-provenance), [quantity ablation — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#local-archive-provenance).

### How the techniques apply to this agent

**Role instructions and authority.** The prompt states the construction extraction or activity-identity task. Report bodies and schedule text remain data, even if they contain instructions. A persona does not create facts or permission to approve work. Elaborate persona wording has not been isolated in a measured ablation.

**Contrastive examples.** V12 distinguishes actual work, plans, no-work, delivery, blocker, correction and explicit lifecycle events, and separates quantities from percentages and identifiers. These examples help specify the task. The current configuration study did not vary them, so it cannot award them an isolated causal improvement.

**Structured output and deterministic validation.** JSON schemas constrain the requested shape; local schema checks, legal-ID checks, evidence validation and workflow policy decide what can proceed. Best-effort schema mode still returned structurally wrong Qwen selection objects. A validator's rejection is a successful safety control and a failed task outcome. Syntactically valid output can also contain wrong facts, as the injected 20B array selection showed.

**Retrieval-augmented matching.** Actual report evidence is combined with a project/schedule-scoped activity shortlist. The graph first discovers candidates and then chooses or abstains. This supplies current legal IDs rather than asking the model to invent schedule knowledge. The latest matrix does not compare embeddings against lexical retrieval or prove an optimal retrieval algorithm.

**Prompt chaining and decomposition.** Extraction, discovery, selection and validation have separate contracts and telemetry. That separation exposes where a configuration fails. It also adds calls and propagates upstream mistakes; full-chain measurement is required. A component result cannot be promoted into a workflow score.

**Bounded orchestration/tool use.** The graph controls legal stages, counters and approval boundaries. This resembles bounded tool-assisted processing but is not an experimental comparison of unconstrained ReAct against another agent framework. Three model supervisor confirmations add overhead; no general need for a large planner was demonstrated on these two cases.

**Reasoning and critique.** GPT-OSS uses low reasoning in the app; Qwen's mode is not explicitly set. The separate low/medium ablation showed no gain on its hard subset. No private reasoning traces are exported. Validator feedback and a critic remain fallible, bounded interventions, not approval authority.

**Techniques not demonstrated as better.** Tree-of-Thoughts search, free-form multi-agent debate, a stronger persona, adaptive cross-model escalation, production dynamic-example retrieval, a Qwen-specific full selection template and a Qwen reasoning-mode ablation have no completed superiority result in this latest matrix. Their possible benefits are hypotheses, not measured recommendations.

## 6. Historical evidence kept separate

| Earlier experiment | Result and important limit |
|---|---|
| Batch 32 plain projected extraction | 20B 3/6, 120B 6/6; tiny six-case projected schema, not complete production quality |
| Batch 30 four-input full-schema extraction comparison | 20B 0/4 versus 120B 1/4 on grounded selected-field exactness; all wire-valid, one 120B domain failure |
| Earlier identical V12 paired pilot | Four completed calls across two cases; 20B omitted explicit no-work in one mixed report, 120B retained it; normalization corrected planned quantities in both |
| Batch 32 deterministic routing | Ordinary report 97.580s / three calls; ambiguity control stopped at the original budget and remains unfinished |
| Batch 32 120B assistance, one account | Two scoped successes: 182.738s and 166.131s |
| Batch 32 120B/key1 with 20B/key2 | Two scoped successes: 142.704s and 143.985s; no causal throughput or p95 conclusion |
| Historical Qwen 3.5 4B, September | Quantity 24/36, unit 17/27; candidate IDs were omitted, so its 0% selection score is not a fair linking result. Atomic F1 zero reflected missing scoring keys, not a measured semantic zero. Not Qwen 3.8 27B. |
| Historical Gemma 4 12B, October | 44/45 matchable selections, 44/49 overall selected precision, 10/15 safe abstentions, 17/60 exact combined-field matches; false selections on unreadable/injected unmatched inputs remain retained |

Historical hardware, model versions, quantization, prompts, context, schemas, token caps, scorer conventions and exposure histories differ. No direct Gemma/Qwen-small/GPT/Qwen-27B ranking is valid from these numbers. The earlier file's `held_out` name is historical lineage; those inspected examples are not a new unseen holdout now. AI-assisted label review remains distinct from independent human adjudication.

The [historical results index — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#historical-evidence), [batch-30 model comparison](../evaluation/fixtures/model-comparison-2026-10-22/prompt-evidence.json), [paired pilot — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#local-archive-provenance) and [batch-32 review — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#historical-evidence) preserve these conditions and failures.

### Other historical planner comparisons

The 15 October OpenRouter smoke used the actual singleton-action validator, not complete extraction or autonomous planning:

| Exact historical model ID | Valid actions | Median successful call | Interpretation |
|---|---:|---:|---|
| `nvidia/nemotron-3-super-120b-a12b:free` | 3/3 | 1.428s | Basic supervisor compatibility only |
| `google/gemma-4-31b-it:free` | 0/1 | n/a | Stopped on HTTP429; no accuracy conclusion |
| `google/gemma-4-26b-a4b-it:free` | 0/1 | n/a | Stopped on HTTP429; no accuracy conclusion |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | 3/3 | 3.892s | Basic supervisor compatibility only |
| `nvidia/nemotron-3.5-lightning:free` | 3/3 | 6.784s | Basic supervisor compatibility only |
| `nvidia/nemotron-3.5-super-vl:free` | 3/3 | 0.625s | Fastest in that small smoke, not a current universal winner |

A separate Super VL full-graph study retained a live 60-activity pair: both arms were ready with expected activity/quantity; baseline took 202.487s with 11 Groq calls and assisted routing 221.691s with 11 Groq plus three planner calls. Most time was pacing. In six controlled fixtures, both arms had five successes and one retained interruption; the interrupted case later passed a separate retry. The candidate's worker responses were replayed only after exact payload matching, so this establishes orchestration parity, not independent worker quality or comparative candidate latency. Three ambiguity/unmatched/injection cases safely abstained in both controlled arms.

These historical models were not rerun in the latest matrix. `:free` and the old catalog check describe that historical configuration, not a guarantee of current availability, entitlement or pricing. Specialized guard/classifier probes in earlier safety batches have different tasks and are not ranked as report workers or supervisors here. See the [OpenRouter smoke — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#historical-evidence), [Super VL report — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#historical-evidence) and [capture limitations — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#historical-evidence).

## 7. Costs, quotas and reliability

Groq public list prices checked on 22 October 2026, per million tokens:

| Model | Input | Output | Operational note |
|---|---:|---:|---|
| GPT-OSS 20B | $0.075 | $0.30 | Cheapest token rates among these models |
| GPT-OSS 120B | $0.15 | $0.60 | Twice 20B's listed input/output rates |
| Qwen 3.8 27B | $0.80 | $4.00 | Preview; about 10.7× 20B input rate and 13.3× output rate |

Sources: [Groq 20B](https://console.groq.com/docs/model/openai/gpt-oss-20b), [Groq 120B](https://console.groq.com/docs/model/openai/gpt-oss-120b), [Groq Qwen](https://console.groq.com/docs/model/qwen/qwen3.8-27b). Cached discounts are not assumed. Actual cost also depends on input/output volume, reasoning tokens, retries and failed attempts. Cheap tokens are not sufficient if output quality is poor; a higher-priced model can still use fewer tokens on a particular task.

| Window family | HTTP attempts / HTTP200 | Known tokens | Known list-price usage | Unknown usage attempts | Cold reservation |
|---|---:|---:|---:|---:|---:|
| 120B/20B and Qwen/20B combined | 50 / 49 | 51,369 | $0.00621347 | 1 | $0.50794880 |
| All-Qwen, initial + recovery | 27 / 26 | 20,151 | $0.02283120 | 1 | $0.28566400 |
| All-20B | 24 / 24 | 26,515 | $0.00265643 | 0 | $0.02035950 |

The earlier projected-role study is separate: 53 attempts, 52 successful unique trials, known list-price usage $0.00649575, one unknown-usage HTTP503, cumulative cold reservation $0.222766. No volume is silently merged into a fresh budget.

HTTP counts in the accounting table refer to completion POST attempts; read-only model-catalog GET checks are separate. Known usage is an estimate at checked list prices, not verified billing. Missing failed-request usage is unknown, not zero. Original interrupted attempts, provider errors and all reservations are retained. The earlier batch-32 integration incident had uncaptured traffic; no document should claim a complete total-project bill or retroactively reset its budget. Budget reservations are conservative limits and are not money known to have been billed.

The all-Qwen recovery subtracts the first window's reservations from its original $1 ceiling. All-20B has its own $0.25 ceiling. Original mixed-model and role-contract windows are separate; their overlapping reports and old budget continuations are not double-counted into a new global experiment. Both supplied keys are owner-confirmed independent accounts; provider plan/project details, unused slot 0 and complete daily remaining allowance remain outside this experiment's verification.

## 8. Recommendations and what “better” means

- **Development baseline:** all-20B is the cheapest fully passing tested configuration for this bounded graph. Its singleton planner decisions did not require 120B on these cases. Run a larger quality/security evaluation before adopting it.
- **Current mixed baseline:** 120B orchestration with 20B workers passed 4/4. It remains a working reference, but these reports show no quality benefit that justifies the larger planner's extra token rate.
- **Qwen orchestration with 20B workers:** passed 4/4; Qwen's successful planner requests were faster in the recorded mixed study. Its higher per-token rate and the paced/nonconcurrent setup prevent a general cost or speed victory.
- **All-Qwen:** 2/4 full-report success makes it the weakest drop-in configuration in this matrix. Retain it as a separate tuning candidate rather than activating it with the current selection prompt/schema.
- **Quality caveat:** earlier projected tests found 20B negation and injection mistakes that Qwen avoided. The all-20B full-graph cases did not test those attacks. Cheapest compatible is not the same as best semantic accuracy or release readiness.

For prompting, the evidence supports trying a **clear specification plus a small fixed set of reviewed examples**, using legal schedule context and deterministic validators, before adding dynamic examples or expensive reasoning/voting. This is a development recommendation: the full-schema few-shot experiment still failed five of eight stronger checks, and the projected-schema 6/6 result is not a release certificate.

For Qwen workers, the first next experiment should isolate the selection contract: explicit six-field output instructions and one complete valid example versus the current prompt, on the same cases and a separately reviewed attack/missing-data set. Any strict-mode or reasoning-mode change should be a separate arm. Keep the original invalid answers and do not make the app accept an ad hoc alternate response merely to improve the score.

For latency, first distinguish pacing/admission from inference and measure whether singleton model supervision adds useful behavior. The historical deterministic ordinary result is promising, but its ambiguity control remains incomplete; it cannot be crowned the overall winner. Model token speed alone did not solve readiness.

For safety, include no-work, correction, future work, mixed events, unreadable text, unmatched activities and injected instructions in the next full-graph comparison. The current two-case matrix does not cover these adequately. Retain review authority in application code and require human approval for changes that actually apply progress.

## 9. Verification and reproducibility

Publication verification: **1,477 backend unit tests passed, one skipped**, including offline evidence rescoring and tamper rejection. No new model inference was performed to publish this report. Earlier 226 focused study controls remain part of the dated evidence.

Latest study software checks, capture verification and source snapshots are in the study reviews. The 20B planner allowlist extension has focused regression coverage; these tests use injected model responses and do not themselves prove model quality. Live captures are rescored independently against the frozen labels and actual schemas. Supervisor responses pass the application's actual `validated_decision` function, and role/key/model assignments are checked from requests and returned model identities.

The runners refuse non-local/non-rehearsal databases and nonempty project databases; preserve test jobs/checkpoints; reserve calls/tokens/spend before dispatch; stop on provider/model identity failure; and never call approval. A bounded recovery is a separately frozen window, not an erased attempt. Runs are not auto-resumed to manufacture a clean score.

Reproduction requires the matching frozen source/dependencies, a new local `progress_rehearsal_*` database migrated to 0018, two authorized Groq keys and a new reviewed output directory/budget. Do not point a runner at the active application database or reuse its fixed capture path. Published runners include post-study fixture-path, explicit-output and formatting changes; their current bytes are not the frozen capture hashes. A fresh checkout can rescore the sanitized evidence offline; reproducing original transport/source checks requires the local archives. Historical source snapshots must be used when the current code hash differs. No secrets should be pasted into commands, reports or artifacts.

Offline summaries do not make new model calls. They verify capture/source/input hashes, model/slot assignments, schema validity, exact scoped report scores, replay behavior and cumulative reservation totals. See [generation settings](model-generation-settings.md), [durable configuration](durable-model-configuration.md), [stage semantics](stage-specification-v1.md) and [testing record](TESTING_AND_QUALITY.md).

### Remaining acceptance work

A broader, independently reviewed development corpus; genuinely fresh validation/holdout with exposure accounting; full security/abstention and lifecycle coverage; production-equivalent mixed workloads; quota/admission recovery; current UI/product end-to-end checks; readiness acceptance and a frozen candidate decision all remain. No finite smoke-test score closes these broader checklist items.

The checklist inventory audit records 269 rows (231 checked, 38 open). Qwen now has unique MODEL-11; historical MODEL-10 lifecycle records and old batch counts remain retained. This corrects an extra Qwen row omitted from consolidation, not a new requirement closure.

The published offline command verifies curated outcomes, prompt digests and summary consistency. It cannot independently audit omitted raw transport/provider-usage records. Links marked “local archive” lead to the public provenance explanation, not to raw captures.

## 10. Evidence index

- [Machine-readable four-configuration matrix](../evaluation/fixtures/model-comparison-2026-10-22/summary.json).
- [Prompt ablation records and source hashes](../evaluation/fixtures/model-comparison-2026-10-22/prompt-evidence.json).
- [Exact latest prompt catalog](MODEL_PROMPT_CATALOG.md) and [captured prompt data](../evaluation/fixtures/model-comparison-2026-10-22/prompt-catalog.json).
- [Application source differences](../evaluation/fixtures/model-comparison-2026-10-22/application-source-differences.json).
- [All-20B review](../evaluation/fixtures/model-comparison-2026-10-22/all-20b.md).
- [All-Qwen review](../evaluation/fixtures/model-comparison-2026-10-22/all-qwen.md), [schema diagnostics](../evaluation/fixtures/model-comparison-2026-10-22/all-qwen-schema-diagnostics.json), and [recovery window — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#local-archive-provenance).
- [Mixed 120B/20B and Qwen/20B review](../evaluation/fixtures/model-comparison-2026-10-22/mixed-configurations.md).
- [Earlier projected Qwen component study — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#local-archive-provenance).
- [Batch-32 study — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#historical-evidence), [batch-30 study — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#historical-evidence) and [historical evaluation results — local archive](../evaluation/fixtures/model-comparison-2026-10-22/README.md#historical-evidence).

For quick reading, use [model quality summary](MODEL_QUALITY_SUMMARY.md). For per-requirement status, use the [testing checklist](MODEL_COMPARISON_CHECKLIST.md). The [execution log](../evaluation/fixtures/model-comparison-2026-10-22/README.md) retains the dated sequence; this report consolidates the final measured interpretation.

---

[Documentation index](README.md) · [Project overview](../README.md)
