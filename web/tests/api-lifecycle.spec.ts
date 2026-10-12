import { expect, test, type APIRequestContext } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const base = (process.env.API_URL || 'http://localhost:8000').replace(/\/$/, '');

async function api(request: APIRequestContext, method: 'get' | 'post', endpoint: string, data?: unknown) {
  const response = await request[method](`${base}${endpoint}`, data === undefined ? undefined : { data });
  expect(response.ok(), `${method.toUpperCase()} ${endpoint} returned ${response.status()}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

async function requireReady(request: APIRequestContext) {
  try {
    const ready = await request.get(`${base}/ready`);
    if (!ready.ok()) throw new Error(`readiness returned ${ready.status()}: ${await ready.text()}`);
    expect((await ready.json()).status).toBe('ok');
  } catch (error) {
    throw new Error(`Compose API is required for this lifecycle test: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function waitForReady(request: APIRequestContext) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const response = await request.get(`${base}/ready`).catch(() => undefined);
    if (response?.ok()) return;
    await new Promise(resolve => setTimeout(resolve, 1_000));
  }
  throw new Error('API did not become ready after Docker Compose restart');
}

test('Compose API lifecycle persists every decision artifact across restart', async ({ page, request }) => {
  await requireReady(request);

  const project = await api(request, 'post', '/api/v1/projects', {
    name: `E2E lifecycle ${Date.now()}`, language: 'en', budget: 1000,
  });
  const prefix = `/api/v1/projects/${project.id}`;
  const analysisRun = await api(request, 'post', `${prefix}/analysis-runs`, { inputs: { market: 'test market' } });
  expect(analysisRun.status).toBe('queued');

  const hypothesis = await api(request, 'post', `${prefix}/hypotheses`, {
    statement: 'At least half of invited users will complete the proposed workflow.',
    category: 'demand', importance: 0.9,
  });
  const candidate = await api(request, 'post', `${prefix}/evidence-candidates`, {
    claim: 'A controlled customer interview supports demand for this workflow.',
    source_name: 'Lifecycle test source', url: `https://example.test/evidence/${project.id}`,
    hypothesis_id: hypothesis.id, source_quality: 0.9,
  });
  await api(request, 'post', `${prefix}/evidence-candidates/${candidate.id}/verify`, { verification_reason: 'Reviewed by lifecycle test' });
  const evidence = await api(request, 'post', `${prefix}/evidence-candidates/${candidate.id}/promote`, {
    verification_reason: 'Classified by lifecycle test', direction: 'supporting', tier: 'E2', category: 'demand',
  });
  expect(evidence.candidate_id).toBe(candidate.id);
  const verdict = await api(request, 'post', `${prefix}/hypotheses/${hypothesis.id}/verdict`);
  expect(verdict.hypothesis_id).toBe(hypothesis.id);

  const provenance = Object.fromEntries(['price', 'variable_cost', 'monthly_churn', 'cac', 'fixed_monthly_cost', 'target_ltv_cac_ratio'].map((parameter) => [parameter, {
    source_type: 'verified_evidence', source_id: String(evidence.id), confidence: 'MEDIUM', observed: true,
  }]));
  const economics = await api(request, 'post', `${prefix}/economics/calculate`, {
    currency: 'USD', scenarios: [{ name: 'base', price: 100, variable_cost: 20, monthly_churn: 0.05, cac: 50, parameter_provenance: provenance }],
    sensitivity: { monthly_churn_rates: [0.03, 0.05] },
  });
  expect(economics.snapshot_id).toBeTruthy();
  expect(economics.reliability).toBeDefined();

  const capitalPlan = await api(request, 'post', `${prefix}/capital-plans`, {
    available_budget: 1000, currency: 'USD', gates: [{ name: 'Demand gate', recommended_spend: 200,
      unlock_conditions: [{ metric: 'verified_evidence_count', operator: '>=', value: 1 }] }],
  });
  const gates = await api(request, 'post', `${prefix}/capital-plans/${capitalPlan.id}/gates/evaluate`, { metrics: {} });
  expect(gates.gates[0].status).toBe('UNLOCKED');
  const allocation = await api(request, 'post', `${prefix}/capital-plans/${capitalPlan.id}/allocate`, {
    candidate_experiments: [{ name: 'Demand test', cost: 200, probability_of_decisive_result: 0.8 }],
  });
  expect(allocation.allocations).toHaveLength(1);

  const templates = await api(request, 'get', `${prefix}/experiments/templates`);
  const proposal = await api(request, 'post', `${prefix}/experiments/propose`, {
    template_key: templates[0].template_key, hypothesis_id: hypothesis.id, title: 'Lifecycle demand test',
  });
  const experiment = await api(request, 'post', `${prefix}/experiment-runs`, {
    proposal_id: proposal.id, title: 'Lifecycle demand test', forecast: { metric: 'conversions', expected_value: 10 },
  });
  await api(request, 'post', `${prefix}/experiment-runs/${experiment.id}/approvals`, { actor: 'e2e' });
  await api(request, 'post', `${prefix}/experiment-runs/${experiment.id}/start`);
  await api(request, 'post', `${prefix}/experiment-runs/${experiment.id}/measurements`, { metric: 'conversions', value: 12, unit: 'users' });
  const evaluation = await api(request, 'post', `${prefix}/experiment-runs/${experiment.id}/evaluate`);
  expect(evaluation.result.outcome).toBe('met');

  const report = await api(request, 'get', `${prefix}/report`);
  expect(report.format_version).toBeTruthy();
  for (const section of ['icp', 'market', 'competitor', 'monetization', 'risk_map']) {
    expect(report[section].status).toBeDefined();
  }
  expect(report.data_gaps).toEqual(expect.any(Array));
  expect(report.latest_economics.reliability).toBeDefined();
  const exported = await api(request, 'get', `${prefix}/export/json`);
  expect(exported.project.id).toBe(project.id);
  expect(exported.evidence).toHaveLength(1);

  execFileSync('docker', ['compose', 'restart', 'api'], { cwd: path.resolve(__dirname, '../..'), stdio: 'pipe' });
  await waitForReady(request);
  const persisted = await api(request, 'get', `${prefix}/report`);
  expect(persisted.hypotheses.map((item: { id: number }) => item.id)).toContain(hypothesis.id);
  expect(persisted.evidence.map((item: { id: number }) => item.id)).toContain(evidence.id);
  expect(persisted.experiments.map((item: { id: number }) => item.id)).toContain(proposal.id);

  await page.goto('/');
  await expect(page.getByRole('button', { name: new RegExp(project.name) })).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: new RegExp(project.name) }).click();
  await expect(page.locator('#workspace')).toBeVisible({ timeout: 10_000 });
});
