import { expect, type Locator, type Page } from "@playwright/test";


export function uniqueName(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export async function expectStatusBanner(page: Page, pattern: RegExp | string) {
  await expect(page.locator(".status-banner")).toContainText(pattern);
}

export async function expectErrorBanner(page: Page, pattern: RegExp | string) {
  await expect(page.locator(".error-banner")).toContainText(pattern);
}

export async function firstReadonlyFieldCard(page: Page): Promise<Locator> {
  const card = page.locator(".readonly-field-card").first();
  await expect(card).toBeVisible();
  return card;
}

export async function acceptNextDialog(page: Page) {
  const dialog = page.waitForEvent("dialog");
  return dialog.then(async (value) => {
    await value.accept();
  });
}
