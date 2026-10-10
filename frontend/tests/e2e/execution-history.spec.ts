import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) test(`execution history filters, evidence and honest durations at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  let sawFilter = false;
  await page.route("**/api/v1/**", async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ status: 401, json: {} });
    if (path.endsWith("/auth/login")) return route.fulfill({ json: { csrf_token: "csrf", user: { id: "u1", username: "planner", role: "reviewer" } } });
    if (path.endsWith("/projects")) return route.fulfill({ json: { items: [{ id: "p1", name: "History fixture", active_schedule_version_id: "v1" }] } });
    if (path.endsWith("/progress")) return route.fulfill({ json: { project_id: "p1", schedule_version: 1, counts: { activities: 1, approved_events: 2, pending_review: 0 }, notice: "Developer fixture", items: [{ activity_id: "a1", external_id: "EXC-01", name: "Excavation", wbs: "Site", completed_quantity: "0", planned_quantity: null, unit: null, physical_percent: null, actual_start: "2026-10-02", actual_start_precision: "date", lifecycle_status: "in_progress", approved_event_count: 2, history: [] }] } });
    if (path.endsWith("/history")) {
      sawFilter ||= url.searchParams.get("blocker") === "access" && url.searchParams.get("active_only") === "true";
      return route.fulfill({ json: { total: 1, next_offset: null, items: [{ event_id: "e1", activity_id: "a1", activity_external_id: "EXC-01", activity_name: "Excavation", discipline: "civil", work_type: "excavation", wbs: "Site", status: "active", correction_status: "correction", event_type: "blocker", work_date: "2026-10-02", scope: null, blocker: "Waiting for access", blocker_category: "access", accepted_values: { blocker: "Waiting for access" }, latest_activity_state: { actual_start: "2026-10-02" }, source_locator: "page:1", provenance: { source: { original_url: "/api/v1/projects/p1/reports/r1/original" } }, evidence: [{ quote: "Waiting for access at excavation", locator: "page:1" }], confidence: { extraction: { score: null, validation_status: "unavailable" } }, decisions: [] }] } });
    }
    if (path.endsWith("/blockers")) return route.fulfill({ json: { items: [{ category: "access", count: 1 }] } });
    if (path.endsWith("/durations")) return route.fulfill({ json: { next_offset: null, items: [{ activity_id: "a1", activity_external_id: "EXC-01", work_type: "excavation", elapsed: { status: "available", basis: "date_span", date_span_days: 3, elapsed_seconds: null }, calendar_working: { reason: "reviewed_versioned_calendar_definition_unavailable" }, labour_productivity: { reason: "measured_compatible_labour_data_unavailable" } }] } });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto("/");
  await page.getByLabel("Username").fill("planner");
  await page.getByLabel("Password", { exact: true }).fill("fixture");
  await page.getByRole("button", { name: /Sign in/ }).click();
  await page.getByRole("button", { name: "Approved progress", exact: true }).click();
  const history = page.getByRole("region", { name: "Execution history", exact: true });
  await expect(history.getByText("1 matching events")).toBeVisible();
  await expect(history.getByText(/3 days between reported dates; clock hours unknown/)).toBeVisible();
  await expect(history.getByText(/Crew-hour productivity: unavailable/)).toBeVisible();
  await history.getByRole("button", { name: /access: 1/ }).click();
  await expect.poll(() => sawFilter).toBeTruthy();
  await expect(history.getByRole("link", { name: "Open original evidence" })).toHaveAttribute("href", /\/reports\/r1\/original/);
  await history.getByText("Accepted event values", { exact: true }).click();
  await expect(history.locator("pre").first()).toContainText("Waiting for access");
  await history.getByRole("combobox", { name: /^Activity/ }).selectOption("a1");
  await history.getByRole("button", { name: "Apply history filters" }).click();
  await expect(history.getByText("1 matching events")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: `../docs/validation/h01-history-${width}.png`, fullPage: true });
  expect(errors).toEqual([]);
});
