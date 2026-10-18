# Evaluation results

`evaluation/run.py` evaluates saved prediction JSONL against a separately supplied
label JSONL. It validates event-family membership before joining labels and
rejects prediction files containing expected-label fields. This prevents the
held-out labels from being available to inference or from being silently mixed
across development, validation, and held-out families.

Each run records SHA-256 hashes for prediction bytes, label bytes, and the
labelled configuration. Run lexical, hybrid, and hybrid-plus-LLM outputs with
the same split and save one JSON result per configuration. CI fixtures are
deterministic and are not real-model measurements; set `real_model: true` only
for a run produced by the local model adapter.

Example:

```bash
python -m evaluation.run predictions.jsonl data/synthetic/labels/seed-labels.jsonl \
  data/splits.json --split held_out --config '{"method":"lexical","real_model":false}' \
  --output evaluation/results/lexical-held-out.json
```

The result includes atomic extraction precision/recall/F1, critical-field
accuracy, candidate Recall@8, exact choice, selected precision, coverage, safe
abstention, latency summaries, and error-category counts. No target is marked
achieved by this documentation; measured values must come from saved runs.

---

## Run 001 — qwen3.5:4b held-out evaluation

**Date:** 2026-09-24
**Reviewer:** cyril (AI-assisted at owner's explicit request)

### Model configuration

| Field | Value |
|---|---|
| Model | `qwen3.5:4b` |
| Digest | `2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd` |
| Family | `qwen35` |
| Parameter size | 4.7B |
| Quantization | Q4\_K\_M |
| Thinking | disabled (`think: false`) |
| Output token cap | 200 (`num_predict`) |
| Temperature | 0.0 (deterministic) |
| Host | Tailscale private — `abdullahs-macbook-pro.tail40fcbd.ts.net` |
| Ollama runtime | 0.34.3 |
| Config SHA-256 | `798a81f80cbf45726b19f9b59196aa5b04f415e6887b5b19c0605683e2ba3244` |

### Dataset

| Field | Value |
|---|---|
| Split | `held_out` |
| Label count | 60 |
| Label SHA-256 | `fed48887d2c7b50c20c6b8f41149893e52d13f2bd43303b110d39d88405c5f8c` |
| Prediction SHA-256 | `f05b57e6f9de8007e805d00c3a9f1a8e7ad24a2cc6bdaf4962beaddede4deed4` |
| Result file | `evaluation/results/qwen3-5-4b-held-out.json` |

### Latency

| Metric | Value |
|---|---|
| Count | 60 |
| Median | 3,728.7 ms |
| Mean | 4,993.3 ms |
| p95 | 9,237.6 ms |

### Critical field accuracy

| Field | Correct | Applicable | Accuracy |
|---|---|---|---|
| Tag (activity ID) | 0 | 45 | **0.0%** |
| Quantity | 24 | 36 | **66.7%** |
| Unit | 17 | 27 | **63.0%** |
| Quantity kind | 22 | 60 | **36.7%** |
| Work date | 0 | 0 | n/a |

### Selection metrics

| Metric | Value |
|---|---|
| Recall@8 | 0.0% (0/45) |
| Exact choice | 0.0% (0/45) |
| Selected precision | 0.0% |
| Coverage | 20.0% (9/45 matchable) |
| Safe abstention | 100.0% (15/15) |

### Atomic extraction (P/R/F1)

| Metric | Value |
|---|---|
| Precision | 0.0 |
| Recall | 0.0 |
| F1 | 0.0 |
| True positive | 0 |
| False positive | 60 |
| False negative | 60 |

### Error categories

| Category | Count |
|---|---|
| correct | 43 |
| event\_type mismatch | 13 |
| quantity mismatch | 12 |

### Interpretation

- **Tag accuracy 0%**: Model was not given candidate activity IDs — tag/selection metrics are not meaningful for this prompt configuration.
- **Quantity / unit ~65%**: Good extraction of numerical values from raw fragments without schedule context.
- **Safe abstention 100%**: Model correctly avoided selecting on all 15 ambiguous/unmatched cases.
- **43 of 60 rows "correct"** in error category: event type and quantity were right; only tag linkage failed.
- **Atomic extraction F1 = 0**: No `atomic_event_keys` in predictions; set-based scorer found no overlap — scaffolding gap, not model failure.

### Limitations

- Label review was AI-assisted (not independent human review) — evaluation confidence is reduced.
- Prompt omitted candidate activity IDs; tag and selection metrics are not meaningful for this run.
- Synthetic data only; results do not reflect real field report performance.

## Gemma 4 12B connection smoke — 8 October 2026

The private Ollama endpoint reported runtime `0.40.0` and exact installed model `gemma4:12b` with digest `6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b0d`. A schema-constrained JSON call passed; its saved record is `evaluation/results/gemma4-12b-smoke.json` (4,621 ms model call).

One live report sample produced two validated observations: three installed spools as actual progress, and tomorrow's two planned welds as planned work with no progress quantity. The extraction call took roughly 100 seconds. A live selection sample initially abstained despite a matching area, work type, and asset tag. Prompt `selection-v3` then returned the correct supplied candidate and evidence fragment on the same sample. These are compatibility checks, not held-out accuracy results. Representative latency, assembled pipeline metrics, and independent label review remain pending.

## Gemma 4 12B quality evaluation — 12 October 2026

**Status: preliminary; batch five retry pending.** Six batches of ten held-out
synthetic cases were attempted. Five batches returned complete responses (50
cases); batch five (`EXP-C281`–`EXP-C290`) timed out at 300 seconds. The owner
subsequently reported a PC crash as the cause and requested that only this batch
be rerun after the endpoint is back live. These ten cases are unavailable outputs,
not model mistakes or verified abstentions. The follow-up endpoint check also timed
out. No retry has been performed yet.

### Scope and configuration

This is a compact joint extraction/selection benchmark with all 60 leaf schedule
activities supplied, distinct from the production extraction → model shortlist →
selection pipeline. Inputs contain case identifiers, source fragments, locators
and report dates; expected answers are supplied only to the scorer. Ten fragments
share each request. The set contains 45 matchable and 15 unmatched cases, with no
ambiguous cases. It is an existing evaluation set previously used with Qwen.

| Setting | Value |
|---|---|
| Model | `gemma4:12b`, 11.9B, Q4_K_M |
| Digest | `6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b` |
| Runtime | Ollama `0.40.0` |
| Endpoint | Owner-supplied private Ollama host `100.111.103.28:11434` |
| Temperature / thinking | `0` / `false` |
| Context / output cap | `8192` / `1536` tokens |
| Request timeout / automatic retries | 300 seconds / zero |
| Response schema | Five parallel arrays, ten entries each (`parallel-arrays-v2`) |
| Dataset | `data/synthetic/expanded`, existing `held_out` split |

Twelve case locators across four tabular reports were shifted one source line to
skip an extra table header. Corrections use source structure, not expected field
values. Original inputs and an explicit correction audit are retained; labels
remain unchanged. Independent human label review is pending.

### Preliminary quality on the 50 returned cases

Timeout cases are excluded from this table. These are conditional scores under
the draft compact prompt, not acceptance results for the application.

| Metric | Correct / applicable | Score |
|---|---|---|
| Activity selection, matchable cases | 39 / 40 | 97.5% |
| Precision among selected activities | 39 / 39 | 100.0% |
| Safe abstention, returned unmatched cases | 10 / 10 | 100.0% |
| Event type | 43 / 50 | 86.0% |
| Quantity, non-null labels | 31 / 31 | 100.0% |
| Quantity kind | 36 / 50 | 72.0% |
| Unit, non-null labels | 19 / 25 | 76.0% |
| Raw JSON-null preservation for missing quantities | 0 / 19 | 0.0% |
| Exact agreement on event type, quantity, quantity kind, unit and selection, including nulls | 15 / 50 | 30.0% |

Across all 60 requested cases, 50 returned outputs (83.3%). Five matchable and
five unmatched cases remain unmeasured because of the crash-associated timeout.
The saved scorer also retains all-request counts (39/45 choices and 31/36
quantities), but those figures combine unavailable outputs with mismatches and
must not be interpreted as final model accuracy.

### Timing and diagnostics

| Batch | Cases | Wall time | Outcome |
|---|---|---|---|
| 1 | EXP-C241–EXP-C250 | 149.5 s | Returned |
| 2 | EXP-C251–EXP-C260 | 260.7 s | Returned |
| 3 | EXP-C261–EXP-C270 | 292.4 s | Returned |
| 4 | EXP-C271–EXP-C280 | 200.9 s | Returned |
| 5 | EXP-C281–EXP-C290 | 300.0 s | Timed out; retry pending |
| 6 | EXP-C291–EXP-C300 | 227.4 s | Returned |

Median ten-case request wall time was 244.1 seconds; p95 was 300.0 seconds,
including the timeout. With only six requests and a reported PC crash, this is
preliminary host-specific timing. Per-case interactive latency and UI-to-export
latency were not measured.

One separate production component case (`EXP-C241`) took 376.8 seconds: extraction
127.9 s, two shortlist calls 113.5 s and 62.2 s, selection 73.2 s. It extracted
10 m3 correctly but returned unrelated piping candidates for civil excavation;
selection then abstained. The production attempt was stopped after that completed
case and an interrupted second case. It is a diagnostic, not a complete production
held-out evaluation. Earlier compact attempts include a 180-second timeout and an
interrupted request before the table-locator correction; they are preserved separately.

### Error examples and interpretation limits

- `EXP-C241`, `EXP-C244` and `EXP-C247`: activity and quantity were correct, but
  duplicate-labelled source assertions became `unknown` rather than the labels'
  `actual_progress`. The draft prompt explicitly permits this interpretation.
- `EXP-C253`: model abstained on curing described as “completed None”; the label
  expects `CIV-A-CURE-01`. This was the only returned matchable-case selection miss.
- `EXP-C248`: a correction states “count is 10” without a unit; the model emitted
  `none`, while the label expects `m3`. Some unit labels therefore require schedule
  context or inference beyond explicit source units.
- `EXP-C250`: the draft prompt steers canonical units toward `equipment`; the label
  and production enum use `each`. The prompt also lists `tonne` and `percent`,
  differing from the production enum. Unit scores cannot isolate model quality
  under these inconsistent conventions.
- Missing quantities were strings such as `"None"` or `"null"`, rather than JSON
  null. Raw benchmark outputs are retained without repair. Production extraction
  has separate placeholder normalization; this benchmark does not test that behavior.

Atomic extraction precision/recall/F1 is unavailable because labels have no
attribute-level atomic events. Candidate Recall@8 is unavailable because the full
schedule is supplied directly. Work dates, lifecycle times, ambiguous-case safety,
real field reports, independent human adjudication, approval/export behavior and
complete graph-runtime quality remain untested. Historical Qwen scores use a
different prompt, omitted candidate context and uncorrected locators, so they do
not support a fair model ranking.

### Saved evidence and reproduction

Evidence directory: [`results/gemma4-12b-2026-10-12/`]().

- [`compact/scored.json`](compact/scored.json): split-validated scores, successful-response metrics and per-case differences.
- [`compact/predictions.jsonl`](compact/predictions.jsonl) and [`compact/calls.jsonl`](compact/calls.jsonl): outputs, raw response arrays, prompt/settings hashes and request timings.
- [`compact/config.json`](compact/config.json), [`compact/runner.py`](compact/runner.py) and [`provenance.json`](provenance.json): model identity, frozen runner, commit and source/dataset hashes.
- [`input-corrections.json`](input-corrections.json): twelve table-locator corrections.
- [`production-diagnostic.json`](production-diagnostic.json): separate incomplete production measurement.
- [`retry-inputs.jsonl`](retry-inputs.jsonl): the ten failed cases queued for the owner-authorized retry.

```bash
# Only after the owner reports that the PC is back live:
.venv/bin/python -m evaluation.gemma_compact \
  --endpoint http://100.111.103.28:11434 \
  --inputs evaluation/results/gemma4-12b-2026-10-12/retry-inputs.jsonl \
  --output-dir evaluation/results/gemma4-12b-2026-10-12/retry-batch-five
```

Runner lint checks passed; the existing evaluation-metrics suite passed 13 tests.
The initial captures are preserved for comparison with the pending retry.
