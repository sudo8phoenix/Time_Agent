# Current prototype status — 18 October 2026

Release acceptance remains incomplete. The prototype uses public schedules,
synthetic reports, owner-authorized AI-assisted review and **MOCK PMIS**.
An owner sample is `not_expected`; independent human review has not occurred.
Earlier dated acceptance records apply to their recorded source and scope.

## App and model

The local homepage at `http://127.0.0.1:8001/` returned HTTP 200 and
`/api/v1/health/live` returned `{"status":"ok"}` on 18 October. An API process
and normal worker were found running. This establishes reachability, not an
accepted-source restart or a complete extraction/approval test. Use
[the local runbook](local-run.md) for startup and recovery.

The inspected extraction configuration is Groq `openai/gpt-oss-20b`.
GPT-OSS 120B is not the configured extraction model. Existing jobs and durable
conversations retain their saved assignments. Changing `.env` requires restarting
the API and worker for new settings; it does not rewrite pinned work.

LangGraph is the only report-processing runtime. Both hierarchy and model-assisted
orchestration rollout flags remain false. The default extraction prompt remains
`extraction-v12-source-clause-check`; V20
(`extraction-v20-short-schedule-ids`) is an explicit candidate, not the default.
The application database was inspected at migration `0018_hosted_admission`.

## Where the measured latency went

The first completed V20 report in the latest mixed rehearsal reached review in
115.757 seconds. Its numeric tool telemetry separates admission from transport:

| Stage | Total tool time | Quota/admission wait | Request/response transport |
|---|---:|---:|---:|
| Extraction | 47.134 s | 46.312 s | 0.806 s |
| Candidate retrieval | 46.566 s | 45.353 s | 1.190 s |
| Selection | 20.519 s | 19.651 s | 0.846 s |

Admission contributed 111.316 seconds and transport 2.842 seconds across the three
calls. Transport includes the remote request and response; it is not a separate
measurement of model generation alone. This report's dominant delay was quota
pacing. It is one synthetic sample, not a sustained p95 or a model comparison.
See [saved numeric timings](../evaluation/results/release-completion-2026-10-18/v20-mixed-workload-v2/initial-report-provider-metrics.json).

PostgreSQL admission coordinates roles, models, key slots and processes using the
same database. The three configured Groq keys share one organization quota.
Separate databases and external clients are outside this coordinator. Requests
keep finite budgets and zero transport retries; there is no quota bypass or
cross-model/provider fallback. Smaller evaluation groups pace submissions but
do not add capacity. See [provider policy](provider-capacity.md).

## Six acceptance workstreams

| Workstream | Current evidence | Still required |
|---|---|---|
| Provider capacity | Bounded successful calls and one 115.757 s full report; prior 429 failures retained | Sustained representative reports and lifecycle conversations within readiness/failure limits |
| Quality | V20 repeated-heading repair recovers three observations in offline replay; BM-02 and BM-03 pass live, alongside earlier bounded blocker/delivery successes | Fresh extraction and broader matching results meeting every approved target; offline replay is development evidence |
| Fresh evaluation | V19 validation failed quality/readiness; V19 holdout is consumed | Fresh V20 validation, then a newly frozen holdout; no reuse of consumed holdouts as unseen data |
| Confidence | Runtime extraction/link scores remain null; no event/link threshold has enough eligible support | Correct event/link predictions under the frozen precision 0.98 / minimum-support 20 study policy, then runtime validation |
| Sustained latency | Isolated browser approval/update and verified mock-delivery timings meet their numerical limits | Repeat during concurrent reports/conversations sharing the API and database |
| Release | Regression evidence and unaccepted candidate hashes exist | Repeat affected checks, accept evidence, freeze accepted hashes, restart on accepted source, then commit and push |

The approved limits are atomic-event F1 ≥0.90, selected-link precision ≥0.98,
coverage ≥0.80, candidate Recall@8 ≥0.95, endpoint field accuracy ≥0.95,
safe ambiguity handling ≥0.95, readiness p95 ≤120 s, internal-update p95 ≤2 s,
mock acknowledgement p95 ≤10 s without retry, and zero hard safety violations.
The [frozen target record](evaluation-targets-approved-2026-10-16.json) governs
definitions and approval. Passing regression tests does not clear these gates.

## Latest verification and retained work

After the evidence repair, 455 unit tests and 14 PostgreSQL prompt-pinning
integration cases passed. After the later rehearsal-only changes, 73 affected
unit cases, scoped Ruff and `git diff --check` passed. Before publishing the
remaining candidate files, all 455 unit and 201 PostgreSQL integration tests
passed again. Frontend typecheck, build and contract checks and changed executable
Python lint passed. These checks do not clear the live acceptance gates. See
[the publication record](publication-2026-10-18.md).

The first new mixed attempt was interrupted because conversations were not pinned
to V20. Its report remains queued in `progress_rehearsal_20261016`. The corrected
second attempt used `progress_rehearsal_eval_20261017` and stopped on expired
ownership after a wall/monotonic clock discontinuity. Its cause is unproven, and
this is not evidence of a renewed 429. Both owned workers exited with code zero;
two reports and two conversations remain running/queued for inspection.

The latest runner pins V20 and Groq assignments, uses lifecycle-start conversation
inputs and rejects completed tasks with no event cards/model calls. That runner
revision has not been live validated. Inspect retained tasks, original budgets,
leases and checkpoints before explicit resume; do not reset them to get a pass.

[The detailed follow-up](release-followup-2026-10-18.md) links the raw evidence.
`v20-candidate-source-v5.json` is an unaccepted candidate snapshot. Publishing
candidate source/evidence to Git does not establish an accepted release. Accepted
hash freeze, accepted-source restart and release acceptance remain pending.
Publication changes no runtime settings, flags, application data, labels or
historical captures.
