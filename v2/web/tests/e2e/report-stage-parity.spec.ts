import { expect, test } from "@playwright/test";

import { loadStageReportRoutes } from "./fixture-routes";

const STAGE_EXPECTATIONS: Record<string, string[]> = {
  data_collection: ["Collection Scope", "Source Durability And LLM Packet", "Screening Handoff"],
  screening: ["Framing, Rules, And Evidence", "Decision Output"],
  business_underwriting: ["Business Quality, Unit Economics, And Industry Structure", "Verification And Decision Output"],
  management_underwriting: ["Hard Gates, Capital Allocation, Incentives, And Culture", "Verification, Category Standard, And Decision Output"],
  financial_underwriting: ["Hard Financial Gates And Core Worksheets", "Red Flags, Verification, Category Standard, And Decision Output"],
  valuation_position_size: ["Imported Economics, Price Ladder, Margin Of Safety, And Position Size", "Error Prevention, Valuation Standard, And Decision Output"],
  execution_rules: ["Entry, Add, Hold, Trim, Exit, And Trigger Rules", "Portfolio Interaction, Error Prevention, Pattern Standard, And Decision Output"],
};

test.describe("native and legacy report stage parity", () => {
  for (const entry of loadStageReportRoutes()) {
    test(`native report route renders ${entry.stageKey} stage clusters`, async ({ page }) => {
      await page.goto(entry.route);
      const stageOverview = page.locator(`[data-stage-renderer="${entry.stageKey}"]`);
      const stageSurface = page.locator(`[data-stage-root="${entry.stageKey}"]`);
      await expect(stageOverview).toBeVisible();
      await expect(stageSurface).toBeVisible();
      await expect(page.locator("main h1")).toHaveText(entry.report.title || /.+/);
      for (const heading of STAGE_EXPECTATIONS[entry.stageKey] || []) {
        await expect(stageSurface.getByRole("heading", { name: heading, exact: true }).first()).toBeVisible();
      }
      await expect(page.getByRole("link", { name: /Open Preserved Legacy Surface/i })).toBeVisible();
    });

    test(`legacy fallback still opens for ${entry.stageKey}`, async ({ page }) => {
      await page.goto(entry.legacyRoute);
      await expect(page.locator("main h1")).toHaveText(`Report ${entry.report.id}`);
      await expect(page.locator("iframe")).toBeVisible();
      const frame = page.frameLocator("iframe");
      await expect(frame.locator("body")).toContainText(entry.report.title || "");
    });

    test(`native and legacy both expose the ${entry.stageKey} report title`, async ({ page }) => {
      await page.goto(entry.route);
      await expect(page.locator("main h1")).toHaveText(entry.report.title || /.+/);

      await page.goto(entry.legacyRoute);
      await expect(page.locator("main h1")).toHaveText(`Report ${entry.report.id}`);
      await expect(page.frameLocator("iframe").locator("body")).toContainText(entry.report.title || "");
    });
  }
});
