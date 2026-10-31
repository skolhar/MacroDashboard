import { test, expect } from '@playwright/test';

test('external liquidity demo stays labelled and responsive', async ({ page }) => {
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/external-liquidity');
    await expect(page.getByRole('heading', { name: 'India External Liquidity' })).toBeVisible();
    await expect(page.getByText('DEMO · SYNTHETIC DATA').first()).toBeVisible();
    await expect(page.getByText('Operational coverage/quality index; not statistical certainty')).toBeVisible();
    await expect(page.locator('.external-grid .panel')).toHaveCount(10);
    await expect(page.getByText('Context only until sign and maturity definitions are validated.')).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  }
});
