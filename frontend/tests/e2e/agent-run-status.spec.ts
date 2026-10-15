import { expect, test, type Page, type Route } from "@playwright/test";

const project = { id: "p1", name: "Agent status fixture", timezone: "UTC", active_schedule_version_id: "schedule-1" };
const jobId = "job-1";
const safeCounters = { node_executions: 4, extraction_calls: 2, selection_calls: 1, corrective_retries: 1 };

function status(state: string, overrides: Record<string, unknown> = {}) {
  const terminal = ["ready_for_review", "failed", "stale", "cancelled"].includes(state);
  return {
    id: "run-1", job_id: jobId, graph_version: "report-analysis-v1", framework_version: "fixture",
    state, current_stage: state === "failed" ? "Failed" : state === "stale" ? "Stale" : state === "ready_for_review" ? "Ready for review" : "Selecting supported matches",
    counters: safeCounters,
    steps: [
      { ordinal: 1, node: "load_context", label: "Loading context", state: "succeeded", attempt: 1, duration_ms: 18, error_code: null },
      { ordinal: 2, node: "repair_extraction", label: "Extracting observations", state: "succeeded", attempt: 2, duration_ms: 1250, error_code: null },
      { ordinal: 3, node: "select", label: "Selecting supported matches", state: "running", attempt: 1, duration_ms: null, error_code: null },
    ],
    error_code: state === "failed" ? "AGENT_INTERNAL_ERROR" : null,
    error_message: state === "failed" ? "SAFE SERVER MESSAGE" : null,
    started_at: "2026-10-12T08:00:00Z", updated_at: "2026-10-12T08:00:03Z",
    completed_at: terminal ? "2026-10-12T08:00:05Z" : null,
    ...overrides,
  };
}

function job(state = "running", id = jobId, agentRunAvailable = true) {
  return { job_id: id, project_id: project.id, state, stage: "extract", proposal_count: 0, proposal_ids: [], agent_run_available: agentRunAvailable };
}

async function baseApi(route: Route, path: string, currentJobState = "running", runAvailable = true): Promise<boolean> {
  if (path === "/auth/me") await route.fulfill({ status: 401, json: { detail: "Authentication required" } });
  else if (path === "/auth/login") await route.fulfill({ json: { csrf_token: "csrf", user: { id: "user-1", username: "reviewer", role: "reviewer" } } });
  else if (path === "/projects") await route.fulfill({ json: { items: [project] } });
  else if (path === `/projects/${project.id}/reports`) await route.fulfill({ status: 202, json: job(currentJobState, jobId, runAvailable) });
  else if (path === `/jobs/${jobId}`) await route.fulfill({ json: job(currentJobState, jobId, runAvailable) });
  else return false;
  return true;
}

async function enterJob(page: Page) {
  await page.goto("/");
  await page.getByLabel("Username").fill("reviewer");
  await page.getByLabel("Password", { exact: true }).fill("password");
  await page.getByRole("button", { name: /Sign in/ }).click();
  await page.getByLabel("Paste report text").fill("A synthetic report for the status display.");
  await page.getByRole("button", { name: /Create review job/ }).click();
  await expect(page.locator(".job-header")).toBeVisible({ timeout: 10000 });
}

for (const width of [390, 1440]) test(`running agent details are bounded and fit at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 950 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  let polls = 0;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === `/jobs/${jobId}/agent-run`) { polls += 1; return route.fulfill({ json: status("running") }); }
    const common = await baseApi(route, path);
    if (common) return common;
    throw new Error(`Unexpected API request ${path}`);
  });
  await enterJob(page);
  await expect(page.getByRole("status").filter({ hasText: "Selecting supported matches" })).toBeVisible();
  await expect(page.getByText("Attempt 2 · 1.3 s")).toBeVisible();
  await expect(page.getByText("Correction retries").locator(".." )).toContainText("1");
  await expect(page.getByText("repair_extraction")).toHaveCount(0);
  await expect(page.getByText("AGENT_INTERNAL_ERROR")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(polls).toBe(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `../docs/validation/agent-status-${width}.png`, fullPage: true });
});

for (const [state, expected] of [["failed", "Failed"], ["stale", "Stale"], ["ready_for_review", "Ready for review"]] as const) {
  test(`terminal ${state} shows public status and stops polling`, async ({ page }) => {
    let polls = 0;
    await page.route("**/api/v1/**", async route => {
      const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
      if (path === `/jobs/${jobId}/agent-run`) { polls += 1; return route.fulfill({ json: status(state) }); }
      const common = await baseApi(route, path, "ready_for_review");
      if (common) return common;
      throw new Error(`Unexpected API request ${path}`);
    });
    await enterJob(page);
    await expect(page.getByText(expected, { exact: true }).first()).toBeVisible();
    if (state === "failed") await expect(page.getByText("The analysis could not complete. Review the job status and retry if available.")).toBeVisible();
    await expect(page.getByText("SAFE SERVER MESSAGE")).toHaveCount(0);
    await page.waitForTimeout(2200);
    expect(polls).toBe(1);
  });
}

test("historical terminal job without a trace hides the status panel without polling", async ({ page }) => {
  let polls = 0;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === `/jobs/${jobId}/agent-run`) { polls += 1; throw new Error("A job without a run must not request trace details"); }
    const common = await baseApi(route, path, "ready_for_review", false);
    if (common) return common;
    throw new Error(`Unexpected API request ${path}`);
  });
  await enterJob(page);
  await expect(page.getByRole("heading", { name: "Agent run" })).toHaveCount(0);
  expect(polls).toBe(0);
  await expect(page.getByRole("heading", { name: "No observations to review" })).toBeVisible();
});

test("queued graph job waits until parent status reports a trace", async ({ page }) => {
  let polls = 0, parentChecks = 0;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === `/jobs/${jobId}/agent-run`) { polls += 1; return route.fulfill({ json: status("running") }); }
    if (path === `/projects/${project.id}/reports`) return route.fulfill({ status: 202, json: job("queued", jobId, false) });
    if (path === `/jobs/${jobId}`) {
      parentChecks += 1;
      return route.fulfill({ json: job("queued", jobId, parentChecks > 1) });
    }
    const common = await baseApi(route, path, "queued", false);
    if (common) return common;
    throw new Error(`Unexpected API request ${path}`);
  });
  await enterJob(page);
  await expect(page.getByText("Waiting for agent status…")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Selecting supported matches" })).toBeVisible({ timeout: 7000 });
  expect(parentChecks).toBeGreaterThan(1);
  expect(polls).toBe(1);
});

test("active job retries bounded 404 and then shows fixed unavailable copy", async ({ page }) => {
  test.setTimeout(15000);
  let polls = 0;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === `/jobs/${jobId}/agent-run`) { polls += 1; return route.fulfill({ status: 404, json: { detail: "private diagnostic" } }); }
    const common = await baseApi(route, path);
    if (common) return common;
    throw new Error(`Unexpected API request ${path}`);
  });
  await enterJob(page);
  await expect(page.getByText("Waiting for agent status…")).toBeVisible();
  await expect.poll(() => polls, { timeout: 12500 }).toBe(6);
  await expect(page.getByText("Agent run details are not available right now.")).toBeVisible();
  await expect(page.getByText("private diagnostic")).toHaveCount(0);
});

test("offline errors use fixed copy and a manual retry recovers", async ({ page }) => {
  let polls = 0;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === `/jobs/${jobId}/agent-run`) {
      polls += 1;
      if (polls < 3) return route.fulfill({ status: 503, json: { detail: "secret prompt and token" } });
      return route.fulfill({ json: status("ready_for_review") });
    }
    const common = await baseApi(route, path, "ready_for_review");
    if (common) return common;
    throw new Error(`Unexpected API request ${path}`);
  });
  await enterJob(page);
  await expect(page.getByText("Connection interrupted. Agent status will be checked again.")).toBeVisible();
  await expect(page.getByText("secret prompt and token")).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect.poll(() => polls).toBe(2);
  await expect(page.getByText("Connection interrupted. Agent status will be checked again.")).toBeVisible();
  await page.getByRole("button", { name: "Check again" }).focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => polls).toBe(3);
  await expect(page.getByText("Ready for review", { exact: true }).first()).toBeVisible();
});

test("unrecognized server labels never reach the page", async ({ page }) => {
  const hostile = "raw prompt: never render this";
  const malformedSafe = status("running", { current_stage: hostile, steps: [{ ordinal: 1, node: hostile, label: hostile, state: "running", attempt: 1, duration_ms: null, error_code: null }] });
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === `/jobs/${jobId}/agent-run`) return route.fulfill({ json: malformedSafe });
    const common = await baseApi(route, path);
    if (common) return common;
    throw new Error(`Unexpected API request ${path}`);
  });
  await enterJob(page);
  await expect(page.getByText(hostile)).toHaveCount(0);
  await expect(page.getByText("Analysis in progress", { exact: true })).toBeVisible();
});

test("changing jobs prevents a late prior run response from appearing", async ({ page }) => {
  let releaseOld: (() => void) | undefined;
  let oldResponseStarted: (() => void) | undefined;
  const responseStarted = new Promise<void>(resolve => { oldResponseStarted = resolve; });
  let reports = 0;
  await page.route("**/api/v1/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace("/api/v1", "");
    if (path === `/jobs/${jobId}/agent-run`) {
      oldResponseStarted?.();
      await new Promise<void>(resolve => { releaseOld = resolve; });
      try { return await route.fulfill({ json: status("running", { job_id: jobId, current_stage: "Loading context" }) }); } catch { return; }
    }
    if (path === "/auth/me") return route.fulfill({ status: 401, json: { detail: "Authentication required" } });
    if (path === "/auth/login") return route.fulfill({ json: { csrf_token: "csrf", user: { id: "user-1", username: "reviewer", role: "reviewer" } } });
    if (path === "/projects") return route.fulfill({ json: { items: [project] } });
    if (path === `/projects/${project.id}/reports`) { reports += 1; return route.fulfill({ status: 202, json: job("running", `job-${reports}`) }); }
    if (path.endsWith("/agent-run")) return route.fulfill({ json: status("running", { job_id: path.split("/")[2], current_stage: "Stale", steps: [] }) });
    if (path.startsWith("/jobs/job-")) return route.fulfill({ json: job("running", path.split("/")[2]) });
    throw new Error(`Unexpected API request ${path}`);
  });
  await page.goto("/");
  await page.getByLabel("Username").fill("reviewer");
  await page.getByLabel("Password", { exact: true }).fill("password");
  await page.getByRole("button", { name: /Sign in/ }).click();
  await page.getByLabel("Paste report text").fill("First report");
  await page.getByRole("button", { name: /Create review job/ }).click();
  await expect(page.getByRole("heading", { name: "Agent run" })).toBeVisible();
  await responseStarted;
  await page.getByRole("button", { name: "Report intake" }).click();
  await page.getByLabel("Paste report text").fill("Second report");
  await page.getByRole("button", { name: /Create review job/ }).click();
  await expect(page.getByText("Stale", { exact: true }).first()).toBeVisible();
  releaseOld?.();
  await page.waitForTimeout(150);
  await expect(page.getByText("Loading context", { exact: true })).toHaveCount(0);
});

for (const width of [390, 1440]) test(`v2 task lineage and budgets fit at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 950 });
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === `/jobs/${jobId}/agent-run`) return route.fulfill({ json: status("running", {
      graph_version: "report-analysis-v2", current_stage: "Analyzing report",
      tasks: [
        { id: "root", parent_task_id: null, role: "root", status: "running", attempt: 1, outcome: null },
        { id: "analysis", parent_task_id: "root", role: "analysis", status: "running", attempt: 1, outcome: null },
        { id: "matching", parent_task_id: "analysis", role: "matching", status: "running", attempt: 1, outcome: null },
        { id: "selection", parent_task_id: "matching", role: "selection", status: "succeeded", attempt: 2, outcome: "unresolved" },
      ],
      hierarchy_usage: { delegations: 4, supervisor_transitions: 2, model_calls: 3, tool_calls: 5 },
    }) });
    if (await baseApi(route, path)) return;
    throw new Error(`Unexpected API request ${path}`);
  });
  await enterJob(page);
  const hierarchy = page.getByRole("list", { name: "Agent task hierarchy" });
  await expect(hierarchy).toBeVisible();
  await expect(hierarchy.getByText("Selection", { exact: true })).toBeVisible();
  await expect(hierarchy.getByText("Unresolved", { exact: true })).toBeVisible();
  await expect(hierarchy.getByText("Attempt 2")).toBeVisible();
  await expect(page.getByLabel("Hierarchy budget usage")).toContainText("3 / 806");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
