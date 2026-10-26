# Gonka role comparison — 26 October 2026

The [completed four-model comparison](FOUR_MODEL_ROLE_COMPARISON.md) supersedes
these preliminary recommendations. The sections below retain earlier trial
evidence; they are not the current configuration. The private profile checked
on 26 October is Qwen planning, GPT-OSS 120B extraction and GPT-OSS 20B selection.
DeepSeek’s planner was independently retested with fence normalization and still
failed all three transitions under the 128-token planner contract.

## Scope and result

The input was [`artifacts/gonka-model-comparison/input.txt`](../artifacts/gonka-model-comparison/input.txt), paired with the five matching rows in `data/review/gt10-five-entry/schedule.csv`. The earlier comparison captured validated extraction output from DeepSeek V4 Flash (six observations) and MiniMax M2.7 (nine observations). The new [`role-run-result.json`](../artifacts/gonka-model-comparison/role-run-result.json) reuses the saved DeepSeek extraction and makes live calls through the application planner and selection validators. It uses deterministic schedule candidates, not live retrieval. The local PostgreSQL test database was unavailable, so this is a role-contract rehearsal, not a full durable graph or persistence test. No progress was approved or written to the ledger.

| Role | Model | Live calls | Observed latency | Output and validation |
|---|---|---:|---|---|
| Orchestrator | `MiniMaxAI/MiniMax-M2.7` | 3 | 3.084s, 11.057s, 14.202s | `intake` and `analysis` passed. `review` failed the adapter completion check (`OllamaResponseError: OpenRouter response was incomplete` at the time of the run). A full model-assisted graph would stop at that failure. |
| Selection | `deepseek-ai/DeepSeek-V4-Flash-0731` | 6 | 59.319s, 45.367s, 1.971s, 10.502s, 10.445s, 10.718s; median 10.610s | Six schema-valid proposals. All six resolved to the corresponding `SUP-GF-01` through `SUP-GF-05` activity: column reinforcement 300 kg delta → 01; slab shuttering 60 m2 delta → 03; column concrete no work → 02; slab reinforcement no work → 04; slab concrete no work → 05; column reinforcement inspection → 01. No selection validation error. |
| Extraction, saved earlier | `deepseek-ai/DeepSeek-V4-Flash-0731` | 0 in this run | Earlier capture: 23.116s | Six validated observations, no schema errors. It classified the column reinforcement inspection as `weld_inspection`, a semantic mismatch to review. |
| Extraction, saved earlier | `MiniMaxAI/MiniMax-M2.7` | 0 in this run | Earlier capture: 90.722s | Nine validated observations, no schema errors; several no-work and blocker records are split. |
| Extraction, saved earlier | `zai-org/GLM-5.3-Flash` | 0 in this run | Earlier capture timed out before an HTTP response | No validated output. |

The two earlier extraction latencies came from a separate script and are not directly comparable to the new role calls. The first two selection calls were much slower than the other four. All six selections passed validation, but this single input does not establish general accuracy or stable latency. The selection of a no-work event identifies its activity; it does not turn the event into installed progress.

## Configuration recommendation

Historical recommendation at this trial stage: retain the then-documented 120B/20B reference pending database-backed comparison. This was not a verification of the active private settings. For a Gonka trial on **new** jobs, use deterministic V2 orchestration with the existing extraction assignment and DeepSeek V4 Flash for selection. This follows the six valid selections without depending on MiniMax's failed planner transition. It still needs an isolated full-graph test before production use.

```dotenv
AGENT_HIERARCHY_ENABLED=true
ORCHESTRATOR_MODEL_ASSISTED=false
EXTRACTION_PROVIDER=groq
EXTRACTION_MODEL=openai/gpt-oss-20b
SELECTION_PROVIDER=gonka
SELECTION_MODEL=deepseek-ai/DeepSeek-V4-Flash-0731
GONKA_BROKER_LLM=<private broker key>
```

The requested paired configuration is supported for further testing by setting `ORCHESTRATOR_MODEL_ASSISTED=true`, `ORCHESTRATOR_PROVIDER=gonka`, and `ORCHESTRATOR_MODEL=MiniMaxAI/MiniMax-M2.7`. The observed failed transition makes it unsuitable as the recommended configuration. Gonka calls share a 10.5-second deployment admission interval; the standalone runner uses the same interval in one process and waits a full minute before resuming across processes. Provider limits and other clients remain authoritative. The broker's [OpenAI-compatible API](https://docs.gonkabroker.com/reference/api-compatibility/) documents the endpoint and exact model identifiers; verify current account limits in the broker dashboard before running parallel clients.

The historical local-only rehearsal used `.venv/bin/python artifacts/gonka-model-comparison/role_run.py` and its saved initial extraction. That runner and the initial raw captures remain in the local archive. The curated push includes its safe result JSON; use the maintained `four_model_matrix.py` runner and the four-model report for the current reproducible comparison. Private keys are read from settings and are not included in the published evidence.

## Groq planner comparison with DeepSeek selection held fixed

On 26 October 2026, [`groq-planner-comparison.json`](../artifacts/gonka-model-comparison/groq-planner-comparison.json) recorded nine further live planner calls using one configured Groq key. The same six saved DeepSeek extraction observations and six valid DeepSeek selection proposals were held fixed for all three arms. The calls were interleaved by supervisor stage and used the production planner validator. No database-backed graph ran in this comparison.

| Orchestrator | Legal transitions | Intake / analysis / review | Three-call total | Median call |
|---|---:|---|---:|---:|
| Qwen 3.8 27B | 3/3 | 0.184s / 2.422s / 2.180s | 4.786s | 2.180s |
| GPT-OSS 20B | 3/3 | 2.516s / 2.466s / 2.512s | 7.494s | 2.512s |
| GPT-OSS 120B | 3/3 | 2.700s / 2.813s / 2.998s | 8.511s | 2.813s |

Qwen was fastest in this small planner-only sample. GPT-OSS 20B is the best cost-focused candidate: all three legal transitions passed, it was second-fastest here, and the earlier four-case complete workflow study found all-20B to have the lowest recorded spend among fully passing configurations. GPT-OSS 120B showed no success advantage on these bounded transitions. The three-call totals are descriptive; the 0.184s Qwen call is unusually fast and one trial cannot establish a latency distribution.

For a **trial** that combines Groq and Gonka, use GPT-OSS 20B orchestration and extraction with DeepSeek V4 Flash selection. If planner latency matters more than model spend, try Qwen orchestration with the same fixed workers. Neither hybrid has passed a database-backed end-to-end graph with this site update. The later safe settings check found Qwen/120B/20B active; see the four-model report and updated runbook.

```dotenv
LLM_PROVIDER=groq
AGENT_HIERARCHY_ENABLED=true
ORCHESTRATOR_MODEL_ASSISTED=true
ORCHESTRATOR_PROVIDER=groq
ORCHESTRATOR_MODEL=openai/gpt-oss-20b
ORCHESTRATOR_KEY_SLOT=1
EXTRACTION_PROVIDER=groq
EXTRACTION_MODEL=openai/gpt-oss-20b
EXTRACTION_KEY_SLOT=2
SELECTION_PROVIDER=gonka
SELECTION_MODEL=deepseek-ai/DeepSeek-V4-Flash-0731
GONKA_BROKER_LLM=<private broker key>
```

For the faster planner trial, change only `ORCHESTRATOR_MODEL` to `qwen/qwen3.8-27b`. The Groq account-slot mapping and provider scopes must match the environment's already verified account setup.
