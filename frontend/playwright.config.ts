import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  reporter: process.env.CI ? "dot" : "list",
  use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:4173" },
  webServer: {
    command: "VITE_FIXTURE_MODE=true npm run dev -- --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  },
});
