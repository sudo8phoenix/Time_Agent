# Time Agent frontend redesign

Implemented 28 October 2026. React 19, TypeScript, Vite and the existing API/session model are retained.

## Product and design

The interface centers construction schedules and source-backed acceptance. A mineral-gray working canvas, translucent floating navigation, teal state accents, Manrope typography, compact activity rows, and rounded controls establish the visual system. Data-heavy work surfaces remain opaque.

- **Overview:** real activity, accepted-event, and pending-proposal counts, review entry point, and active schedule.
- **Schedule:** read-only Gantt-style baseline, WBS grouping, collapse/expand, search, accepted/unreported filtering, 50-row paging, table alternative, fit/30-day/90-day windows and date navigation. Missing dates remain visible. Date-only values retain their calendar date across browser time zones.
- **Import:** visible upload → inspect/map → validate/stage → activate stages, native previews and per-task mapping, separate canonical CSV path, explicit version activation, and compact project creation disclosure.
- **Intake:** readable text/file submission, source constraints, report date, existing XLSX mapping and reviewed PDF transcription.
- **Review:** source evidence and provenance on one side; proposed effects and reviewer decisions on the other. Additional matching/alias tools use a disclosure. Warnings, revisions, scope, evidence, and approval requirements remain enforced.
- **Approved progress:** searchable, paginated register, quantities, lifecycle dates, available physical progress, delivery receipts, expandable history, corrections/retractions, and existing CSV export.
- **History:** report processing history plus an Accepted updates & audit view using the existing execution-history APIs and filters.
- **Appearance:** light default, persisted dark appearance, reduced-motion/reduced-transparency support, blur fallback, visible focus, keyboard controls, and responsive navigation. Horizontally scrollable schedules retain activity labels on narrow screens.

Report intake remains the initial reviewer destination to preserve the existing operating workflow and draft restoration. Overview and Schedule are first-class navigation destinations.

## Components and research

Studied the five supplied Dribbble reference pages: [Employee Management](https://dribbble.com/shots/26973590-Employee-Management-Dashboard), [Calendar appointments](https://dribbble.com/shots/25786979-Calendar-app-dashboard-for-scheduling-appointments), [HR Calendar](https://dribbble.com/shots/25775178-HR-Management-Calendar), [Jetrise](https://dribbble.com/shots/23006375-Jetrise-HR-Managament-Dashboard), and [Project Management](https://dribbble.com/shots/26586590-Project-Management-Dashboard). Their hierarchy, restrained surfaces, and schedule density informed the direction; HR-specific widgets and appointment features were not imported into the product.

| Choice | Reason |
| --- | --- |
| Base UI 1.9.0, MIT | React 19-compatible accessible tabs, keyboard navigation and measured sliding indicators. Tree-shaken by Vite. |
| Lucide React 1.62.0, ISC | Consistent lightweight SVG icons; only used icons are bundled. |
| Native CSS | Glass surfaces, motion, fallbacks, responsive layouts and the read-only schedule visualization. |
| Glassy UI evaluated, not installed | The registry source matches React 19, but the segmented control pulls in shared optics, refraction and motion utilities plus a large stylesheet. This app uses a smaller CSS treatment over accessible primitives. See [Glassy documentation](https://glassyui.com/docs) and [MIT repository](https://github.com/alexburlis/glassyui). |
| No Gantt editing, table or animation package added | The supported schedule view is read-only; native tables, bounded row rendering, and CSS transitions cover the implemented interactions. |

No Tailwind migration or redundant component system was introduced. The old workspace-theme stylesheet was removed and the retained workflow styles consolidated. The new shell, schedule and audit data loader are separate components.

## TimeChat removal and existing edits

TimeChat/Text log has no application route, navigation, conversation panel, or production import. Conversation requests and ElevenLabs are absent from the production bundle. Obsolete chat styling and active frontend conversation-test registrations were removed. The old modified `TimeChat.tsx` and conversation test files are preserved on disk because they contained pre-existing local edits; they are outside the active application and test paths. The legacy session draft key is still cleared on logout.

No backend conversation endpoints, database models, or services were deleted. Pre-existing backend changes and other workspace artifacts were preserved.

## API change and limitations

The sole new backend change is additive: `/projects/{project_id}/progress` includes nullable ISO `planned_start` and `planned_finish`, read directly from imported Activity records. Its existing session and project authorization dependencies are unchanged. A new SQLite unit test checks dated/undated activities and verifies that reading does not create ActivityState or dirty ORM state.

- Backend deployment is needed for timeline bars. Older responses without these fields safely render undated rows.
- No dependency relationship API was added; the frontend does not invent links. Native import previews still show their source relationships.
- Schedules cannot be dragged or edited in the workspace. Import staging and explicit activation remain the supported schedule changes.
- Physical progress is only shown when supplied per activity. No artificial overall completion, forecasts, productivity metrics or analytics were introduced.
- PMIS remains the existing MOCK integration. Acceptance and external delivery remain separate states.
- The progress endpoint returns a full schedule snapshot; client rendering is bounded to 50 activities per page. Server-side schedule paging would be a separate API improvement for very large projects.
- Browser tests use synthetic fixtures and intercepted API responses. A running production backend, PostgreSQL concurrency, real model processing, and actual external delivery were not exercised during this redesign.

## Verification

- `npm run typecheck` — passed.
- `npm run build` — passed; approximately 342 kB JavaScript / 106 kB gzip and 58 kB CSS / 12 kB gzip.
- `node tests/frontend-contracts.test.mjs` — passed. Assertions tolerate source formatting.
- `npm run test:e2e -- --project=fixtures --project=review-api` — **61 passed** after the redesign. Covers import validation/staging, review/revision/rejection/approval, scope, provenance, transcription/mapping, stale sessions/CSRF, project isolation, late responses, delivery, history, error states, and new scheduling interactions.
- Relevant Python unit tests — **17 passed**: schedule timeline read, progress export, approval regressions and ledger.
- Visual QA — screenshots and overflow checks at **320, 390, 768, 1024 and 1440 px**, plus dark appearance, review, import, progress and audit screens.

Run `node tests/visual-redesign.mjs` from frontend with an API-mode dev server at port 4175 (or set `VISUAL_BASE_URL`) and an
opt-in `VITE_FIXTURE_MODE=true` dev server at port 4173 (or set `VISUAL_FIXTURE_URL`). This script intercepts requests only in its own browser and labels its synthetic project/data. It never substitutes production application data.

Screenshots: [desktop overview](../artifacts/frontend-redesign/overview-1440.png), [mobile overview](../artifacts/frontend-redesign/overview-390.png), [dark appearance](../artifacts/frontend-redesign/overview-dark-1440.png), [approved register](../artifacts/frontend-redesign/progress-1440.png), [audit](../artifacts/frontend-redesign/audit-1440.png), [evidence review](../artifacts/frontend-redesign/review-1440.png), and [mobile import](../artifacts/frontend-redesign/import-390.png).
