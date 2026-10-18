# Retrieval resumption — 17 October 2026

> Historical record: statements and instructions below apply to the recorded stage.
> [Current status — 18 October](current-status.md) and the
> [latest V20 follow-up](release-followup-2026-10-18.md) supersede its operational
> status. Both V19 splits are consumed; release remains unaccepted.

This records the initial resumption and v13 stage. Later v18 candidate scoring
and final verification are in [the current candidate review](release-review-2026-10-17.md).
The original retrieval failure remains unproven throughout those later results.

The owner resumed work after the 16 October pause. Inspection preceded worker
restart. Evidence lives in `evaluation/results/release-completion-2026-10-17/`.

## Preserved interruption and recovery evidence

`pre-resume-inspection.json` records read-only sanitized job/run/tool inventories,
checkpoint identifiers, and hashes of checkpoint, blob and pending-write rows.
Both interrupted job leases had expired; neither provider held a lease, and no
conversation tasks existed. The database contained two previously approved events
from earlier workflows; these are not events created by the diagnostic jobs.

The bounded two-worker one-shot resume is retained as `resumed-diagnostic/`.
Its result is correctly marked incomplete: one worker processed C01 and the other
returned exit 3 without claiming C03. C01 terminated with `AGENT_DEADLINE`, because
its original hierarchical root deadline was pinned to run creation and expired
during the pause. No deadline or checkpoint was reset to manufacture a success.
A subsequent single one-shot worker resumed C03; retrieval returned one candidate
and the job reached review. Its sanitized log is `remaining-worker.log`.
The database event count remained at its pre-resume value of two during the
two-worker attempt. No worker invokes proposal acceptance.

## Fresh bounded reproduction

`fresh-retrieval-diagnostic/` contains a separate C01/C03 capture using the same
provider policy as the paused diagnostic: v2 free OpenRouter planner, Groq slot 0
specialists, v1 Groq slot 0. Both worker rollout flags were false; the persisted
graph versions were honored. Two workers operated and exited cleanly.

| Case | Graph | Result | Observed readiness from enqueue |
| --- | --- | --- | --- |
| C01 | v2 | Ready for review | 192.248 seconds |
| C03 | v1 | Ready for review | 139.829 seconds |

Both retrieval calls succeeded, returning one candidate each. C01 extraction,
retrieval and selection tool durations were 80.769, 71.124 and 31.543 seconds.
C03 retrieval and selection durations were 52.896 and 82.567 seconds. These are
whole tool durations, including admission waiting; they do not isolate provider
network latency. The saved live status showed no expired worker ownership or
active provider cooldown at that observation, which is not a claim about the
entire run. Zero approved events were created for the fresh fixture project.

This reproduction did not reproduce the original retrieval errors. Original
traces still contain only `AGENT_TOOL_FAILED`, so their cause cannot be assigned
to capacity, transport or invalid decisions from these later successes. Keep
the original two failures in workload totals. The fresh run also fails the
approved 120-second readiness target; two successful reports do not establish
sustained capacity. Admission/network timing separation is still needed to
attribute the long tool durations.

## Extraction follow-up

The development scorer now checks explicitly declared per-event fields. Q01
checks location and work type, Q02 checks clause-specific location/work identity,
and Q04 checks destination versus asset classification. Rescoring saved v12
outputs rejects all three despite correct event/quantity checks. These remain
known development cases, not unseen acceptance inputs.

V13 adds location-heading inheritance, clause-local location boundaries, blocked
work identity and destination classification instructions. V12's prompt hash is
unchanged: `e388e2807330a6d81289bf508dccfab25be06c54c9f1e122f3767dac9bf52ec6`.
The v13 live capture is recorded separately in `v13-field-checks/`; its saved
outputs, including rejected responses, determine the component result.

That capture completed all three requests but passed only Q02. Q01 retained the
zone and cable work type but merged testing's blocker into the progress item.
Q04 left area null and used the report date instead of resolving yesterday.
V13 is therefore **not promoted**: the runtime default remains v12. The registered
v13 prompt remains available for replay and explicit diagnostic selection using
`--prompt-version extraction-v13-location-scope`. Exact fixture bytes matching
the capture's fixture hash are retained in `v13-field-checks/fixtures.json`.
No claim that the remaining extraction defects are fixed is supported.

Verification: 407 unit tests passed; 195 integration tests passed on the v13
candidate, followed by all eight extraction prompt-pinning integration tests
after restoring the v12 default. The final unit suite was also rerun.
Scoped Ruff and diff checks passed. The release remains unfrozen, rollout flags
remain off, and the normal application's processes have not been restarted.
