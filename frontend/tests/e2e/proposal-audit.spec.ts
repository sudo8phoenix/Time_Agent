import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) test(`confidence and decision history at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const project = { id: "project-1", name: "Audit developer fixture", active_schedule_version_id: "schedule-1" };
  const confidence = { score: null, method: "not_estimated", version: "v1", validation_status: "unavailable" };
  const proposal = { id: "p1", revision: 1, current_activity_revision: 0,
    review_state: "pending", mapping_state: "suggested", match_strength: "strong", chosen_activity_id: "a1",
    observation: { summary: "Started excavation", quantity: null, unit: null, work_type: "excavation", area: "F8", tags: [] },
    evidence: [{ quote: "Started excavation on 2026-10-02", locator: "line 1", fragment_id: "f1" }],
    candidates: [{ id: "a1", name: "Excavation F8", area: "F8", work_type: "excavation", tags: [], rank: 1 }],
    warnings: [], missing_information: [], proposed_effects: { event_type: "actual_start", scope: "whole_activity",
      effective_date: "2026-10-02", endpoint: { local_date: "2026-10-02", precision: "date", local_time: null } },
    provenance: { capture_status: "recorded", confidence: { extraction: confidence, linking: confidence },
      source: { report_id: "report-1", schedule_version_id: "schedule-1", report_hash: "f".repeat(64) },
      original_fields: { summary: "Original started excavation" }, original_selection: { candidate_id: "a1" },
      validation: { status: "requires_authorized_review" }, model_metadata: { model: "developer-fixture" } },
    decision_history: { scope: "report_job", proposals: [], events: [], decisions: [{ id: "d1", action: "revise",
      actor_id: "reviewer-1", timestamp: "2026-10-02T09:00:00Z", reason: "Reviewed the source date",
      before: { effects: { effective_date: null } }, after: { effects: { effective_date: "2026-10-02" } } }] } };
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === "/auth/me") return route.fulfill({ status: 401, json: {} });
    if (path === "/auth/login") return route.fulfill({ json: { csrf_token: "csrf", user: { id: "u1", role: "reviewer", username: "reviewer" } } });
    if (path === "/projects") return route.fulfill({ json: { items: [project] } });
    if (path.endsWith("/reports") || path === "/jobs/j1") return route.fulfill({ json: { job_id: "j1", project_id: project.id, state: "ready_for_review", stage: "persist", proposal_count: 1, proposal_ids: [proposal.id] } });
    if (path === "/proposals/p1") return route.fulfill({ json: proposal });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto("/");
  await page.getByLabel("Username").fill("reviewer");
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.getByRole("button", { name: /Sign in/ }).click();
  await expect(page.getByText("Ready for intake", { exact: true })).toBeVisible();
  await page.getByLabel("Paste report text").fill("Started excavation on 2026-10-02");
  await page.getByRole("button", { name: /Create review job/ }).click();
  await page.getByRole("button", { name: /Open review queue/ }).click();
  const audit = page.getByRole("region", { name: "Confidence and decision history" });
  await expect(audit.getByText("Extraction confidence", { exact: true })).toBeVisible();
  await expect(audit.getByText("Unavailable · unavailable", { exact: true })).toHaveCount(2);
  await audit.getByText("Original extraction, link decision and source", { exact: true }).click();
  await expect(audit.getByText(/Original started excavation/)).toBeVisible();
  await audit.getByText("Decision history for this report", { exact: true }).click();
  await expect(audit.getByText("Reviewed the source date", { exact: true })).toBeVisible();
  await audit.getByText("Before and after", { exact: true }).click();
  await expect(audit.getByText(/"before"/)).toBeVisible();
  await page.screenshot({ path: `../docs/validation/a01-audit-${width}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  expect(errors).toEqual([]);
});
