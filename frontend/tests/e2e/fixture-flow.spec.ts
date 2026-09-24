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

  await page.getByRole("button", { name: "Next proposal" }).click();
  await page.getByRole("button", { name: "Approved progress" }).click();
  await expect(page.getByRole("heading", { name: "Activity-level progress, with its history." })).toBeVisible();
  await expect(page.getByText("Erect spools on line 24-XX")).toBeVisible();
  await expect(page.getByText("25%", { exact: true })).toBeVisible();
});

test("fixture schedule import validates and stages a native source", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Sign in/ }).click();
  await page.getByRole("button", { name: "Import schedule" }).click();
  await page.locator('input[type="file"]').first().setInputFiles({ name: "demo.xer", mimeType: "text/plain", buffer: Buffer.from("SCHEDULE\n") });
  await page.getByRole("button", { name: "Read schedule source" }).click();
  await expect(page.getByText("PROJECT")).toBeVisible();
  await page.getByLabel("Reviewer reason").fill("Verified source project and baseline against the imported schedule.");
  await page.getByRole("button", { name: "Validate mapping" }).click();
  await page.getByRole("button", { name: /Stage schedule/ }).click();
  await expect(page.getByText("Staged version is not active until you explicitly activate it.")).toBeVisible();
});
