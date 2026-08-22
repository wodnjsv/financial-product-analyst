FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_CONSTRAINT=/app/requirements/ingestion.lock \
    FINANCIAL_AGENT_PROJECT_ROOT=/app

WORKDIR /app

COPY pyproject.toml ./
COPY requirements/ingestion.lock ./requirements/ingestion.lock
COPY docker/ingestion-check.Dockerfile ./docker/ingestion-check.Dockerfile
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY schemas/ ./schemas/
COPY tests/ ./tests/

RUN python -m pip install ".[dev,storage,ingestion]" \
    && python -m pytest tests/contracts tests/ingestion \
       -m "not postgres and not organizer_data and not object_storage and not ncp_integration" -q \
    && python scripts/export_contract_schemas.py --check

CMD ["python", "-m", "pytest", "tests/ingestion", "-m", "not postgres and not organizer_data and not object_storage and not ncp_integration", "-q"]
