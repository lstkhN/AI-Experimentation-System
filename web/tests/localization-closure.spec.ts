import { test, expect } from '@playwright/test';

test('Russian workspace localizes backend narratives, comparison titles, gates, and experiment rules', async ({ page }) => {
  const verdict = {
    id: 1, verdict: 'UNPROVEN', decision: 'VALIDATE', action: 'validate_critical_assumptions', rule: 'hypothesis_weak', evidence_coverage: 0,
    market_attractiveness: { status: 'unknown', summary: 'Search snippets are candidates, not confirmed evidence.', market_signals: 0, icp_segments: 0, competitors: 0, unknowns: [] },
    business_viability: { status: 'incomplete', economics_status: 'missing', economics_reliability: 'INSUFFICIENT_CRITICAL_INPUTS', supported_hypotheses: 0, hypotheses_assessed: 1, monetization_assumptions: 0, unknowns: [] },
    experiment_comparison: { status: 'compared', selected: [{ id: 2, title: 'Landing page demand test', status: 'approved' }], why_not_alternatives: [] },
    capital_recommendation: { status: 'gated', currency: 'USD', available_budget: 0, recommended_spend: 0, recommendation: 'No experiment result is available.', gates: [] },
    idea_summary: { description: 'English backend idea description' }, success_conditions: [], failure_conditions: [], tested_hypotheses: [],
    market_findings: [{ title: 'English market finding', url: '', snippet: '', status: 'candidate', evidence_status: 'unverified_search_snippet' }], evidence_quality: {},
    next_recommended_tests: [], economics: { snapshot_id: null, status: 'missing', unknowns: [] }, decisive_facts: [], unknowns: [], kill_gates: [],
    ranked_assumptions: [{ hypothesis_id: 1, statement: 'English ranked assumption', importance: 1, verdict: 'UNPROVEN', coverage: 0, unknowns: [] }], language_metadata: { code: 'ru', source: 'project_intake' }, data_gaps: [], created_at: '',
  };
  await page.route('**/api/v1/projects', route => route.fulfill({ json: [{ id: 9300, name: 'Локализация', language: 'ru' }] }));
  await page.route('**/api/v1/projects/9300/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/verdict') && !path.includes('/hypotheses/')) return route.fulfill({ json: verdict });
    if (/(analysis-runs|history)$/.test(path)) return route.fulfill({ json: [] });
    if (path.endsWith('/hypotheses')) return route.fulfill({ json: [{ id: 1, statement: 'English hypothesis statement', category: 'demand', importance: 1, criticality: 'HIGH', is_blocking: false, status: 'open' }] });
    if (path.endsWith('/experiments')) return route.fulfill({ json: [{ id: 2, hypothesis_id: 1, template_key: 'landing_page_v1', title: 'Landing page demand test', rationale: null, status: 'proposed', created_at: '', rules: { target: { metric: 'qualified conversion rate', unit: 'unique visitors' }, pass_rule: { operator: '>=', threshold: '10%' }, stop_rule: 'Stop at 300 visitors or after 200 when a boundary is conclusive.' } }] });
    if (path.endsWith('/experiment-runs') || path.endsWith('/capital-plans')) return route.fulfill({ json: path.endsWith('/capital-plans') ? [{ id: 3, project_id: 9300, currency: 'USD', available_budget: 0, recommended_spend: 0, gates: [{ id: 1, name: 'Validate: English hypothesis statement', recommended_spend: 0, status: 'LOCKED', unlock_conditions: [] }] }] : [] });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Локализация' }).click();
  await page.getByRole('tab', { name: 'Решение в первую очередь' }).click();
  await expect(page.getByText('Гипотеза', { exact: true })).toBeVisible();
  await expect(page.getByText('Тест спроса на лендинге — одобрен')).toHaveCount(1);
  await expect(page.getByText('Описание идеи', { exact: true })).toBeVisible();
  await expect(page.getByText('Рыночный источник').first()).toBeVisible();
  await expect(page.getByText('Допущение').first()).toBeVisible();
  await expect(page.getByText('English hypothesis statement')).toHaveCount(0);
  await page.getByRole('tab', { name: 'План капитала' }).click();
  await expect(page.getByText('Проверка: гипотеза')).toBeVisible();
  await page.getByRole('tab', { name: 'Предложения экспериментов' }).click();
  await expect(page.getByText('Тест спроса на лендинге', { exact: true })).toBeVisible();
  await expect(page.getByText('конверсия квалифицированных посетителей')).toBeVisible();
  await expect(page.getByText('10%', { exact: true })).toBeVisible();
  await expect(page.getByText('Остановить на 300 посетителях или после 200, когда граница результата определена.')).toBeVisible();
});
