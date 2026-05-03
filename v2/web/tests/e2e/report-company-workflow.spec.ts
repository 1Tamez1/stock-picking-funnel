import { expect, test } from "@playwright/test";

import { loadPrimaryReportRoute, loadSampleCompanyRoute, loadStageReportRoute } from "./fixture-routes";
import { acceptNextDialog, expectErrorBanner, expectStatusBanner, firstReadonlyFieldCard, uniqueName } from "./helpers";

const COMPANY_TARGET = loadSampleCompanyRoute();
const REPORT_TARGET = loadPrimaryReportRoute();
const INHERITED_TARGET = loadStageReportRoute("business_underwriting");

test.describe("company and report workflow parity", () => {
  test("company route exposes native detail workflow", async ({ page }) => {
    await page.goto(COMPANY_TARGET.route);
    await expect(page.getByRole("heading", { name: /Reports/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Create Report/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Documents/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Company Sources/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Monitoring Rules/i })).toBeVisible();
  });

  test("company route can create a new routed report on the isolated browser-test runtime", async ({ page }) => {
    const reportTitle = uniqueName("Playwright Routed Report");
    await page.goto(COMPANY_TARGET.route);
    await page.getByLabel("Title").first().fill(reportTitle);
    await page.getByRole("button", { name: "Create Report" }).click();
    await expect(page).toHaveURL(/\/reports\//);
    await expect(page.locator("main h1")).toHaveText(reportTitle);
  });

  test("report route exposes native stage, source, and completion workflow", async ({ page }) => {
    await page.goto(REPORT_TARGET.route);
    await expect(page.getByRole("button", { name: /Refresh Completion Preview/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Save Draft/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Finalize Report/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Agent and Workflow Surface/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sources", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Report Documents/i })).toBeVisible();
  });

  test("report route supports source create, update, and delete on isolated runtime", async ({ page }) => {
    const sourceTitle = uniqueName("Playwright Source");
    await page.goto(REPORT_TARGET.route);
    const sourceEditor = page.locator(".inset-panel").filter({ has: page.getByRole("heading", { name: /Add Source|Edit Source/ }) }).first();

    await sourceEditor.getByRole("textbox", { name: "Title", exact: true }).fill(sourceTitle);
    await sourceEditor.getByRole("textbox", { name: "URL", exact: true }).fill(`https://example.com/${sourceTitle}`);
    await sourceEditor.getByRole("textbox", { name: "Notes", exact: true }).fill("Browser parity source create/update/delete check.");
    await sourceEditor.getByRole("textbox", { name: "Link-Only Reason", exact: true }).fill("Deliberate URL-only fixture for isolated parity testing.");
    await sourceEditor.getByRole("checkbox", { name: /snapshot guidance/i }).check();
    await page.getByRole("button", { name: "Save Source" }).click();

    await expectStatusBanner(page, /Source created\./);
    const createdCard = page.locator(".row-card.compact-row-card").filter({ hasText: sourceTitle }).first();
    await expect(createdCard).toBeVisible();

    await createdCard.getByRole("button", { name: "Edit" }).click();
    await sourceEditor.getByRole("textbox", { name: "Notes", exact: true }).fill("Updated browser parity source note.");
    await page.getByRole("button", { name: "Update Source" }).click();
    await expectStatusBanner(page, /Source updated\./);

    const confirm = acceptNextDialog(page);
    await createdCard.getByRole("button", { name: "Delete" }).click();
    await confirm;
    await expectStatusBanner(page, /Source deleted\./);
    await expect(createdCard).toHaveCount(0);
  });

  test("report route allows inherited read-only field annotation and save draft", async ({ page }) => {
    const noteValue = `Inherited note ${Date.now()}`;
    await page.goto(INHERITED_TARGET.route);
    const readonlyCard = await firstReadonlyFieldCard(page);
    await readonlyCard.getByLabel("Field Note").fill(noteValue);
    const saveResponse = page.waitForResponse((response) => response.url().includes("/api/reports/") && response.request().method() === "PATCH");
    await page.getByRole("button", { name: "Save Draft" }).click();
    const response = await saveResponse;
    expect(response.ok()).toBeTruthy();
    await page.reload();
    const reloadedReadonlyCard = await firstReadonlyFieldCard(page);
    await expect(reloadedReadonlyCard.getByLabel("Field Note")).toHaveValue(noteValue);
  });

  test("report route exposes blocked finalize path for an incomplete new report", async ({ page }) => {
    const reportTitle = uniqueName("Finalize Blocked Draft");
    await page.goto(COMPANY_TARGET.route);
    await page.getByLabel("Title").first().fill(reportTitle);
    await page.getByRole("button", { name: "Create Report" }).click();
    await expect(page.locator("main h1")).toHaveText(reportTitle);
    await page.getByRole("button", { name: "Finalize Report" }).click();
    await expectErrorBanner(page, /choose a final decision before finalizing/i);
    await expect(page.getByRole("heading", { name: /Completion/i })).toBeVisible();
  });
});
