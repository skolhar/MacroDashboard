import { test, expect } from '@playwright/test';

test('cycle intelligence requires private page credentials', async ({ page }) => {
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    const response = await page.goto('/intelligence');
    expect([401, 404]).toContain(response?.status());
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
});

test('spoofed proxy headers do not bypass private page authentication', async ({ request }) => {
  const response = await request.get('/intelligence', { headers: { 'X-Forwarded-User': 'research', 'X-SmartHedge-Client-IP': '127.0.0.1' } });
  expect([401, 404]).toContain(response.status());
  if (process.env.RESEARCH_UI_USER && process.env.RESEARCH_UI_PASSWORD && process.env.RESEARCH_OPERATOR_TOKEN) {
    const wrong = await request.get('/intelligence', { headers: { Authorization: 'Basic ' + Buffer.from('research:wrong').toString('base64') } });
    expect(wrong.status()).toBe(401);
    const allowed = await request.get('/intelligence', { headers: { Authorization: 'Basic ' + Buffer.from(`${process.env.RESEARCH_UI_USER}:${process.env.RESEARCH_UI_PASSWORD}`).toString('base64') } });
    expect(allowed.status()).toBe(200);
  }
});
