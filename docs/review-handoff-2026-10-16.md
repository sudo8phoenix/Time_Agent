# Data review and calibration handoff — 2026-10-16

> Historical record: statements and instructions below apply to the recorded stage.
> [Current status — 18 October](current-status.md) and the
> [latest V20 follow-up](release-followup-2026-10-18.md) supersede its operational
> status. Both V19 splits are consumed; release remains unaccepted.

This package records the current evidence state for D01/D03/D04/D05 and A02. The demo fixtures are prepared, but the final reviewed evaluation/calibration gate is still open. No human review, approval, threshold, or label change is asserted by this handoff.

## Review set

| Review area | Exact files to inspect | Current state |
| --- | --- | --- |
| D01 source/version and license | `data/references/schedule-sources.json`, `docs/data-decisions.md`, `docs/dataset-audit-2026-10-09.md`, `docs/d01-d05-completion-audit-2026-10-10.md`; originals/audit sources under `../data/` | Registry/hash checks are verified: both local GT10 workbooks match their members in the pinned d7eff9bb archive, and the retained MIT notice matches its registry SHA-256. Keep the MIT copyright and permission notice with permitted derivatives. Cambridge upstream byte identity and its exact retained attribution record remain unverified; independent source-version acceptance remains pending. Owner package: not received. |
| D03 schedule quality | `data/review/schedule-quality-review.jsonl`, `data/review/schedule-overrides.jsonl`, `data/review/technical-review-2026-10-12.json`, related original GT10 workbooks and Cambridge source/profile | Queue has 21 records; correction overlay is empty. Technical screening is not independent adjudication. Planner decisions, evidence-backed exclusions/corrections, selected subset and derived hash remain unavailable. |
| D04 synthetic report labels | `data/synthetic/v2/reports.jsonl`, `data/synthetic/v2/proposed-labels.jsonl`, `data/synthetic/v2/manifest.json`, `data/review/v2-label-adjudication.jsonl`, `data/review/W-03-review-instructions.md` | 16 synthetic development cases. Manifest marks labels AI-proposed/unreviewed and ineligible for evaluation. All 16 adjudication decisions are pending; reviewer/adjudicator IDs and dates, final label hashes, and any required second reviews are absent. These are not owner/site records. |
| D05 grouping and frozen split | `data/synthetic/v2/check_splits.py`, `data/synthetic/v2/split-check.json`, `../data/schedule-audit-2026-10-09/provisional-splits.json`, `docs/data-splits.md`, `docs/d01-d05-completion-audit-2026-10-10.md` | Structural check passes only. Cambridge groups/partitions remain provisional (299 projects, 54 groups, 221/39/39 projects); the 16 GT10 scenarios remain development. Independent project/snapshot/scenario grouping, domain-coverage review, unseen validation/holdout inventories, reviewed labels, and a frozen manifest are unavailable. |
| A02 confidence calibration | `docs/confidence-calibration.md`, `evaluation/calibrate.py`, `evaluation/results/calibration-v1-pending.json`, captured predictions if later produced | Calibration artifact explicitly remains pending; field/event/link thresholds are null. Current extraction/link estimators report `score: null`, `method: not_estimated`, `validation_status: unavailable`. No eligible independently reviewed validation labels, frozen manifest, or estimator-versioned scored predictions are supplied. |

## Human decisions and evidence still needed

1. A source-version reviewer must record selected source versions and intended-use decisions. GT10 integrity evidence is present: both workbook hashes match the pinned archive members, and `data/references/licenses/GT10-MIT.txt` hashes to `e9d0e6c0666a540af93165fef00ab7cb461b405237f67d3ee52ce2413b63125f`, matching both GT10 registry entries. Retain its copyright and permission notice with permitted derivatives. Cambridge upstream byte identity and exact retained attribution remain unverified.
2. An independent planner must review the quality queue against original source values, record decisions with evidence/reviewer/date/reason, settle GT10 naming/relationship/lag issues before dependency-derived claims, and document selected Cambridge fields/projects and exclusions. Any approved correction must be a separate overlay with a derived version/hash.
3. Independent label reviewers must review each report-label pair. Record actual reviewer IDs/dates and decisions in the adjudication process; second-review temporal/scope/conflict/ambiguous examples and sampled cases as required, adjudicate disagreements, and retain final labels separately with hashes. The current 16 examples remain development after review; they do not become validation or holdout cases.
4. A split reviewer must resolve physical project and snapshot identity, aliases, scenario families, repeated floors, paraphrases and alternate formats, then assess domain coverage. Create separate unseen validation/holdout cases and reviewed labels, and freeze the exact split inventory and hashes. Keep groups disjoint across development/train/validation/holdout.
5. Before calibration, the responsible owner/reviewer must agree and freeze the target precision and minimum support. The sample `0.95` and `20` values in the documented command are examples, not agreed release criteria. Capture predictions before scoring with non-null, versioned extraction/link confidence estimates and freeze their hash.
6. An independent live validation/release attestation and owner package remain unavailable. Neither a public schedule nor synthetic data substitutes for owner-specific validation. Calibration still does not authorize confidence-based acceptance; authorized human acceptance remains required.

## Existing commands

Run from the repository root (`site-progress-agent`). The structural checker is reproducible but does not freeze or approve the split:

```sh
.venv/bin/python data/synthetic/v2/check_splits.py
```

Once reviewed validation labels, captured predictions, a qualifying frozen manifest, and the agreed policy exist, the documented calibration command is:

```sh
.venv/bin/python -m evaluation.calibrate \
  --labels PATH_TO_FROZEN_VALIDATION_LABELS \
  --predictions PATH_TO_CAPTURED_PREDICTIONS \
  --manifest PATH_TO_REVIEWED_MANIFEST \
  --output evaluation/results/calibration-VERSION.json \
  --target-precision AGREED_VALUE --min-support AGREED_COUNT
```

The command refuses non-frozen/unreviewed evidence, mismatched hashes/policy, cross-split case/group leakage, missing validation cases, and mixed estimator versions. It checks declared attestations but cannot establish a reviewer's identity or independence. Output must be a new path. Keep holdout labels unread during calibration.

Additional D01–D05 background and fixture checks are documented in `docs/d01-d05-completion-audit-2026-10-10.md`; those checks are demo-preparation evidence and do not satisfy independent evaluation acceptance.

## Integrity note

`data/review/release-readiness-2026-10-16.json` is a machine-readable pending checklist with SHA-256 values for the reviewed input artifacts as they existed at handoff creation. It contains no invented reviewer details or acceptance decisions. Recompute hashes and update the handoff when source artifacts change.
