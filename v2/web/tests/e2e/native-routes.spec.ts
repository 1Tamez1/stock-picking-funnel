import { expect, test } from "@playwright/test";

const ROUTES = [
  { route: "/dashboard", heading: "Dashboard", expectsLegacyLink: true },
  { route: "/pool", heading: "All Companies", expectsLegacyLink: true },
  { route: "/funnel", heading: "Funnel", expectsLegacyLink: true },
  { route: "/reports", heading: "Reports", expectsLegacyLink: true },
  { route: "/companies", heading: "Companies", expectsLegacyLink: false },
  { route: "/monitoring", heading: "Monitoring", expectsLegacyLink: true },
  { route: "/watchlist", heading: "Watchlist", expectsLegacyLink: true },
  { route: "/archive", heading: "Archive", expectsLegacyLink: true },
  { route: "/templates", heading: "Templates", expectsLegacyLink: true },
] as const;

test.describe("native routed surfaces", () => {
  for (const { route, heading, expectsLegacyLink } of ROUTES) {
    test(`renders ${route}`, async ({ page }) => {
      await page.goto(route);
      await expect(page.locator("main h1")).toHaveText(heading);
      const legacyLink = page.getByRole("link", { name: /Open Preserved Legacy Surface/i });
      if (expectsLegacyLink) {
        await expect(legacyLink).toBeVisible();
      } else {
        await expect(legacyLink).toHaveCount(0);
      }
    });
  }
});
