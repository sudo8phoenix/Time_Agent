# D01–D05 completion audit — 2026-10-10

D01–D05 demo preparation is marked complete in the separate demo-readiness checklist, following the user’s clarification that this is for a demo. D02 acceptance is scoped to the tested GT10 flow; Cambridge staged import remains pending. Full evaluation acceptance remains open for all five tasks. This audit does not approve labels, schedule corrections, source versions or splits.

| Task | Verified evidence | Remaining acceptance |
| --- | --- | --- |
| D01 | Recomputed SHA-256 and byte count match the registry for Cambridge JSON and both GT10 workbooks. Export is selected for development; input is reconciliation evidence. Owner package is explicitly not received; sources are not owner data or report gold. | Retain source-version review decision and exact license/attribution text before packaging permitted derivatives. Upstream byte identity remains unverified. |
| D02 | Existing adapter and GT10 staging tests: 4 passed. GT10 preserves raw timestamps and relationships in the source sidecar and exercises explicit activation/retrieval. Cambridge read adapter retains raw fields and composite identity. | Cambridge lossless staged persistence, explicit activation and retrieval evidence; broader malformed/heterogeneous relationship and calendar validation. Full Cambridge counts are prior handoff evidence, not rerun in this audit. |
| D03 | 21 quality-review records; original sources unchanged; correction overlay is zero bytes. | Independent planner decisions, reviewed subset inclusions/exclusions, approved correction overlay and derived hash where corrections are needed. |
| D04 | 16 synthetic development reports and proposed labels; all 16 adjudication decisions are pending. | Independent first reviews, required second reviews and adjudication, final label hashes; separate validation/holdout scenarios with reviewed labels. |
| D05 | Rerun structural checker passed: 299 projects in 54 groups, 221/39/39 provisional partitions; all 16 GT10 cases remain development. | Independent physical-project/scenario grouping and coverage review, unseen report inventories, reviewed labels and frozen split manifest. |

## Reproducible checks

From `site-progress-agent/backend`:

```sh
../.venv/bin/pytest -q tests/unit/test_schedule_datasets.py tests/integration/test_gt10_schedule_flow.py
```

Result: 4 passed. The GT10 activation test uses isolated SQLite; it does not establish production PostgreSQL acceptance or independent mapping approval.

From `site-progress-agent`:

```sh
.venv/bin/python data/synthetic/v2/check_splits.py
```

Result: `structural_checks_passed_not_frozen`. Provisional split SHA-256: `1cca54fadc3518cc951a87d19d8e8e433b3cd4cba54cbf87a481243a51afee75`. Proposed label SHA-256: `0690d1561891c0f9802405e0ebe63a82c0cdff4dee4612f05e3975d2ff661471`.

## Reviewer handoff

1. Source-version reviewer: inspect [registry](../data/references/schedule-sources.json) and [source decisions](data-decisions.md); record identity, date, selected versions, intended-use approval and unresolved restrictions. Keep unknown retrieval dates and upstream identity explicit.
2. Independent construction/planning reviewer: resolve [quality queue](../data/review/schedule-quality-review.jsonl), using each source locator and original value. Record approved correction or exclusion, reviewer/date/reason and evidence. Review F8 naming, relationship type, plaster lag and lag units before dependency-based claims. Record selected Cambridge fields/projects and exclusions. Approved corrections belong in [overlay](../data/review/schedule-overrides.jsonl), with a derived version/hash; preserve originals.
3. Independent label reviewer: compare [reports](../data/synthetic/v2/reports.jsonl), [proposed labels](../data/synthetic/v2/proposed-labels.jsonl) and reviewed schedule decisions. Use [adjudication queue](../data/review/v2-label-adjudication.jsonl) to retain proposed hashes, real reviewer IDs/dates, second reviews and adjudication. Store final labels separately and hash them. These 16 cases remain development even after approval.
4. Split reviewer: inspect [split documentation](data-splits.md) and `../../data/schedule-audit-2026-10-09/provisional-splits.json`. Resolve physical-project/snapshot identity and skewed coverage; keep aliases, repeated floors, format variants, paraphrases and corrections together. Author separate unseen validation/holdout cases, review their labels, then freeze inventories and exact hashes. Rerun structural checks after changes.

Reviewer fields must come from actual review decisions. Agents and test attestations do not supply independent human approval. The full evaluation acceptance checkboxes remain unchecked until these acceptance records and remaining D02 technical evidence exist. The separate demo-preparation checkboxes are checked.

A02 additionally requires a frozen precision/support policy and captured estimator-versioned scored predictions. Completing this review package alone does not meet that requirement; see [calibration contract](confidence-calibration.md).
