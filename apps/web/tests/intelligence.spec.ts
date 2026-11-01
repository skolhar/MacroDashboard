import { test, expect } from '@playwright/test';

test('cycle intelligence stays honest without private operator access', async ({ page }) => {
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/intelligence');
    await expect(page.getByRole('heading', { name: 'Cycle intelligence' })).toBeVisible();
    await expect(page.getByText('Research assessment unavailable')).toBeVisible();
    await expect(page.getByText('No live macro conclusion is implied.')).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
});
