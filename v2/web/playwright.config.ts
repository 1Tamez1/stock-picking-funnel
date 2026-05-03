import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  workers: 1,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  webServer: process.env.PLAYWRIGHT_NO_WEBSERVER
    ? undefined
    : [
        {
          command: "../scripts/run_api_playwright.sh",
          url: process.env.PLAYWRIGHT_API_URL || "http://127.0.0.1:8212/api/health",
          reuseExistingServer: true,
          timeout: 180_000,
        },
        {
          command: "../scripts/run_web_playwright.sh",
          url: process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3000",
          reuseExistingServer: true,
          timeout: 180_000,
        },
      ],
});
