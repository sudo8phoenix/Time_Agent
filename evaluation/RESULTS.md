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
