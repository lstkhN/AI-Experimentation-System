import { defineConfig, devices } from '@playwright/test';
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000';
const port = new URL(baseURL).port || '3000';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  use: { baseURL, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: { command: `npm run dev -- -p ${port}`, url: baseURL, reuseExistingServer: true, timeout: 120_000 },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
