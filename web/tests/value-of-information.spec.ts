import { expect, test } from '@playwright/test';

test('calculates and displays Bayesian value of information', async ({ page }) => {
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9090, name: 'VOI project', language: 'en' }] }));
  await page.route('**/api/v1/projects/9090/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/economics/value-of-information') && route.request().method() === 'GET') return route.fulfill({ status: 404, json: { detail: 'Value of information snapshot not found' } });
    if (path.endsWith('/economics/value-of-information')) {
      expect(route.request().method()).toBe('POST');
      expect(route.request().postDataJSON()).toMatchObject({ prior_alpha: 1, prior_beta: 1, decision_threshold: 0.5, iterations: 5000, seed: 0, experiments: [{ name: 'Validation experiment', sample_size: 100, cost: 100 }] });
      return route.fulfill({ json: { method: 'beta_binomial_nested_monte_carlo', current_decision: 'GO', current_value: 100, evpi: 80, experiments: [{ name: 'Validation experiment', sample_size: 100, cost: 100, evsi_gross: 50, evsi_net: -50, decision_change_probability: 0.2, recommended: false }], recommended_experiment: null, provenance: { iterations: 5000, seed: 0, rng: 'numpy.PCG64' }, assumptions: ['Unknown success rate follows a Beta prior.'] } });
    }
    if (/(analysis-runs|history|experiments|experiment-runs|capital-plans)$/.test(path)) return route.fulfill({ json: [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: 'not found' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'VOI project' }).click();
  await page.getByRole('tab', { name: 'Unit economics' }).click();
  await expect(page.getByRole('heading', { name: 'Value of information' })).toBeVisible();
  await page.getByRole('button', { name: 'Calculate value of information' }).click();
  await expect(page.getByText('Current decision: GO')).toBeVisible();
  await expect(page.getByText('80.00')).toBeVisible();
  await expect(page.getByText('No experiment recommended')).toBeVisible();
});
