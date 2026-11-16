import { defineConfig, devices } from "@playwright/test";

const isCI = Boolean(process.env.CI);
const appUrl = process.env.VITE_TONCONNECT_APP_URL ?? "https://viltara-escrow-e2e.example";

export default defineConfig({
  testDir: "./e2e-escrow",
  testMatch: "**/*.pw.ts",
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: isCI ? 1 : undefined,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report-escrow", open: "never" }],
  ],
  outputDir: "test-results-escrow",
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5174",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: !isCI,
    timeout: 60_000,
    env: {
      VITE_TONCONNECT_APP_URL: appUrl,
      VITE_TONCONNECT_MANIFEST_URL: "",
      VITE_ESCROW_TESTNET_ENABLED: "true",
    },
  },
});
