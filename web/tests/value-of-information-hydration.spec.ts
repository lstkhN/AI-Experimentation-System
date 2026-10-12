import { expect, test } from '@playwright/test';

const savedSnapshot = {
  snapshot_id: 77,
  method: 'beta_binomial_nested_monte_carlo',
  current_decision: 'GO',
  current_value: 100,
  evpi: 80,
  experiments: [{ name: 'Saved experiment', sample_size: 100, cost: 10, evsi_gross: 50, evsi_net: 40, decision_change_probability: 0.2, recommended: true }],
  recommended_experiment: 'Saved experiment',
  provenance: { iterations: 5000, seed: 0, rng: 'numpy.PCG64' },
  assumptions: ['Unknown success rate follows a Beta prior.'],
};

test('hydrates the saved VOI snapshot and localizes its persistence state', async ({ page }) => {
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9091, name: 'Saved VOI project', language: 'en' }] }));
  await page.route('**/api/v1/projects/9091/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/economics/value-of-information') && route.request().method() === 'GET') return route.fulfill({ json: savedSnapshot });
    if (/(analysis-runs|history|experiments|experiment-runs|capital-plans)$/.test(path)) return route.fulfill({ json: [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: 'not found' } });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Saved VOI project' }).click();
  await page.getByRole('tab', { name: 'Unit economics' }).click();
  await expect(page.getByText('Saved snapshot #77')).toBeVisible();
  await expect(page.getByText('Current decision: GO')).toBeVisible();
  await expect(page.getByText('Saved experiment', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'RU', exact: true }).click();
  await expect(page.getByText('Сохранённый снимок #77')).toBeVisible();
});

test('shows an empty saved VOI state when no snapshot exists', async ({ page }) => {
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9092, name: 'Empty VOI project', language: 'en' }] }));
  await page.route('**/api/v1/projects/9092/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/economics/value-of-information') && route.request().method() === 'GET') return route.fulfill({ status: 404, json: { detail: 'Value of information snapshot not found' } });
    if (/(analysis-runs|history|experiments|experiment-runs|capital-plans)$/.test(path)) return route.fulfill({ json: [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: 'not found' } });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Empty VOI project' }).click();
  await page.getByRole('tab', { name: 'Unit economics' }).click();
  await expect(page.getByText('No saved value-of-information assessment yet.')).toBeVisible();
});
