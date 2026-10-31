import { test, expect } from '@playwright/test';

test('prototype is broker-free, labeled synthetic, and responsive', async ({ page }) => {
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/prototype');
    await expect(page.getByRole('heading', { name: 'Market attention radar' })).toBeVisible();
    await expect(page.getByText('DEMO · SYNTHETIC, NOT MARKET DATA')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Nifty 50' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'WTI crude proxy' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'USD/INR' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  }
});

test('horizon and user-triggered investigation work without implying a real cycle', async ({ page }) => {
  await page.goto('/prototype');
  await page.getByRole('button', { name: '20 sessions' }).click();
  await expect(page.getByText('Synthetic 20-session change').first()).toBeVisible();
  await page.getByRole('button', { name: 'Investigate' }).first().click();
  await expect(page.getByRole('heading', { name: 'Investigating: Gold vs real yields' })).toBeVisible();
  await page.getByLabel('Your research notes (stored in this page only; no server persistence)').fill('Test competing explanations.');
  await page.getByRole('button', { name: 'Keep notes during this session' }).click();
  await expect(page.getByText('Notes retained in browser memory until you reload this page.')).toBeVisible();
  await expect(page.getByText('unassessable coverage')).toBeVisible();
});
