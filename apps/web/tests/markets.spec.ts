import { test, expect } from '@playwright/test';

test('market research route keeps unavailable source honest on desktop and mobile', async ({ page }) => {
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/markets');
    await expect(page.getByRole('heading', { name: 'Market Research' })).toBeVisible();
    await expect(page.getByText('DATA UNAVAILABLE · RESEARCH FEED DISABLED')).toBeVisible();
    await expect(page.getByText('WTI is not MCX crude.', { exact: false })).toBeVisible();
    await expect(page.locator('.market-choice')).toHaveCount(15);
    await expect(page.getByText('DATA UNAVAILABLE · two source-backed daily closes required')).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  }
});
