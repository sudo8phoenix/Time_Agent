# Confidence and calibration contract

A01 records `proposal-provenance-v1` in observation JSON for legacy jobs, graph jobs and confirmed conversations. Reviewer corrections record their parent observation/event. No migration or backfill is required. Extraction and linking estimates are separate objects with score, method, version and validation status. Current estimators return `score: null`, `method: not_estimated`, `validation_status: unavailable`. Match strength, retrieval rank and source-quote presence are not calibrated probabilities.

The proposal GET response includes `provenance` and `decision_history`. History is explicitly scoped to the report job: all atomic observations, proposal revisions, accepted events, corrections/retractions, and review audit records with actor, timestamp, reason and before/after values. Original observations and candidate decisions remain stored. New review actions use application UTC timestamps to distinguish multiple actions in the same PostgreSQL transaction. Historic proposal reads permit a superseded schedule; mutation paths retain active/pinned schedule checks and project authorization. Legacy proposals explicitly report incomplete capture. Missing model identity/config metadata from injected callables is unknown, never invented. Confidence metadata is visible in the review screen.

## Calibration inputs

`evaluation/calibrate.py` consumes three separate files. It never reads holdout labels or writes operational approval policy.

- Validation labels JSONL: unique `case_id`, `group_id`, `review_status: independently_reviewed`, and `targets` containing `event`, `link`, and/or `field:<name>` values. Each case represents one independently aligned atomic event. Use an explicitly reviewed alignment; model-supplied correctness is not an input.
- Predictions JSONL: `case_id`, `targets`, and `confidence` objects under `extraction` and `linking`. A scored estimate requires `score` in [0,1], `method`, and `version`. Missing/abstained predictions and unavailable scores stay in the denominators. Extra predicted targets count as precision errors. Mixed estimator versions are rejected. Predictions are captured before scoring.
- Frozen manifest JSON: `status: frozen`, `labels_sha256`, `predictions_sha256`, `group_review_status: independently_reviewed`, `policy: {target_precision, min_support}`, `review` and `splits`.

The `review` object requires `status: independently_reviewed`, `kind: human`, `reviewer_id`, `reviewed_at`, `label_authors` (excluding the reviewer), and a nonempty `attestation` referencing review evidence. The tool checks the declared attestation; it cannot establish a person's identity or independence. Do not invent these fields to pass the gate.

`splits` must contain `development`, `train`, `validation`, and `holdout` arrays with `case_id` and `group_id`. Group IDs identify underlying project/scenario families, including aliases, schedule snapshots, paraphrases and format variants. D05 must establish these groups independently. Groups and case IDs cannot cross splits. Validation labels must cover exactly the validation inventory. Label hashes and frozen policy must match. Holding a manifest does not establish domain coverage by itself.

Run only after D04/D05 review and prediction capture are complete:

```sh
.venv/bin/python -m evaluation.calibrate \
  --labels PATH_TO_FROZEN_VALIDATION_LABELS \
  --predictions PATH_TO_CAPTURED_PREDICTIONS \
  --manifest PATH_TO_REVIEWED_MANIFEST \
  --output evaluation/results/calibration-VERSION.json \
  --target-precision 0.95 --min-support 20
```

The policy values are examples, not agreed release targets. Freeze agreed values before examining outcomes. Output must be a new path; existing artifacts and inputs cannot be overwritten.

## Meaning of results

The artifact records input hashes, declared reviewer, denominators, abstentions/missing cases, extra targets, unavailable scores, estimator versions, four confidence bands, and every threshold's empirical precision/coverage tradeoff. Field metrics weight individual target fields; event and link metrics weight atomic cases. Threshold selection maximizes coverage among candidates meeting the frozen precision/support policy. If none qualifies, the threshold is null. These are exact-match metrics, not event discovery F1, probability calibration proof, or live-model accuracy. Event alignment, unseen-flow measurements and project/domain weighting remain E02 responsibilities.

Thresholds only inform review priority. Low-confidence, ambiguous or conflicting cases still need review; all updates retain deterministic validation and authorized acceptance. No automatic confidence-based approval is installed.

## Current evidence gate

D04's reports are developer-authored synthetic development cases awaiting independent review. D05's group manifests are provisional and unfrozen. Current confidence scores are unavailable. Therefore A02 cannot produce defensible operational threshold choices yet. `evaluation/results/calibration-v1-pending.json` records this status and dependency hashes. Unit fixtures test the tool's behavior, including simulated review attestations, and are never submitted as actual independently reviewed calibration evidence.
