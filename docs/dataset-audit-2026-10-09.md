# Audit of Cambridge and GT10 construction schedules

Date: 9 October 2026. Scope: inspect the supplied local data, verify public source descriptions, prepare non-destructive partition metadata, and inform a new completion TODO. **No application feature was implemented, no application database was changed, and neither original dataset was edited.**

## Recommendation

Use **GT10 for a small, understandable development/demo schedule** and **Cambridge for multi-project schedule coverage, historical actual fields, calendar work and scaling tests**. Both are useful. Neither supplies the paired site-report text, independently reviewed activity mapping, actual-event labels and correction history needed to validate the complete conversational workflow.

Create and independently review synthetic reports against selected schedules. Keep their synthetic origin explicit. The problem owner's sample package is not yet available and remains a separate later validation gate.

Current implementation and validation status is recorded in [release.md](release.md) and the versioned task handoffs.

## Sources and local identity

| Source | Local artifact | Observed size/content | Provenance/licensing status |
| --- | --- | --- | --- |
| Cambridge | `../../data/cambridge -construction schedules/JPF_Anonymised_Project_Data.json` | 1,287,747,624 bytes; 299 projects, 444,156 activity records, 1,371 calendars. | Repository describes construction scheduling data and states CC BY 4.0. Local file was supplied by the user; upstream archive byte identity was not independently verified. |
| GT10 | `../../data/GT10BLDG-P6-Schedule/` | Two XLSX workbooks, local README/known issues, Gantt PDF/PNG, chart script; native `schedule/` folder contains only `.gitkeep`. | GitHub describes a simulated planning exercise and identifies MIT. The local package omits LICENSE; exact remote license text could not be fetched through the web tool. Preserve this limitation and verify the license text before redistribution. |

Sources: [Cambridge dataset record](https://www.repository.cam.ac.uk/items/6cb214a6-f52d-4846-b2de-3a2e2a34d431), [GT10 repository](https://github.com/SionRani/GT10BLDG-P6-Schedule).

Cambridge SHA-256: `e32f311e05c73b8b891b25149d85c95f27536d739f97d17bc52624fbc5ef8f47`.

The associated [research paper](https://www.itcon.org/paper/2022/4) describes an analysis database of 302 projects and 293,263 tasks. Those are not the counts in this supplied JSON. Use the measured local counts; this audit does not establish why the research cohort and deposited file differ.

## What was actually checked

- Decoded the full Cambridge JSON one project at a time, with duplicate-object-key checks and root/trailing-data validation.
- Counted fields, populated/parseable dates, actual/planned chronology, status-date conflicts, task IDs, names, dependencies, project types, WBS structure and calendar references.
- Checked dependency endpoints, self-links, topological residuals and cross-project ID reuse. Topological residuals identify possible cycles and downstream nodes, not the number of cycles.
- Read every worksheet in both GT10 workbooks using the spreadsheet skill's read-only workflow. Counted rows, inspected headers, compared identities, dates, names, links, units and WBS, and checked formula/error cells.
- Reviewed the local GT10 known-issue notes and chart script as source text; did not execute the supplied script or alter its outputs.
- Prepared derived JSON profiles, a project catalog, a small GT10 review extract and a provisional split manifest. No raw files were moved or physically divided.
- Did not visually audit every Gantt page, load either dataset into the application, validate field observations independently, recalculate a Primavera schedule, or claim measured model performance.

Reproducible audit script: `../../data/schedule-audit-2026-10-09/audit_sources.py`. It only reads source datasets and writes derived audit artifacts in its own audit directory. It is not application implementation.

## Cambridge: useful content and limits

### Core counts

| Measure | Local count |
| --- | ---: |
| Projects | 299 |
| Activity rows | 444,156 |
| Distinct task IDs globally | 436,377 |
| Task ID values used in multiple projects | 7,718 |
| Dependency records | 758,285 |
| Activities with actual start | 267,490 |
| Activities with actual finish and start | 258,352 |
| Actual start only | 9,138 |
| Neither actual field | 176,666 |
| Populated planned start and finish | 444,156 each |
| Calendars | 1,371 |

All populated values in the four audited activity date fields parsed as ISO-compatible local date/times. No actual finish-before-start pair or finish-without-start row was found by these checks. This is a structural result, not independent verification that the events occurred as recorded.

The file includes actual WBS tables (`Work_Breakdown_Structure`) with parent references, not just WBS text on activities: 129,298 nodes, with computed depths 1–15 when roots count as level 1. No unresolved WBS depth or missing activity-to-WBS reference was found. There are 73,119 activities attached to depth-5 WBS nodes and 109,736 attached to depth-6 nodes. Preserve those trees, but do not equate parent-WBS depth with the owner's operational L5/L6 activity definition without review.

Project distribution is uneven: 179 Clean Water Networks projects and 63 Rail projects account for most project entries. Other types include highways, treatment works, light rail, airports, power and marine work. Report project-type and size distributions when evaluating; this is not a balanced sample of every discipline or project type.

### Actual time precision

- 110,429 populated actual starts have the clock value `00:00:00`.
- 110,091 populated actual finishes have the clock value `00:00:00`.
- Source date/time strings do not specify a timezone.
- Other values cluster around shift-like times such as 08:00, 16:00 and 17:00.

Preserve raw values. The file alone does not prove whether a midnight value is a precisely reported time, an export default, or date-only data represented as a timestamp. Do not replace it automatically, and do not use it to claim validated minute-level extraction. For generated report labels, record the authored report precision separately from imported schedule precision.

### Data-quality findings requiring explicit handling

| Finding | Count / evidence | Consequence |
| --- | --- | --- |
| `Task_Type:` equals `Task_ID` | Every activity: 444,156 | This field is not a usable task-type classification. Do not map it to discipline, milestone type or work type. |
| Planned finish precedes planned start | 1,022 activities | Flag/quarantine from trusted chronology fixtures pending review; do not silently swap dates. |
| Negative original and at-completion durations | 4 rows in each field | Preserve and flag. Do not use as valid duration/productivity examples. |
| Actual finish after project status date | 235 activities | Possible stale/inconsistent snapshot metadata; needs interpretation, not automatic date correction. |
| Actual start after project status date | 198 activities | Same caveat. |
| Finish exists but physical percent is below 100 | 5,393 activities | Status/measurement semantics need review; lifecycle and physical completion are not interchangeable. |
| Physical percent 100 without finish | 417 activities | Do not infer an actual finish from percent. |
| Blank activity descriptions | 333 | Identity matching needs other evidence or review. |
| Repeated activity descriptions within project | 229,132 rows beyond each first occurrence | Name-only matching is unsafe; retain project, WBS, location and IDs. |
| Anonymized activity descriptions containing `XXXXX` | 123,045 | Missing identifiers/locations cannot be reconstructed as fact. |
| Anonymized activity WBS descriptions containing `XXXXX` | 106,320 | Same restriction on context. |
| Predecessors outside the current project | 17,631 references | Some may be external links or ID collisions; must resolve with provenance. |
| Predecessors absent from every supplied project | 5,993 references | Preserve unresolved references; do not fabricate nodes or treat network as complete. |
| Nonstandard relationship type | One `PR_FF1` | Review as an unsupported raw type; do not silently coerce to FF. |
| Nodes left by topological removal | 42,758, summed across projects | They are in cycles or downstream of cycles; not 42,758 independently confirmed cycles. |
| Isolated nodes in the within-project graph | 29,498 | Graph completeness/standalone activity semantics require review. |
| Relationship container is string `"null"` | 39,798 | Source sentinel, not a dictionary. Adapter needs explicit handling. |
| `Calendar_ID` is `#N/A` | 7,795 activities | Working duration cannot use a real calendar for these without a reviewed mapping. |

The weather fields also show strong evidence of semantic corruption or column misalignment: all 346,110 populated minimum/maximum pairs have minimum greater than maximum, and 314,145 mean values fall outside a broad -40°C to +50°C check. Do not attempt to guess a repair from plausible-looking neighbouring columns. Exclude these fields from the proposed operational workflow and any trusted explanatory labels until independently clarified.

The file contains precomputed outcomes and research features, including at-completion duration and duration growth. These must not leak target outcomes into a supposed unseen extraction/matching benchmark. A GMM topic label is also not a reviewed construction discipline label.

### Calendar opportunity, with boundaries

The calendar records include working weekdays, shift intervals, declared hours and exceptions. Exception entries include both date strings (548,076 entries) and dictionaries with date-specific intervals (31,064). Across activities there are 736 distinct raw calendar references; one is the missing-value marker `#N/A`, accounting for 7,795 rows.

The audit checked weekday-list counts against declared working-day counts. It did **not** fully validate all interval arithmetic, exception semantics, effective periods, timezone/DST behavior or historical calendar changes. This data makes a reviewed working-calendar prototype possible; it does not immediately establish accurate historical crew hours.

No measured labour/crew-hour records, installed quantities or site diary narratives were found in the audited activity schema. Start/finish plus a working calendar cannot establish metres per crew-hour.

## GT10: a useful development schedule with specific defects

### Workbook structure

Export `exports/GT10BLDG_v1_P6_export.xlsx`:

- `TASK`: 140 activity rows after a technical-header row and a human-label row.
- `TASKPRED`: 176 dependency rows after two header rows.
- `RSRC`: a resource directory, not evidence of task labour allocation.
- `TASKRSRC`: zero assignment rows.
- `USERDATA`: export display/settings metadata; does not supply a complete working calendar.

Input `source/GT10BLDG_input_activities_relationships.xlsx`:

- `WBS`: 28 nodes including the project root, i.e. 27 beneath it.
- `ACTIVITES`: 140 activity rows. Preserve the actual misspelled sheet name in the adapter.
- `RELATIONSHIP`: 176 relationships.
- `Sheet4`: 140 separately dated activity rows, not an independent project or a site diary.

The supplied XLSX files contain no formula or spreadsheet-error cells according to the reader checks. The export triggers an openpyxl warning that no default workbook style is present; that did not prevent data extraction.

### Schedule facts

| Measure | Observed value |
| --- | --- |
| Activity IDs | 140 unique; same set in input/export |
| Activity status | All 140 `Not Started` |
| Actual date fields in TASK | None |
| Export scheduled range | 2026-10-01 08:00 to 2028-02-04 16:00, timezone unstated |
| Relationship types | 164 FS, 11 SS, 1 FF |
| Dependency pairs | Same 176 pairs in input/export; no duplicate pairs or missing endpoints |
| Within-project graph | Acyclic; one source, one sink, zero isolated tasks |
| Input WBS depth | Three levels including root: 1 root, 7 children, 20 grandchildren |
| Distinct exported WBS codes | 10 |
| Task resources / assignments | None populated / zero assignments |
| Calendar | Input says `6-Day Week`; full intervals/holiday rules not included locally |
| Native XER | Not present; schedule directory is a placeholder |

Do not call these planned start/end values actual events. The Gantt PDF visualizes the schedule, not observed field execution. No verified L5/L6 coding or F-01 asset mapping is established by this package.

### Reconciliation issues

1. **Wrong-floor activity name.** `TASK!A43:D43` contains ID `SUP-F8-06` with name `De-shuttering - F9`. The input names it F8. The genuine F9 ID also exists. This can directly cause incorrect text-to-activity matching.
2. **FF relationship.** Export `TASKPRED` row 77 links `SUP-F9-06` → `SUP-F10-01` using FF. The input uses FS; the local known-issues document calls for a fix. Do not apply that fix without a recorded derived-version decision.
3. **F10 plaster lag.** `TASKPRED` row 81 uses zero lag for `MAS-F10-01` → `MAS-F10-02`, versus input value 3. The local notes also flag this.
4. **Other changed relationship types.** PRE-020 → PRE-030 and eleven masonry-to-plumbing links use FS in the export versus SS in input. Local notes describe these as intentional simplifications. Total raw type/value differences: 14.
5. **Lag-unit ambiguity.** Export column `lag_hr_cnt`, display label `Lag(h)`, contains numbers 1/2/3/5/7. The input column is simply `Lag`, and prose describes day lags. For example `TASKPRED!L76` is `7` for GF slab-concrete → de-shuttering, while prose describes seven days. This audit cannot prove the intended/export unit conversion. Preserve raw units and seek planner resolution; do not multiply by eight or reinterpret as days silently.
6. **Dates differ throughout.** All 140 matched activities differ in at least one date between `Sheet4` and the P6 export. These are different schedule representations/versions, not independent training samples. The local README's finish agrees with the measured export; the current online README also contains a conflicting shorter-duration statement.
7. **WBS differs.** The input has a detailed 28-node tree, but export activity assignments use 10 WBS codes and group much structural work together. Do not join input and export WBS by string similarity alone or assume the input tree is the exported hierarchy.
8. **Missing full planning inputs.** No local XER, complete calendar definitions or measured resource assignments are provided. The exporter does not carry original duration in TASK, so the known-issues duration checks cannot be settled from that table alone.

Keep an immutable raw copy and a separately reviewed correction overlay. The input workbook is useful evidence for disputed values; it is not automatically authoritative over every export value.

## Partition decision

The audit produces `provisional-splits.json`, containing IDs/groups and source hash rather than copying or moving the 1.2 GB file. It keeps GT10 as one development/demo family.

For Cambridge it conservatively groups exact content, substantial shared IDs, high name overlap and possible cross-project predecessor connections. This is a **leakage screening heuristic**, not proof of shared physical-project identity. Some shared IDs refer to different descriptions. A large connected group results, so group-preserving splits may have poor coverage or balance.

Before any benchmark is frozen:

1. Review near-project pairs and ID reuse; determine which connections are actual snapshots, repeated templates, ambiguous IDs or real cross-project links.
2. Inspect both project-count and activity-count distributions and project-type coverage. Do not advertise a 70/15/15 benchmark just because that was the requested allocation target.
3. Preserve whole scenario families, including synthetic report variants, corrections and alternate formats, in one partition.
4. Reserve newly authored independently reviewed report scenarios for final unseen testing. The existence of schedule actual dates is not equivalent to unseen reviewed report labels.

No partition is approved as gold/evaluation-ready by this audit. See the split artifact for exact provisional memberships and counts.

The final provisional allocation is:

| Partition | Projects | Activity rows |
| --- | ---: | ---: |
| Development | 221 | 114,583 |
| Validation | 39 | 176,962 |
| Heldout candidate | 39 | 152,611 |
| Total | 299 | 444,156 |

There are 54 indivisible candidate groups; the largest contains 221 projects. The assignment puts largest groups first and uses remaining target project-count deficits with a deterministic hash tie order. Coverage, not randomness, is the main unresolved issue: 175 of the 221 development projects are Clean Water Networks, while the smaller validation/heldout partitions contain more activities. This is useful inspection metadata, **not a recommended final 70/15/15 benchmark**. D05 explicitly requires reviewing group identity and partition representativeness before use.

## Generated audit artifacts

All paths below are under `../../data/schedule-audit-2026-10-09/`:

- `source-inventory.json`: source paths, sizes and SHA-256 hashes.
- `cambridge-profile.json`: full counts, field coverage, anomaly examples, clocks, calendars, grouping evidence and WBS depth checks.
- `cambridge-project-catalog.json`: per-project counts, metadata and WBS source records for inspection.
- `gt10-profile.json`: sheet inventory, full input/export differences and quality checks.
- `gt10-schedule-review.json`: compact original-value task/relationship/WBS extract; explicitly not a corrected/import-ready schedule.
- `provisional-splits.json`: non-destructive candidate partitions and limitations.
- `audit_sources.py`: reproducible audit-only helper, outside application code.

## Effect on the completion plan

Proceed with a lifecycle prototype using a reviewed small schedule slice and explicitly synthetic reports. Add dedicated schedule adapters for Cambridge JSON and GT10 schedule XLSX; the current native importer does not accept these formats as equivalent XER files.

Keep field-report ingestion, paired label generation, independent review, confidence calibration and live UI-to-export validation as separate work. Neither newly supplied schedule dataset closes those requirements by itself. Retain the owner-package validation gate for when that package arrives.
