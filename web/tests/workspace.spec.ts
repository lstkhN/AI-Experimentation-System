import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('intake is keyboard accessible and tabs are available after project creation', async ({ page }) => {
  await page.route('**/api/v1/projects', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: [{ id: 9001, name: 'Playwright smoke project', language: 'en' }] });
    await route.continue();
  });
  await page.route('**/api/v1/projects/9001/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/analysis-runs')) return route.fulfill({ json: [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] });
    if (path.endsWith('/history')) return route.fulfill({ json: [] });
    if (path.endsWith('/experiments')) return route.fulfill({ json: [] });
    if (path.endsWith('/verdict')) return route.fulfill({ status: 404, json: { detail: 'not evaluated' } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Business Hypothesis Analyst' })).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
  await page.getByRole('button', { name: /Playwright smoke project/ }).click();
  await expect(page.locator('#workspace')).toBeVisible({ timeout: 10_000 });
  for (const tab of ['Decision first', 'Evidence summary', 'Unit economics', 'Capital plan', 'Experiment proposals', 'Activity history']) {
    await expect(page.getByRole('tab', { name: tab })).toBeVisible();
  }
});

test('mobile workspace keeps primary navigation usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('.intake')).toBeVisible();
  await expect(page.locator('.skip-link')).toBeAttached();
});

test('switching projects clears prior project state and Russian controls are accessible', async ({ page }) => {
  await page.route('**/api/v1/projects', async route => route.fulfill({ json: [
    { id: 1, name: 'First project', language: 'en' }, { id: 2, name: 'Второй проект', language: 'ru' },
  ] }));
  await page.route('**/api/v1/projects/*/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const projectId = path.split('/')[4];
    if (path.endsWith('/analysis-runs')) return route.fulfill({ json: projectId === '1' ? [{ id: 11, project_id: 1, status: 'completed', result: {}, created_at: '2025-01-01T00:00:00Z', completed_at: null }] : [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: projectId === '1' ? [{ id: 101, statement: 'Only first project', category: 'market', importance: 1, criticality: 'HIGH', is_blocking: false, status: 'pending' }] : [] });
    if (path.endsWith('/history') || path.endsWith('/experiments')) return route.fulfill({ json: [] });
    if (path.endsWith('/verdict')) return route.fulfill({ status: 404, json: { detail: 'not evaluated' } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/');
  await page.getByRole('button', { name: /First project/ }).click();
  await expect(page.getByText('Only first project')).toBeVisible();
  await page.getByRole('button', { name: /Второй проект/ }).click();
  await expect(page.getByText('Only first project')).toHaveCount(0);
  await expect(page.getByText('Запусков ещё нет')).toBeVisible();
  const languageGroup = page.getByRole('group', { name: 'Язык интерфейса' });
  await expect(languageGroup.getByRole('button', { name: 'RU' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('нет запуска')).toBeVisible();
});
