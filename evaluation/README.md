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
