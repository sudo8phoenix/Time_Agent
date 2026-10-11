# GT10 five-activity schedule

This replaces the synthetic demo subset for the requested test. Extracted directly from GT10BLDG_v1_P6_export.xlsx, TASK sheet. The five activities cover the ground-floor column and slab work. IDs, names, WBS codes and planned calendar dates are preserved.

| ID | Source activity | Start | Finish |
| --- | --- | --- | --- |
| SUP-GF-01 | Column Reinforcement - GF | 2026-12-11 | 2026-12-15 |
| SUP-GF-02 | Column Concreting - GF | 2026-12-16 | 2026-12-16 |
| SUP-GF-03 | Slab Shuttering - GF | 2026-12-18 | 2026-12-23 |
| SUP-GF-04 | Slab Reinforcement - GF | 2026-12-22 | 2026-12-25 |
| SUP-GF-05 | Slab Concreting - GF | 2026-12-28 | 2026-12-28 |

`source-activities.csv` preserves every exported TASK column, including original date/time values and status. `source-relationships.csv` preserves all source relationships touching these activities, including links to activities outside the subset. The canonical `schedule.csv` does not carry dependency logic; this is a bounded workflow test, not a standalone construction programme.

The GT10 source has no quantities, units, area tags or baseline quantities. The user authorized population with synthetic test quantities on 2026-10-11. The quantities below are test assumptions, not recovered GT10 values. Discipline/work type are classifications from the names; GF area is derived from the names. Measurement basis is quantity_ratio using the explicitly synthetic planned quantities. Baseline completed quantity is zero for all five activities; source status is Not Started. The import-required baseline date uses the source README's project data date, 2026-10-01, and does not establish quantity progress. Source WBS codes are retained even where their grouping is coarse.

The user approved app startup, test updates and access for cyril. The schedule is imported and active in the separate **GT10 five-activity workflow test** project. All five labelled synthetic quantity reports were processed by the live model and approved after source checks. See [LIVE-RESULTS.md](LIVE-RESULTS.md) for verification.

Validation: five unique activities; application CSV parser returned no errors; all selected IDs, names, WBS codes and planned dates checked against the workbook. Full source provenance and mapping choices are in validation.json.

## Populated test quantities

All added quantities are synthetic test assumptions authorized by the user.

| ID | Basis | Planned | Unit | Actual at baseline | Test cumulative actual | Expected percent after approval |
| --- | --- | --- | --- | --- | --- | --- |
| SUP-GF-01 | quantity_ratio | 1000 | kg | 0 | 200 | 20% |
| SUP-GF-02 | quantity_ratio | 20 | m3 | 0 | 4 | 20% |
| SUP-GF-03 | quantity_ratio | 200 | m2 | 0 | 40 | 20% |
| SUP-GF-04 | quantity_ratio | 3000 | kg | 0 | 600 | 20% |
| SUP-GF-05 | quantity_ratio | 50 | m3 | 0 | 10 | 20% |

The schedule and quantities are populated in the running app. Approved progress shows all five cumulative actual quantities at 20% each.
