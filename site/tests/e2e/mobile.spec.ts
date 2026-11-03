import { expect, test } from '@playwright/test';

test.describe('mobile viewport', () => {
  test('national: single column, no horizontal scroll, cards instead of table, bottom sheet on tap', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Loading map…')).toHaveCount(0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await expect(page.locator('table.desktop')).toBeHidden();
    await expect(page.locator('ul.cards li').first()).toBeVisible();
    await page.locator('canvas').evaluate((c) => c.scrollIntoView({ block: 'center' }));
    const box = (await page.locator('canvas').boundingBox())!;
    expect(box.width / box.height).toBeCloseTo(1.6, 1);
    const s = Math.min(box.width / 975, box.height / 610);
    const ox = (box.width - 975 * s) / 2, oy = (box.height - 610 * s) / 2;
    await page.touchscreen.tap(box.x + ox + 770 * s, box.y + oy + 400 * s);
    const sheet = page.getByRole('dialog');
    await expect(sheet).toBeVisible();
    await expect(sheet.getByRole('link', { name: 'View state' })).toBeVisible();
    await page.screenshot({ path: 'test-results/mobile-national-sheet.png' });
  });

  test('national mobile screenshot', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Loading map…')).toHaveCount(0);
    await expect(page).toHaveScreenshot('mobile-national.png', { fullPage: false, mask: [page.locator('.head p')] });
  });

  test('state mobile: no horizontal scroll', async ({ page }) => {
    await page.goto('/state/GA');
    await expect(page.locator('svg path[data-geoid]').first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    await expect(page).toHaveScreenshot('mobile-state.png', { fullPage: false, mask: [page.locator('.head p')] });
  });
});
