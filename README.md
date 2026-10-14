# AI Experimentation System

Локальная система для структурированной проверки бизнес-идей: от описания проекта и гипотез до анализа доказательств, экономики, экспериментов и итогового решения.

> Проект находится в активной разработке. Это локальный single-user инструмент, а не готовый production SaaS.

## Возможности

- intake проекта на русском и английском языках;
- автоматическое формирование и ранжирование гипотез;
- research через подключаемый search provider или локальный fallback;
- Evidence Ledger с источниками, provenance и оценкой качества;
- детерминированные verdict по гипотезам и проекту: `PROMISING`, `WEAK`, `NO-GO-FOR-NOW`, `UNPROVEN`;
- unit economics, sensitivity analysis и Monte Carlo simulation;
- value of information, capital plan и capital gates;
- шаблоны экспериментов и lifecycle `proposed → approved → running → completed`;
- ввод измерений и сравнение фактических результатов с прогнозом;
- audit history и экспорт в JSON, Markdown и HTML;
- Docker Compose для запуска всех сервисов.

Система помогает принимать решения на основе проверяемых данных. Она не заменяет интервью, платные пилоты или реальное рыночное исследование: неподтверждённые search snippets не считаются доказательствами автоматически.

## Архитектура

- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Alembic;
- **База данных:** PostgreSQL в Compose, SQLite для локальных тестов;
- **Worker:** отдельный процесс для очереди analysis runs;
- **Frontend:** Next.js, React, TypeScript;
- **Проверки:** pytest, frontend build и Playwright.

Структура основных каталогов:

```text
api/app/api/       HTTP endpoints
api/app/db/        модели и сессии SQLAlchemy
api/app/engines/   детерминированная бизнес-логика
api/app/services/  orchestration, research, snapshots и audit
api/app/workers/   worker очереди анализа
api/tests/         backend-тесты
web/app/           Next.js интерфейс
web/tests/         UI/E2E-тесты
```

## Быстрый запуск через Docker

Требуется Docker с Docker Compose.

```bash
cp .env.example .env
# При необходимости добавьте ключи в .env:
# OPENAI_API_KEY=...
# SEARCH_API_KEY=...
docker compose up --build
```

После запуска:

- Web: http://127.0.0.1:3000
- API: http://127.0.0.1:8000
- API docs: http://127.0.0.1:8000/docs
- liveness: http://127.0.0.1:8000/health
- readiness: http://127.0.0.1:8000/ready

Миграции применяются отдельным сервисом `migrator`; API не изменяет схему базы при старте.

## Локальная разработка и проверки

Backend:

```bash
pip install -r api/requirements.txt
cd api
pytest -q
cd ..
```

Проверка миграций:

```bash
alembic -c alembic.ini upgrade head
alembic -c alembic.ini current
alembic -c alembic.ini check
```

Frontend:

```bash
cd web
npm ci
npm run build
npm run test:e2e
```

## Основные API-группы

```text
POST/GET /api/v1/projects
POST/GET /api/v1/projects/{id}/analysis-runs
POST/GET /api/v1/projects/{id}/hypotheses
POST/GET /api/v1/projects/{id}/evidence
POST/GET /api/v1/projects/{id}/verdict
POST     /api/v1/projects/{id}/economics/calculate
POST     /api/v1/projects/{id}/economics/simulate
POST     /api/v1/projects/{id}/economics/value-of-information
POST/GET /api/v1/projects/{id}/experiments/*
GET      /api/v1/projects/{id}/export/{json|markdown|html}
```

Полная интерактивная спецификация доступна в `/docs` после запуска API.

## Конфигурация и безопасность

Секреты задаются только через `.env`, который не должен добавляться в Git. В репозитории находится только `.env.example` с пустыми значениями. Не публикуйте API-ключи, реальные пользовательские данные или локальные базы данных.

Значения PostgreSQL по умолчанию (`analyst`/`analyst`) предназначены только для локального Docker-запуска. Для публичного или production-развёртывания их необходимо заменить и добавить authentication, HTTPS, управление доступом и отдельную политику хранения данных.

## Лицензия

Проект распространяется по лицензии MIT. См. [LICENSE](LICENSE).
