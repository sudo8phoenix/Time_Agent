# L04–L06 lifecycle validation — 10 October 2026

## Development fixture and isolated environment

The live browser flow used a synthetic one-row canonical CSV activity `F-01-EXC` (Excavation at Foundation F-01, unsupported numeric measurement basis), synthetic text reports, and a separate migrated PostgreSQL database `progress_lifecycle_l04_test`. No production or user schedule was migrated. The real API, browser, legacy worker, private Ollama model, review endpoint, progress endpoint, and CSV export were used. The live Playwright suite does not intercept APIs.

- Project `8538dcc8-61a8-42ce-b34b-426f54afbf72`
- Schedule version `ae33345e-797d-4a08-a447-21a13c4622b6` (version 1, staged then activated 2026-10-09 19:16:28 UTC)
- Activity `e29a19c9-205f-49c3-888c-bd8064515ceb`
- Model `gemma4:12b`, digest `6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b`; extraction prompt `extraction-v7-lifecycle`

## Passed live flow

The `lifecycle-live` Playwright run passed in 9.1 minutes. It registered and logged in a real reviewer, staged and activated the CSV schedule, submitted each report through the browser, invoked the real worker/model, reviewed and accepted both proposals, refreshed the progress page, and read the CSV export. It submitted the finish report a second time; report ingestion returned `existing=true`, with no extra accepted event.

| Step | Report/job | Proposal/event | Accepted value | Activity state after acceptance |
| --- | --- | --- | --- | --- |
| Before | — | — | — | No actual start or finish; revision 0; quantity 0; physical percent unknown |
| Start | report `66fd86f7-371b-478e-a2b4-fd37fa78245e`; job `14247ef3-c26e-47ff-aa67-a283ba198adf` | proposal `93f36f4e-4813-46e2-adac-0d1abdc11d2e`; event `4881503d-634f-4694-aabb-b59335f36ae9` | 2026-10-09 08:30, minute precision; approved 2026-10-09 19:20:07 UTC | In progress, revision 1; quantity 0; physical percent unknown |
| Finish | report `0135ea77-56b3-4c86-bc5f-0e3fa7b720e5`; job `4119c159-60a4-4a9d-a4e1-3ef897034d14` | proposal `bc697289-2abc-41fd-9d77-0749ceb9a862`; event `fad74e74-1dcb-4c04-b4f5-9e19ea10ffb4` | 2026-10-10, date precision, no time; approved 2026-10-09 19:25:34 UTC | Completed, revision 2; quantity 0; physical percent unknown |

The browser assertion saw the actual dates after refresh. The API returned the same values and separate null physical percent. CSV contained the lifecycle event kind, scope, endpoint date/time/precision and accepted state. This is a developer smoke fixture, not an unseen accuracy benchmark.

## Earlier blocked live conflict attempt

The separate `lifecycle-conflict` browser test submitted `Started excavation at Foundation F-01 at 07:45 on 2026-10-08.` against the accepted 2026-10-09 start. It used the real login, API, and worker, but the private model timed out before creating a proposal. Job `3c3044a4-92b0-45f5-aae5-6d4045479388`, report `5f69f4ea-2e1c-46c7-9bb4-f80d9167a0ea`, ended `failed` after three attempts with `PIPELINE_ERROR` at 2026-10-09 19:40:10 UTC. A subsequent model health request also timed out. The activity remained revision 2 with start 2026-10-09 08:30 and finish 2026-10-10. This proved no state mutation on worker failure; it did **not** prove a real-model conflicting proposal was rejected at acceptance. L06 remained open at that point.

A rolled-back direct pipeline diagnostic of an earlier synthetic start report succeeded through extraction, matching, and proposal assembly. Model output varied across calls. Source-grounded repairs for omitted clock time and mismatched precision were added to extraction, with unit tests that reject unsupported clock repairs. The worker now logs only the exception class on failure; it does not log report text or model output.

## Other verification

- 164 backend unit tests passed.
- 19 focused PostgreSQL review/lifecycle integration tests passed, including quantity-free approval on an unsupported numeric basis, concurrent same-key retry producing one event, correction, retraction, chronology rejection, stale schedule rejection, and no-mutation failures.
- 21 fixture/API browser tests passed; frontend typecheck and production build passed.
- Ruff and `git diff --check` passed.

## L06 completed live rerun — 10 October 2026

After the private model recovered, the complete `lifecycle-live` browser suite passed in 11.1 minutes against a fresh migrated database, `progress_lifecycle_l06_test`. The API and worker both used that database. The synthetic project was `a6d0769b-8c96-43b1-8bd2-41ffd391a692`, schedule version `07b35b64-a089-4f70-b7e6-4813c4839298`, and activity `57f15804-d783-4b67-8f08-4ee79920c895`. Each of the three report jobs reached `ready_for_review` on its first attempt with `gemma4:12b` and prompt `extraction-v7-lifecycle`. The model digest was again `6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b`.

The start job `81e9f1e4-7ce6-4903-9d08-612185520f12` produced an accepted actual start of 2026-10-09 08:30 (minute precision), event `5c4e9285-5b73-4f75-a6ce-650c5e36e2c7`, approved 2026-10-10 07:01:10 UTC. The finish job `92c4981c-65f0-4f30-8ebd-e91dd07033a8` produced an accepted 2026-10-10 date-only finish, event `dbe345f8-863b-489f-80e8-cae2ad9fc056`, approved 2026-10-10 07:04:27 UTC. Duplicate ingestion, refreshed progress and CSV export passed again.

The conflicting report `2a5eeb2e-6610-44dd-8948-51cd05f1b765` stated a 2026-10-08 07:45 start. Job `af9724bc-8460-40bd-bf0b-b7f54e650d06` completed at 2026-10-10 07:08:19 UTC and created proposal `6a246944-3ffe-4ca5-af1f-ee7fa6dde007`. Warning review revised it to proposal `01deb066-6d38-48ff-ae99-492b03c65502` without changing the proposed start. Approval of that revised proposal returned HTTP 422 with `CONFLICTING_EFFECT`. Before and after, the activity had start 2026-10-09 08:30, finish 2026-10-10, revision 2 and exactly two approved events; the revised proposal remained pending. The browser asserted the response code and unchanged API state, and a read-only database query confirmed revision 2 and the two events. L06's live conflict gate is now verified. The run artifact is `frontend/test-results/lifecycle-live-run.json`.

This remains a developer smoke fixture, not an unseen accuracy benchmark.
