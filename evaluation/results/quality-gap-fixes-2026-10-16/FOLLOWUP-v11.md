# Remaining quality and capacity gaps — extraction v11 follow-up

Both rollout flags remain disabled. Human approval is preserved. No deployment,
production migration, approval, progress-ledger write, paid fallback, or key
rotation was performed. This record extends [the v10 report](REPORT.md); older
captures and failed attempts remain unchanged.

## Implemented

- **Evidence:** v11 explicitly asks for literal source quotes and identifier-only
  fragment references. An exact decorated header can be unwrapped only when its
  exact quote occurs once in that same source. Quotes are never rewritten and an
  approval-blocking reviewer warning marks the repair. Other IDs, paraphrases,
  repeated ambiguous quotes and invented evidence remain rejected.
- **Completeness:** cause-before-stoppage and standalone work stoppages now join
  the narrow missing-blocker presence check. A merged `blocker` field also triggers
  review when no separate blocker exists. If any sibling observation fails
  evidence validation, retained observations get a blocking completeness warning.
  These checks do not manufacture missing events or establish full semantic
  completeness; multiple constraints and entirely omitted fragments remain a
  human/model quality gate.
- **Delivery identity:** new v11 report runs receive explicit discovery/selection
  instructions separating a receiving asset/work package from installed progress.
  Dedicated delivery rows are preferred when supported; multiple possible
  receiving activities require abstention. Delivery creates no progress effects.
  No ID is forced or selected by source-text heuristics.
- **Compatibility:** exact v9 and v10 prompts and processing are retained. Existing
  unpinned work uses v9; saved v10 work stays v10. New v11 runs alone use the new
  delivery instructions. Tests cover all three versions across report execution
  and conversation crash/replay despite a changed default.
- **Shared admission:** the default hosted transport now reserves each provider
  in PostgreSQL, across roles, key slots, worker processes and restarts sharing
  that database. It persists numeric quota/reset/cooldown state with a bounded,
  owner-fenced lease. Short transactions end before inference/waits. A missing
  coordinator fails closed, rather than using an uncoordinated local bypass.
- **Pacing/timeouts:** Groq uses estimated request cost against advertised TPM in
  addition to minimum request spacing. The byte estimate is approximate; provider
  enforcement remains authoritative. Daily request state clears after reset;
  OpenRouter epoch-millisecond reset times are converted correctly. Body reads
  use the remaining deadline, including trickled responses, and retain the 2 MiB
  bound. Stale provider reservations cannot return usable model output.

## Migration and operational boundary

Additive migration `0018_hosted_admission` was applied to `progress_test` only.
It is a prerequisite before starting this source version's hosted transports on
an intended deployment. Production has not been migrated or restarted. The
backup/restore manifest includes the new private provider table. An old provider
owner cannot clear a replacement reservation. After a crash, a lease can be
reclaimed once its two socket-timeout windows plus five seconds expire.
External clients or deployments using a different database are not coordinated.
No live deployment-wide throughput certification or restore rehearsal is claimed.

## Verification

Final backend regression: **376 unit tests and 188 PostgreSQL integration tests**
pass. Scoped Ruff and `git diff --check` pass. No frontend changes were made in
this follow-up, so no new browser acceptance is claimed.

Shared-admission tests include three independent Python processes performing
four simulated calls each: all twelve reservations completed, with no overlapping
work intervals. Separate tests kill a reservation owner, verify bounded lease
recovery, fence stale release, share cooldown/daily quota across independent
coordinators, reject coordinator outages, and prove the default transport holds
no database transaction during its mocked network request. These are deterministic
coordination/fault results, not live model throughput measurements.

Approval tests exercise both report runtimes and reject direct approval when
warnings concern dates, omitted/reversed blockers, partial evidence rejection or
repaired identifiers. They verify zero progress events.

## Live evidence and all unsuccessful attempts

| Artifact | Outcome |
| --- | --- |
| `wording-variants-02` | All seven checks unassessed: first request rate-limited, remaining calls blocked by cooldown |
| `capacity-diagnostic-01.json` | One tiny Groq synthetic health request succeeded; does not establish capacity for extraction-sized prompts |
| `wording-variants-03` | All seven unassessed; first Groq response specified 405 seconds of retry delay |
| `wording-variants-04` | After that delay, first request still rate-limited with a further 75-second delay; remaining cases blocked locally/shared gate |
| `date-retry-05` | After the latest delay, Q06 passed live; Q07 hit `MODEL_RATE_LIMITED` with a 992-second delay after admission pacing |
| `../provider-capacity-2026-10-16/shared-admission-03` | OpenRouter preflight declined the two-request probe: captured quota was used 49 / limit 50 / remaining 1. Zero inference calls |

Q06 is the previously unassessed “tomorrow” plan without a trusted report date:
the live result retained `planned_work`, left the date unknown, and produced no
quantity, installed progress or lifecycle endpoints. Q07 contradictory-date live
verification remains blocked. Unit/integration date-conflict safety passes, but
that is separate evidence.

Groq returned full advertised minute-token availability alongside the later 429s.
This record does not attribute those failures conclusively to a particular quota
bucket or account tier; captured numeric headers cannot prove that. The 992-second
cooldown was respected and no further Groq inference was attempted. The OpenRouter
probe preserved its original configuration scope label; it performed preflight
only, so it supplies no live shared-admission evidence. Future probe metadata now
names the PostgreSQL scope correctly.

## Still open

The v11 blocker/evidence improvements and delivery matching need successful live
re-evaluation on the known cases and fresh wording after quota reset. They are
implemented and safety-tested, not proven accuracy improvements. Q07 remains
unassessed live. Independently reviewed ambiguous matches, dates, quantities and
semantic evidence remain pending. Sustained representative provider workloads,
real multi-worker deployment measurements, historical transport/lease root-cause
attribution, controlled flag enablement, monitoring and rollback rehearsal remain
release gates. No rollout was started.
