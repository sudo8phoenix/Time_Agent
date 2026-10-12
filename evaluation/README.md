# Model evaluation guide

[RESULTS.md](RESULTS.md) is the measured-results record. Fixture tests, live model
benchmarks and full application acceptance have different scopes; each result must
identify its inputs, model digest, prompt/settings, denominators and limitations.

## Local evidence availability

This documentation-only publication includes the guide and measured report. The Gemma runners, scorer and raw/combined captures remain in the original local workspace. Commands below apply to that workspace; a fresh GitHub checkout alone does not contain the additional scripts or captures. Artifact paths are local references.

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
