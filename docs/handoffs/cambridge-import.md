# Cambridge selected-project staging handoff

`ops/prepare_cambridge_import.py` derives a single project snapshot from the Cambridge source without loading the full 1.3 GB file into memory. It streams the parent SHA-256, scans projects one at a time using the existing Cambridge reader, and writes only the selected project, its raw metadata, complete raw task and WBS records, referenced calendar records, and derivation provenance. The output is capped at 10 MiB so it can enter the existing native schedule upload flow.

Example:

```sh
cd site-progress-agent
.venv/bin/python ops/prepare_cambridge_import.py \
  "../data/cambridge -construction schedules/JPF_Anonymised_Project_Data.json" \
  5060 /tmp/cambridge-5060.json
```

Upload the resulting `.json` snapshot through the schedule-import API. It is accepted only when its `_cambridge_snapshot.kind` identifies this derived snapshot format. The workflow then supports project selection, reviewer mapping, staging, explicit activation, source metadata retrieval, and activity lookup.

The saved provenance marks the snapshot as locally derived and records its parent SHA-256 and source locator. The hash is computed from the local parent file bytes; upstream identity verification is explicitly not performed. Raw source values remain available in persisted source metadata, including the full WBS parent hierarchy. Cambridge `PR_FS`, `PR_SS`, `PR_FF`, and `PR_SF` map to the corresponding FS/SS/FF/SF links while preserving each raw relationship record and type; other types are reported without inventing an edge. Lag units remain unknown. Invalid or chronologically reversed dates are retained raw and surfaced as issues. Actual endpoints after the project’s raw status data date are omitted from the canonical schedule and retained in the source record. Calendar semantics and timezone remain unreviewed/unspecified.

The PostgreSQL integration flow uses project `5060`, a small real-derived project snapshot. Its mapping reason is test evidence only; it does not represent independent planner approval. Reviewers still need to assess source version, intended use, relationship semantics, calendars, dates, and mapping before operational use.
