import { expect, test } from "@playwright/test";

test("fixture reviewer can approve a report and inspect progress", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Review field progress with evidence." })).toBeVisible();
  await page.getByRole("button", { name: /Sign in/ }).click();

  await expect(page.getByRole("heading", { name: "Bring in a field report" })).toBeVisible();
  await page.getByLabel("Paste report text").fill("Area A: erected three spools on line 24-XX.");
  await page.getByRole("button", { name: /Create review job/ }).click();
  await expect(page.getByRole("heading", { name: "Ready for review" })).toBeVisible();
  await page.getByRole("button", { name: /Open review queue/ }).click();

  await expect(page.getByRole("heading", { name: "Check one observation before it changes progress" })).toBeVisible();
  await expect(page.getByText("Three spools erected on the stated line.")).toBeVisible();
  await page.getByRole("button", { name: "Approve update" }).click();
  await expect(page.getByText(/EVIDENCE REVIEW .* APPROVED/)).toBeVisible();

  await page.getByRole("button", { name: "Finish review" }).click();
  await expect(page.getByRole("heading", { name: "Review queue complete" })).toBeVisible();
  await page.getByRole("button", { name: "Approved progress" }).click();
  await expect(page.getByRole("heading", { name: "Activity-level progress, with its history." })).toBeVisible();
  await expect(page.getByText("Erect spools on line 24-XX")).toBeVisible();
  await expect(page.getByText("25%", { exact: true })).toBeVisible();
});

test("fixture schedule import validates and stages a native source", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: /Sign in/ }).click();
  await page.getByRole("button", { name: "Import schedule" }).click();
  await page.locator('input[type="file"]').first().setInputFiles({ name: "demo.xer", mimeType: "text/plain", buffer: Buffer.from("SCHEDULE\n") });
  await page.getByRole("button", { name: "Read schedule source" }).click();
  await expect(page.getByRole("heading", { name: "PROJECT", exact: true })).toBeVisible();
  await page.getByLabel("Find activity").fill("101717");
  await expect(page.getByText("1 of 1 activities shown")).toBeVisible();
  await page.getByLabel("Work type").selectOption("welding");
  await page.getByLabel("Area").fill("Area A");
  await page.getByLabel(/Asset tags/).fill("24-XX; 24-YY");
  await page.getByLabel("Measurement basis").selectOption("quantity_ratio");
  await page.getByLabel("Planned quantity").fill("12");
  await page.getByLabel("Unit").selectOption("spool");
  await page.getByLabel("Baseline quantity").fill("0");
  await page.getByLabel("Find activity").fill("missing task");
  await expect(page.getByText("0 of 1 activities shown")).toBeVisible();
  await page.getByLabel("Find activity").fill("");
  expect(await page.getByRole("button", { name: "Sign out" }).evaluate(element => element.getBoundingClientRect().right <= window.innerWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/import-390.png", fullPage: true });
  await page.getByLabel("Reviewer reason").fill("Verified source project and baseline against the imported schedule.");
  await page.getByRole("button", { name: "Validate mapping" }).click();
  await expect(page.getByRole("alert")).toHaveText("Confirm a source project, baseline date and reviewer mapping reason.");
  await page.getByLabel("Baseline date").fill("2026-09-19");
  await page.getByRole("button", { name: "Validate mapping" }).click();
  await page.getByRole("button", { name: /Stage schedule/ }).click();
  await expect(page.getByText("Staged version is not active until you explicitly activate it.")).toBeVisible();
});
