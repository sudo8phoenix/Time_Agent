import { expect, test } from "@playwright/test";

test("restores session, saves drafts, isolates projects and confirms logout", async ({ page }) => {
  const projects = ["one", "two"].map(id => ({ id, name: `Project ${id}`, timezone: "UTC", active_schedule_version_id: null }));
  let authenticated = true, logoutFails = true;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === "/auth/me") return route.fulfill(authenticated ? { json: { id: "user", username: "reviewer", role: "reviewer", csrf_token: "csrf" } } : { status: 401, json: { detail: "Invalid or expired session" } });
    if (path === "/auth/login") { authenticated = true; return route.fulfill({ json: { csrf_token: "csrf", user: { id: "user", username: "reviewer", role: "reviewer" } } }); }
    if (path === "/projects") return route.fulfill({ json: { items: projects } });
    if (path === "/auth/logout") { if (logoutFails) return route.fulfill({ status: 503, json: { detail: "Server unavailable" } }); authenticated = false; return route.fulfill({ status: 204 }); }
    if (path.endsWith("/progress")) return route.fulfill(authenticated ? { json: { project_id: "one", project_name: "Project one", schedule_version: 1, counts: { activities: 0, approved_events: 0, pending_review: 0 }, items: [], notice: "Approved progress" } } : { status: 401, json: { detail: "Invalid or expired session" } });
    throw new Error(`Unexpected request ${path}`);
  });
  page.on("dialog", dialog => dialog.accept());
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Bring in a field report" })).toBeVisible();
  await page.getByLabel("Paste report text").fill("Saved report for project one");
  await page.getByLabel("Active project").selectOption("two");
  await expect(page.getByLabel("Paste report text")).toHaveValue("");
  await page.getByLabel("Active project").selectOption("one");
  await expect(page.getByLabel("Paste report text")).toHaveValue("Saved report for project one");
  await page.reload();
  await expect(page.getByLabel("Paste report text")).toHaveValue("Saved report for project one");
  await page.locator('input[type="file"]').setInputFiles({ name: "report.txt", mimeType: "text/plain", buffer: Buffer.from("uploaded report") });
  await page.getByRole("button", { name: "Remove file and use text" }).click();
  await expect(page.getByLabel("Paste report text")).toHaveValue("Saved report for project one");
  authenticated = false;
  await page.getByRole("button", { name: "Approved progress" }).click();
  await expect(page.getByText(/Your session ended/)).toBeVisible();
  await page.getByLabel("Username").fill("reviewer");
  await page.getByLabel("Password", { exact: true }).fill("password");
  await page.getByRole("button", { name: /Sign in →/ }).click();
  await page.getByRole("button", { name: "Report intake" }).click();
  await expect(page.getByLabel("Paste report text")).toHaveValue("Saved report for project one");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Sign out could not be confirmed");
  await expect(page.getByRole("button", { name: "Report intake" })).toBeVisible();
  logoutFails = false;
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("button", { name: /Sign in →/ })).toBeVisible();
});

for (const width of [320, 768, 1024, 1440]) {
  test(`login fits viewport at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/v1/auth/me", route => route.fulfill({ status: 401, json: { detail: "Authentication required" } }));
    await page.goto("/");
    await expect(page.getByRole("button", { name: /Sign in →/ })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole("button", { name: "Show password" }).click();
    await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("type", "text");
    await page.screenshot({ path: `test-results/login-${width}.png`, fullPage: true });
  });
}

test("recovers a stale CSRF token and reopens a job after refresh", async ({ page }) => {
  let token = "old-csrf", rejected = false, submissions = 0;
  const project = { id: "one", name: "Project one", timezone: "UTC", active_schedule_version_id: "schedule" };
  const job = { job_id: "job-1", project_id: "one", state: "ready_for_review", stage: "persist", proposal_count: 0, proposal_ids: [] };
  await page.route("**/api/v1/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace("/api/v1", "");
    if (path === "/auth/me") return route.fulfill({ json: { id: "user", username: "reviewer", role: "reviewer", csrf_token: token } });
    if (path === "/projects") return route.fulfill({ json: { items: [project] } });
    if (path === "/projects/one/reports") {
      if (!rejected) { rejected = true; token = "new-csrf"; return route.fulfill({ status: 403, json: { detail: "CSRF validation failed" } }); }
      expect(request.headers()["x-csrf-token"]).toBe("new-csrf"); submissions++;
      return route.fulfill({ status: 202, json: job });
    }
    if (path === "/jobs/job-1") return route.fulfill({ json: job });
    throw new Error(`Unexpected request ${path}`);
  });
  await page.goto("/");
  await page.getByLabel("Paste report text").fill("Recoverable report");
  await page.getByRole("button", { name: /Create review job/ }).click();
  await expect(page.getByRole("heading", { name: "No observations to review" })).toBeVisible();
  expect(submissions).toBe(1);
  await page.reload();
  await expect(page.getByRole("heading", { name: "No observations to review" })).toBeVisible();
  await page.getByRole("button", { name: "Report intake" }).click();
  await expect(page.getByLabel("Paste report text")).toHaveValue("");
  await page.getByRole("button", { name: /Open job/ }).click();
  await expect(page.getByRole("heading", { name: "No observations to review" })).toBeVisible();
});

test("signing out updates another open tab", async ({ context }) => {
  let authenticated = true;
  await context.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === "/auth/me") return route.fulfill(authenticated ? { json: { id: "user", username: "reviewer", role: "reviewer", csrf_token: "csrf" } } : { status: 401, json: { detail: "Authentication required" } });
    if (path === "/projects") return route.fulfill({ json: { items: [{ id: "one", name: "Project one", timezone: "UTC", active_schedule_version_id: null }] } });
    if (path === "/auth/logout") { authenticated = false; return route.fulfill({ status: 204 }); }
    throw new Error(`Unexpected request ${path}`);
  });
  const first = await context.newPage(), second = await context.newPage();
  await first.goto("/"); await second.goto("/");
  await expect(first.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(second.getByRole("button", { name: "Sign out" })).toBeVisible();
  await first.getByRole("button", { name: "Sign out" }).click();
  await expect(first.getByRole("button", { name: /Sign in →/ })).toBeVisible();
  await expect(second.getByRole("button", { name: /Sign in →/ })).toBeVisible();
});

test("late progress responses cannot appear under another project", async ({ page }) => {
  let release: (() => void) | undefined;
  const projects = ["one", "two"].map(id => ({ id, name: `Project ${id}`, timezone: "UTC", active_schedule_version_id: "schedule" }));
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === "/auth/me") return route.fulfill({ json: { id: "user", username: "reviewer", role: "reviewer", csrf_token: "csrf" } });
    if (path === "/projects") return route.fulfill({ json: { items: projects } });
    if (path === "/projects/two/progress") return route.fulfill({ status: 503, json: { detail: "Project two is unavailable" } });
    if (path === "/projects/one/progress") {
      await new Promise<void>(resolve => { release = resolve; });
      return route.fulfill({ json: { project_id: "one", project_name: "Project one", schedule_version: 1, counts: { activities: 0, approved_events: 0, pending_review: 0 }, items: [], notice: "Old project data" } });
    }
    throw new Error(`Unexpected request ${path}`);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Approved progress" }).click();
  await expect.poll(() => Boolean(release)).toBe(true);
  await page.getByLabel("Active project").selectOption("two");
  await page.getByRole("button", { name: "Approved progress" }).click();
  await expect(page.getByRole("alert")).toHaveText("Project two is unavailable");
  const response = page.waitForResponse("**/projects/one/progress"); release!(); await response;
  await expect(page.getByText("Old project data")).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveText("Project two is unavailable");
});
