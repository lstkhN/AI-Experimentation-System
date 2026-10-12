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

test('research links reject unsafe schemes and project changes reset the active tab', async ({ page }) => {
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [
    { id: 9400, name: 'Unsafe source', language: 'en' }, { id: 9401, name: 'Next project', language: 'en' },
  ] }));
  await page.route('**/api/v1/projects/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/analysis-runs')) return route.fulfill({ json: path.includes('/9400/') ? [{ id: 1, status: 'completed', created_at: '', result: { research_results: [{ title: 'Unsafe link', url: 'javascript:alert(1)' }] } }] : [] });
    if (/(hypotheses|history|experiments|experiment-runs|capital-plans)$/.test(path)) return route.fulfill({ json: [] });
    if (path.endsWith('/verdict')) return route.fulfill({ status: 404, json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Unsafe source' }).click();
  await page.getByRole('tab', { name: 'Evidence summary' }).click();
  await expect(page.getByText('Unsafe link', { exact: true })).not.toHaveAttribute('href');
  await page.getByRole('button', { name: 'Next project' }).click();
  await expect(page.getByRole('tab', { name: 'Decision first' })).toHaveAttribute('aria-selected', 'true');
});

test('mobile workspace keeps primary navigation usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('.intake')).toBeVisible();
  await expect(page.locator('.skip-link')).toBeAttached();
});

test('switching projects clears state immediately and ignores stale responses', async ({ page }) => {
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9010, name: 'Slow first project', language: 'en' }, { id: 9011, name: 'Fast second project', language: 'en' }] }));
  await page.route('**/api/v1/projects/**', async route => { const path = new URL(route.request().url()).pathname; const first = path.includes('/9010/'); if (first) await new Promise(resolve => setTimeout(resolve, 300)); if (/(analysis-runs|history|experiments|experiment-runs)$/.test(path)) return route.fulfill({ json: [] }); if (path.endsWith('/hypotheses')) return route.fulfill({ json: first ? [{ id: 1, statement: 'Stale hypothesis', category: 'market', importance: 1, criticality: 'NORMAL', is_blocking: false, status: 'open' }] : [] }); return route.fulfill({ status: 404, json: { detail: 'not found' } }); });
  await page.goto('/'); await page.getByRole('button', { name: /Slow first project/ }).click(); await page.getByRole('button', { name: /Fast second project/ }).click();
  await expect(page.locator('#workspace')).toContainText('Fast second project'); await page.waitForTimeout(500); await expect(page.getByText('Stale hypothesis')).toHaveCount(0);
});

test('saved capital and completed measurements hydrate when opening a project', async ({ page }) => {
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9020, name: 'Hydrated project', language: 'en', budget: 500 }] }));
  await page.route('**/api/v1/projects/9020/**', route => { const path = new URL(route.request().url()).pathname; if (/(analysis-runs|history|experiments)$/.test(path)) return route.fulfill({ json: [] }); if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] }); if (path.endsWith('/economics/capital-plan')) return route.fulfill({ json: { currency: 'USD', total_required: 120, steps: [{ name: 'Validate', amount: 120 }], scenarios: [], unknowns: [], reliability: 'RELIABLE', economics_inputs: { currency: 'USD', scenarios: [{ price: 42 }] } } }); if (path.endsWith('/capital-plans')) return route.fulfill({ json: [{ id: 3, project_id: 9020, currency: 'USD', available_budget: 500, recommended_spend: 120, gates: [] }] }); if (path.endsWith('/experiment-runs')) return route.fulfill({ json: [{ id: 7, title: 'Completed test', forecast: {}, status: 'completed', evaluation: { outcome: 'pass' } }] }); if (path.endsWith('/experiment-runs/7/measurements')) return route.fulfill({ json: [{ id: 8, metric: 'signups', value: 12, unit: 'users' }] }); return route.fulfill({ status: 404, json: { detail: 'not found' } }); });
  await page.goto('/'); await page.getByRole('button', { name: 'Hydrated project' }).click(); await page.getByRole('tab', { name: 'Capital plan' }).click(); await expect(page.getByText('Total required:')).toContainText('$120'); await page.getByRole('tab', { name: 'Experiment proposals' }).click(); await expect(page.getByText('Completed test')).toBeVisible();
});

test('experiment lifecycle controls and tab panels update from mocked API responses', async ({ page }) => {
  let status = 'proposed'; await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9030, name: 'Lifecycle project', language: 'en' }] }));
  await page.route('**/api/v1/projects/9030/**', route => { const path = new URL(route.request().url()).pathname; if (/(analysis-runs|history|experiments)$/.test(path)) return route.fulfill({ json: [] }); if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] }); if (path.endsWith('/experiment-runs')) return route.fulfill({ json: [{ id: 9, title: 'Lifecycle run', forecast: {}, status, evaluation: null }] }); if (path.endsWith('/approvals')) { status = 'approved'; return route.fulfill({ json: {} }); } if (path.endsWith('/start')) { status = 'running'; return route.fulfill({ json: {} }); } if (path.endsWith('/stop')) { status = 'stopped'; return route.fulfill({ json: {} }); } return route.fulfill({ status: 404, json: {} }); });
  await page.goto('/'); await page.getByRole('button', { name: 'Lifecycle project' }).click(); await page.getByRole('tab', { name: 'Experiment proposals' }).click(); await page.getByRole('button', { name: 'Approve' }).click(); await expect(page.getByRole('button', { name: 'Start' })).toBeVisible(); await page.getByRole('button', { name: 'Start' }).click(); await expect(page.getByRole('button', { name: 'Add measurement' })).toBeVisible(); await page.getByRole('button', { name: 'Stop' }).click(); await expect(page.getByText('stopped', { exact: true })).toBeVisible();
});

test('Russian recommendation renders the localized experiment template', async ({ page }) => {
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9070, name: 'Шаблон', language: 'ru' }] })); await page.route('**/api/v1/projects/9070/**', route => { const path = new URL(route.request().url()).pathname; if (path.endsWith('/experiments/recommend-next-test')) return route.fulfill({ json: { hypothesis_id: null, rationale: 'Проверить спрос', template: { template_key: 'landing_page_v1', name: 'Landing page demand test', category: 'demand', description: 'Measure qualified interest.', rules: {}, version: 1 } } }); if (/(analysis-runs|history|experiments|experiment-runs|capital-plans)$/.test(path)) return route.fulfill({ json: [] }); if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] }); return route.fulfill({ status: 404, json: {} }); });
  await page.goto('/'); await page.getByRole('button', { name: 'Шаблон' }).click(); await page.getByRole('tab', { name: 'Предложения экспериментов' }).click(); await page.getByRole('button', { name: 'Подобрать следующий тест' }).click(); await expect(page.getByText('Тест спроса на лендинге')).toBeVisible();
});

test('empty project and history states plus language toggle semantics are explicit', async ({ page }) => { await page.route('**/api/v1/projects', route => route.fulfill({ json: [] })); await page.goto('/'); await expect(page.getByText('No projects yet.')).toBeVisible(); await expect(page.getByRole('group', { name: 'Language' })).toBeVisible(); await page.getByRole('button', { name: 'RU', exact: true }).click(); await expect(page.locator('html')).toHaveAttribute('lang', 'ru'); });

test('Russian catalog localizes template, status, metric, proposal title, run title, and evaluation fields', async ({ page }) => {
  const plan = { id: 41, project_id: 9080, currency: 'USD', available_budget: 100, recommended_spend: 0, gates: [{ id: 1, name: 'Evidence validation', recommended_spend: 0, status: 'LOCKED', unlock_conditions: [{ metric: 'verified_evidence_count', operator: '>=', value: 1 }], evaluation: { passed: false, checks: [] } }] };
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9080, name: 'Каталог', language: 'ru' }] }));
  await page.route('**/api/v1/projects/9080/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (/(analysis-runs|history)$/.test(path)) return route.fulfill({ json: [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] });
    if (path.endsWith('/experiments')) return route.fulfill({ json: [{ id: 3, hypothesis_id: null, template_key: 'landing_page_v1', title: 'Landing page demand test', rationale: 'No unproposed project hypothesis remains; validate baseline demand.', rules: {}, status: 'PROPOSED', created_at: '' }] });
    if (path.endsWith('/experiment-runs')) return route.fulfill({ json: [{ id: 4, proposal_id: 3, title: 'Landing page demand test', forecast: {}, status: 'completed', evaluation: { outcome: 'passed', verified_evidence_count: 1 } }] });
    if (path.endsWith('/experiment-runs/4/measurements')) return route.fulfill({ json: [] });
    if (path.endsWith('/capital-plans')) return route.fulfill({ json: [plan] });
    return route.fulfill({ status: 404, json: { detail: 'not found' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Каталог' }).click();
  await page.getByRole('tab', { name: 'Предложения экспериментов' }).click();
  await expect(page.getByText('Тест спроса на лендинге').first()).toBeVisible();
  await expect(page.getByText('Непредложенных гипотез не осталось; проверьте базовый спрос.')).toBeVisible();
  await expect(page.getByText('результат', { exact: true })).toBeVisible();
  await expect(page.getByText('число проверенных доказательств', { exact: true })).toBeVisible();
  await expect(page.getByText('Landing page demand test')).toHaveCount(0);
  await page.getByRole('tab', { name: 'План капитала' }).click();
  await expect(page.getByText('Проверка доказательств')).toBeVisible();
  await expect(page.getByText('число проверенных доказательств >= 1')).toBeVisible();
});

test('capital allocation retries a failed request with the same idempotency key', async ({ page }) => {
  const allocationKeys: string[] = []; let attempts = 0;
  const plan = { id: 52, project_id: 9090, currency: 'USD', available_budget: 100, recommended_spend: 100, gates: [] };
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9090, name: 'Allocation retry', language: 'en' }] }));
  await page.route('**/api/v1/projects/9090/**', route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (path.endsWith('/capital-plans/52/allocate')) { allocationKeys.push(request.headers()['idempotency-key']); attempts += 1; return attempts === 1 ? route.fulfill({ status: 500, json: { detail: 'temporary failure' } }) : route.fulfill({ json: { plan_id: 52, allocations: [] } }); }
    if (/(analysis-runs|history|experiments|experiment-runs)$/.test(path)) return route.fulfill({ json: [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] });
    if (path.endsWith('/capital-plans')) return route.fulfill({ json: [plan] });
    return route.fulfill({ status: 404, json: { detail: 'not found' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Allocation retry' }).click();
  await page.getByRole('tab', { name: 'Capital plan' }).click();
  await page.getByRole('button', { name: 'Allocate available capital' }).click();
  await expect.poll(() => allocationKeys.length).toBe(1);
  await page.getByRole('button', { name: 'Allocate available capital' }).click();
  await expect.poll(() => allocationKeys.length).toBe(2);
  expect(allocationKeys[0]).toBeTruthy();
  expect(allocationKeys[1]).toBe(allocationKeys[0]);
});

const russianTemplateCatalog = [
  ['problem_interviews_v1', 'Интервью о проблеме'], ['problem_survey_v1', 'Опрос о проблеме'],
  ['landing_page_v1', 'Тест спроса на лендинге'], ['smoke_test_v1', 'Дымовой тест'],
  ['fake_door_v1', 'Тест фальшивой двери'], ['prototype_usability_v1', 'Тест удобства прототипа'],
  ['concierge_v1', 'Консьерж-пилот'], ['wizard_of_oz_v1', 'Тест Волшебник страны Оз'],
  ['mvp_pilot_v1', 'Пилот MVP'], ['preorder_v1', 'Тест предзаказа'],
  ['pricing_interviews_v1', 'Интервью о цене'], ['paid_pilot_v1', 'Платный пилот'],
] as const;

for (const [template_key, localizedName] of russianTemplateCatalog) {
  test(`Russian catalog localizes ${template_key}`, async ({ page }) => {
    await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9200, name: 'Каталог', language: 'ru' }] }));
    await page.route('**/api/v1/projects/9200/**', route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/experiments/recommend-next-test')) return route.fulfill({ json: { hypothesis_id: null, rationale: 'hypothesis_weak', template: { template_key, name: 'English name', category: 'solution', description: 'English description', rules: {}, version: 1 } } });
      if (/(analysis-runs|history|experiments|experiment-runs|capital-plans)$/.test(path)) return route.fulfill({ json: [] });
      if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] });
      return route.fulfill({ status: 404, json: {} });
    });
    await page.goto('/');
    await page.getByRole('button', { name: 'Каталог' }).click();
    await page.getByRole('tab', { name: 'Предложения экспериментов' }).click();
    await page.getByRole('button', { name: 'Подобрать следующий тест' }).click();
    await expect(page.getByText(localizedName)).toBeVisible();
    await expect(page.getByText('гипотеза слаба')).toBeVisible();
  });
}

test('stopped runs hydrate measurements and persisted gate checks render recursively', async ({ page }) => {
  const plan = { id: 93, project_id: 9210, currency: 'USD', available_budget: 100, recommended_spend: 10, gates: [{ id: 2, name: 'Evidence validation', recommended_spend: 10, status: 'LOCKED', unlock_conditions: [], evaluation: { passed: false, checks: [{ metric: 'verified_evidence_count', actual: 0, expected: 1 }] } }] };
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9210, name: 'Stopped', language: 'ru' }] }));
  await page.route('**/api/v1/projects/9210/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (/(analysis-runs|history|experiments)$/.test(path)) return route.fulfill({ json: [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] });
    if (path.endsWith('/capital-plans')) return route.fulfill({ json: [plan] });
    if (path.endsWith('/experiment-runs')) return route.fulfill({ json: [{ id: 5, title: 'Stopped test', forecast: {}, status: 'stopped', evaluation: null }] });
    if (path.endsWith('/experiment-runs/5/measurements')) return route.fulfill({ json: [{ id: 6, metric: 'signups', value: 3, unit: 'users' }] });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/'); await page.getByRole('button', { name: 'Stopped' }).click();
  await page.getByRole('tab', { name: 'Предложения экспериментов' }).click();
  await expect(page.getByText('signups: 3 users')).toBeVisible();
  await page.getByRole('tab', { name: 'План капитала' }).click();
  await expect(page.getByText('проверки', { exact: true })).toBeVisible();
  await expect(page.getByText('фактическое значение', { exact: true })).toBeVisible();
});

test('sidebar project switcher filters projects, exposes its active state, and supports arrow navigation', async ({ page }) => {
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [
    { id: 9600, name: 'Alpha workspace', language: 'en' }, { id: 9601, name: 'Beta workspace', language: 'en' },
  ] }));
  await page.route(/\/api\/v1\/projects\/\d+\/.*/, route => {
    const path = new URL(route.request().url()).pathname;
    if (/(analysis-runs|history|experiments|experiment-runs|capital-plans)$/.test(path)) return route.fulfill({ json: [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.setViewportSize({ width: 1280, height: 844 });
  await page.goto('/');
  await expect(page.locator('.project-sidebar')).toBeVisible();
  await expect(page.locator('.workspace-layout')).toBeVisible();
  await expect(page.locator('.project-sidebar')).toHaveCSS('position', 'sticky');
  const [sidebarBox, intakeBox] = await Promise.all([page.locator('.project-sidebar').boundingBox(), page.locator('.intake').boundingBox()]);
  expect((sidebarBox?.x ?? 0) + (sidebarBox?.width ?? 0)).toBeLessThanOrEqual(intakeBox?.x ?? 0);
  expect(sidebarBox?.y).toBeCloseTo(intakeBox?.y ?? 0, 0);
  const search = page.getByLabel('Find a project');
  await search.fill('Beta');
  await expect(page.getByRole('button', { name: 'Alpha workspace' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Beta workspace' })).toBeVisible();
  await search.fill('');
  await page.getByRole('button', { name: 'Alpha workspace' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('button', { name: 'Beta workspace' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: 'Beta workspace' })).toHaveAttribute('aria-current', 'true');
  await search.fill('not found');
  await expect(page.getByText('No projects match your search.')).toBeVisible();
  await search.fill('');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('.project-sidebar')).toHaveCSS('position', 'static');
  await expect(page.locator('.project-sidebar .projects')).toHaveCSS('display', 'flex');
});
