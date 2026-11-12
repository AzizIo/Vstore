# VILTARA SHOP backend

## Requirements

- Python 3.13 or newer.
- PostgreSQL 16 for the integration suite.
- Redis 7 for the API-backed E2E environment.

## Local setup

From this directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Set `TEST_DATABASE_URL` to a disposable PostgreSQL database before running tests marked for integration. Do not point tests or migration commands at production data.

## Quality checks

Run Ruff:

```bash
ruff check app tests migrations scripts
```

Run the complete backend test suite with coverage:

```bash
pytest --cov=app --cov-report=term-missing -q
```

The PostgreSQL integration tests live in `tests/test_postgres_integration.py`. They exercise transactional and concurrency behavior against an isolated PostgreSQL database and must not be replaced by SQLite-only coverage.

## API-backed end-to-end fixture

The CI API-backed Playwright workflow provisions disposable PostgreSQL and Redis services, applies Alembic migrations, starts a local TON provider fixture and the FastAPI app, then checks persisted order, event and notification-outbox records.

For the same safety preflight used by CI:

```bash
python -m scripts.e2e_preflight
python -m alembic upgrade head
```

Only run the preflight/migration sequence against a disposable test database. The E2E fixture uses synthetic Telegram credentials and a local TON provider; it does not contact a real Telegram bot or a live TON provider.
