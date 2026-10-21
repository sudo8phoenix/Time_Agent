// Real UI/API/DB/worker/MOCK flow with explicitly injected synthetic model outputs.
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { readFileSync, writeFileSync } from 'node:fs';
const fixture = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const output = process.argv[3];
const base = process.env.CHECKLIST_API_URL;
const mock = process.env.CHECKLIST_MOCK_URL;
if (![base, mock].every(url => /^http:\/\/127\.0\.0\.1:\d+$/.test(url ?? ''))) throw new Error('Loopback only');
const browser = await chromium.launch({ headless: true });
let page;
const row = { scope: 'synthetic injected model; real browser/API/worker/DB/MOCK receiver', passed: false };
try {
  page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.name));
  row.stage = 'sign_in';
  await page.goto(base);
  await page.getByLabel('Username').fill(fixture.username);
  await page.getByLabel('Password', { exact: true }).fill(process.env.CHECKLIST_PASSWORD);
  await page.getByRole('button', { name: /Sign in/ }).click();
  row.stage = 'intake';
  await page.getByLabel('Paste report text').fill('Installed 2 m of cable today.');
  await page.getByLabel('Report date', { exact: true }).fill('2026-09-24');
  const submitted = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/reports') && response.request().method() === 'POST');
  await page.getByRole('button', { name: /Create review job/ }).click();
  const response = await submitted;
  if (response.status() !== 202) throw new Error('INTAKE_FAILED');
  row.job_id = (await response.json()).job_id;
  row.stage = 'review_queue';
  await page.getByRole('button', { name: /Open review queue/ }).click({ timeout: 60000 });
  row.stage = 'evidence';
  await page.locator('blockquote').filter({ hasText: '2 m of cable' }).first().waitFor();
  row.stage = 'approval';
  const approval = page.waitForResponse(response => /\/proposals\/[^/]+\/approve$/.test(new URL(response.url()).pathname) && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Approve update', exact: true }).click();
  const accepted = await approval;
  if (!accepted.ok()) throw new Error('APPROVAL_FAILED');
  row.approval_http_status = accepted.status();
  row.stage = 'durable_update_and_mock';
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const progress = await page.request.get(`${base}/api/v1/projects/${fixture.project_id}/progress`);
    if (!progress.ok()) throw new Error('PROGRESS_FAILED');
    const item = (await progress.json()).items.find(item => item.id === fixture.activity_id || item.activity_id === fixture.activity_id || item.external_id === 'CABLE-001');
    row.internal_update_verified = item?.state_revision === 1 && Number(item?.completed_quantity) === 2;
    const received = await page.request.get(`${mock}/activities/${fixture.project_id}/${fixture.schedule_id}/CABLE-001`);
    if (received.ok()) {
      const receipt = await received.json();
      row.mock_verified = receipt.state_revision === 1 && Number(receipt.state.completed_quantity) === 2;
    } else if (received.status() !== 404) throw new Error('MOCK_FAILED');
    if (row.internal_update_verified && row.mock_verified) break;
    await page.waitForTimeout(50);
  }
  row.browser_error_count = errors.length;
  row.passed = Boolean(row.internal_update_verified && row.mock_verified && !errors.length);
  await page.screenshot({ path: output.replace(/\.json$/, '.png'), fullPage: true });
} catch (error) {
  row.error_type = error.constructor.name;
  if (page) await page.screenshot({ path: output.replace(/\.json$/, '-failure.png'), fullPage: true }).catch(() => {});
} finally {
  writeFileSync(output, JSON.stringify(row, null, 2) + '\n', { flag: 'wx' });
  await browser.close();
}
if (!row.passed) process.exitCode = 1;
