# Documentation index

Current status: [18 October prototype status](current-status.md).
Latest evidence: [V20 follow-up](release-followup-2026-10-18.md).
Previous live follow-up: [V19 acceptance resumption](release-live-followup-2026-10-17.md).
Earlier candidate review: [17 October acceptance evidence](release-review-2026-10-17.md).
The [12 October reconciliation audit](documentation-audit-2026-10-12.md) is historical.

## Current guides and status

| Document | Purpose |
|---|---|
| [Current status](current-status.md) | Configured model, measured admission/transport latency, six open gates and retained work |
| [18 October documentation audit](documentation-audit-2026-10-18.md) | Reconciliation scope, historical evidence boundary and link verification |
| [Project overview](../README.md) | Current runtime, setup and model-quality summary |
| [Local runbook](local-run.md) | Application setup, graph worker, recovery and model checks |
| [Remote Ollama](remote-ollama.md) | Private endpoint configuration and recorded model identity |
| [Release evidence](release.md) | Verified local prototype behavior and remaining acceptance gates |
| [18 October V20 follow-up](release-followup-2026-10-18.md) | Evidence repair, live blocker checks and interrupted mixed rehearsal |
| [17 October candidate review](release-review-2026-10-17.md) | Earlier frozen validation/holdout, calibration and candidate source record |
| [Implementation task state](task-board.md) | Latest task status, with dated W-series execution evidence |
| [V2 completion checklist](../PROJECT_COMPLETION_TODO_V2.md) | Lifecycle/data/workflow completion and pending release gates |
| [API contract](api-contract.json) | Generated OpenAPI for the current application |
| [Graph-only runtime](handoffs/graph-only-runtime.md) | Current processing and status UI, with recorded verification |
| [Evaluation guide](../evaluation/README.md) | Capture/scoring reproduction and metric scope |
| [Measured results](../evaluation/RESULTS.md) | Compact Gemma benchmark and historical results |
| [Split status](data-splits.md) | Consumed evaluation sets, development data and new holdout requirements |
| [Calibration contract](confidence-calibration.md) | Review policies, unsupported event/link thresholds and runtime confidence limits |
| [Approved targets](evaluation-targets-approved-2026-10-16.json) | Frozen accuracy, readiness and latency acceptance limits |
| [Execution history](execution-history.md) | Authorized history, correction, duration and export behavior |
| [Data decisions](data-decisions.md) | Source provenance and model-visible projections |
| [Technical data review](data-review-2026-10-12.md) | Source-backed suggestions, separate from human adjudication |

## Reading dated records

Task handoffs, source audits and validation transcripts preserve evidence for the
implementation and test configuration at their recorded date. Earlier legacy
routing, rollback and embedding retrieval descriptions are superseded by the
current graph-only worker and model-led candidate discovery. Prior fixture totals
are historical measurements, not latest regression totals.

The September decision records in [decisions.md](decisions.md) have a current
runtime amendment. [E01](handoffs/V2-E01.md) and [E03](handoffs/V2-E03.md) preserve
October 10 implementation/recovery evidence; [release.md](release.md) records the
later graph-only checks. [E02](handoffs/V2-E02.md) distinguishes the completed
compact benchmark from the still-pending independent UI-to-export gate.

The external `progress-agent-plan/` planning package is outside this Git repository.
References to that package in dated records are historical planning references;
current repository operation is documented by the guides above.

- [Durable conversations](durable-conversations.md) — versioned worker orchestration, budgets, restart recovery and rollback.

- [Hosted provider capacity](provider-capacity.md) — admission, quota observations, bounded live probes and failure policy.
