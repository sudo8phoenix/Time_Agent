import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) test(`audited reanalysis at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const project = { id: "project-1", name: "Reanalysis fixture", active_schedule_version_id: "schedule-1" };
  let submitted: Record<string, unknown> | undefined;
  const run = (id: string) => ({ job_id: id, project_id: project.id, report_id: "report-1", state: "ready_for_review", stage: "persist", proposal_count: 0, proposal_ids: [], ...(id === "j2" ? { parent_job_id: "j1", reanalysis_reason: "Recheck model extraction" } : {}) });
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === "/auth/me") return route.fulfill({ status: 401, json: {} });
    if (path === "/auth/login") return route.fulfill({ json: { csrf_token: "csrf", user: { id: "u1", role: "reviewer", username: "reviewer" } } });
    if (path === "/projects") return route.fulfill({ json: { items: [project] } });
    if (path === "/projects/project-1/reports/report-1/reanalysis") {
      submitted = route.request().postDataJSON();
      expect(route.request().headers()["x-csrf-token"]).toBe("csrf");
      return route.fulfill({ status: 202, json: run("j2") });
    }
    if (path.endsWith("/reports") || path === "/jobs/j1") return route.fulfill({ json: run("j1") });
    if (path === "/jobs/j2") return route.fulfill({ json: run("j2") });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto("/");
  await page.getByLabel("Username").fill("reviewer");
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.getByRole("button", { name: /Sign in/ }).click();
  await page.getByLabel("Paste report text").fill("Started excavation on 2026-10-02");
  await page.getByRole("button", { name: /Create review job/ }).click();
  await expect(page.getByRole("button", { name: "Create reanalysis run" })).toBeDisabled();
  await page.getByLabel("Reason for reanalysis").fill("Recheck model extraction");
  await page.getByRole("button", { name: "Create reanalysis run" }).click();
  await expect(page.getByText(/Previous run:/)).toContainText("j1");
  expect(submitted?.reason).toBe("Recheck model extraction");
  expect(submitted?.idempotency_key).toBeTruthy();
  await page.screenshot({ path: `../docs/validation/e01-reanalysis-${width}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  expect(errors).toEqual([]);
});
