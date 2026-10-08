import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  test(`review revisions, rejection, approval and queue completion at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const project = { id: "project-1", name: "Review test", timezone: "UTC", active_schedule_version_id: "schedule-1" };
    const makeProposal = (id: string, activity: string) => ({
      id, revision: 1, current_activity_revision: 0, review_state: "pending",
      mapping_state: "suggested", match_strength: "review", chosen_activity_id: activity,
      observation: { summary: `Observation ${id}`, quantity: id === "p1" ? null : "2", unit: id === "p1" ? null : "spool", work_type: "pipe_spool_erection", area: "A", tags: [] },
      evidence: [{ quote: "Installed 2 spools today.", locator: "paragraph:1", fragment_id: "fragment-1" }],
      candidates: [{ id: activity, name: `Install ${activity}`, area: "A", work_type: "pipe_spool_erection", tags: [], rank: 1 }],
      warnings: [] as string[], missing_information: [],
      proposed_effects: { quantity: id === "p1" ? null : "2", unit: id === "p1" ? null : "spool", quantity_semantics: id === "p1" ? "none" : "delta", event_type: "actual_progress", effective_date: "2026-09-25" },
    });
    const proposals = new Map([['p1', makeProposal("p1", "a1")], ['p2', makeProposal("p2", "a2")]]);
    proposals.get("p1")!.warnings = ["Date needs confirmation"];
    let queue = ["p1", "p2"];
    const mutations: string[] = [];
    const job = () => ({ job_id: "job-1", project_id: project.id, state: "ready_for_review", stage: "persist", proposal_count: 2, proposal_ids: queue });
    await page.route("**/api/v1/**", async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace("/api/v1", "");
      const method = request.method();
      if (path === "/auth/login") return route.fulfill({ json: { csrf_token: "test-csrf" } });
      if (path === "/projects") return route.fulfill({ json: { items: [project] } });
      if (path === `/projects/${project.id}/reports`) {
        expect(request.postDataJSON()).toMatchObject({ text: "Installed 2 spools today.", report_date: "2026-09-25", report_date_evidence: "Reviewer-entered report date" });
        return route.fulfill({ status: 202, json: job() });
      }
      if (path === "/jobs/job-1") return route.fulfill({ json: job() });
      const match = path.match(/^\/proposals\/([^/]+)(?:\/(revise|approve|reject))?$/);
      if (match) {
        const [, id, action] = match;
        const proposal = proposals.get(id)!;
        if (method === "GET") return route.fulfill({ json: proposal });
        expect(request.headers()["x-csrf-token"]).toBe("test-csrf");
        const body = request.postDataJSON();
        expect(body.expected_proposal_revision).toBe(proposal.revision);
        expect(proposal.review_state).toBe("pending");
        mutations.push(`${id}/${action}`);
        if (action === "revise") {
          expect(body.reason).toBe("Verified date and quantity");
          expect(body.field_changes.proposed_effects).toMatchObject({ quantity: "3", unit: "spool", quantity_semantics: "delta" });
          proposal.review_state = "superseded";
          const revised = { ...proposal, id: "p1-r2", revision: 2, review_state: "pending", warnings: [],
            proposed_effects: { ...proposal.proposed_effects, ...body.field_changes.proposed_effects } };
          proposals.set(revised.id, revised);
          queue = queue.map(value => value === id ? revised.id : value);
          return route.fulfill({ json: revised });
        }
        if (action === "reject") {
          expect(body.reason).toBe("Duplicate observation");
          proposal.review_state = "rejected";
        } else {
          expect(id).toBe("p2");
          expect(body.expected_activity_revision).toBe(0);
          proposal.review_state = "approved";
        }
        queue = queue.filter(value => value !== id);
        return route.fulfill({ json: { review_state: proposal.review_state, state_revision: 1 } });
      }
      throw new Error(`Unexpected API call: ${method} ${path}`);
    });
    await page.goto("/");
    await page.getByLabel("Username").fill("reviewer");
    await page.getByLabel("Password").fill("test-password");
    await page.getByRole("button", { name: /Sign in/ }).click();
    await page.getByLabel("Paste report text").fill("Installed 2 spools today.");
    await page.getByLabel("Report date", { exact: true }).fill("2026-09-25");
    await page.getByRole("button", { name: /Create review job/ }).click();
    await page.getByRole("button", { name: /Open review queue/ }).click();
    await expect(page.getByText("Observation p1", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve update" })).toBeDisabled();
    await expect(page.getByText("A measured quantity is required for a progress update.")).toBeVisible();
    await expect(page.getByText("A measured unit is required for a progress update.")).toBeVisible();
    await expect(page.getByText(/Submit an amended report with the quantity/)).toBeVisible();
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await expect(page.getByRole("alert")).toHaveText("Add a reason before rejecting.");
    expect(mutations).toEqual([]);
    await page.getByLabel("Date needs confirmation").check();
    await page.getByLabel(/Correct proposed quantity/).fill("done");
    await page.getByLabel(/Review reason/).fill("Verified date and quantity");
    await page.getByRole("button", { name: "Revise", exact: true }).click();
    await expect(page.getByRole("alert")).toHaveText("Quantity must be a finite, non-negative number.");
    await page.getByLabel(/Correct proposed quantity/).fill("3");
    await page.getByLabel(/Correct unit/).selectOption("spool");
    await page.getByLabel(/Quantity meaning/).selectOption("delta");
    await page.getByRole("button", { name: "Revise", exact: true }).click();
    await expect(page.getByLabel(/Correct proposed quantity/)).toHaveValue("");
    await expect(page.getByRole("button", { name: "Approve update" })).toBeEnabled();
    await page.getByRole("button", { name: /Back to job/ }).click();
    await page.getByRole("button", { name: /Open review queue/ }).click();
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeEnabled();
    await page.getByLabel(/Review reason/).fill("Duplicate observation");
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("REJECTED");
    await page.getByRole("button", { name: /Next proposal/ }).click();
    await expect(page.getByText("Observation p2", { exact: true })).toBeVisible();
    await expect(page.getByLabel(/Review reason/)).toHaveValue("");
    await expect(page.getByLabel("Schedule candidate")).toHaveValue("a2");
    await expect(page.getByRole("button", { name: "Approve update" })).toBeEnabled();
    await page.screenshot({ path: `test-results/review-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Approve update" }).click();
    await expect(page.getByRole("status")).toContainText("APPROVED");
    await page.getByRole("button", { name: "Finish review" }).click();
    await expect(page.getByRole("heading", { name: "Review queue complete" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Open review queue/ })).toHaveCount(0);
    expect(mutations).toEqual(["p1/revise", "p1-r2/reject", "p2/approve"]);
    expect(errors).toEqual([]);
  });
}
