# Model evaluation guide

## Current acceptance workflow — 18 October 2026

[Current status](../docs/current-status.md) records the six open workstreams.
Extraction is configured as Groq `openai/gpt-oss-20b`; V20 remains opt-in.
The latest completed report spent 111.316 seconds in admission and 2.842 seconds
in transport across three calls. Its 115.757-second readiness is one sample, not
a sustained p95. Regression success is not quality/capacity acceptance.

Both V19 validation and holdout are consumed, including provider-failed cases.
Freeze fresh inputs, group-disjoint splits and eligible reviewed labels before
V20 acceptance capture. Keep labels out of model calls. Seal initial responses,
normalized proposals, source/config hashes and failures before scoring every case.
Evaluate a new holdout after validation; never tune against its results.
The [frozen owner targets](../docs/evaluation-targets-approved-2026-10-16.json)
govern acceptance. Use the following current tools:

| Tool | Scope |
|---|---|
| `evaluation.extraction_quality` | Live development extraction; accepts `--prompt-version` and `--batch-size` |
| `evaluation.delivery_matching` | Supplied-observation blocker/delivery matching; `--short-ids` selects V20 behavior |
| `evaluation.frozen_acceptance` | Real worker report capture for a frozen validation/holdout split |
| `evaluation.score_frozen_acceptance` | Offline scoring after sealed-capture integrity checks |
| `evaluation.calibrate` | Eligible validation confidence study; no runtime policy installation |
| `evaluation.mixed_workload` | Bounded two-worker report/lifecycle-conversation rehearsal on an idle local rehearsal database |
| `evaluation.full_approval_delivery_latency` | Browser approval, durable commit and automatic HTTP MOCK delivery; isolated by default |

Read each module's `--help` with
`PYTHONPATH=backend .venv/bin/python -m <module> --help` from the repository root.
Live commands consume shared provider quota and require a new output directory.
Extraction, matching and frozen capture default to groups of at most five cases,
with at least 60 seconds between groups and a cooldown check before each case.
Pre-submission pacing is recorded separately from report readiness.

Inspect retained work in `progress_rehearsal_20261016` and
`progress_rehearsal_eval_20261017` before starting workers. The latest mixed runner
pins V20/Groq conversations, supplies lifecycle starts and rejects empty-card or
model-free completions, but that revision has not been live validated. The second
18 October attempt stopped on expired ownership after a clock discontinuity;
it does not certify sustained operation. Browser latency has not yet been measured
during the required sustained concurrent workload. See
[the follow-up](../docs/release-followup-2026-10-18.md).

[RESULTS.md](RESULTS.md) is the measured-results record. Fixture tests, live model
benchmarks and full application acceptance have different scopes; each result must
identify its inputs, model digest, prompt/settings, denominators and limitations.

## Local evidence availability

The current workspace contains runners, scorers and raw/combined captures. Some remain uncommitted/unpushed, so verify availability before reproducing from a fresh checkout. Historical documentation-only publications did not include every local artifact. Documentation updates do not publish these files or establish acceptance.

## Completed compact Gemma benchmark

The `results/gemma4-12b-2026-10-12/combined-after-retry/scored.json`
cover 60 existing synthetic held-out cases. Original batches 1–4 are combined with
the owner-requested post-crash reruns of batches 5–6. Original captures and failures
are retained. The model sees report fragments and all 60 leaf schedule activities,
not expected labels. Twelve table locators were corrected from source structure;
see the `results/gemma4-12b-2026-10-12/input-corrections.json`.

| Measurement | Result |
|---|---|
| Matchable activity choice | 44/45 (97.8%) |
| Precision across all selections | 44/49 (89.8%) |
| Unmatched-case safe abstention | 10/15 (66.7%); five false matches |
| Stated quantity accuracy | 36/36 (100%) |
| Event type / quantity kind / applicable units | 53/60, 41/60, 21/27 |
| Ten-case request median / p95 | 206.3 / 292.4 seconds |

The draft prompt's unit conventions differ from production, and duplicate/unclear
wording can differ from label conventions. Missing quantities were represented as
strings rather than JSON null. Labels lack independent human adjudication. There
are no ambiguous cases or attribute-level atomic labels; atomic F1, candidate
Recall@8 and UI-to-export timings are unavailable. Historical Qwen inputs/prompt
also differ, so these records cannot establish a fair model ranking.

### Score saved captures

From the repository root, this command makes no model or database calls:

```sh
.venv/bin/python -m evaluation.summarize_gemma \
  --capture-dir evaluation/results/gemma4-12b-2026-10-12/combined-after-retry
```

The scorer validates held-out family membership, exactly matching case identities
and absence of expected-label fields in predictions. It reports all-selection
precision and prevents failed requests from counting as verified safe abstentions.
Original preliminary scores remain in `results/gemma4-12b-2026-10-12/compact/`.

### Generate a new compact capture

This is an explicit live model call and may take many minutes. Use a new output
directory to preserve existing evidence. Endpoint/model configuration is supplied
by the operator; inputs must be label-free. The runner uses `gemma4:12b`, batches
of ten, `temperature=0`, `think=false`, context/output caps of 8192/1536 and a
300-second request timeout with zero automatic transport retries.

```sh
.venv/bin/python -m evaluation.gemma_compact \
  --endpoint http://PRIVATE_OLLAMA_HOST:11434 \
  --inputs evaluation/results/gemma4-12b-2026-10-12/inputs-corrected.jsonl \
  --output-dir evaluation/results/NEW_CAPTURE_DIRECTORY
```

Existing case IDs in the output are skipped on resume, including failed-case rows.
Retries require a separate capture with the same source cases. The saved combined
configuration records SHA-256 hashes for its original and retry prediction files;
per-row/call `capture_source` fields identify the selected attempt. Do not substitute
labels, tune against these outcomes, or call this existing set independently unseen.

## Production component diagnostic

`evaluation/gemma_quality.py` calls the production extraction, model shortlist and
selection functions on isolated fragments. The saved one-case diagnostic took
376.8 seconds and missed the matching activity during candidate discovery. This is
incomplete component evidence; it does not drive the browser, persist application
jobs, approve proposals or export accepted state.

## Independent acceptance remains pending

The genuine UI-to-export capture contract is described in [E02](../docs/handoffs/V2-E02.md).
Independent label adjudication, reviewed/frozen splits, target agreement and
calibration remain separate gates. The [targets](../docs/evaluation-targets-draft.md)
are an unapproved draft and have not been tuned to this compact benchmark.


## Hierarchical report planner evaluation

[The Super VL report evaluation](results/report-planner-super-vl-2026-10-15/REPORT.md) records the live independent report pair, exact-payload specialist replay fixtures, retained failures/retries, and rollout limitations. Discovery requests are byte bounded; the evaluation transport observes provider quota headers without credential rotation.

To reproduce the controlled matrix with synthetic inputs and the isolated local database:

```sh
.venv/bin/python -m evaluation.report_planner_eval \
  --output-dir evaluation/results/NEW_PLANNER_CAPTURE \
  --dataset seed --replay-specialists --timeout 60
```

The baseline makes live Groq requests. Candidate specialist responses are replayed only for identical payload fingerprints; Super VL planner calls stay live. This checks orchestration parity and does not establish an independent specialist quality or latency ranking. Labels never enter model inputs. Every new run must use a new capture directory; failed first attempts remain evidence.

## Report scoring and provider capacity — 16 October

`report_scoring.py` adds versioned normalized quantity/effect safety, exact activity-set coverage and atomic-event metrics while retaining historical raw scores. `report-scoring-v3` uses the production reducer's documented unit conversions, so `0.5 t` and `500 kg` compare correctly without allowing mass/volume guesses. Planned/no-work/delivery quantities are tested against normalized non-progress behavior separately from literal source-quantity recall.

`reviews/seed-source-review-2026-10-16.json` contains separate source-level technical notes, explicitly not human adjudication. Apply them to saved evidence without editing the original capture:

```sh
PYTHONPATH=backend .venv/bin/python -m evaluation.review_saved_reports \
  --capture-dir evaluation/results/EXISTING_CAPTURE \
  --output-dir evaluation/results/NEW_REVIEW
```

Add `--deterministic-planner` to `report_planner_eval` for v2 deterministic orchestration. These rows are named `v2_deterministic`; they do not consume OpenRouter planner quota. Report captures now retain sanitized ownership snapshots and use the production heartbeat primitive in an independent thread. Successful specialist replay still requires identical complete payloads; failed transport replay preserves its error type rather than inventing HTTP 599.

See [provider capacity and policy](../docs/provider-capacity.md) for the bounded live probes, per-process admission guard, deterministic fault coverage, unchanged fallback identity and remaining deployment-level limits.
