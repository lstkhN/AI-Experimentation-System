import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('workspace tabs follow ARIA relationships and roving keyboard navigation', async ({ page }) => {
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9500, name: 'Accessible tabs', language: 'en' }] }));
  await page.route('**/api/v1/projects/9500/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (/(analysis-runs|history|experiments|experiment-runs|capital-plans)$/.test(path)) return route.fulfill({ json: [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: 'not found' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Accessible tabs' }).click();
  const tabs = page.getByRole('tab');
  await expect(tabs).toHaveCount(6);
  await expect(page.getByRole('tablist')).toHaveAttribute('aria-orientation', 'horizontal');
  await expect(tabs.nth(0)).toHaveAttribute('aria-controls', 'panel-decision');
  await tabs.nth(0).focus();
  await page.keyboard.press('End');
  await expect(tabs.nth(5)).toBeFocused();
  await expect(tabs.nth(5)).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#panel-history')).toBeVisible();
  await page.keyboard.press('Home');
  await expect(tabs.nth(0)).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await expect(tabs.nth(1)).toBeFocused();
  await expect(page.locator('#panel-evidence')).toBeVisible();
  const results = await new AxeBuilder({ page }).include('#workspace').analyze();
  expect(results.violations).toEqual([]);
});
