// axe-core: zero serious/critical violations on all four page types, in both color schemes (plan §11.4).
import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const pages = [
  ['national', '/'],
  ['national (shift view)', '/?view=shift'],
  ['state', '/state/GA'],
  ['methodology', '/methodology'],
  ['about', '/about']
] as const;

for (const scheme of ['light', 'dark'] as const) {
  for (const [name, path] of pages) {
    test(`axe: ${name} (${scheme})`, async ({ browser }) => {
      const ctx = await browser.newContext({ colorScheme: scheme });
      const page = await ctx.newPage();
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
      const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
      expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([]);
      await ctx.close();
    });
  }
}
