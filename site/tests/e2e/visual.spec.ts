// Visual regression of both toggle states (plan §11.4, tolerance 1% set in playwright.config.ts).
// Baselines are created on first run (`--update-snapshots`) and are platform-specific; commit them from the CI image.
import { expect, test } from '@playwright/test';

for (const view of ['projection', 'shift'] as const) {
  test(`national map, ${view} view`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'light' });
    await page.goto(`/?view=${view}`);
    await expect(page.getByText('Loading map…')).toHaveCount(0);
    await page.waitForTimeout(300);
    await expect(page.locator('canvas')).toHaveScreenshot(`national-${view}.png`);
  });
  test(`state map GA, ${view} view`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'light' });
    await page.goto(`/state/GA?view=${view}`);
    await expect(page.locator('svg path[data-geoid]').first()).toBeVisible();
    await page.waitForTimeout(300);
    await expect(page.locator('.statemap')).toHaveScreenshot(`ga-${view}.png`);
  });
}
