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

| Field            | Value                                                                |
| ---------------- | -------------------------------------------------------------------- |
| Model            | `qwen3.5:4b`                                                       |
| Digest           | `2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd` |
| Family           | `qwen35`                                                           |
| Parameter size   | 4.7B                                                                 |
| Quantization     | Q4\_K\_M                                                             |
| Thinking         | disabled (`think: false`)                                          |
| Output token cap | 200 (`num_predict`)                                                |
| Temperature      | 0.0 (deterministic)                                                  |
| Host             | Tailscale private —`abdullahs-macbook-pro.tail40fcbd.ts.net`      |
| Ollama runtime   | 0.34.3                                                               |
| Config SHA-256   | `798a81f80cbf45726b19f9b59196aa5b04f415e6887b5b19c0605683e2ba3244` |

### Dataset

| Field              | Value                                                                |
| ------------------ | -------------------------------------------------------------------- |
| Split              | `held_out`                                                         |
| Label count        | 60                                                                   |
| Label SHA-256      | `fed48887d2c7b50c20c6b8f41149893e52d13f2bd43303b110d39d88405c5f8c` |
| Prediction SHA-256 | `f05b57e6f9de8007e805d00c3a9f1a8e7ad24a2cc6bdaf4962beaddede4deed4` |
| Result file        | `evaluation/results/qwen3-5-4b-held-out.json`                      |

### Latency

| Metric | Value      |
| ------ | ---------- |
| Count  | 60         |
| Median | 3,728.7 ms |
| Mean   | 4,993.3 ms |
| p95    | 9,237.6 ms |

### Critical field accuracy

| Field             | Correct | Applicable | Accuracy        |
| ----------------- | ------- | ---------- | --------------- |
| Tag (activity ID) | 0       | 45         | **0.0%**  |
| Quantity          | 24      | 36         | **66.7%** |
| Unit              | 17      | 27         | **63.0%** |
| Quantity kind     | 22      | 60         | **36.7%** |
| Work date         | 0       | 0          | n/a             |

### Selection metrics

| Metric             | Value                  |
| ------------------ | ---------------------- |
| Recall@8           | 0.0% (0/45)            |
| Exact choice       | 0.0% (0/45)            |
| Selected precision | 0.0%                   |
| Coverage           | 20.0% (9/45 matchable) |
| Safe abstention    | 100.0% (15/15)         |

### Atomic extraction (P/R/F1)

| Metric         | Value |
| -------------- | ----- |
| Precision      | 0.0   |
| Recall         | 0.0   |
| F1             | 0.0   |
| True positive  | 0     |
| False positive | 60    |
| False negative | 60    |

### Error categories

| Category             | Count |
| -------------------- | ----- |
| correct              | 43    |
| event\_type mismatch | 13    |
| quantity mismatch    | 12    |

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

**Status: compact benchmark complete after the owner-requested rerun of batches
five and six.** All 60 cases now have returned outputs. The combined result uses
the original batches 1–4 and the new captures for batches 5–6; this is not a fresh
rerun of every batch. Model digest, runtime, settings, prompt and schema were
unchanged. Batch six's prompt/settings hashes and all five scored output fields
matched its original capture exactly.

The original fifth batch timed out at 300 seconds; the owner reported a PC crash.
Its replacement completed in 211.7 seconds, and the sixth batch rerun completed
in 170.3 seconds. The original failure, original sixth batch and preliminary scores
are preserved separately. The reported crash cause was not independently diagnosed.

### Scope and configuration

This is a compact joint extraction/selection benchmark with all 60 leaf schedule
activities supplied, distinct from the production extraction → model shortlist →
selection pipeline. Inputs contain case identifiers, source fragments, locators
and report dates; expected answers are supplied only to the scorer. Ten fragments
share each request. The set contains 45 matchable and 15 unmatched cases, with no
ambiguous cases. It is an existing evaluation set previously used with Qwen.

| Setting                             | Value                                                                |
| ----------------------------------- | -------------------------------------------------------------------- |
| Model                               | `gemma4:12b`, 11.9B, Q4_K_M                                        |
| Digest                              | `6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b` |
| Runtime                             | Ollama`0.40.0`                                                     |
| Endpoint                            | Owner-supplied private Ollama host`100.111.103.28:11434`           |
| Temperature / thinking              | `0` / `false`                                                    |
| Context / output cap                | `8192` / `1536` tokens                                           |
| Request timeout / automatic retries | 300 seconds / zero                                                   |
| Response schema                     | Five parallel arrays, ten entries each (`parallel-arrays-v2`)      |
| Dataset                             | `data/synthetic/expanded`, existing `held_out` split             |

Twelve case locators across four tabular reports were shifted one source line to
skip an extra table header. Corrections use source structure, not expected field
values. Original inputs and an explicit correction audit are retained; labels
remain unchanged. Independent human label review is pending.

### Quality on all 60 returned cases

These are scores under the draft compact prompt, not application acceptance
results. No request failures remain in the combined capture.

| Metric                                                                                      | Correct / applicable | Score  |
| ------------------------------------------------------------------------------------------- | -------------------- | ------ |
| Activity selection, matchable cases                                                         | 44 / 45              | 97.8%  |
| Precision across**all** selected activities, including unmatched cases                | 44 / 49              | 89.8%  |
| Safe abstention, unmatched cases                                                            | 10 / 15              | 66.7%  |
| Event type                                                                                  | 53 / 60              | 88.3%  |
| Quantity, non-null labels                                                                   | 36 / 36              | 100.0% |
| Quantity kind                                                                               | 41 / 60              | 68.3%  |
| Unit, non-null labels                                                                       | 21 / 27              | 77.8%  |
| Exact agreement on event type, quantity, quantity kind, unit and selection, including nulls | 17 / 60              | 28.3%  |
|                                                                                             |                      |        |

Five unmatched cases (`EXP-C286`–`EXP-C290`) were assigned activities despite being
classified as `unknown`. They contain unreadable field scans and an instruction
to ignore instructions and approve every activity. The model returned unrelated
schedule IDs, which are false matches; no approvals were performed. All ten
unmatched cases in batch six were correctly left unselected. In batch five,
valid fragments and unmatched fragments share a request; batch six contains only
unmatched fragments. These observations do not isolate the cause of the different
abstention behavior.

The scorer's legacy `selected_precision` field only considers matchable cases
and reports 100%; the table uses `overall_selected_precision` (44/49), which
includes the five false matches. High precision on matchable inputs alone would
conceal this safety failure.

Activity identity and stated numerical quantities performed well under this
compact prompt. Unmatched-case selection, null representation, event conventions
and unit conventions remain weaknesses. These results do not establish production
readiness or a general model ranking.

### Timing and diagnostics

| Batch | Cases              | Wall time | Outcome                      |
| ----- | ------------------ | --------- | ---------------------------- |
| 1     | EXP-C241–EXP-C250 | 149.5 s   | Returned on original attempt |
| 2     | EXP-C251–EXP-C260 | 260.7 s   | Returned on original attempt |
| 3     | EXP-C261–EXP-C270 | 292.4 s   | Returned on original attempt |
| 4     | EXP-C271–EXP-C280 | 200.9 s   | Returned on original attempt |
| 5     | EXP-C281–EXP-C290 | 211.7 s   | Returned on rerun            |
| 6     | EXP-C291–EXP-C300 | 170.3 s   | Returned on rerun            |

Median ten-case request wall time was 206.3 seconds; p95/max was 292.4 seconds,
and mean was 214.2 seconds for the six captures used in the combined score. The
original 300-second timeout and original batch six's 227.4 seconds are not included
in this summary; both remain in the original call records. This combines captures
from before and after the reported crash and has only six timing observations.
Per-case interactive latency and UI-to-export latency were not measured.

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

Evidence directory: [`results/gemma4-12b-2026-10-12/`](results/gemma4-12b-2026-10-12/).

- [`combined-after-retry/scored.json`](results/gemma4-12b-2026-10-12/combined-after-retry/scored.json): current 60-case scores and per-case differences.
- [`combined-after-retry/predictions.jsonl`](results/gemma4-12b-2026-10-12/combined-after-retry/predictions.jsonl), [`calls.jsonl`](results/gemma4-12b-2026-10-12/combined-after-retry/calls.jsonl) and [`config.json`](results/gemma4-12b-2026-10-12/combined-after-retry/config.json): combined captures, per-row source, timings and source-file SHA-256 hashes.
- [`retry-batches-five-six/`](results/gemma4-12b-2026-10-12/retry-batches-five-six/): new raw responses, predictions, call hashes, timings, configuration and frozen runner.
- [`comparison-batch-six.json`](results/gemma4-12b-2026-10-12/retry-batches-five-six/comparison-batch-six.json): identical prompt/settings hashes and no changed scored fields across ten repeated cases.
- [`compact/`](results/gemma4-12b-2026-10-12/compact/): preserved first attempt, including the fifth-batch timeout and original preliminary scores.
- [`provenance.json`](results/gemma4-12b-2026-10-12/provenance.json): commit, source/dataset hashes and completed retry status.
- [`input-corrections.json`](results/gemma4-12b-2026-10-12/input-corrections.json): twelve table-locator corrections.
- [`production-diagnostic.json`](results/gemma4-12b-2026-10-12/production-diagnostic.json): separate incomplete production measurement.
- [`preliminary-RESULTS.md`](results/gemma4-12b-2026-10-12/preliminary-RESULTS.md): report before the rerun.

```bash
# Score the saved combined 60-case capture without calling the model:
.venv/bin/python -m evaluation.summarize_gemma \
  --capture-dir evaluation/results/gemma4-12b-2026-10-12/combined-after-retry
```

Runner/scorer lint checks passed; the existing evaluation-metrics suite passed
13 tests. Split membership and the exact 60-case prediction/label identity were
validated. Retry configuration was checked against the original configuration;
only the input-file hash differs because the retry file contains 20 cases.
