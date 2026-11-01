import { test, expect } from '@playwright/test';

test('isolated staging shows source coverage without claiming composite risk', async ({ page, request }) => {
  const staging = process.env.STAGING_BASE_URL;
  test.skip(!staging, 'Set STAGING_BASE_URL for an isolated staging browser run');
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(staging!);
    await expect(page.getByText('STAGING · SOURCE-BACKED DATA ONLY').first()).toBeVisible();
    await expect(page.getByText('Data confidence')).toBeVisible();
    await expect(page.getByText('Operational coverage/quality index · not statistical certainty')).toBeVisible();
    await expect(page.getByText('1/42 source-backed')).toBeVisible();
    await expect(page.getByText('Insufficient cycle coverage')).toBeVisible();
    await expect(page.locator('.cycle-history')).toHaveCount(6);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  }
  const blocked = await request.post(`${staging}/api/v1/admin/ingestion/run`, { data: { adapter: 'us_treasury' } });
  expect(blocked.status()).toBe(403);
});

test('external liquidity staging keeps Indian gaps and reference-rate basis explicit', async ({ page }) => {
  const staging = process.env.STAGING_BASE_URL;
  test.skip(!staging, 'Set STAGING_BASE_URL for an isolated staging browser run');
  await page.goto(`${staging}/external-liquidity`);
  await expect(page.getByText('STAGING · SOURCE-BACKED DATA ONLY').first()).toBeVisible();
  await expect(page.getByText('INSUFFICIENT EVIDENCE')).toBeVisible();
  await expect(page.getByText('RBI (through 9 July 2018) and FBIL (from 10 July 2018) publish reference fixings; neither is a continuous tradable quote.')).toBeVisible();
  await expect(page.getByText('No source-backed observation.').first()).toBeVisible();
  await expect(page.getByText('RBI WEEKLY GROSS RESERVES')).toBeVisible();
  await expect(page.getByText('DATA UNAVAILABLE · no approved RBI WSS reserves release has been imported.')).toBeVisible();
  await expect(page.getByText('INSUFFICIENT EVIDENCE')).toBeVisible();
  await expect(page.getByText('USD/INR published FBIL reference rate')).toHaveCount(0);
});
