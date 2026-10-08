# План достижения полного соответствия брифу v1.1

## Этап 0 — baseline и quality gates
- Зафиксировать API/UI/Compose baseline.
- Ввести обязательные CI gates: backend, frontend build, axe, Playwright against Compose; отсутствие `test.skip` для обязательного lifecycle.
- Проверять migration upgrade и restart persistence.

## Этап 1 — durable research pipeline
- Добавить модели ResearchStageRun/ResearchDocument/ResearchClaim/ResearchVerification с run/project/source/claim provenance, hashes и idempotency.
- Оркестрировать search → fetch → extract → claims → verify → cluster в `run_execution` с checkpoint/resume/lease heartbeat.
- Исправить provider contract (`max_results`), retry/failure states и stage outputs.
- Candidate claims остаются unverified; promotion требует direction/tier/category и является atomic/idempotent.
- Report использует persisted stage records, а не только `AnalysisRun.result`.

## Этап 2 — decision/report completeness
- Гарантировать аналитические блоки: market, ICP, problem, competition, monetization, distribution, risks, economics, experiments.
- UNKNOWN при недостатке данных; 5–10 hypotheses; decisive facts/unknowns.
- Fatal/blocking NO-GO всегда блокирует project decision.
- Добавить contradiction, freshness, independence и source-cluster evals.

## Этап 3 — economics
- Типизированный provenance schema.
- Reliability зависит от source/confidence/observed/benchmark/inferred, а не только наличия чисел.
- Реализовать EVSI/EVPI либо явно документированный deterministic HEURISTIC fallback с method, assumptions, decision threshold и candidate budgets.
- P10/P50/P90, sensitivity, unknown churn и immutable snapshots.

## Этап 4 — capital
- Автоматически строить inputs из persisted hypotheses/evidence/experiment outcomes.
- Fatal hypotheses, adverse evidence и failed experiments блокируют gates.
- System-derived metrics нельзя переопределить request payload.
- Idempotency-Key + unique persistence.
- Transactional row lock/atomic budget invariant и concurrency tests.
- Capital ladder €0/€100/€500/€1k и learning/unlock conditions.

## Этап 5 — UI/accessibility/localization
- Полная RU/EN translation catalog для visible, placeholder и aria strings.
- Настоящие ARIA tabs/tablist/tabpanel, keyboard arrows/Home/End, active panel visibility.
- CAPITAL: metric inputs, gate evaluation, allocation, errors, durable history.
- Experiments: proposal → run → approve → start/stop → measurements → evaluate actual-vs-forecast.
- Axe/keyboard/RU tests для всех панелей.

## Этап 6 — full lifecycle E2E
- Compose-backed test: project → analysis run → worker completion → hypotheses → research candidates → verify/promote → verdict → economics → capital plan/gates/allocation → experiment run → export.
- Не skip при API failure; skip допускается только при явно отключённом Docker profile.
- Migration from empty DB, service restart, data re-read and export verification.
- CI job запускает Compose, readiness, Playwright и cleanup.

## Definition of Done
- Все MUST из брифа имеют код и интеграционный тест.
- Все database migrations применяются на чистой PostgreSQL.
- Backend tests, frontend build, axe, full Compose Playwright lifecycle проходят.
- Нет silent skips, post-call cap violations, client metric bypasses или overspend races.
- `PROJECT_DESCRIPTION.md` обновлён только после успешного полного прогона.
