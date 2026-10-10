import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

test.skip(process.env.LIFECYCLE_LIVE !== "1" || !process.env.LIFECYCLE_SMOKE_CREDENTIALS,
  "Requires the isolated accepted lifecycle project and a live model");
test.setTimeout(720_000);

test("real-model conflicting start is rejected without changing accepted dates", async ({ page }) => {
  const root = resolve(process.cwd(), "..");
  const credentials = JSON.parse(readFileSync(process.env.LIFECYCLE_SMOKE_CREDENTIALS!, "utf8"));
  await page.goto("/");
  await page.getByLabel("Username").fill(credentials.username);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: /Sign in/ }).click();
  await expect(page.getByRole("heading", { name: "Bring in a field report" })).toBeVisible();
  const projectId = credentials.project_id as string;
  const beforeView = await (await page.request.get(`/api/v1/projects/${projectId}/progress`)).json();
  const before = beforeView.items.find((item: { external_id: string }) => item.external_id === "F-01-EXC");
  expect(before.actual_start).toBe("2026-10-09");
  expect(before.actual_finish).toBe("2026-10-10");
  const csrf = (await (await page.request.get("/api/v1/auth/me")).json()).csrf_token as string;
  await page.getByLabel("Paste report text").fill("Started excavation at Foundation F-01 at 07:45 on 2026-10-08.");
  await page.getByLabel("Report date", { exact: true }).fill("2026-10-08");
  const submitted = page.waitForResponse(response => response.url().endsWith(`/projects/${projectId}/reports`) && response.request().method() === "POST");
  await page.getByRole("button", { name: /Create review job/ }).click();
  const report = await (await submitted).json();
  let status: Record<string, any> = {};
  for (let attempt = 0; attempt < 3; attempt++) {
    execFileSync(resolve(root, ".venv/bin/python"), [resolve(root, "ops/run_worker.py"), "--once"],
      { cwd: root, env: { ...process.env, PYTHONPATH: "backend" }, timeout: 360_000, stdio: "pipe" });
    status = await (await page.request.get(`/api/v1/jobs/${report.job_id}`)).json();
    if (status.state === "ready_for_review") break;
    expect(status.state, JSON.stringify(status)).toBe("failed");
    if (attempt === 2) break;
    const retry = await page.request.post(`/api/v1/jobs/${report.job_id}/retry`, { headers: { "X-CSRF-Token": csrf } });
    expect(retry.ok(), await retry.text()).toBeTruthy();
  }
  expect(status.state, JSON.stringify(status)).toBe("ready_for_review");
  expect(status.proposal_ids.length).toBeGreaterThan(0);
  const proposalId = status.proposal_ids[0] as string;
  const proposal = await (await page.request.get(`/api/v1/proposals/${proposalId}`)).json();
  expect(proposal.proposed_effects.event_type).toBe("actual_start");
  expect(proposal.chosen_activity_id).toBe(before.activity_id);
  await page.getByRole("button", { name: /Open review queue/ }).click();
  if (proposal.warnings.length) {
    for (const warning of proposal.warnings) await page.getByLabel(warning).check();
    await page.getByLabel(/Review reason/).fill("Verified the source quote; the prior accepted start conflicts.");
    await page.getByRole("button", { name: "Revise", exact: true }).click();
  }
  const rejected = page.waitForResponse(response => response.url().endsWith("/approve") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Approve update" }).click();
  const approvalResponse = await rejected;
  expect(approvalResponse.status()).toBe(422);
  const approvalError = await approvalResponse.json();
  expect(approvalError.detail.code).toBe("CONFLICTING_EFFECT");
  const afterView = await (await page.request.get(`/api/v1/projects/${projectId}/progress`)).json();
  const after = afterView.items.find((item: { external_id: string }) => item.external_id === "F-01-EXC");
  expect(after.actual_start).toBe(before.actual_start);
  expect(after.actual_finish).toBe(before.actual_finish);
  expect(after.state_revision).toBe(before.state_revision);
  expect(after.approved_event_count).toBe(before.approved_event_count);
  const record = { project_id: projectId, report_id: report.report_id, job_id: report.job_id,
    proposal_id: proposalId, schedule_version_id: status.schedule_version_id,
    model_effect: proposal.proposed_effects, approval_status: approvalResponse.status(),
    approval_error_code: approvalError.detail.code,
    before: { actual_start: before.actual_start, actual_finish: before.actual_finish, state_revision: before.state_revision, event_count: before.approved_event_count },
    after: { actual_start: after.actual_start, actual_finish: after.actual_finish, state_revision: after.state_revision, event_count: after.approved_event_count },
    tested_at: new Date().toISOString() };
  writeFileSync("test-results/lifecycle-conflict-run.json", JSON.stringify(record, null, 2));
});
