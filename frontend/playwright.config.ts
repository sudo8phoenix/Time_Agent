import { defineConfig, devices } from "@playwright/test";

const liveBaseURL = process.env.LIVE_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  reporter: process.env.CI ? "dot" : "list",
  use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:4173" },
  projects: [
    { name: "fixtures", testMatch: "**/fixture-flow.spec.ts" },
    { name: "lifecycle-conflict", testMatch: "**/lifecycle-conflict-live.spec.ts", use: { baseURL: liveBaseURL } },
    { name: "lifecycle-live", testMatch: "**/lifecycle-live.spec.ts", use: { baseURL: liveBaseURL } },
    { name: "conversation-live", testMatch: "**/conversation-live.spec.ts", use: { baseURL: liveBaseURL } },
    { name: "review-api", testMatch: ["**/batch26-critical-flow.spec.ts", "**/conversation-durable.spec.ts", "**/agent-run-status.spec.ts", "**/reanalysis.spec.ts", "**/execution-history.spec.ts", "**/flexible-intake.spec.ts", "**/proposal-audit.spec.ts", "**/review-api.spec.ts", "**/planner-scope.spec.ts", "**/outbox-status.spec.ts", "**/session-recovery.spec.ts", "**/workflow-safeguards.spec.ts"], use: { baseURL: "http://127.0.0.1:4174" } },
  ],
  webServer: process.env.CONVERSATION_LIVE === "1" || process.env.LIFECYCLE_LIVE === "1" ? [] : [{
    command: "VITE_FIXTURE_MODE=true npm run dev -- --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  }, {
    command: "VITE_FIXTURE_MODE=false npm run dev -- --host 127.0.0.1 --port 4174",
    url: "http://127.0.0.1:4174",
    reuseExistingServer: false,
  }],
});
