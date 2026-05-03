import { expect, test } from "@playwright/test";

import { loadPrimaryReportRoute, loadSampleCompanyRoute } from "./fixture-routes";

const LIVE = process.env.PLAYWRIGHT_LIVE_HOSTED === "1";
const OWNER_EMAIL = process.env.PLAYWRIGHT_OWNER_EMAIL || "";
const OWNER_PASSWORD = process.env.PLAYWRIGHT_OWNER_PASSWORD || "";
const COMPANY_TARGET = loadSampleCompanyRoute();
const REPORT_TARGET = loadPrimaryReportRoute();

test.describe("live hosted stack", () => {
  test.skip(!LIVE, "Set PLAYWRIGHT_LIVE_HOSTED=1 to run against the local hosted validation stack.");
  test.skip(!OWNER_EMAIL || !OWNER_PASSWORD, "Set PLAYWRIGHT_OWNER_EMAIL and PLAYWRIGHT_OWNER_PASSWORD.");

  test("protects native and legacy routes behind hosted login", async ({ page, context }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);

    await page.getByLabel("Email").fill(OWNER_EMAIL);
    await page.getByLabel("Password").fill(OWNER_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    await page.goto("/__legacy/dashboard");
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expect(page.locator("iframe")).toBeVisible();

    await page.getByRole("button", { name: "Log Out" }).click();
    await expect(page).toHaveURL(/\/login/);

    await context.clearCookies();
    await page.goto("/__legacy/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });

  test("runs a hosted single-user company and report path after login", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(OWNER_EMAIL);
    await page.getByLabel("Password").fill(OWNER_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();

    await page.goto(COMPANY_TARGET.route);
    await expect(page.getByRole("heading", { name: /Reports/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Documents/i })).toBeVisible();

    await page.goto(REPORT_TARGET.route);
    await expect(page.getByRole("button", { name: /Refresh Completion Preview/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Agent and Workflow Surface/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Report Documents/i })).toBeVisible();
  });
});
