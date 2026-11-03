from __future__ import annotations

import os
from pathlib import Path
from time import monotonic

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.ingestion.capacity_probe import (
    measure_application_storage_bytes,
    measure_database_acceptance,
    require_stage03_local_acceptance,
    write_database_acceptance_report,
)
from financial_agent.ingestion.official_pipeline import (
    OrganizerInputs,
    build_stage03b_dataset,
    load_official_manifests,
)
from financial_agent.ingestion.official.models import OfficialSnapshotManifest
from financial_agent.ingestion.pipeline import SOURCE_SPECS
from financial_agent.ingestion.sources import sha256_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_COMPLETION = os.getenv("RUN_STAGE03_LOCAL_COMPLETION_TESTS") == "1"
ORGANIZER_ROOT = os.getenv("FINANCIAL_AGENT_CURRENT_ORGANIZER_ROOT")
CAPTURE_ROOTS = os.getenv("FINANCIAL_AGENT_STAGE03_CAPTURE_ROOTS")
DATABASE_A_URL = os.getenv("LOCAL_STAGE03_A_DATABASE_URL")
REPORT_A_PATH = os.getenv("FINANCIAL_AGENT_STAGE03_A_ACCEPTANCE_PATH")


@pytest.fixture(scope="session", autouse=True)
def _require_explicit_completion_configuration() -> None:
    if RUN_COMPLETION and any(
        value is None
        for value in (
            ORGANIZER_ROOT,
            CAPTURE_ROOTS,
            DATABASE_A_URL,
            REPORT_A_PATH,
        )
    ):
        pytest.fail("STAGE03_COMPLETION_CONFIGURATION_MISSING", pytrace=False)


def _organizer_inputs(root: Path) -> OrganizerInputs:
    data_paths = {
        code: root / spec.data_file_name for code, spec in SOURCE_SPECS.items()
    }
    schema_paths = {
        code: root / spec.schema_file_name
        for code, spec in SOURCE_SPECS.items()
    }
    return OrganizerInputs(
        data_paths=data_paths,
        schema_paths=schema_paths,
        data_sha256={
            code: sha256_path(path) for code, path in data_paths.items()
        },
        schema_sha256={
            code: sha256_path(path) for code, path in schema_paths.items()
        },
    )


def _capture_inputs() -> tuple[
    tuple[OfficialSnapshotManifest, ...],
    tuple[Path, ...],
]:
    roots = tuple(
        Path(value)
        for value in (CAPTURE_ROOTS or "").split(os.pathsep)
        if value
    )
    manifests = tuple(
        manifest
        for root in roots
        for manifest in load_official_manifests(root / "manifests")
    )
    return manifests, tuple(root / "objects" for root in roots)


def _async_url(database_url: str) -> str:
    normalized = normalize_psycopg_url(database_url)
    if normalized.startswith("postgresql://"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    return normalized


def _migrate(database_url: str) -> None:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _build_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        _async_url(database_url),
        pool_size=5,
        max_overflow=0,
        connect_args={"options": "-c role=fa_build -c timezone=UTC"},
    )


async def _assert_empty(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        count = await connection.scalar(
            sa.text("SELECT count(*) FROM operations.dataset_version")
        )
    assert count == 0


@pytest.mark.organizer_data
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_COMPLETION,
    reason="explicit Stage 03 local completion gate is disabled",
)
async def test_clean_stage03_build_is_accepted_and_remains_inactive() -> None:
    assert DATABASE_A_URL is not None
    _migrate(DATABASE_A_URL)
    organizer_inputs = _organizer_inputs(Path(ORGANIZER_ROOT or ""))
    manifests, object_roots = _capture_inputs()
    engine = _build_engine(DATABASE_A_URL)
    try:
        await _assert_empty(engine)
        started = monotonic()
        build_report = await build_stage03b_dataset(
            engine,
            dataset_version="stage03-final-a",
            organizer_inputs=organizer_inputs,
            official_manifests=manifests,
            official_object_root=object_roots,
        )
        duration = monotonic() - started
        acceptance = await measure_database_acceptance(engine, build_report)
        require_stage03_local_acceptance(acceptance)
        storage_bytes = await measure_application_storage_bytes(engine)
    finally:
        await engine.dispose()

    write_database_acceptance_report(acceptance, Path(REPORT_A_PATH or ""))
    assert (acceptance.dataset_status, acceptance.active) == ("building", False)
    assert "KRX_ETF_DAILY" not in acceptance.approved_source_codes
    assert acceptance.organizer_missing_external_substitute_count == 0
    assert acceptance.organizer_nonvalue_observation_count > 0
    assert acceptance.organizer_zero_observation_count > 0
    print(
        "STAGE03_LOCAL_ACCEPTANCE_MEASURED "
        f"duration_seconds={duration:.3f} "
        f"storage_bytes={storage_bytes} "
        f"acceptance={acceptance.reproducibility_hash}"
    )
