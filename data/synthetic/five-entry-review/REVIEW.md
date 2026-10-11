SUPERSEDED: use ../../review/gt10-five-entry/REVIEW.md and schedule.csv for the current requested test. This older package contains synthetic demo activities and is not selected for the workflow.

# Five-entry schedule for review

Status: prepared and validated locally; awaiting user review before app startup or restart and end-to-end execution. This file has not been imported or activated.

Source: `../schedules/demo-utility-01.csv`, an existing synthetic development schedule. These are fictional test activities, not owner or field data. All 18 columns and all selected row values are preserved exactly. No quantities or dates were inferred from native schedules.

| Activity ID | Activity | Location / asset | Planned quantity | Planned dates |
| --- | --- | --- | --- | --- |
| CIV-A-EXC-01 | Excavate footing F-01 | AREA-A / F-01 | 100 m3 | 2026-09-19 to 2026-09-29 |
| CIV-A-REBAR-01 | Fix rebar for footing F-01 | AREA-A / F-01 | 1000 kg | 2026-09-19 to 2026-10-01 |
| CIV-A-FORM-01 | Formwork for footing F-01 | AREA-A / F-01 | 80 m2 | 2026-09-19 to 2026-10-01 |
| CIV-A-POUR-01 | Concrete footing F-01 | AREA-A / F-01 | 50 m3 | 2026-09-19 to 2026-10-03 |
| ELE-A-CABLE-01 | Lay cable on tray TR-A | AREA-A / TR-A | 500 m | 2026-09-19 to 2026-10-10 |

Each entry is a leaf activity using quantity-ratio measurement. Baseline date is 2026-09-19 and baseline quantity is zero. Actual dates are blank. The historical planned dates are retained for a reproducible test; this is not a newly calculated construction programme or a dependency-linked schedule.

## What to review

Review the five activities, quantities, units, and retained dates in `schedule.csv`. Confirm whether this synthetic subset is suitable. Request any changes before authorizing app startup/restart.

## End-to-end check after explicit startup approval

1. Inspect the current app configuration and services, then start or restart the required app services.
2. Create a separate test project and import `schedule.csv`; verify five staged activities and activate the reviewed version.
3. Submit synthetic report text with explicit dates, activity descriptions, quantities and units. Use separate reports where needed to keep evidence easy to inspect.
4. Verify actual worker/model processing, evidence, activity matches, quantities and pending proposals. Diagnose and fix failures, then rerun the affected flow.
5. Present proposals for human review before approval. Verify accepted progress in history and exported CSV after authorized acceptance.

Suggested cumulative test quantities from a zero baseline: excavation 20 m3 (20%), rebar 100 kg (10%), formwork 16 m2 (20%), concrete 5 m3 (10%), cable 50 m (10%). These are newly proposed synthetic test inputs, not observations from the source data. Use report dates within the corresponding planned windows. Verify duplicate submission cannot double-count accepted progress.

Local validation uses the application's `parse_schedule_csv` function: exactly five activities, no parser errors, and source rows preserved. See `validation.json` for the content hash. No live workflow or model accuracy has been verified at this stage.
