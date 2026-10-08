# AI Experimentation System

Подробное описание продукта, архитектуры, lifecycle анализа, verdict-правил,
экспериментов, endpoint-групп и ограничений находится в
[`PROJECT_DESCRIPTION.md`](PROJECT_DESCRIPTION.md).

## API database migrations

Database schema is managed by Alembic; the API does not mutate schema on startup. In Docker Compose, the one-shot `migrator` service runs `upgrade head` before the API starts.

From the repository root:

```bash
# Install API dependencies (includes Alembic)
pip install -r api/requirements.txt

# Apply all migrations locally; DATABASE_URL defaults to sqlite:///./app.db
DATABASE_URL='postgresql+psycopg://analyst:analyst@localhost:5432/analyst' \
  alembic -c alembic.ini upgrade head

# Verify the database revision and detect ORM metadata changes without a migration
alembic -c alembic.ini current
alembic -c alembic.ini check

# Generate a reviewed migration after changing app.db.models
alembic -c alembic.ini revision --autogenerate -m "describe schema change"
```

Run API tests with:

```bash
cd api && pytest
```

## Run and operate

```bash
cp .env.example .env
# Optional: set OPENAI_API_KEY and SEARCH_API_KEY in .env
docker compose up --build
```

The API is bound to `127.0.0.1:8000` and the web UI to `127.0.0.1:3000`.
`/health` is a dependency-free liveness probe; `/ready` additionally checks the
DB connection and that Alembic is at the expected revision. Compose waits for
Postgres, migrations, and API health before starting dependent services.

The UI supports English and Russian project intake and generated starter/LLM
hypotheses. Existing projects can be selected from the project list, where
project audit history is also available. Reports can be downloaded as Markdown
or opened as a safe print-ready HTML document and saved as PDF by the browser.

CI runs API tests, verifies migration metadata with `alembic check`, and builds
the Next.js application. To run the same web validation locally:

```bash
cd web && npm ci && npm run build
```
