import { expect, test } from "@playwright/test";
const project = { id: "one", name: "North utility works", timezone: "UTC", active_schedule_version_id: "schedule" };
const proposal = { id: "p1", revision: 1, current_activity_revision: 0, review_state: "pending", mapping_state: "suggested", match_strength: "review", chosen_activity_id: "activity", chosen_activity_measurement_basis: "manual_physical", observation: { summary: "Cable installation is halfway complete.", quantity: null, unit: null, work_type: "cable_laying", area: "North", tags: [] }, evidence: [{ quote: "Cable installation 50% complete on 2026-10-09.", locator: "Paragraph 1", fragment_id: "fragment" }], candidates: [{ id: "activity", name: "Install cables", area: "North", work_type: "cable_laying", tags: [], rank: 1 }], warnings: [], missing_information: [], proposed_effects: { reported_percent: null, effective_date: "2026-10-09" } };

async function base(page: import("@playwright/test").Page, handler: (route: import("@playwright/test").Route, path: string) => Promise<void>, role = "reviewer", active = true) {
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === "/auth/me") return route.fulfill({ json: { id: "user", username: "reviewer", role, csrf_token: "csrf" } });
    if (path === "/projects") return route.fulfill({ json: { items: [{ ...project, active_schedule_version_id: active ? "schedule" : null }, { ...project, id: "two", name: "South utility works" }] } });
    return handler(route, path);
  });
}

test("pending submission locks inputs and project navigation", async ({ page }) => {
  let release: (() => void) | undefined;
  await base(page, async (route, path) => {
    if (path.endsWith("/reports")) { await new Promise<void>(resolve => { release = resolve; }); return route.fulfill({ status: 202, json: { job_id: "job", project_id: "one", state: "ready_for_review", proposal_count: 0, proposal_ids: [] } }); }
    throw new Error(path);
  });
  await page.goto("/"); await page.getByLabel("Paste report text").fill("Original report");
  await page.getByRole("button", { name: /Create review job/ }).click();
  await expect.poll(() => !!release).toBe(true);
  await expect(page.getByLabel("Paste report text")).toBeDisabled();
  await expect(page.getByLabel("Report date", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("Active project")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeDisabled();
  release!(); await expect(page.getByRole("heading", { name: "No observations to review" })).toBeVisible();
});

test("missing schedule directs intake to import and viewer sees only permitted actions", async ({ page }) => {
  await base(page, async (route, path) => { throw new Error(path); }, "reviewer", false);
  await page.goto("/");
  await expect(page.getByRole("button", { name: /Create review job/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Go to schedule import" })).toBeVisible();
  await page.unroute("**/api/v1/**");
  await base(page, async (route, path) => {
    if (path.endsWith("/progress")) return route.fulfill({ json: { project_id: "one", project_name: project.name, schedule_version: 1, counts: { activities: 0, approved_events: 0, pending_review: 1 }, items: [], notice: "Approved progress" } });
    throw new Error(path);
  }, "viewer");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Activity-level progress, with its history." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Import schedule" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Report intake" })).toHaveCount(0);
  await page.getByLabel("Active project").selectOption("two");
  await expect(page.getByRole("button", { name: /Create review job/ })).toHaveCount(0);
});

test("durable history paginates and queue supports percentage revision", async ({ page }) => {
  let revision = 1, effects: Record<string, unknown> = { ...proposal.proposed_effects };
  await base(page, async (route, path) => {
    if (path === "/jobs") {
      const params = new URL(route.request().url()).searchParams;
      return route.fulfill({ json: { items: [{ job_id: "job", project_id: "one", state: "ready_for_review", report_name: params.get("offset") === "25" ? "Older report" : "Daily report", created_at: "2026-10-09T09:00:00Z", pending_count: 1, proposal_count: 1 }], next_offset: params.get("offset") === "25" ? null : 25 } });
    }
    if (path === "/jobs/job") return route.fulfill({ json: { job_id: "job", project_id: "one", state: "ready_for_review", proposal_ids: ["p1"], proposal_count: 1 } });
    if (path === "/proposals/p1") return route.fulfill({ json: { ...proposal, revision, proposed_effects: effects } });
    if (path === "/proposals/p1/revise") { const body = route.request().postDataJSON(); expect(body.field_changes.proposed_effects.reported_percent).toBe("50"); revision++; effects = { ...effects, reported_percent: "50" }; return route.fulfill({ json: { ...proposal, revision, proposed_effects: effects } }); }
    throw new Error(path);
  });
  await page.goto("/"); await page.getByRole("button", { name: "Job history" }).click();
  await expect(page.getByRole("heading", { name: "Daily report" })).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Older report" })).toBeVisible();
  await page.getByRole("button", { name: "Review queue", exact: true }).click();
  await page.screenshot({ path: "test-results/queue-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "Review proposals →" }).click();
  await expect(page.getByRole("button", { name: "Approve update" })).toBeDisabled();
  await page.getByLabel(/Correct reported percent/).fill("50");
  await page.getByLabel(/Review reason/).fill("Confirmed against source");
  await page.getByRole("button", { name: "Revise", exact: true }).click();
  await expect(page.getByRole("button", { name: "Approve update" })).toBeEnabled();
});

test("saved import refreshes staging information and CSV shows row errors", async ({ page }) => {
  const old = { id: "import", revision: 1, state: "ready", source_format: "p6_xer", selected_source_project_id: "source", staged_schedule_version_id: null, preview: { projects: [{ source_project_id: "source", name: "Imported schedule" }], tasks: [], wbs: [], relationships: [], issues: [] } };
  await page.addInitScript(record => { sessionStorage.setItem("spa-draft:user:import:one:record", JSON.stringify(record)); }, old);
  await base(page, async (route, path) => {
    if (path.endsWith("/progress")) return route.fulfill({ json: { schedule_version: 1 } });
    if (path.endsWith("/schedule-imports/import")) return route.fulfill({ json: { ...old, revision: 2, state: "staged", staged_schedule_version_id: "staged", schedule_version_id: "staged", version: 2 } });
    if (path.endsWith("/schedules")) return route.fulfill({ status: 422, json: { detail: { code: "SCHEDULE_INVALID", errors: ["Row 4: planned quantity must be positive"] } } });
    throw new Error(path);
  });
  await page.goto("/"); await page.getByRole("button", { name: "Import schedule" }).click();
  await expect(page.getByRole("button", { name: "Activate staged version" })).toBeEnabled();
  await expect(page.getByLabel("Baseline date")).toBeDisabled();
  await page.locator('input[type="file"]').last().setInputFiles({ name: "invalid.csv", mimeType: "text/csv", buffer: Buffer.from("invalid") });
  await page.getByRole("button", { name: "Stage canonical CSV" }).click();
  await expect(page.getByRole("alert")).toContainText("Row 4: planned quantity must be positive");
});

test("mapping validation locks edits and refreshes conflicting imports", async ({ page }) => {
  const record = { id: "import", revision: 1, state: "needs_mapping", source_format: "p6_xer", selected_source_project_id: "source", staged_schedule_version_id: null, preview: { projects: [{ source_project_id: "source", name: "Imported schedule" }], tasks: [{ source_task_id: "task", external_id: "TASK-1", name: "Install pipe", is_summary: false, source_wbs_id: null, source_fields: {} }], wbs: [], relationships: [], issues: [] } };
  let release: (() => void) | undefined, conflict = false;
  await base(page, async (route, path) => {
    if (path.endsWith("/progress")) return route.fulfill({ json: { schedule_version: 1 } });
    if (path.endsWith("/schedule-imports")) return route.fulfill({ status: 201, json: record });
    if (path.endsWith("/mapping")) { await new Promise<void>(resolve => { release = resolve; }); conflict = true; return route.fulfill({ status: 409, json: { detail: { code: "SCHEDULE_IMPORT_CONFLICT" } } }); }
    if (path.endsWith("/schedule-imports/import") && conflict) return route.fulfill({ json: { ...record, revision: 2, state: "ready", reviewed_mapping: { baseline_date: "2026-10-01", reason: "Updated by another reviewer", task_overrides: { task: { area: "Latest area" } } } } });
    throw new Error(path);
  });
  await page.goto("/"); await page.getByRole("button", { name: "Import schedule" }).click();
  await page.locator('input[type="file"]').first().setInputFiles({ name: "schedule.xer", mimeType: "text/plain", buffer: Buffer.from("schedule") });
  await page.getByRole("button", { name: "Read schedule source" }).click();
  await page.getByLabel("Baseline date").fill("2026-10-02"); await page.getByLabel("Reviewer reason").fill("Original mapping");
  await page.getByRole("button", { name: "Validate mapping" }).click();
  await expect.poll(() => !!release).toBe(true);
  await expect(page.getByLabel("Baseline date")).toBeDisabled();
  await expect(page.getByLabel("Area", { exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Stage schedule →" })).toBeDisabled();
  release!();
  await expect(page.getByLabel("Area", { exact: true })).toHaveValue("Latest area");
  await expect(page.getByLabel("Reviewer reason")).toHaveValue("Updated by another reviewer");
  await expect(page.getByRole("alert")).toContainText("latest version has been loaded");
});

for (const width of [320, 768, 1024, 1440]) {
  test(`workspace fits ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await base(page, async (route, path) => {
      if (path === "/jobs") return route.fulfill({ json: { items: [{ job_id: "job", project_id: "one", report_name: "Daily progress report for the northern utility installation", state: "ready_for_review", pending_count: 2, created_at: "2026-10-09T09:00:00Z" }], next_offset: null } });
      throw new Error(path);
    });
    await page.goto("/");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/intake-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Review queue", exact: true }).click();
    await expect(page.getByRole("button", { name: "Review proposals →" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/queue-${width}.png`, fullPage: true });
  });
}
