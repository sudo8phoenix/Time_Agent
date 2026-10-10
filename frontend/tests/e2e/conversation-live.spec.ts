import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

test.skip(process.env.CONVERSATION_LIVE !== "1", "Requires isolated PostgreSQL API and configured live model");
test.setTimeout(900_000);

test("supervisor multi-event confirmation survives refresh until reviewer acceptance", async ({ page }) => {
  const root = resolve(process.cwd(), "..");
  const suffix = randomUUID().slice(0, 10);
  const reviewer = `t02review_${suffix}`;
  const supervisor = `t02super_${suffix}`;
  const password = `Conversation-${randomUUID()}!`;
  await page.goto("http://127.0.0.1:8000/");
  await page.getByRole("button", { name: /New here/ }).click();
  await page.getByLabel("Username").fill(reviewer);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password").fill(password);
  await page.getByRole("button", { name: /Create account/ }).click();
  await expect(page.getByRole("heading", { name: "Bring in a field report" })).toBeVisible();
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  const csrf = me.csrf_token as string;
  const project = me.projects[0];
  const columns = ["activity_id", "activity_name", "wbs_path", "discipline", "work_type", "area", "asset_tags", "is_leaf", "measurement_basis", "planned_quantity", "unit", "planned_start", "planned_finish", "baseline_date", "baseline_quantity", "actual_start", "actual_finish", "aliases"];
  const rows = [
    ["F01-EXC", "Excavation at F-01", "FOUNDATION / F-01", "civil", "excavation", "F-01", "F-01", "true", "unsupported", "", "", "2026-10-01", "2026-10-31", "2026-10-01", "", "", "", "excavation F-01"],
    ["F02-EXC", "Excavation at F-02", "FOUNDATION / F-02", "civil", "excavation", "F-02", "F-02", "true", "unsupported", "", "", "2026-10-01", "2026-10-31", "2026-10-01", "", "", "", "excavation F-02"],
  ];
  const csv = [columns.join(","), ...rows.map(row => row.join(","))].join("\n") + "\n";
  const stagedResponse = await page.request.post(`/api/v1/projects/${project.id}/schedules`, { headers: { "X-CSRF-Token": csrf }, multipart: { upload: { name: "conversation-live.csv", mimeType: "text/csv", buffer: Buffer.from(csv) } } });
  expect(stagedResponse.ok(), await stagedResponse.text()).toBeTruthy();
  const staged = await stagedResponse.json();
  const activated = await page.request.post(`/api/v1/projects/${project.id}/schedules/${staged.version}/activate`, { headers: { "X-CSRF-Token": csrf }, data: { expected_active_version: null } });
  expect(activated.ok(), await activated.text()).toBeTruthy();
  const setup = `from app.db.session import session_factory
from app.db.models import User, ProjectMembership
from app.db.passwords import hash_password
from uuid import UUID
with session_factory.begin() as db:
 u=User(username=${JSON.stringify(supervisor)}, password_hash=hash_password(${JSON.stringify(password)}), role='viewer')
 db.add(u); db.flush()
 db.add(ProjectMembership(project_id=UUID(${JSON.stringify(project.id)}), user_id=u.id))`;
  execFileSync(resolve(root, ".venv/bin/python"), ["-c", setup], { cwd: root, env: { ...process.env, PYTHONPATH: "backend" } });
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Username").fill(supervisor);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: /Sign in/ }).click();
  await page.getByRole("button", { name: "Text log" }).click();
  await page.getByRole("button", { name: "New conversation" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("Message").focus();
  await expect(page.getByLabel("Message")).toBeFocused();
  await page.getByLabel("Message").fill("On 9 October 2026, excavation at F-01 started at 08:30. Excavation at F-02 finished at 16:15 on 9 October 2026.");
  await page.getByLabel("Known report date (optional)").fill("2026-10-09");
  const analyzed = page.waitForResponse(response => response.url().endsWith("/messages") && response.request().method() === "POST", { timeout: 600_000 });
  await page.getByRole("button", { name: "Send", exact: true }).click();
  const analyzedBody = await (await analyzed).json();
  expect(analyzedBody.events, JSON.stringify(analyzedBody)).toHaveLength(2);
  await page.reload();
  await page.getByRole("button", { name: "Text log" }).click();
  await expect(page.locator(".time-event-card")).toHaveCount(2, { timeout: 30000 });
  await page.locator(".time-event-card").first().getByLabel("Date", { exact: true }).fill("2026-10-09");
  await page.locator(".time-event-card").first().getByLabel("Time (optional)").fill("08:35");
  const corrected = page.waitForResponse(response => response.url().endsWith("/edit") && response.request().method() === "POST");
  await page.locator(".time-event-card").first().getByRole("button", { name: "Save correction" }).click();
  expect((await (await corrected).json()).events[0].effect.endpoint.local_time).toBe("08:35:00");
  await page.reload();
  await page.getByRole("button", { name: "Text log" }).click();
  await expect(page.locator(".time-event-card").first()).toContainText("08:35");
  const conversationId = (await (await page.request.get(`/api/v1/projects/${project.id}/conversations`)).json()).items[0].id;
  const confirmation = page.waitForResponse(response => response.url().endsWith("/confirm") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Confirm and send for review" }).click();
  expect((await (await confirmation).json()).status).toBe("pending_review");
  await page.reload();
  await page.getByRole("button", { name: "Text log" }).click();
  await expect(page.getByText("Confirmed and awaiting reviewer acceptance.")).toBeVisible();
  const pending = await (await page.request.get(`/api/v1/projects/${project.id}/conversations/${conversationId}`)).json();
  expect(pending.status).toBe("pending_review");
  expect(pending.proposal_ids).toHaveLength(2);
  const supervisorMe = await (await page.request.get("/api/v1/auth/me")).json();
  const stale = await page.request.post(`/api/v1/projects/${project.id}/conversations/${conversationId}/confirm`, { headers: { "X-CSRF-Token": supervisorMe.csrf_token }, data: { expected_revision: pending.revision - 1 } });
  expect(stale.status()).toBe(409);
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Username").fill(reviewer);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: /Sign in/ }).click();
  await expect(page.getByRole("heading", { name: "Bring in a field report" })).toBeVisible();
  const reviewerMe = await (await page.request.get("/api/v1/auth/me")).json();
  for (const id of pending.proposal_ids) {
    let proposal = await (await page.request.get(`/api/v1/proposals/${id}`)).json();
    expect(proposal.review_state).toBe("pending");
    if (proposal.warnings.length) {
      const revision = await page.request.post(`/api/v1/proposals/${id}/revise`, { headers: { "X-CSRF-Token": reviewerMe.csrf_token }, data: { expected_proposal_revision: proposal.revision, chosen_activity_id: proposal.chosen_activity_id, field_changes: { resolve_warnings: proposal.warnings }, reason: "Verified the quoted source clock against the event endpoint." } });
      expect(revision.ok(), await revision.text()).toBeTruthy();
      proposal = await revision.json();
    }
    const response = await page.request.post(`/api/v1/proposals/${proposal.id}/approve`, { headers: { "X-CSRF-Token": reviewerMe.csrf_token }, data: { expected_proposal_revision: proposal.revision, expected_activity_revision: 0, idempotency_key: randomUUID() } });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Username").fill(supervisor);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: /Sign in/ }).click();
  await page.getByRole("button", { name: "Text log" }).click();
  await expect(page.getByText("Accepted by a reviewer.")).toBeVisible();
});
