import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) test(`planner search beyond shortlist and subactivity review at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const project = { id: "project-1", name: "Planner fixture", active_schedule_version_id: "schedule-1" };
  let proposal: Record<string, any> = { id: "p1", revision: 1, current_activity_revision: 0,
    review_state: "pending", mapping_state: "unmatched", match_strength: "unresolved", chosen_activity_id: null,
    observation: { summary: "Finished east trench", quantity: null, unit: null, work_type: "excavation", area: "Site", tags: [] },
    evidence: [{ quote: "Finished east trench on 2026-10-02", locator: "line 1", fragment_id: "f1" }],
    candidates: [], warnings: [], missing_information: [],
    proposed_effects: { event_type: "actual_finish", scope: "subactivity", subactivity_key: "east trench",
      effective_date: "2026-10-02", endpoint: { local_date: "2026-10-02", precision: "date", local_time: null },
      evidence: [{ fields: ["scope", "subactivity_key", "endpoint"], fragment_id: "f1", quote: "Finished east trench on 2026-10-02" }] } };
  const candidate = { id: "a8", external_id: "EXC-F8", name: "Excavation F8", area: "F8", wbs: "Site.F8", work_type: "excavation", tags: [], rank: 0 };
  let approved = false;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === "/auth/me") return route.fulfill({ status: 401, json: {} });
    if (path === "/auth/login") return route.fulfill({ json: { csrf_token: "csrf", user: { id: "u1", role: "reviewer", username: "planner" } } });
    if (path === "/projects") return route.fulfill({ json: { items: [project] } });
    if (path.endsWith("/reports") || path === "/jobs/j1") return route.fulfill({ json: { job_id: "j1", project_id: project.id, state: "ready_for_review", stage: "persist", proposal_count: 1, proposal_ids: approved ? [] : [proposal.id] } });
    if (path.endsWith("/activities")) return route.fulfill({ json: { total: 1, items: [candidate] } });
    if (path.endsWith("/revise")) {
      const body = route.request().postDataJSON();
      expect(body.chosen_activity_id).toBe("a8"); expect(body.reason).toBe("Reviewed east trench mapping");
      proposal = { ...proposal, id: "p2", revision: 2, mapping_state: "suggested", chosen_activity_id: "a8", candidates: [candidate], proposed_effects: { ...proposal.proposed_effects, scheduled_parent_id: "a8" } };
      return route.fulfill({ json: proposal });
    }
    if (path.endsWith("/approve")) { approved = true; return route.fulfill({ json: { activity_id: "a8" } }); }
    if (path === "/proposals/p1" || path === "/proposals/p2") return route.fulfill({ json: proposal });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto("/");
  await page.getByLabel("Username").fill("planner");
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.getByRole("button", { name: /Sign in/ }).click();
  await expect(page.getByText("Ready for intake", { exact: true })).toBeVisible();
  await page.getByLabel("Paste report text").fill("Finished east trench on 2026-10-02");
  await page.getByRole("button", { name: /Create review job/ }).click();
  await page.getByRole("button", { name: /Open review queue/ }).click();
  await expect(page.getByRole("button", { name: "Approve update" })).toBeDisabled();
  await page.getByLabel("Search the pinned schedule").fill("F8");
  await page.getByRole("button", { name: "Search activities" }).click();
  await page.getByRole("button", { name: /EXC-F8 · Excavation F8/ }).click();
  await page.getByLabel("Review reason").fill("Reviewed east trench mapping");
  await page.getByRole("button", { name: "Revise", exact: true }).click();
  await expect(page.getByLabel("Schedule candidate")).toHaveValue("a8");
  await expect(page.getByLabel("Reviewed scope")).toHaveValue("subactivity");
  await expect(page.getByText(/Scheduled parent: Excavation F8/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve update" })).toBeEnabled();
  await page.screenshot({ path: `../docs/validation/m01-m02-review-${width}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.getByRole("button", { name: "Approve update" }).click();
  await expect(page.getByRole("button", { name: "Approve update" })).toBeDisabled();
  expect(errors).toEqual([]);
});
