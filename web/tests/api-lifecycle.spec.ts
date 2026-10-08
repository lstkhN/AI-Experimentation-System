import { test, expect } from '@playwright/test';

test('API-backed project lifecycle opens a real workspace', async ({ page, request }) => {
  const base = (process.env.API_URL || 'http://localhost:8000').replace(/\/$/, '');
  let project;
  try {
    const response = await request.post(`${base}/api/v1/projects`, { data: { name: `E2E real ${Date.now()}`, language: 'en' } });
    if (!response.ok()) { if (process.env.CI_API_REQUIRED) throw new Error(`API returned ${response.status()}`); test.skip(true, `API returned ${response.status()}`); }
    project = await response.json();
  } catch (error) {
    if (process.env.CI_API_REQUIRED) throw error;
    test.skip(true, 'API is unavailable; run Docker Compose first');
    return;
  }
  await page.goto('/');
  await expect(page.getByRole('button', { name: new RegExp(project.name) })).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: new RegExp(project.name) }).click();
  await expect(page.locator('#workspace')).toBeVisible({ timeout: 10_000 });
  for (const tab of ['Decision first', 'Evidence summary', 'Unit economics', 'Capital plan', 'Experiment proposals', 'Activity history']) {
    await expect(page.getByRole('tab', { name: tab })).toBeVisible();
  }
});
