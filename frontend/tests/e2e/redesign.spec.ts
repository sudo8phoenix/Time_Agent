import { expect, test } from "@playwright/test";
test.use({ timezoneId: "America/Los_Angeles" });
const project = {
  id: "p",
  name: "North utility works",
  timezone: "Asia/Kolkata",
  active_schedule_version_id: "v1",
};
const items = Array.from({ length: 64 }, (_, n) => ({
  activity_id: `a${n}`,
  external_id: `PIP-${String(n).padStart(3, "0")}`,
  name:
    n === 0
      ? "Install process pipework across the northern utility corridor"
      : `Install pipework section ${n}`,
  wbs: n < 32 ? "North / Piping" : "South / Mechanical",
  planned_start:
    n === 63 ? null : `2026-10-${String(1 + (n % 15)).padStart(2, "0")}`,
  planned_finish:
    n === 63 ? null : `2026-11-${String(1 + (n % 15)).padStart(2, "0")}`,
  planned_quantity: "100",
  completed_quantity: n % 2 ? "0" : "20",
  unit: "m",
  physical_percent: n % 2 ? null : "20",
  approved_event_count: n % 2 ? 0 : 1,
  history: [],
}));
for (const width of [320, 768, 1440])
  test(`schedule is truthful, searchable and keyboard accessible at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/api/v1/**", (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/auth/me"))
        return route.fulfill({
          json: {
            id: "u",
            username: "reviewer",
            role: "reviewer",
            csrf_token: "csrf",
          },
        });
      if (path.endsWith("/projects"))
        return route.fulfill({ json: { items: [project] } });
      if (path.endsWith("/progress"))
        return route.fulfill({
          json: {
            project_id: "p",
            project_name: project.name,
            schedule_version: 3,
            counts: { activities: 64, approved_events: 32, pending_review: 5 },
            items,
            notice:
              "Per-activity values only. No overall project percentage is calculated.",
          },
        });
      throw Error(path);
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Overview", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Project overview." }),
    ).toBeVisible();
    await expect(page.getByText("64", { exact: true })).toBeVisible();
    await expect(page.locator(".gantt-bar").first()).toBeVisible();
    await expect(page.locator(".timeline-scale span").first()).toHaveText("Oct 1");
    await expect(
      page.getByRole("button", { name: "Text log", exact: true }),
    ).toHaveCount(0);
    await expect(page.getByRole("button", { name: "TimeChat" })).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.getByLabel("Timeline scale").selectOption("30");
    await expect(
      page.getByRole("button", { name: "Previous date window" }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "Next date window" }).click();
    await expect(
      page.getByRole("button", { name: "Previous date window" }),
    ).toBeEnabled();
    await page.getByLabel("Timeline scale").selectOption("0");
    await page
      .getByRole("button", { name: "North / Piping 32", exact: true })
      .click();
    await expect(
      page.getByText("Install pipework section 1", { exact: true }),
    ).toHaveCount(0);
    await page
      .getByRole("button", { name: "North / Piping 32", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Next activities", exact: true })
      .click();
    await expect(
      page.getByText("No planned date range", { exact: true }),
    ).toBeVisible();
    await page.getByLabel("Search schedule").fill("PIP-001");
    await expect(
      page.getByText("Install pipework section 1", { exact: true }),
    ).toBeVisible();
    await expect(page.locator(".gantt-bar")).toHaveCount(1);
    await page.getByRole("tab", { name: "Timeline", exact: true }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(
      page.getByRole("tab", { name: "Table", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByRole("columnheader", { name: "Planned finish" }),
    ).toBeVisible();
    await page.getByLabel("Search schedule").fill("");
    await page.getByLabel("Filter activities").selectOption("accepted");
    await expect(
      page.getByText("Install pipework section 1", { exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Use dark theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    expect(errors).toEqual([]);
  });
test("overview handles empty schedule and retries a failed read", async ({
  page,
}) => {
  let failed = true;
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me"))
      return route.fulfill({
        json: {
          id: "u",
          username: "viewer",
          role: "viewer",
          csrf_token: "csrf",
        },
      });
    if (path.endsWith("/projects"))
      return route.fulfill({ json: { items: [project] } });
    if (path.endsWith("/progress"))
      return failed
        ? route.fulfill({
            status: 503,
            json: { detail: "Schedule temporarily unavailable" },
          })
        : route.fulfill({
            json: {
              project_id: "p",
              schedule_version: 1,
              counts: { activities: 0, approved_events: 0, pending_review: 0 },
              items: [],
              notice: "Per activity only",
            },
          });
    throw Error(path);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Could not load this schedule" }),
  ).toBeVisible();
  failed = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByText("No activities are available in this version."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "New field report" }),
  ).toHaveCount(0);
});

test("report history opens the accepted audit workspace", async ({ page }) => {
  const requests: string[] = [];
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    requests.push(path);
    if (path.endsWith("/auth/me"))
      return route.fulfill({
        json: {
          id: "u",
          username: "reviewer",
          role: "reviewer",
          csrf_token: "csrf",
        },
      });
    if (path.endsWith("/projects"))
      return route.fulfill({ json: { items: [project] } });
    if (path.endsWith("/jobs"))
      return route.fulfill({ json: { items: [], next_offset: null } });
    if (path.endsWith("/progress"))
      return route.fulfill({
        json: { project_id: "p", schedule_version: 3, items },
      });
    if (path.endsWith("/history"))
      return route.fulfill({
        json: { items: [], total: 0, next_offset: null },
      });
    if (path.endsWith("/blockers") || path.endsWith("/durations"))
      return route.fulfill({ json: { items: [], next_offset: null } });
    throw Error(path);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Job history", exact: true }).click();
  await page.getByRole("tab", { name: "Accepted updates & audit" }).click();
  await expect(
    page.getByRole("heading", { name: "Execution history", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("No events match these filters.")).toBeVisible();
  expect(requests).toContain("/api/v1/projects/p/history");
  await page.getByRole("tab", { name: "Reports & processing" }).click();
  await expect(
    page.getByRole("heading", { name: "No reports yet" }),
  ).toBeVisible();
});
