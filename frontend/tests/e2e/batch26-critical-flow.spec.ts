import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
const output = resolve(process.cwd(), "../evaluation/results/prompting-checklist-2026-10-20/batch-26/frontend");
mkdirSync(output, { recursive: true });
const project = { id: "b26", name: "Controlled review", timezone: "UTC", active_schedule_version_id: "schedule26" };
const source = "On 2026-10-09, installed 2.50 m of cable in North. Total is not 25 m.";
const proposal = { id: "p26", revision: 7, current_activity_revision: 2, review_state: "pending", mapping_state: "suggested", match_strength: "review", chosen_activity_id: "a26", observation: { event_type: "actual_progress", summary: "Installed 2.50 m cable in North.", quantity: "2.50", unit: "m", work_type: "cable_laying", area: "North", tags: [] }, evidence: [{ quote: source, locator: "page:2 / paragraph:3", fragment_id: "f26" }], candidates: [{ id: "a26", name: "North cable installation", area: "North", work_type: "cable_laying", tags: [], rank: 1 }], warnings: [], missing_information: [], proposed_effects: { event_type: "actual_progress", quantity: "2.50", unit: "m", quantity_semantics: "delta", effective_date: "2026-10-09" } };
const job = (state: string, more: Record<string, unknown> = {}) => ({ job_id: "j26", project_id: project.id, state, stage: "select", proposal_count: 0, proposal_ids: [], agent_run_available: false, ...more });
async function api(page: Page, handler: (route: Route, path: string) => Promise<void>) {
 await page.route("**/api/v1/**", async route => {
  const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
  if (path === "/auth/me") return route.fulfill({ json: { id: "u26", username: "reviewer", role: "reviewer", csrf_token: "csrf26" } });
  if (path === "/projects") return route.fulfill({ json: { items: [project] } });
  return handler(route, path);
 });
}
async function submit(page: Page) { await page.goto("/"); await page.getByLabel("Paste report text").fill(source); await page.getByRole("button", { name: /Create review job/ }).click(); }
for (const width of [390, 1440]) test(`FLOW02/13 card fields and keyboard review at ${width}`, async ({ page }) => {
 await page.setViewportSize({ width, height: 1000 });
 const errors: string[] = [], writes: unknown[] = []; page.on("pageerror", e => errors.push(e.message));
 let release: (() => void) | undefined;
 await api(page, async (route, path) => {
  if (path.endsWith("/reports") || path === "/jobs/j26") return route.fulfill({ json: job("ready_for_review", { proposal_count: 1, proposal_ids: [proposal.id] }) });
  if (path === "/proposals/p26") return route.fulfill({ json: proposal });
  if (path === "/proposals/p26/approve") { writes.push(route.request().postDataJSON()); await new Promise<void>(r => { release = r; }); return route.fulfill({ json: { review_state: "approved", state_revision: 3 } }); }
  throw new Error(path);
 });
 await submit(page); await page.getByRole("button", { name: /Open review queue/ }).focus(); await page.keyboard.press("Enter");
 await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
 await expect(page.locator("blockquote")).toHaveText(`“${source}”`);
 await expect(page.locator("figcaption")).toContainText("page:2 / paragraph:3"); await expect(page.locator("figcaption code")).toHaveText("f26");
 await expect(page.locator(".decision-card")).toContainText("2.50 m");
 await expect(page.locator(".effect-list")).toContainText("actual progress"); await expect(page.locator(".effect-list")).toContainText("2026-10-09");
 await expect(page.getByLabel("Schedule candidate")).toHaveValue("a26");
 await expect(page.getByLabel("Schedule candidate").locator("option:checked")).toHaveText("North cable installation · North"); expect(writes).toEqual([]);
 await page.getByRole("button", { name: "Reject", exact: true }).focus(); await page.keyboard.press("Enter");
 await expect(page.getByRole("alert")).toHaveText("Add a reason before rejecting."); expect(writes).toEqual([]);
 await page.getByRole("button", { name: "Approve update" }).focus(); await page.keyboard.press("Tab"); await page.keyboard.press("Shift+Tab");
 await expect(page.getByRole("button", { name: "Approve update" })).toBeFocused(); await page.keyboard.press("Enter");
 await expect.poll(() => !!release).toBe(true); await expect(page.getByRole("button", { name: "Approve update" })).toBeDisabled(); await expect(page.getByLabel(/Review reason/)).toBeDisabled();
 await page.screenshot({ path: `${output}/review-pending-${width}.png`, fullPage: true });
 expect(writes).toHaveLength(1); expect(writes[0]).toMatchObject({ expected_proposal_revision: 7, expected_activity_revision: 2 }); release!();
 await expect(page.locator(".review-header [role=status]")).toContainText("APPROVED"); expect(errors).toEqual([]);
 expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
 await page.screenshot({ path: `${output}/review-${width}.png`, fullPage: true });
});
for (const state of ["empty", "partial", "failed", "quota"]) test(`FLOW03 ${state} response is explicit in actual UI`, async ({ page }) => {
 const value = state === "empty" ? job("ready_for_review") : state === "partial" ? job("ready_for_review", { proposal_count: 1, proposal_ids: [proposal.id] }) : state === "failed" ? job("failed", { error_code: "MODEL_RESPONSE_INVALID", attempts: 1 }) : job("queued", { error_code: "MODEL_QUOTA_EXHAUSTED" });
 await api(page, async (route, path) => {
  if (path.endsWith("/reports") || path === "/jobs/j26") return route.fulfill({ json: value });
  if (path === "/proposals/p26") return route.fulfill({ json: { ...proposal, warnings: ["EXTRACTION_ITEMS_REJECTED"], missing_information: ["One source event requires clarification"] } });
  throw new Error(path);
 }); await submit(page);
 if (state === "empty") { await expect(page.getByRole("heading", { name: "No observations to review" })).toBeVisible(); await expect(page.getByRole("status")).toContainText("No reviewable observations"); }
 else if (state === "partial") { await page.getByRole("button", { name: /Open review queue/ }).click(); await expect(page.getByText("One source event requires clarification")).toBeVisible(); await expect(page.getByLabel("EXTRACTION_ITEMS_REJECTED")).not.toBeChecked(); await expect(page.getByRole("button", { name: "Approve update" })).toBeDisabled(); }
 else if (state === "failed") { await expect(page.getByRole("heading", { name: "Could not complete" })).toBeVisible(); await expect(page.getByRole("alert")).toContainText("invalid response"); await expect(page.getByRole("button", { name: "Retry failed job" })).toBeEnabled(); await expect(page.getByRole("button", { name: /Open review queue/ })).toHaveCount(0); }
 else { await expect(page.getByRole("heading", { name: "Processing report" })).toBeVisible(); await expect(page.getByRole("alert")).toContainText("The model provider quota is exhausted. Wait for the provider reset before starting a new analysis."); await expect(page.getByRole("button", { name: /Open review queue/ })).toHaveCount(0); }
 await page.screenshot({ path: `${output}/state-${state}.png`, fullPage: true });
});
for (const state of ["queued", "running"]) test(`FLOW14 refresh reconnect preserves ${state} without resubmitting`, async ({ page }) => {
 let submissions = 0, failed = false, complete = false, polls = 0;
 await api(page, async (route, path) => {
  if (path.endsWith("/reports")) { submissions++; return route.fulfill({ status: 202, json: job(state) }); }
  if (path === "/jobs/j26") { polls++; if (failed) return route.abort("failed"); return route.fulfill({ json: job(complete ? "ready_for_review" : state) }); }
  throw new Error(path);
 }); await submit(page); await expect(page.getByRole("heading", { name: "Processing report" })).toBeVisible(); await page.reload(); await expect(page.getByRole("heading", { name: "Processing report" })).toBeVisible();
 failed = true; await expect(page.getByRole("alert")).toContainText("Retrying automatically", { timeout: 10000 }); failed = false; complete = true;
 await expect(page.getByRole("heading", { name: "No observations to review" })).toBeVisible({ timeout: 10000 }); await expect(page.getByRole("alert")).toHaveCount(0); expect(submissions).toBe(1); expect(polls).toBeGreaterThanOrEqual(3);
});
