// Explicitly synthetic visual QA. This script intercepts requests in its own browser;
// production application requests and fixture-mode behavior are unchanged.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
const output = new URL("../../artifacts/frontend-redesign/", import.meta.url)
  .pathname;
mkdirSync(output, { recursive: true });
const browser = await chromium.launch();
const names = [
  "Excavate northern pipe trench",
  "Install underground pipework",
  "Inspect pipework welds",
  "Hydrotest utility network",
  "Backfill and compact trench",
  "Install distribution panels",
  "Lay power and control cables",
  "Terminate field instruments",
];
const items = names.map((name, n) => ({
  activity_id: `a${n}`,
  external_id: `UTIL-${100 + n * 10}`,
  name,
  wbs:
    n < 5 ? "01 / Underground utilities" : "02 / Electrical & instrumentation",
  planned_start: `2026-10-${String(1 + n * 3).padStart(2, "0")}`,
  planned_finish: `2026-11-${String(2 + n * 3).padStart(2, "0")}`,
  planned_quantity: n < 5 ? "200" : "80",
  completed_quantity: n === 0 ? "120" : "0",
  unit: "m",
  physical_percent: n === 0 ? "60" : null,
  approved_event_count: n === 0 ? 2 : 0,
  history: [],
}));
const page = await browser.newPage();
page.on("pageerror", (e) => {
  throw e;
});
await page.route("**/api/v1/**", (route) => {
  const path = new URL(route.request().url()).pathname;
  if (path.endsWith("/auth/me"))
    return route.fulfill({
      json: {
        id: "visual-qa",
        username: "site.reviewer",
        role: "reviewer",
        csrf_token: "qa",
      },
    });
  if (path.endsWith("/projects"))
    return route.fulfill({
      json: {
        items: [
          {
            id: "synthetic-visual-project",
            name: "North Utility Works · Visual QA",
            timezone: "Asia/Kolkata",
            active_schedule_version_id: "v3",
          },
        ],
      },
    });
  if (path.endsWith("/progress"))
    return route.fulfill({
      json: {
        project_id: "synthetic-visual-project",
        project_name: "Synthetic visual QA",
        schedule_version: 3,
        counts: { activities: 8, approved_events: 2, pending_review: 4 },
        items,
        notice:
          "Synthetic visual QA data. Per-activity values only. No overall project percentage is calculated.",
      },
    });
  if (path.endsWith("/jobs"))
    return route.fulfill({ json: { items: [], next_offset: null } });
  if (/\/(history|durations|blockers)$/.test(path))
    return route.fulfill({ json: { items: [], total: 0, next_offset: null } });
  throw Error(`Unexpected visual request: ${path}`);
});
await page.goto(process.env.VISUAL_BASE_URL || "http://127.0.0.1:4175");
for (const width of [1440, 1024, 768, 390, 320]) {
  await page.setViewportSize({ width, height: 1000 });
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await page.getByRole("heading", { name: "Project overview." }).waitFor();
  await page.waitForTimeout(350);
  await page.screenshot({
    path: `${output}overview-${width}.png`,
    fullPage: true,
  });
  if (
    await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  )
    throw Error(`Overflow at ${width}`);
}
await page.setViewportSize({ width: 1440, height: 1000 });
await page.getByRole("button", { name: "Use dark theme" }).click();
await page.waitForTimeout(350);
await page.screenshot({
  path: `${output}overview-dark-1440.png`,
  fullPage: true,
});
await page.getByRole("button", { name: "Use light theme" }).click();
await page
  .getByRole("button", { name: "Approved progress", exact: true })
  .click();
await page
  .getByRole("heading", { name: "Activity-level progress, with its history." })
  .waitFor();
await page.waitForTimeout(350);
await page.screenshot({ path: `${output}progress-1440.png`, fullPage: true });
await page.getByRole("button", { name: "Job history", exact: true }).click();
await page.getByRole("tab", { name: "Accepted updates & audit" }).click();
await page
  .getByRole("heading", { name: "Execution history", exact: true })
  .waitFor();
await page.waitForTimeout(350);
await page.screenshot({ path: `${output}audit-1440.png`, fullPage: true });
// Optional existing opt-in fixture server exercises the source and import forms.
for (const width of [1440, 390]) {
  const fixturePage = await browser.newPage({ viewport: { width, height: 1000 } });
  await fixturePage.goto(process.env.VISUAL_FIXTURE_URL || "http://127.0.0.1:4173");
  await fixturePage.getByRole("button", { name: /Sign in/ }).click();
  await fixturePage.getByRole("heading", { name: "Bring in a field report" }).waitFor();
  await fixturePage.waitForTimeout(350);
  await fixturePage.screenshot({ path: `${output}intake-${width}.png`, fullPage: true });
  await fixturePage.getByLabel("Paste report text").fill("Area A: erected three spools on line 24-XX.");
  await fixturePage.getByRole("button", { name: /Create review job/ }).click();
  await fixturePage.getByRole("button", { name: /Open review queue/ }).click();
  await fixturePage.getByRole("heading", { name: "Source evidence" }).waitFor();
  await fixturePage.waitForTimeout(350);
  await fixturePage.screenshot({ path: `${output}review-${width}.png`, fullPage: true });
  await fixturePage.getByRole("button", { name: "Approve update" }).click();
  await fixturePage.getByRole("button", { name: "Finish review" }).click();
  await fixturePage.getByRole("button", { name: "Import schedule", exact: true }).click();
  await fixturePage.locator('input[type="file"]').first().setInputFiles({ name: "visual-qa.xer", mimeType: "text/plain", buffer: Buffer.from("SYNTHETIC VISUAL QA") });
  await fixturePage.getByRole("button", { name: "Read schedule source" }).click();
  await fixturePage.getByRole("heading", { name: "PROJECT", exact: true }).waitFor();
  await fixturePage.waitForTimeout(350);
  await fixturePage.screenshot({ path: `${output}import-${width}.png`, fullPage: true });
  if (await fixturePage.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error(`Import overflow at ${width}`);
  await fixturePage.close();
}
await browser.close();
console.log("Visual checks passed at 320, 390, 768, 1024 and 1440px.");
