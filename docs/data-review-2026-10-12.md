# Development data technical review — 12 October 2026

This review records reproducible technical findings and candidate label suggestions for development data. It is not independent planner review, human adjudication, or approval. The original quality queue, reports, proposed labels, and adjudication records were left unchanged; suggestions are stored separately in [technical-review-2026-10-12.json](../data/review/technical-review-2026-10-12.json).

## Scope and method

The review consumed all 21 records in `data/review/schedule-quality-review.jsonl`, all 16 paired reports and proposed labels in `data/synthetic/v2/`, both locally supplied GT10 workbooks through `backend/app/ingest/schedule_datasets/gt10_xlsx.py:read_gt10`, the D01–D05 audit, and the split checker. The JSON artifact preserves every original queue record and label, adds technical disposition/reason, cites source workbook sheet-row locators, and supplies a separate suggested label. Input hashes and byte counts are included there.

The GT10 input workbook has 140 activities and 176 relationships; the selected export has 140 activities and 176 relationships. Both were read with `read_gt10`, which preserves source cells and row locators. The owner package remains `not_received`.

## Schedule queue findings

| Queue records | Evidence and technical disposition |
| --- | --- |
| 1: `SUP-F8-06` name | Input `ACTIVITES!65` names `SUP-F8-06` “De-shuttering - F8”; export `TASK!43` keeps that code but names it “De-shuttering - F9”. The code supports stable identity, while the conflicting export name should be excluded from name matching until a planner decides whether to correct it. |
| 2–15: relationships | All 14 queued predecessor/successor pairs were found in both workbooks. Input `RELATIONSHIP` rows use relationship types including `SS` and `FF` with numeric lag; export `TASKPRED` rows report `FS` and `lag_hr_cnt` values. The per-pair source cells and exact row locators are preserved in the JSON findings. Exclude each pair from dependency claims until a planner selects the governing snapshot, resolves the relationship type, and establishes the lag-unit interpretation. No replacement edge or lag is asserted. |
| 16–21: Cambridge aggregate flags | The queue cites aggregate profile counts for planned finish before start, actual after status date, redacted identifiers, calendar status, invalid weather, and external/unresolved predecessors. A separate technical screen of derived project 5060 provides bounded row locators for five actual-after-status-date cases and three unresolved predecessor references; it also marks 181 redacted activity descriptions, a related but non-identical signal to the queued redacted-identifiers field. It does not identify rows behind global aggregates. The other queued fields have aggregate-only evidence here. Keep all fields out of trusted labels/duration claims pending subset selection and planner disposition. |

The F8 conflict is supported by the paired source sheets, but the technical review does not authorize changing the source schedule. Relationship differences likewise remain unresolved engineering choices; “lag” interpretation cannot be settled from a header name alone.

## Development label findings

All 16 report/label pairs were checked against the literal report text, evidence span, proposed event, time precision, activity/scope, and duplicate/correction lineage. Proposed activity IDs are checked against task IDs in both workbook versions and accompanied by exact activity-name and row-locator evidence. Generator assertions require every evidence span to be a literal substring of its report and the duplicate report text to match exactly. Each suggested disposition and candidate label is in the JSON artifact. The main outcomes are:

- `SUB-010` is present in input `ACTIVITES!5` and export `TASK!3` as “Excavation for Foundation”; the three ordinary excavation start/finish candidates can therefore cite a workbook-supported target. `SUP-F8-03` is present at input `ACTIVITES!62` and export `TASK!54` as “Slab Shuttering - F8”.
- `gt10-dev-008` asserts two activities in one sentence. Its non-atomic proposal is split into date-only starts for `SUB-010` and `SUB-020` (“Anti-termite Treatment”, input `ACTIVITES!6`, export `TASK!4`), with each candidate tied to the exact report sentence.
- Ambiguous time, missing floor, unmatched tower-crane activity, and fictional asset F-01 preserve the reported start/finish candidate and any stated date/time; their `application_status` records the missing information or mapping that blocks use. Explicit future intent and negation produce no actual event. The blocker report remains a dated blocker candidate, not a start/finish.
- `gt10-dev-009` exactly duplicates report 001 and should not count as another event. Report 010 states a correction and corrected time, but the original-event link is scenario metadata rather than text evidence; require review before applying it.
- A finish without an accepted start, explicitly impossible chronology, and subactivity/parent scope preserve their source-supported event candidates while blocking state application pending the relevant prerequisite or planner decision.

These are synthetic development scenarios, not source-paired field truth. The report date or schedule date was not used to invent unspoken event information. No reviewer identity, approval, or adjudication was supplied.

## Reproduction and status

From the repository root:

```sh
.venv/bin/python ops/review_development_data.py
.venv/bin/python data/synthetic/v2/check_splits.py
shasum -a 256 data/review/technical-review-2026-10-12.json data/review/schedule-quality-review.jsonl data/synthetic/v2/reports.jsonl data/synthetic/v2/proposed-labels.jsonl
```

The review generator reported 21 quality records and 16 labels. The structural split checker returned `structural_checks_passed_not_frozen`, with 299 provisional Cambridge projects in 54 groups, partition counts 221/39/39, and 16 GT10 scenarios in development. The proposed-label SHA-256 remains `0690d1561891c0f9802405e0ebe63a82c0cdff4dee4612f05e3975d2ff661471`; the provisional split SHA-256 is `1cca54fadc3518cc951a87d19d8e8e433b3cd4cba54cbf87a481243a51afee75`. Structural checks do not freeze a split or approve labels.

The separate [Cambridge project 5060 technical screen](../data/review/cambridge-5060-technical-screen.json) covers 1,496 rows from one derived project snapshot. Its row locators and flag counts are supplemental subset evidence only; independent planner acceptance remains pending, and they do not substantiate the full dataset's aggregate counts or other Cambridge projects.

Independent planner decisions, real first/second label reviews and adjudication, any approved correction overlay, planner acceptance of a Cambridge row subset (including project 5060), physical-project/scenario grouping review, frozen unseen validation/holdout inventories, and owner-package validation remain open. The six Cambridge queue findings are global aggregates; only the bounded project 5060 screen has row-level locators, and its redacted-description signal does not exactly match the queued identifier field. No model, production data, or live application was used.
