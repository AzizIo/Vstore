import { defineConfig, devices } from "@playwright/test";

const isCI = Boolean(process.env.CI);
const appUrl = process.env.VITE_TONCONNECT_APP_URL ?? "https://viltara-e2e.example";
const manifestUrl = process.env.VITE_TONCONNECT_MANIFEST_URL
  ?? "https://viltara-e2e.example/tonconnect-manifest.json";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: isCI ? 2 : undefined,
  timeout: 30_000,
  expect: {
    timeout: 8_000,
  },
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  outputDir: "test-results",
  use: {
    baseURL: "http://127.0.0.1:5173",
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
    command: "npm run dev -- --host 127.0.0.1 --port 5173",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !isCI,
    timeout: 60_000,
    env: {
      VITE_TONCONNECT_APP_URL: appUrl,
      VITE_TONCONNECT_MANIFEST_URL: manifestUrl,
    },
  },
});
