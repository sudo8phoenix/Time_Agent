# Release gap inspection — 16 October 2026

> Historical record: statements and instructions below apply to the recorded stage.
> [Current status — 18 October](current-status.md) and the
> [latest V20 follow-up](release-followup-2026-10-18.md) supersede its operational
> status. Both V19 splits are consumed; release remains unaccepted.

Inspection only for the configured application deployment, as requested. No
application migration, restart, restore, flag change or ledger write was performed.
The existing 376 unit / 188 integration result remains historical; those suites
were not rerun for this inspection.

## Deployment state

Read-only queries returned `0015_schedule_source_metadata` for the configured
application database and `0018_hosted_admission` for `progress_test`. Both configured
flags, `AGENT_HIERARCHY_ENABLED` and `ORCHESTRATOR_MODEL_ASSISTED`, are false.
These are configuration observations, not proof of the environment loaded by an
already running API or worker. The old `/private/tmp/time-agent-graph-runtime`
process record is absent in this environment.

Migration 0018 remains a prerequisite for the new hosted transports on the
application database. Do not start this source version's hosted workers against
0015. Applying it and rehearsing restart/restore remain deployment work; neither
the test database's migration nor older restore evidence closes that gate.

## Fresh provider evidence

- The first sandboxed Q07 attempt failed admission in 172 ms with
  `MODEL_CAPACITY_TIMEOUT`, zero retry delay and no quota headers. A subsequent
  database query outside the sandbox succeeded. This initial attempt supplies no
  evidence about provider quotas or Q07 quality. Its capture is retained at
  `evaluation/results/quality-gap-fixes-2026-10-16/q07-investigation-06/`.
- OpenRouter preflight now reports used 0 / limit 50 / remaining 50. The saved
  `evaluation/results/provider-capacity-2026-10-16/reset-investigation-04/`
  probe completed 2/2 free-model requests, both HTTP 200, in a 17.516 second span.
  Submitted concurrency was two; maximum network concurrency was one. This is a
  small single-process synthetic check through PostgreSQL admission, not sustained
  capacity or a measurement of deployed workers.
- Fresh Groq extraction outputs are retained in
  `evaluation/results/quality-gap-fixes-2026-10-16/live-investigation-07/`.
  Expected checks were excluded from prompts; original captures were preserved.
  The evaluator uses fixture order even when `--case-ids` lists Q07 first.
  Q07 completed and passed: `material_delivery`, unknown work date, a conflicting
  date clarification warning, no quantity or lifecycle effects, and no extraction
  errors. This supplies one live component observation, not full report/approval
  acceptance. Four cases were attempted: two completed and one passed; Q01 failed
  completeness, while Q02 and Q05 raised `ExtractionError`. Q07 took 47.660 seconds
  including admission; that duration is not isolated provider inference time.

## Source-based technical review

This is another technical inspection of synthetic sources and saved predictions.
It does not constitute independent human adjudication or change the labels.
References: `data/synthetic/reports/seed-reports.jsonl`,
`data/synthetic/schedules/demo-utility-01.csv`, the known-case review and the
twelve-case v3 review under `evaluation/results/`.

| Case | Source support and remaining issue |
| --- | --- |
| C02 | Line 24-XX occurs in both Area A and Area B erection rows. Without an area or equivalent distinguishing fact, a unique selection is unsupported. No fresh C02 model capture was made. |
| C03 | Tomorrow resolves to 22 September from trusted 21 September metadata. The source names Area A, line 24-XX and erection, supporting the erection activity. Three planned spools must not become installed quantity; the saved normalized effect is empty. |
| C05 | Three erected spools and welding stopped by rain are separate claims. The saved known-case output preserves both and assigns quantity only to erection. Neither clause states a work date; the saved unknown dates avoid inventing one. |
| C06 | Delivery is supported; installation is not. The twelve-row seed schedule has no delivery row. The saved unmatched result may be appropriate abstention, despite the current reference counting it as a mapping failure. Adjudicate the intended receiving-activity association before treating this score as a defect or forcing erection selection. The saved area `A` also warrants canonical-area review. |
| C08 | The explicit cumulative total is five, not five additional spools. Saved quantity semantics correctly preserve cumulative. |
| C12 | 0.5 metric tonnes equals 500 kg. Rebar on footing F-01 supports the rebar row, not concrete on that footing. This quantity assertion does not prove the entire activity finished. |
| C13 | Continued cable laying supports ongoing work; it supplies no measured amount or actual start. The saved output preserves those omissions. |
| C17 | Preserve the reported 20 spools, but the matching schedule row plans 12. Extraction correctness does not authorize an incompatible ledger update. |
| C18 | Conflicting current-day anchors leave the effective date unresolved. The saved output clears the date and adds a blocking warning while preserving the physical quantity claim. |

Quote membership alone cannot support every field. Fresh Q01 retains 8 m of cable
but omits the separate permit-related testing blocker and drops Zone C. Its
`discipline=civil` also deserves review for cable work. The missing-blocker warning
is present, but it does not make the extraction complete. Fresh Q02 and Q05 raised
`ExtractionError`; the capture records neither schema details nor raw output, so
their specific invalid fields cannot be established from this artifact.

## Historical interruption

The old retrieval failure and later `JOB_LEASE_LOST` remain distinct observations.
The old harness had no ownership snapshots or independent heartbeat. A short run
with an initial fifteen-minute lease does not prove expiry, lease replacement,
or a particular worker race. Current `heartbeat()` resets expiry to the normal
lease window rather than preserving a longer manually assigned expiry; an initial
lease duration alone is therefore insufficient diagnostic evidence.

The existing eight fault scenarios establish current separation of transport-only
failure and deliberately replaced ownership. They cannot establish the historical
root cause. Recovering original process/DB logs or ownership history is required
for stronger attribution; those records were not found in this inspection.

## Verification boundary

The existing component and capacity CLIs were executed for the fresh captures.
`git diff --check` passed. No implementation or regression tests were changed;
the full unit/integration suites were not rerun. No deployment acceptance is claimed.

## Remaining release work

Keep both flags disabled. Independent semantic adjudication, sustained
representative workloads on deployed workers, migration/restart/restore, staged
monitoring and rollback rehearsal remain open. A flag rollback must account for
already pinned durable conversations, which continue under their stored version;
changing the flag alone does not cancel or reinterpret that work. Monitoring must
cover pending task age, provider cooldowns/errors, ownership loss, duplicate domain
outputs, reviewer warnings and ledger effects, with agreed stop criteria before
the staged rollout begins.
