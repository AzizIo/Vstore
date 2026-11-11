import { defineConfig, devices } from "@playwright/test";

const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./e2e/api-backed",
  testMatch: "**/*.api.pw.ts",
  fullyParallel: false,
  forbidOnly: isCI,
  retries: 0,
  workers: 1,
  timeout: 45_000,
  expect: {
    timeout: 10_000,
  },
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report-api-backed", open: "never" }],
  ],
  outputDir: "test-results-api-backed",
  use: {
    baseURL: "http://127.0.0.1:5173",
    // Traces can capture Authorization headers and signed Telegram initData.
    trace: "off",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 15_000,
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5173",
    url: "http://127.0.0.1:5173",
    // Never attach to a stale local Vite process with an unknown API proxy.
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      VITE_API_PROXY_TARGET: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
      VITE_TONCONNECT_APP_URL: "https://viltara-e2e.example",
      VITE_TONCONNECT_MANIFEST_URL: "",
    },
  },
});
