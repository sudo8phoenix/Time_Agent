import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";
import { mkdirSync, writeFileSync } from "node:fs";

// This suite uses a separate migrated PostgreSQL database and a reachable real model.
// No API routes are intercepted. Run with LIFECYCLE_LIVE=1 and an API on port 8000.
test.skip(process.env.LIFECYCLE_LIVE !== "1", "Requires a live API, worker, private model and isolated database");
test.setTimeout(900_000);

test("quantity-free lifecycle through login, schedule, model, review, refresh and export", async ({ page }) => {
  const root = resolve(process.cwd(), "..");
  const username = `l04live_${randomUUID().slice(0, 12)}`;
  const password = `Lifecycle-${randomUUID()}!`;
  const evidence: Record<string, unknown> = { fixture: "developer synthetic", started_at: new Date().toISOString() };
  await page.goto("/");
  await page.getByRole("button", { name: /New here/ }).click();
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password").fill(password);
  await page.getByRole("button", { name: /Create account/ }).click();
  await expect(page.getByRole("heading", { name: "Bring in a field report" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: /Sign in/ }).click();
  await expect(page.getByRole("heading", { name: "Bring in a field report" })).toBeVisible();
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  const csrf = me.csrf_token as string;
  const project = (await (await page.request.get("/api/v1/projects")).json()).items[0];
  const headers = { "X-CSRF-Token": csrf };
  evidence.project_id = project.id;
  const columns = ["activity_id", "activity_name", "wbs_path", "discipline", "work_type", "area", "asset_tags", "is_leaf", "measurement_basis", "planned_quantity", "unit", "planned_start", "planned_finish", "baseline_date", "baseline_quantity", "actual_start", "actual_finish", "aliases"];
  const row = ["F-01-EXC", "Excavation at Foundation F-01", "FOUNDATION / F-01", "civil", "excavation", "F-01", "F-01", "true", "unsupported", "", "", "2026-10-01", "2026-10-31", "2026-10-01", "", "", "", "excavate foundation F-01"];
  const csv = `${columns.join(",")}\n${row.join(",")}\n`;
  const stagedResponse = await page.request.post(`/api/v1/projects/${project.id}/schedules`, { headers, multipart: { upload: { name: "lifecycle-development.csv", mimeType: "text/csv", buffer: Buffer.from(csv) } } });
  expect(stagedResponse.ok(), await stagedResponse.text()).toBeTruthy();
  const staged = await stagedResponse.json();
  expect(staged.state).toBe("staged");
  const activatedResponse = await page.request.post(`/api/v1/projects/${project.id}/schedules/${staged.version}/activate`, { headers, data: { expected_active_version: null } });
  expect(activatedResponse.ok(), await activatedResponse.text()).toBeTruthy();
  evidence.schedule_version_id = staged.id;
  await page.reload();

  const processReport = async (text: string, reportDate: string) => {
    await page.getByRole("button", { name: "Report intake" }).click();
    await page.getByLabel("Paste report text").fill(text);
    await page.getByLabel("Report date", { exact: true }).fill(reportDate);
    const submitted = page.waitForResponse(response => response.url().endsWith(`/projects/${project.id}/reports`) && response.request().method() === "POST");
    await page.getByRole("button", { name: /Create review job/ }).click();
    const report = await (await submitted).json();
    execFileSync(resolve(root, ".venv/bin/python"), [resolve(root, "ops/run_worker.py"), "--once"],
      { cwd: root, env: { ...process.env, PYTHONPATH: "backend" }, timeout: 360_000, stdio: "pipe" });
    const status = await (await page.request.get(`/api/v1/jobs/${report.job_id}`)).json();
    expect(status.state, JSON.stringify(status)).toBe("ready_for_review");
    expect(status.proposal_ids.length, JSON.stringify(status)).toBeGreaterThan(0);
    evidence[`job_${reportDate}`] = { ...status, report_id: report.report_id };
    return status.proposal_ids[0] as string;
  };

  const startId = await processReport("Started excavation at Foundation F-01 at 08:30.", "2026-10-09");
  const startProposal = await (await page.request.get(`/api/v1/proposals/${startId}`)).json();
  expect(startProposal.proposed_effects.event_type).toBe("actual_start");
  expect(startProposal.proposed_effects.endpoint.local_time).toMatch(/^08:30/);
  await page.getByRole("button", { name: /Open review queue/ }).click();
  await expect(page.getByText("actual start", { exact: true }).first()).toBeVisible();
  if (startProposal.warnings.length) {
    for (const warning of startProposal.warnings) await page.getByLabel(warning).check();
    await page.getByLabel(/Review reason/).fill("Verified the quoted clock time against the source report.");
    await page.getByRole("button", { name: "Revise", exact: true }).click();
  }
  await page.getByRole("button", { name: "Approve update" }).click();
  await expect(page.getByText(/EVIDENCE REVIEW .* APPROVED/)).toBeVisible();
  await page.getByRole("button", { name: "Approved progress" }).click();
  await expect(page.getByText("2026-10-09 08:30", { exact: false }).first()).toBeVisible();
  let progress = await (await page.request.get(`/api/v1/projects/${project.id}/progress`)).json();
  const item = progress.items.find((entry: { external_id: string }) => entry.external_id === "F-01-EXC");
  expect(item.actual_start).toBe("2026-10-09");
  expect(item.physical_percent).toBeNull();
  evidence.start_state = { actual_start: item.actual_start, actual_start_time: item.actual_start_time, precision: item.actual_start_precision };

  const finishId = await processReport("Finished excavation at Foundation F-01.", "2026-10-10");
  const finishProposal = await (await page.request.get(`/api/v1/proposals/${finishId}`)).json();
  expect(finishProposal.proposed_effects.event_type).toBe("actual_finish");
  expect(finishProposal.proposed_effects.endpoint.precision).toBe("date");
  await page.getByRole("button", { name: /Open review queue/ }).click();
  if (finishProposal.warnings.length) {
    for (const warning of finishProposal.warnings) await page.getByLabel(warning).check();
    await page.getByLabel(/Review reason/).fill("Verified the date-only endpoint against the source report.");
    await page.getByRole("button", { name: "Revise", exact: true }).click();
  }
  await page.getByRole("button", { name: "Approve update" }).click();
  await page.getByRole("button", { name: "Approved progress" }).click();
  await page.reload();
  progress = await (await page.request.get(`/api/v1/projects/${project.id}/progress`)).json();
  const completed = progress.items.find((entry: { external_id: string }) => entry.external_id === "F-01-EXC");
  expect(completed.actual_finish).toBe("2026-10-10");
  expect(completed.actual_finish_time).toBeNull();
  expect(completed.lifecycle_status).toBe("completed");
  expect(completed.physical_percent).toBeNull();
  evidence.finish_state = { actual_finish: completed.actual_finish, precision: completed.actual_finish_precision, status: completed.lifecycle_status };
  const exported = await (await page.request.get(`/api/v1/projects/${project.id}/exports/approved.csv`)).text();
  expect(exported).toContain("endpoint_precision");
  expect(exported).toContain("actual_finish");
  expect(exported).toContain("date");
  const duplicate = await page.request.post(`/api/v1/projects/${project.id}/reports`, { headers, data: { text: "Finished excavation at Foundation F-01.", report_date: "2026-10-10", report_date_evidence: "Reviewer-entered report date" } });
  expect(duplicate.ok()).toBeTruthy();
  expect((await duplicate.json()).existing).toBeTruthy();
  evidence.duplicate = "deduplicated by report ingestion";
  const beforeConflictCount = completed.approved_event_count;
  const beforeConflictRevision = completed.state_revision;
  const conflictId = await processReport("Started excavation at Foundation F-01 at 07:45 on 2026-10-08.", "2026-10-08");
  const conflictProposal = await (await page.request.get(`/api/v1/proposals/${conflictId}`)).json();
  expect(conflictProposal.proposed_effects.event_type).toBe("actual_start");
  await page.getByRole("button", { name: /Open review queue/ }).click();
  if (conflictProposal.warnings.length) {
    for (const warning of conflictProposal.warnings) await page.getByLabel(warning).check();
    await page.getByLabel(/Review reason/).fill("Verified the source quote; the conflicting accepted start still requires review.");
    await page.getByRole("button", { name: "Revise", exact: true }).click();
  }
  const rejected = page.waitForResponse(response => response.url().endsWith("/approve") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Approve update" }).click();
  const approvalResponse = await rejected;
  expect(approvalResponse.status()).toBe(422);
  const approvalError = await approvalResponse.json();
  expect(approvalError.detail.code).toBe("CONFLICTING_EFFECT");
  const attemptedProposalId = new URL(approvalResponse.url()).pathname.split("/").at(-2);
  expect(attemptedProposalId).toBeTruthy();
  const afterConflict = await (await page.request.get(`/api/v1/projects/${project.id}/progress`)).json();
  const unchanged = afterConflict.items.find((entry: { external_id: string }) => entry.external_id === "F-01-EXC");
  expect(unchanged.actual_start).toBe("2026-10-09");
  expect(unchanged.actual_finish).toBe("2026-10-10");
  expect(unchanged.state_revision).toBe(beforeConflictRevision);
  expect(unchanged.approved_event_count).toBe(beforeConflictCount);
  evidence.conflict = { extracted_proposal_id: conflictId, attempted_proposal_id: attemptedProposalId,
    approval_status: approvalResponse.status(), approval_error_code: approvalError.detail.code,
    before: { actual_start: completed.actual_start, actual_finish: completed.actual_finish,
      state_revision: beforeConflictRevision, approved_event_count: beforeConflictCount },
    after: { actual_start: unchanged.actual_start, actual_finish: unchanged.actual_finish,
      state_revision: unchanged.state_revision, approved_event_count: unchanged.approved_event_count } };
  mkdirSync(resolve(root, "frontend/test-results"), { recursive: true });
  writeFileSync(resolve(root, "frontend/test-results/lifecycle-live-run.json"), JSON.stringify(evidence, null, 2));
});
