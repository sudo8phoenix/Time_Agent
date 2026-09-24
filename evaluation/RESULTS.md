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
