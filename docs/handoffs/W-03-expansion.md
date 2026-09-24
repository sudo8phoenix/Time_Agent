# W-03 expansion handoff

Task ID: W-03 expansion and pending human-review package

## Delivered

- `data/synthetic/expanded/schedule.csv`: 60 executable leaf activities across AREA-A, AREA-B, and AREA-C, plus three separately excluded WBS summary rows.
- `data/synthetic/expanded/reports.jsonl`: 100 short authored synthetic reports in five styles.
- `data/synthetic/expanded/labels.jsonl`: 300 atomic proposed labels, separate from inputs.
- `data/synthetic/expanded/splits.json`: 180 development / 60 validation / 60 held-out observations, assigned by intact event family.
- `data/synthetic/expanded/manifest.json`: provenance, counts, SHA-256 hashes, and pending-review status.
- `data/review/w03-expanded-review.csv` and `data/review/W-03-review-instructions.md`: an actionable human-review/adjudication package.

## Evidence

Primary-label allocation: 120 unambiguous actual, 45 ambiguous match, 30 unmatched, 30 future-plan/no-work, 30 duplicate/correction/quantity, 30 messy date/unit, and 15 injection/unreadable cases (300 total).

Package hashes: schedule `d576de978efcad0f3a7c014ed13119a36e7f6d5212c010d14a2d175eaebacad8`; reports `7e22107aab344799949d8381047abcd37103940f0dff08e6d8a8a37c62e878c1`; labels `fed48887d2c7b50c20c6b8f41149893e52d13f2bd43303b110d39d88405c5f8c`; splits `b7d226cdf9e0b1026ddaf205ecd5c82ac1f75c91ac7a75e10d4cb1c16250f3d8`.

## Validation

Run: `cd site-progress-agent/backend && uv run pytest tests/unit/test_expanded_dataset.py -q`

The test verifies leaf/summary isolation, three-area schedule coverage, exactly 100 reports and five styles, exact case allocation, pending synthetic provenance, activity referential integrity, intact 180/60/60 event-family splits, and manifest hashes.

## Limitations

This is generated synthetic material and is **not human reviewed**. `reviewer_status` remains `pending`; it is not a completed gold dataset and must not be used to claim real-model accuracy or industrial reliability. Held-out labels must stay inaccessible until predictions are saved. Human reviewers must record individual decisions and adjudication in the supplied review sheet, then regenerate manifest hashes if labels change.
