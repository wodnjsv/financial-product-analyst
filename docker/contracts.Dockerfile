FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_CONSTRAINT=/app/requirements/contracts.lock

WORKDIR /app

COPY pyproject.toml ./
COPY requirements/contracts.lock ./requirements/contracts.lock
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY schemas/ ./schemas/
COPY tests/ ./tests/

RUN python -m pip install ".[dev]" \
    && python -m pytest tests/contracts -q \
    && python scripts/export_contract_schemas.py --check

CMD ["python", "scripts/export_contract_schemas.py", "--check"]
