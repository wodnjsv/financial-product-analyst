FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_CONSTRAINT=/app/requirements/resolver.lock \
    FINANCIAL_AGENT_PROJECT_ROOT=/app

WORKDIR /app

COPY .dockerignore ./
COPY pyproject.toml ./
COPY alembic.ini ./
COPY requirements/resolver.lock ./requirements/resolver.lock
COPY alembic/ ./alembic/
COPY config/intent/ ./config/intent/
COPY docker/initdb/001-ncp-extension-layout.sql ./docker/initdb/001-ncp-extension-layout.sql
COPY docker/postgres.compose.yml ./docker/postgres.compose.yml
COPY docker/resolver-check.Dockerfile ./docker/resolver-check.Dockerfile
COPY ontology/ ./ontology/
COPY schemas/ ./schemas/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/

RUN python -m pip install ".[dev,storage,graph,resolver]"

CMD ["sh", "-c", "python scripts/export_contract_schemas.py --check &&\npython scripts/export_intent_schemas.py --check &&\npython -m pytest tests/intent tests/evaluation/intent -m 'not postgres and not clova_integration' -q &&\npython -m pytest tests/contracts -q &&\nif [ -n \"${FINANCIAL_AGENT_TEST_DATABASE_URL:-}\" ]\nthen\npython scripts/verify_database_migrations.py &&\npython -m pytest tests/db/test_intent_entity_repository.py tests/db/test_artifact_repository.py -q &&\npython scripts/export_database_objects.py --check --database-url-env FINANCIAL_AGENT_TEST_DATABASE_URL\nfi"]
