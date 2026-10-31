import { defineConfig } from '@playwright/test';
const port = process.env.PLAYWRIGHT_PORT || '3000';
export default defineConfig({ testDir: './tests', outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || './test-results', use: { baseURL: `http://localhost:${port}`, launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : undefined }, webServer: { command: `npm run dev -- -p ${port}`, url: `http://localhost:${port}`, reuseExistingServer: !process.env.CI, timeout: 120000 } });
