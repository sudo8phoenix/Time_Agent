# Extraction quality follow-up — 16 October 2026

Both rollout flags remain off. Human approval is preserved. No deployment,
production migration, approval or progress-ledger write was performed.

## Implemented changes

Extraction v10 asks for separate factual clauses, separate work/blocker events,
and planned/delivery dates independent of quantity effects. The exact v9 prompt
is retained. New report runs and conversation tasks pin v10 in saved config;
existing unpinned runs/tasks use v9, including postprocessing, to preserve replay
fingerprints and normalization across restarts. A future default does not change
a saved task's prompt. Explicit unsupported prompt versions are rejected.

For v10, missing planned/delivery dates can be restored from already validated,
exact evidence quotes containing one unambiguous today/yesterday/tomorrow with
a trusted report date. Alternatives, negation, other dates and declared conflicts
stay unresolved. This never creates installed quantities or lifecycle effects.

A narrow source check adds a blocking observation warning when an explicit
stoppage-with-cause clause lacks any separate blocker for that fragment. It
never generates an observation or activity match from a regex. This is only a
presence check: it does not detect every paraphrase, a second missing blocker
when another blocker exists, or a fragment with no accepted observations.

## Known-case full report capture

`known-cases-01` is immutable: three synthetic reports, eleven live Groq calls,
then exact specialist replay through deterministic hierarchy (eleven replays,
zero planner calls). Both runtimes reached pending review for all three cases,
with zero ledger writes. `known-cases-review-01` rescored into separate artifacts
using the existing source-backed technical reference; this is not human review.

| Check | Each runtime |
| --- | --- |
| Normalized quantity/effect policy | 3/3 |
| Separate expected atomic events | 3/3 |
| Reviewed work date | 3/3 |
| Exact activity mapping | 2/3 |

C03 retains tomorrow's planned date (2026-09-22). C05 now contains both the work
and the separate blocker. C06 retains the delivery date (2026-09-21), but its
activity mapping is unmatched. The source does not explicitly say today in C06;
the model used trusted report context. Do not attribute that result to the
relative-word recovery alone, or infer consistent recall from one generation.

## Fresh wording diagnostic

`wording-variants-01` uses seven synthetic development checks in a separate
component evaluator. Expected checks never enter model input. Only five checks
completed inference; two passed all checks. No schedules or persistence are
used. These are not independently unseen acceptance cases.

| Case | Result |
| --- | --- |
| Q01 work + permit stoppage | Work retained, blocker merged; blocking missing-blocker warning present |
| Q02 reversed cause + work | Work retained; invalid blocker evidence rejected; atomic-event check fails |
| Q03 tomorrow plan across month boundary | Pass: 2026-10-01, no progress effects |
| Q04 yesterday delivery | Pass: 2026-09-29, no progress effects |
| Q05 negated stoppage + ongoing work | Malformed evidence fragment identifier rejected; no accepted observation |
| Q06 relative date without trusted context | Not assessed: provider MODEL_RATE_LIMITED |
| Q07 contradictory dates | Not assessed: subsequent MODEL_CAPACITY_TIMEOUT during shared cooldown |

No automatic provider/key fallback or repeated capture was used to hide these
failures. Q06/Q07 need rerunning after provider capacity is available, into a new
directory. The rate limit confirms that bounded earlier health probes do not
establish sustained provider capacity. Admission remains process-local.

## Regression verification

359 unit tests and 173 PostgreSQL integration tests pass. These include new and
legacy prompt pinning through report execution and conversation crash/replay,
and direct approval rejection for missing-blocker and conflicting-date warnings
in both graph versions. Scoped Ruff and `git diff --check` pass. Backend-only
changes did not require a new browser build; earlier browser evidence remains
separate. Live captures use synthetic data and isolated test database fixtures.

## Remaining work

Improve blocker/evidence reliability across paraphrases and delivery matching;
repeat the two provider-blocked wording checks; independently adjudicate dates,
quantities, mappings and semantic evidence. Deployment-wide admission, sustained
quota/timeout/fallback validation, and attribution of the historical transport/
lease interruption remain open. Controlled rollout and rollback rehearsal have
not been started. These findings do not authorize enabling either flag.
