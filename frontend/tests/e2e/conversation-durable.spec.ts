import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) test(`saved analysis survives refresh and resumes clarification at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const project = { id: "p-durable", name: "Conversation fixture", active_schedule_version_id: "s1", timezone: "UTC" };
  let authenticated = false;
  let complete = false;
  let failedPoll = false;
  let revision = 0;
  let state = "draft";
  const source = "Started excavation at F-01 at 08:30";
  const conversation = () => ({ id: "c1", revision, status: state, pending_question: complete ? "date" : null,
    question: complete ? "What date did this work happen? A time is optional." : null,
    turns: revision ? [{ ordinal: 1, role: "user", text: source }] : [], events: [], job_id: null, proposal_ids: [] });
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const method = route.request().method();
    const user = { id: "u1", username: "supervisor", role: "reviewer" };
    if (path === "/auth/me") return route.fulfill({ status: authenticated ? 200 : 401, json: authenticated ? { ...user, csrf_token: "csrf" } : {} });
    if (path === "/auth/login") { authenticated = true; return route.fulfill({ json: { user, csrf_token: "csrf" } }); }
    if (path === "/projects") return route.fulfill({ json: { items: [project] } });
    if (path.endsWith("/conversations")) return route.fulfill({ json: method === "POST" ? conversation() : { items: [conversation()] } });
    if (path.endsWith("/messages")) { state = "analyzing"; revision = 1; return route.fulfill({ json: conversation() }); }
    if (path.endsWith("/conversations/c1")) {
      if (complete && !failedPoll) { failedPoll = true; return route.abort("failed"); }
      if (complete) { state = "draft"; revision = 2; }
      return route.fulfill({ json: conversation() });
    }
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto("/");
  await page.getByLabel("Username").fill("supervisor");
  await page.getByLabel("Password", { exact: true }).fill("password");
  await page.getByRole("button", { name: /Sign in/ }).click();
  await page.getByRole("button", { name: "Text log" }).click();
  await page.getByLabel("Message", { exact: true }).fill(source);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText("Analyzing your saved message.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm and send for review" })).toHaveCount(0);
  await page.reload();
  await page.getByRole("button", { name: "Text log" }).click();
  await expect(page.getByText("Analyzing your saved message.", { exact: false })).toBeVisible();
  await expect(page.getByText(source, { exact: true })).toBeVisible();
  complete = true;
  await expect(page.getByRole("alert")).toContainText("Reconnecting automatically", { timeout: 10000 });
  await expect(page.getByText("What date did this work happen? A time is optional.")).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole("button", { name: "Confirm and send for review" })).toBeDisabled();
  await expect(page.getByLabel("Message", { exact: true })).toBeEnabled();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `../docs/validation/conversation-durable-${width}.png`, fullPage: true });
});
