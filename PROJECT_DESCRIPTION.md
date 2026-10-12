# AI Business Hypothesis Analyst — описание проекта

> **Статус соответствия брифу v1.1 (актуальный):** Release 0.1 работает и проходит автоматические unit/API/UI проверки, но проект **не является 100% соответствующим брифу**. Полный research claim-verification pipeline, автоматическая интеграция capital allocator с hypotheses/evidence/experiments и часть decision-oriented persistence/API остаются Release 0.2 задачами. Тестовые данные также не подтверждают реальную коммерческую привлекательность идеи.

## 1. Назначение

AI Business Hypothesis Analyst — локальная single-user система для проверки бизнес-идеи до полноценной разработки продукта.

Система превращает минимальное описание идеи в структурированный цикл анализа:

```text
Project Intake
  → Analysis Run
  → Research
  → Hypotheses
  → Evidence Ledger
  → Hypothesis Verdicts
  → Economics
  → Experiments
  → Actual vs Forecast
  → Project Verdict
  → Decision Report / Export
```

Главная цель — не просто выдать текстовое мнение, а показать:

- какие предположения лежат в основе идеи;
- какие из них подтверждены или опровергнуты;
- какие данные пока неизвестны;
- при каких условиях идея может работать;
- какие условия приведут к остановке или пересмотру идеи;
- какой следующий тест даст максимальную полезную информацию.

Система не должна выдавать положительный вывод только потому, что идея хорошо описана. Все арифметические решения и итоговые правила выполняются детерминированным Python-кодом.

## 2. Границы версии

### Входит в Release 0.1

- локальная работа одного пользователя;
- создание и удаление проектов;
- intake на русском и английском языках;
- генерация базовых гипотез;
- research через подключённый provider;
- Evidence Ledger с provenance;
- verdict по отдельным гипотезам;
- project-level verdict;
- unit economics и Monte Carlo simulation;
- capital plan, capital gates и минимальная текущая allocation-рекомендация;
- шаблоны экспериментов;
- approval и lifecycle experiment runs;
- measurements и deterministic actual-vs-forecast;
- audit history;
- JSON, Markdown и print-ready HTML export;
- Docker Compose deployment.

### Не входит в текущую версию

- authentication и multi-tenancy;
- автоматический запуск рекламы, платежей, email-кампаний или интервью;
- реальное внешнее выполнение экспериментов;
- production SaaS security;
- платёжные интеграции;
- автоматическое доказательство фактов из одного search snippet.

Система формирует план и анализирует внесённые результаты. Она не может самостоятельно получить оплату клиента или провести интервью без внешней интеграции.

## 3. Как работает анализ

### 3.1 Project Intake

Пользователь вводит:

- название и описание идеи;
- тип бизнеса;
- географию;
- бюджет и срок;
- известные факты;
- язык проекта.

Минимального описания достаточно для запуска предварительного анализа. Чем больше конкретных исходных данных, тем полезнее итоговый отчёт.

### 3.2 Analysis Run

Analysis Run — durable-задача в очереди. Она имеет состояния:

```text
queued → running → completed
                  ↘ failed
```

Для надёжности используются:

- `Idempotency-Key`;
- lease ownership;
- lease token;
- heartbeat;
- retry и backoff;
- `max_attempts`;
- восстановление просроченных задач;
- cost cap и лимиты research/tool calls.

Worker выполняется отдельным процессом:

```bash
python -m app.workers.main
```

### 3.3 Research

Если настроены `SEARCH_API_KEY` и `SEARCH_API_URL`, система вызывает search provider и сохраняет результаты с источниками.

В текущем Release 0.1 search/fetch/extract/claim/verify/cluster представлены отдельными service boundaries, но полный production-grade автоматический pipeline с отдельными durable claim records и автоматической независимой верификацией ещё не завершён. `EvidenceCandidate` и review API доступны; candidate не считается decision evidence до явной классификации и проверки.

Если внешние ключи не настроены, используется starter fallback. В этом режиме система всё равно создаёт гипотезы и отчёт, но не притворяется, что провела внешний market research.

Search snippets по умолчанию являются кандидатами на проверку и не считаются автоматически доказательствами. Они отображаются как unverified market findings.

### 3.4 Гипотезы

Из intake формируются основные классы предположений:

- problem — проблема существует и достаточно болезненна;
- customer — существует конкретный покупатель;
- solution — решение даёт измеримое улучшение;
- willingness_to_pay — клиент готов платить;
- channel — клиента можно привлекать по доступной цене.

Гипотезы ранжируются по `importance`. Наиболее важными считаются предположения, провал которых делает идею экономически или практически бессмысленной.

Пользователь не обязан сам выбирать эти гипотезы: система формирует и ранжирует их автоматически.

### 3.5 Evidence Ledger

Evidence — проверяемый факт, связанный с гипотезой. Для каждого evidence хранятся:

- содержание;
- источник и URL;
- дата получения;
- направление: `supporting` или `contradicting`;
- tier качества `E0–E6`;
- категория;
- relevance;
- source quality;
- source cluster;
- признак независимости;
- provenance.

Примеры сильного evidence:

- клиент подписал платный пилот;
- несколько независимых интервью подтверждают одну проблему;
- измеренная конверсия превысила заранее заданный порог;
- независимый источник подтверждает размер рынка.

Фраза «рынок большой» без источника и метода является неизвестным, а не доказательством.

### 3.6 Verdict по гипотезе

Deterministic Verdict Engine рассчитывает:

- support score;
- evidence coverage;
- data quality;
- supporting/contradicting mass;
- независимость источников;
- decisive facts;
- unknowns.

Возможные verdict:

- `PROMISING` — достаточно качественной поддерживающей информации;
- `WEAK` — данные указывают на слабую гипотезу;
- `NO-GO-FOR-NOW` — есть существенные противоречия или kill gate;
- `UNPROVEN` — данных недостаточно для уверенного вывода.

`UNPROVEN` — это не ошибка и не утверждение, что идея плохая. Это означает, что вывод ещё нельзя обосновать имеющимися данными.

### 3.7 Economics

Экономика рассчитывается кодом, а не LLM. Поддерживаются:

- price;
- variable cost;
- monthly churn;
- CAC;
- fixed monthly cost;
- LTV/CAC;
- payback;
- sensitivity analysis;
- capital steps;
- Monte Carlo simulation с seed;
- P10/P50/P90;
- break-even;
- budget bands;
- learning value.

Каждый economics snapshot сохраняет входные данные и результат. Модель `EconomicParameter` для provenance уже добавлена, однако автоматическое заполнение provenance для каждого Monte Carlo parameter и полное влияние reliability-gating на все economics flows ещё требуют завершения.

Совместимый legacy `POST /api/v1/projects/{project_id}/economics/simulate` принимает распределения unit economics и сохраняется без перенаправления: его контракт не содержит Beta prior, Binomial likelihood, decision threshold или utilities, необходимые для байесовской оценки. Поэтому `scenarios[].value_of_information.status` всегда `HEURISTIC`; его EVPI/EVSI — только deterministic per-customer contribution fallback, а не вероятностная финансовая модель. Для явной байесовской модели нужно вызывать `POST /api/v1/projects/{project_id}/economics/value-of-information`, передавая prior, threshold, utilities и candidate experiments.

### 3.8 Experiments

Система предлагает тесты с:

- целью;
- проверяемой гипотезой;
- аудиторией;
- sample size;
- forecast;
- pass rule;
- partial rule;
- fail rule;
- stop rule;
- ожидаемой ценностью обучения.

Локальный lifecycle эксперимента:

```text
proposed → approved → running → completed
                             ↘ stopped
```

Для завершённого теста пользователь вносит measurements. Затем код сравнивает фактические значения с forecast и выдаёт deterministic actual-vs-forecast result: `met`, `partial`, `missed` или соответствующий итоговый статус.

После завершения эксперимента project report пересчитывается.

## 4. Расширенный итоговый отчёт

Project verdict содержит не только короткий статус, но и decision-ready анализ:

- `idea_summary` — структурированное описание идеи, intake и гипотез;
- `tested_hypotheses` — какие предположения проверялись;
- `market_findings` — найденные рыночные факты и неподтверждённые кандидаты;
- `evidence_quality` — качество и полнота базы доказательств;
- `success_conditions` — условия, при которых модель может работать;
- `failure_conditions` — условия провала;
- `kill_gates` — критерии остановки;
- `decisive_facts` — наиболее важные факты;
- `unknowns` — неизвестные данные;
- `next_recommended_tests` — следующие тесты;
- economics summary;
- verdict rule и coverage.

Пример интерпретации:

```text
PROMISING

Идея может работать, если:
- платная конверсия сохраняется выше заданного порога;
- CAC остаётся ниже допустимого значения;
- churn не превышает сценарный уровень;
- подтверждён сегмент клиентов.

Идею нужно остановить или пересмотреть, если:
- LTV становится ниже CAC;
- платные пилоты не подтверждаются;
- конверсия существенно ниже forecast;
- ключевой buyer не принимает решение о покупке.
```

## 5. Архитектура

### Backend

- Python 3.12;
- FastAPI;
- SQLAlchemy;
- PostgreSQL в Docker Compose;
- SQLite для локальных тестов;
- Alembic migrations;
- отдельный worker;
- deterministic engines для verdict, economics и experiment evaluation.

Основные каталоги:

```text
api/app/api/       HTTP endpoints
api/app/db/        SQLAlchemy models and sessions
api/app/engines/   deterministic business logic
api/app/services/  orchestration, research, snapshots, audit
api/app/workers/   durable analysis worker
api/app/schemas/   Pydantic request/response models
api/tests/         backend tests
```

### Frontend

- Next.js 16.4;
- React;
- TypeScript;
- dashboard на `/`;
- RU/EN toggle;
- project intake;
- verdict and hypotheses;
- evidence;
- economics;
- experiments;
- extended report;
- loading/error states;
- export actions.

### Docker Compose

Сервисы:

```text
postgres  — database
migrator  — alembic upgrade head
api       — FastAPI/Uvicorn
worker    — analysis queue worker
web       — Next.js application
```

API не выполняет `create_all()` при старте. Схема базы изменяется только через Alembic.

## 6. Основные endpoint-группы

```text
POST   /api/v1/projects
GET    /api/v1/projects
GET    /api/v1/projects/{project_id}/report
GET    /api/v1/projects/{project_id}/history
GET    /api/v1/projects/{project_id}/decision

POST   /api/v1/projects/{project_id}/analysis-runs
GET    /api/v1/projects/{project_id}/analysis-runs/{run_id}

POST   /api/v1/projects/{project_id}/hypotheses
GET    /api/v1/projects/{project_id}/hypotheses
POST   /api/v1/projects/{project_id}/hypotheses/{hypothesis_id}/verdict

POST   /api/v1/projects/{project_id}/evidence
GET    /api/v1/projects/{project_id}/evidence-candidates
POST   /api/v1/projects/{project_id}/evidence-candidates
POST   /api/v1/projects/{project_id}/evidence-candidates/{candidate_id}/verify
POST   /api/v1/projects/{project_id}/evidence-candidates/{candidate_id}/reject
POST   /api/v1/projects/{project_id}/verdict
GET    /api/v1/projects/{project_id}/verdict

POST   /api/v1/projects/{project_id}/economics/calculate
POST   /api/v1/projects/{project_id}/economics/simulate
POST   /api/v1/projects/{project_id}/economics/value-of-information
POST   /api/v1/projects/{project_id}/economics/capital-plan

GET    /api/v1/projects/{project_id}/experiments/templates
POST   /api/v1/projects/{project_id}/experiments/propose
GET    /api/v1/projects/{project_id}/experiments/recommend-next-test

Capital intelligence endpoints are currently exposed under `/api/v1/capital-plans/{plan_id}/...`; the final decision-oriented `/capital/allocate`, `/capital/plan` and `/capital/gates/{gate_id}/evaluate` aliases are not yet complete.

POST   /api/v1/projects/{project_id}/experiment-runs
POST   /api/v1/projects/{project_id}/experiment-runs/{run_id}/approvals
POST   /api/v1/projects/{project_id}/experiment-runs/{run_id}/start
POST   /api/v1/projects/{project_id}/experiment-runs/{run_id}/measurements
POST   /api/v1/projects/{project_id}/experiment-runs/{run_id}/evaluate

GET    /api/v1/projects/{project_id}/export/json
GET    /api/v1/projects/{project_id}/export/markdown
GET    /api/v1/projects/{project_id}/export/html
```

Проверки доступности:

```text
GET /health  — liveness
GET /ready   — database + migration readiness
```

## 7. Запуск

```bash
cp .env.example .env
# При необходимости добавить OPENAI_API_KEY и SEARCH_API_KEY

docker compose up --build
```

Адреса:

```text
Web: http://127.0.0.1:3000
API: http://127.0.0.1:8000
API docs: http://127.0.0.1:8000/docs
```

Локальные проверки:

```bash
cd api
pytest -q

cd ../web
npm ci
npm run build
npm audit --audit-level=high
npm run test:e2e

cd ..
docker compose config --quiet
docker compose up --build
# в работающем Compose:
docker compose exec -T api alembic -c /app/alembic.ini check
```

Актуальный проверенный результат: backend — 81 passed, frontend build — PASS, npm audit — 0 vulnerabilities, Playwright smoke — 2 passed. Полный API-backed browser lifecycle требует работающих Docker/PostgreSQL; UI smoke может использовать mocked API. Для production acceptance необходимо отдельно выполнить полный lifecycle на реальном Compose окружении.

## 8. Как интерпретировать успешный сценарий

Успешный pipeline не означает, что любая идея автоматически истинна. Он означает, что система:

1. корректно создала проект;
2. поставила analysis run в очередь;
3. обработала его worker-ом;
4. сформировала гипотезы;
5. сохранила evidence и provenance;
6. рассчитала economics;
7. провела experiment lifecycle;
8. сравнила actual с forecast;
9. сформировала расширенный verdict;
10. экспортировала результат без потери данных.

Для реального бизнес-решения в систему должны попасть реальные источники и измерения. Тестовые данные проверяют работу механики, но не доказывают коммерческую привлекательность конкретного проекта.

## 9. Известные ограничения и направления развития

Следующие функции относятся к будущему Release 0.2+ или требуют завершения перед заявлением о полном соответствии брифу:

- полный search → fetch → extract → claims → verify → cluster pipeline с durable claim persistence;
- автоматическая интеграция allocator с ranked hypotheses, evidence и всеми candidate experiments;
- automatic Capital Gates из critical hypotheses;
- полная per-parameter provenance и reliability gating для Monte Carlo;
- отдельные persisted market assessment/project decision snapshots;
- decision-oriented capital endpoint aliases;
- полноценная UI CAPITAL-вкладка с gate allocation и сравнением альтернатив;
- подключение реального execution experiments;
- измерения из внешних аналитических систем;
- payments и billing;
- рекламные кабинеты;
- автоматические интервью и outreach;
- более глубокое извлечение claims из источников;
- contradiction detection;
- расширенный freshness/provenance scoring для всех research claims и economics parameters;
- authentication;
- multi-tenancy;
- production security hardening.
