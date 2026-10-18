// Real browser approval timing against an isolated API and MOCK PMIS receiver.
// Input contains synthetic fixture IDs only; credentials are environment-only.
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { readFileSync, appendFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';

const fixtures = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const output = process.argv[3];
const base = process.env.LATENCY_API_URL;
const mock = process.env.LATENCY_MOCK_URL;
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base ?? '') ||
    !/^http:\/\/127\.0\.0\.1:\d+$/.test(mock ?? '')) {
  throw new Error('Loopback API and mock receiver required');
}
const browser = await chromium.launch({ headless: true });
try {
  for (const [index, fixture] of fixtures.entries()) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const row = { sample: index + 1, started_at: new Date().toISOString(), proposal_id: fixture.proposal_id, passed: false };
    try {
      await page.goto(base);
      await page.getByLabel('Username').fill(fixture.username);
      await page.getByLabel('Password', { exact: true }).fill(process.env.LATENCY_PASSWORD);
      await page.getByRole('button', { name: /Sign in/ }).click();
      await page.getByRole('button', { name: 'Review queue', exact: true }).click();
      await page.getByRole('button', { name: 'Review proposals →', exact: true }).click();
      const button = page.getByRole('button', { name: 'Approve update', exact: true });
      await button.waitFor({ state: 'visible' });
      const approval = page.waitForResponse(response =>
        new URL(response.url()).pathname === `/api/v1/proposals/${fixture.proposal_id}/approve` &&
        response.request().method() === 'POST');
      const began = performance.now();
      await button.click();
      const response = await approval;
      if (!response.ok()) throw new Error(`APPROVAL_HTTP_${response.status()}`);
      row.browser_click_to_approval_response_seconds = (performance.now() - began) / 1000;
      let updated = false;
      let received = false;
      while (performance.now() - began < 15000) {
        if (!updated) {
          const progress = await page.request.get(`${base}/api/v1/projects/${fixture.project_id}/progress`);
          if (!progress.ok()) throw new Error(`PROGRESS_HTTP_${progress.status()}`);
          const item = (await progress.json()).items.find(item => item.id === fixture.activity_id || item.activity_id === fixture.activity_id || item.external_id === 'A-1');
          if (item?.actual_start === '2027-02-01' && item?.state_revision === 1) {
            updated = true;
            row.browser_click_to_verified_internal_update_seconds = (performance.now() - began) / 1000;
          }
        }
        if (!received) {
          const receipt = await page.request.get(`${mock}/activities/${fixture.project_id}/${fixture.schedule_id}/A-1`);
          if (receipt.ok()) {
            const body = await receipt.json();
            if (body.state_revision === 1 && body.state.actual_start?.local_date === '2027-02-01' &&
                body.state.actual_start?.local_time === '08:15:00') {
              received = true;
              row.browser_click_to_verified_mock_seconds = (performance.now() - began) / 1000;
            }
          } else if (receipt.status() !== 404) throw new Error(`MOCK_HTTP_${receipt.status()}`);
        }
        if (updated && received) break;
        await page.waitForTimeout(50);
      }
      row.passed = updated && received;
      if (!row.passed) row.error_code = 'VERIFICATION_DEADLINE';
    } catch (error) {
      // Error messages may contain page text or credentials; retain category only.
      row.error_type = error.constructor.name;
    } finally {
      appendFileSync(output, `${JSON.stringify(row)}\n`);
      console.log(JSON.stringify(row));
      await context.close();
    }
    if (index + 1 < fixtures.length) await new Promise(resolve => setTimeout(resolve, Number(process.env.LATENCY_SAMPLE_INTERVAL_MS ?? '0')));
  }
} finally {
  await browser.close();
}
