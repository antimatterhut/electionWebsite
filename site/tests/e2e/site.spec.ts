import { expect, test } from '@playwright/test';

test.describe('national page', () => {
  test('map loads in under 3 s and draws pixels', async ({ page }) => {
    const t0 = Date.now();
    await page.goto('/');
    await expect(page.getByText('Loading map…')).toHaveCount(0, { timeout: 3000 });
    expect(Date.now() - t0).toBeLessThan(3000);
    const painted = await page.locator('canvas').evaluate((c: HTMLCanvasElement) => {
      const d = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
      let colored = 0;
      for (let i = 0; i < d.length; i += 4 * 97) if (d[i + 3] !== 0) colored++;
      return colored;
    });
    expect(painted).toBeGreaterThan(200);
  });

  test('toggle changes legend, URL and persists', async ({ page }) => {
    await page.goto('/');
    const legend = page.getByRole('figure', { name: /Projected margin/ });
    await expect(legend).toBeVisible();
    await page.getByRole('radio', { name: 'Shift from 2024' }).click();
    await expect(page.getByRole('figure', { name: /Shift from 2024/ })).toBeVisible();
    await expect(page).toHaveURL(/view=shift/);
    expect(await page.evaluate(() => localStorage.getItem('senate.view'))).toBe('shift');
    await page.reload();
    await expect(page.getByRole('radio', { name: 'Shift from 2024' })).toHaveAttribute('aria-checked', 'true');
    // ?view= wins over storage
    await page.goto('/?view=projection');
    await expect(page.getByRole('radio', { name: 'Projection' })).toHaveAttribute('aria-checked', 'true');
  });

  test('toggle is keyboard operable (radiogroup arrows)', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('radio', { name: 'Projection' }).focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('radio', { name: 'Shift from 2024' })).toBeFocused();
    await expect(page.getByRole('radio', { name: 'Shift from 2024' })).toHaveAttribute('aria-checked', 'true');
  });

  test('clicking a county opens its state page', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Loading map…')).toHaveCount(0);
    // Click the centre of a race state: Georgia's centroid in atlas units (975x610 box) -> element coordinates.
    await page.locator('canvas').evaluate((c) => c.scrollIntoView({ block: 'center' }));
    const box = (await page.locator('canvas').boundingBox())!;
    const s = Math.min(box.width / 975, box.height / 610);
    const ox = (box.width - 975 * s) / 2, oy = (box.height - 610 * s) / 2;
    await page.mouse.move(box.x + ox + 770 * s, box.y + oy + 400 * s);
    await expect(page.getByRole('tooltip')).toBeVisible();
    await page.mouse.click(box.x + ox + 770 * s, box.y + oy + 400 * s);
    await expect(page).toHaveURL(/\/state\/[A-Z]{2}$/);
    await expect(page.getByRole('heading', { level: 1 })).toContainText('U.S. Senate');
  });

  test('keyboard reaches the race table and sorts it', async ({ page }) => {
    await page.goto('/');
    const sort = page.getByRole('button', { name: /Projected margin/ });
    await sort.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('columnheader', { name: /Projected margin/ })).toHaveAttribute('aria-sort', 'descending');
    await page.keyboard.press('Enter');
    await expect(page.getByRole('columnheader', { name: /Projected margin/ })).toHaveAttribute('aria-sort', 'ascending');
    await expect(page.locator('table.desktop tbody tr')).toHaveCount(35);
    await page.getByLabel('Show').selectOption('competitive');
    expect(await page.locator('table.desktop tbody tr').count()).toBeLessThan(35);
  });

  test('skip link and landmarks', async ({ page }) => {
    await page.goto('/');
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused();
    await expect(page.getByRole('main')).toHaveCount(1);
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  });

  test('fixture banner is shown on mock data', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Fixture data.')).toBeVisible();
  });
});

test.describe('failure states', () => {
  test('map data failure shows the error state with retry and recovers', async ({ page }) => {
    let fail = true;
    await page.route('**/data/topo/counties.topojson*', (r) => (fail ? r.abort() : r.continue()));
    await page.goto('/');
    await expect(page.getByRole('alert').filter({ hasText: 'could not be loaded' })).toBeVisible();
    await expect(page.getByRole('img', { name: 'Static national projection map' })).toBeVisible();
    fail = false;
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByText('Loading map…')).toHaveCount(0);
    await expect(page.getByRole('alert').filter({ hasText: 'could not be loaded' })).toHaveCount(0);
  });

  test('missing state detail (client navigation) shows the message, not a crash', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Loading map…')).toHaveCount(0); // hydrated: the click below must be a client-side navigation
    await page.route('**/data/states/GA.json*', (r) => r.fulfill({ status: 404, body: 'not found' }));
    await page.locator('table.desktop').getByRole('link', { name: 'Georgia' }).click();
    await expect(page).toHaveURL(/\/state\/GA$/);
    await expect(page.getByText("Detailed county data isn't available for this race")).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Georgia');
  });

  test('summary refresh failure keeps the last good run and shows a banner', async ({ page }) => {
    await page.goto('/');
    await page.waitForFunction(() => !!localStorage.getItem('senate.lastGoodSummary'));
    await page.route('**/data/summary.json*', (r) => r.abort());
    await page.evaluate(() => window.dispatchEvent(new Event('online'))); // triggers the layout refresh
    const banner = page.getByRole('alert').filter({ hasText: 'Projection unavailable — last good run shown' });
    await expect(banner).toBeVisible();
    await expect(page.getByRole('heading', { name: /Chance Democrats control/ })).toBeVisible(); // still rendering last good
    await page.unroute('**/data/summary.json*');
    await page.evaluate(() => window.dispatchEvent(new Event('online')));
    await expect(banner).toHaveCount(0);
  });

  test('unknown state is a 404 page', async ({ page }) => {
    const res = await page.goto('/state/ZZ');
    expect(res?.status()).toBe(404);
  });
});

test.describe('state page', () => {
  test('renders all panels, the map responds to arrow keys and the table sorts/searches/downloads', async ({ page }) => {
    await page.goto('/state/GA');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Georgia');
    for (const name of ['How the projection is built', 'Counties', 'Swing by group', /Early vote/, 'Recent polls']) {
      await expect(page.getByRole('heading', { name })).toBeVisible();
    }
    const map = page.getByRole('group', { name: /County map for GA/ });
    await expect(map.locator('path').first()).toBeVisible();
    await map.locator('path[tabindex="0"]').focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('tooltip')).toBeVisible();
    const live = page.locator('p.sr-only[aria-live="polite"]').last();
    await expect(live).toContainText('Projected 2026 Senate');
    await page.keyboard.press('Enter');
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);

    await page.getByLabel('Search').fill('fulton');
    await expect(page.locator('section[aria-labelledby="ct-h"] tbody tr')).toHaveCount(1);
    await page.getByLabel('Search').fill('');
    const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download CSV' }).click()]);
    expect(dl.suggestedFilename()).toBe('GA_counties.csv');
  });

  test('view toggle recolors the state map', async ({ page }) => {
    await page.goto('/state/GA');
    const path = page.locator('svg path[data-geoid]').first();
    const before = await path.getAttribute('fill');
    await page.getByRole('radio', { name: 'Shift from 2024' }).click();
    await expect.poll(() => path.getAttribute('fill')).not.toBe(before);
  });
});

test.describe('static pages', () => {
  test('methodology has live params and the backtest table', async ({ page }) => {
    await page.goto('/methodology');
    await expect(page.getByRole('heading', { level: 1, name: 'Methodology' })).toBeVisible();
    await expect(page.getByText('weights **')).toHaveCount(0);
    await expect(page.getByRole('table', { name: /Backtest/ })).toBeVisible();
    await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(1);
    await expect(page.locator('main')).not.toContainText('{{');
  });
  test('about page has attribution and disclaimer', async ({ page }) => {
    await page.goto('/about');
    await expect(page.getByText('CC BY-SA')).toBeVisible();
    await expect(page.getByText('not an official result').first()).toBeVisible();
  });
  test('sitemap and robots are served', async ({ request }) => {
    const sm = await request.get('/sitemap.xml');
    expect(sm.ok()).toBe(true);
    expect((await sm.text()).match(/<loc>/g)?.length).toBe(38);
    expect((await request.get('/robots.txt')).ok()).toBe(true);
  });
});

test.describe('reduced motion', () => {
  test('toggle does not animate under prefers-reduced-motion', async ({ browser }) => {
    const ctx = await browser.newContext({ reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    await page.goto('/state/GA');
    const dur = await page.locator('svg path[data-geoid]').first().evaluate((e) => getComputedStyle(e).transitionDuration);
    expect(dur === '0s' || dur === '1e-05s' || dur.startsWith('0.00001')).toBe(true);
    await ctx.close();
  });
});
