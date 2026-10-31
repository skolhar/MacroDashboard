import { test, expect } from '@playwright/test';
test('demo overview and provenance work on desktop and mobile', async ({ page }) => {
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    await expect(page.getByText('DEMO · SYNTHETIC DATA').first()).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Stress overview' })).toBeVisible();
    await expect(page.locator('.cycle-card')).toHaveCount(6);
    await expect(page.locator('.metric')).toHaveCount(12);
    await page.locator('.metric summary').first().focus();
    await page.keyboard.press('Enter');
    await expect(page.getByText('Provider: synthetic_fixture').first()).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  }
});

test('v2 inflection monitor remains readable on mobile and desktop', async ({ page }) => {
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/?ruleset=v2');
    await expect(page.getByRole('heading', { name: 'Inflection Monitor' })).toBeVisible();
    await expect(page.locator('.cycle-card')).toHaveCount(6);
    await expect(page.locator('.metric')).toHaveCount(42);
    await expect(page.getByRole('heading', { name: 'Coverage and freshness' })).toBeVisible();
    await expect(page.getByText('DATA_UNAVAILABLE').first()).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  }
});
