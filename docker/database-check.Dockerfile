FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_CONSTRAINT=/app/requirements/storage.lock \
    FINANCIAL_AGENT_PROJECT_ROOT=/app

WORKDIR /app

COPY pyproject.toml ./
COPY alembic.ini ./
COPY requirements/ ./requirements/
COPY alembic/ ./alembic/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY schemas/ ./schemas/
COPY tests/ ./tests/

RUN python -m pip install ".[dev,storage]"

CMD ["sh", "-c", "python scripts/verify_database_migrations.py && python -m pytest tests/db -m 'not performance and not ncp_integration' -q && python scripts/export_database_objects.py --check --database-url-env FINANCIAL_AGENT_TEST_DATABASE_URL"]
