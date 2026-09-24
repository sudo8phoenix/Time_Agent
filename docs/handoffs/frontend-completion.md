Task ID: W-14 / W-15 / W-17 / W-28 frontend completion

Contract version: Technical specification v1.1; native schedule import builder contract, 23 September 2026.

Changed files:

- `frontend/src/main.tsx`
- `frontend/src/styles.css`
- `frontend/tests/frontend-contracts.test.mjs`

Behaviour implemented:

- Development fixtures are opt-in only (`VITE_FIXTURE_MODE=true`) and visibly labelled.
- Logout now calls the CSRF-protected `POST /auth/logout`; report-intake navigation is always available.
- Failed jobs expose retry; review advances through every proposal ID returned for the job.
- Review sends the current `ReviewChange` shape, including corrected effects and explicit warning resolutions. Approval remains disabled until warnings/mapping are resolved.
- Schedule UI supports canonical CSV staging, native-file upload using the correct multipart field, source-project selection, leaf-only task overrides, stage, explicit activation, and visible activation result.
- An account with no project can create its first project before importing.

Commands run and results:

- `npm run build` — passed.
- `node tests/frontend-contracts.test.mjs` — passed.

Evidence and limitations:

- The repository now includes a Playwright fixture-mode smoke suite at `frontend/tests/e2e/fixture-flow.spec.ts`. It covers report intake through approval/progress and native schedule import through staging without requiring PostgreSQL, Ollama, or real uploaded source bytes.
- Run it with `make test-e2e` after `cd frontend && npm ci` (and `npx playwright install chromium` on a fresh machine). Real API/authentication, database, model, and visual browser walkthrough gates remain separate.
- Browser walkthrough, keyboard/mobile visual QA, real authenticated API flow, and native parser runtime scenarios were not run; browser plugin/harness is unavailable.
- Task overrides expose discipline in this compact screen; the backend remains the validation authority for the full reviewed-mapping schema.

Shared contract changes requested: none.

Next dependent task now unblocked: W-30 assembled native-import UI verification, once the existing E2E harness and local parser runtime are provisioned.
