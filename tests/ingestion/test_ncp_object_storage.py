from __future__ import annotations

import os
import tempfile
from pathlib import Path

import boto3
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from financial_agent.ingestion.cli import (
    ObjectStorageEndpointError,
    _async_database_url,
    _validated_object_storage_endpoint,
)
from financial_agent.ingestion.pipeline import SOURCE_SPECS, _preflight_sources
from financial_agent.ingestion.sources import (
    download_verified_object,
    sha256_path,
    verify_local_source,
)


OBJECT_ENVIRONMENT = (
    "FINANCIAL_AGENT_SOURCE_ROOT",
    "FINANCIAL_AGENT_OBJECT_STORAGE_ENDPOINT",
    "FINANCIAL_AGENT_OBJECT_STORAGE_BUCKET",
    "FINANCIAL_AGENT_OBJECT_STORAGE_ACCESS_KEY_ID",
    "FINANCIAL_AGENT_OBJECT_STORAGE_SECRET_ACCESS_KEY",
    "FINANCIAL_AGENT_BUILD_DATABASE_URL",
)
RUN_OBJECT_CHECK = os.getenv("RUN_NCP_OBJECT_STORAGE_TESTS") == "1"
HAS_OBJECT_CONFIGURATION = all(os.getenv(name) for name in OBJECT_ENVIRONMENT)


@pytest.fixture(scope="session", autouse=True)
def _require_explicit_gate_configuration() -> None:
    if RUN_OBJECT_CHECK and not HAS_OBJECT_CONFIGURATION:
        pytest.fail("OBJECT_STORAGE_CONFIGURATION_MISSING", pytrace=False)


def _configuration():
    root = Path(os.environ["FINANCIAL_AGENT_SOURCE_ROOT"])
    data_paths = {
        code: root / spec.data_file_name for code, spec in SOURCE_SPECS.items()
    }
    schema_paths = {
        code: root / spec.schema_file_name for code, spec in SOURCE_SPECS.items()
    }
    data_hashes = {code: sha256_path(path) for code, path in data_paths.items()}
    schema_hashes = {
        code: sha256_path(path) for code, path in schema_paths.items()
    }
    return data_paths, schema_paths, data_hashes, schema_hashes


def _object_storage_client():
    endpoint = _validated_object_storage_endpoint(
        os.environ["FINANCIAL_AGENT_OBJECT_STORAGE_ENDPOINT"]
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ[
            "FINANCIAL_AGENT_OBJECT_STORAGE_ACCESS_KEY_ID"
        ],
        aws_secret_access_key=os.environ[
            "FINANCIAL_AGENT_OBJECT_STORAGE_SECRET_ACCESS_KEY"
        ],
        region_name=os.getenv(
            "FINANCIAL_AGENT_OBJECT_STORAGE_REGION", "kr-standard"
        ),
    )


async def _load_build_lineage(
    database_url: str,
    dataset_version: str,
) -> tuple[object | None, tuple[object, ...], str | None]:
    engine = None
    result: tuple[object | None, tuple[object, ...], str | None]
    try:
        engine = create_async_engine(
            _async_database_url(database_url),
            connect_args={"options": "-c timezone=UTC"},
        )
        async with engine.connect() as connection:
            manifest_hash = await connection.scalar(
                sa.text(
                    "SELECT manifest_hash FROM operations.dataset_version "
                    "WHERE dataset_version = :dataset_version"
                ),
                {"dataset_version": dataset_version},
            )
            source_rows = tuple(
                (
                    await connection.execute(
                        sa.text(
                            "SELECT source_locator_root, content_checksum "
                            "FROM evidence.source_record "
                            "WHERE dataset_version = :dataset_version"
                        ),
                        {"dataset_version": dataset_version},
                    )
                ).all()
            )
        result = (manifest_hash, source_rows, None)
    except SQLAlchemyError:
        result = (None, (), "DATABASE_UNREACHABLE")
    finally:
        if engine is not None:
            try:
                await engine.dispose()
            except SQLAlchemyError:
                result = (None, (), "DATABASE_UNREACHABLE")
    return result


def test_object_storage_gate_rejects_an_unsafe_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FINANCIAL_AGENT_OBJECT_STORAGE_ENDPOINT",
        "http://object.example.invalid",
    )
    monkeypatch.setenv(
        "FINANCIAL_AGENT_OBJECT_STORAGE_ACCESS_KEY_ID",
        "synthetic-access-key",
    )
    monkeypatch.setenv(
        "FINANCIAL_AGENT_OBJECT_STORAGE_SECRET_ACCESS_KEY",
        "synthetic-secret-key",
    )

    with pytest.raises(ObjectStorageEndpointError):
        _object_storage_client()


def test_object_storage_gate_builds_a_client_for_a_safe_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_client = object()
    observed: dict[str, object] = {}
    monkeypatch.setenv(
        "FINANCIAL_AGENT_OBJECT_STORAGE_ENDPOINT",
        "https://object.example.invalid",
    )
    monkeypatch.setenv(
        "FINANCIAL_AGENT_OBJECT_STORAGE_ACCESS_KEY_ID",
        "synthetic-access-key",
    )
    monkeypatch.setenv(
        "FINANCIAL_AGENT_OBJECT_STORAGE_SECRET_ACCESS_KEY",
        "synthetic-secret-key",
    )

    def client(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return expected_client

    monkeypatch.setattr(boto3, "client", client)

    assert _object_storage_client() is expected_client
    assert observed["args"] == ("s3",)
    assert observed["kwargs"] == {
        "endpoint_url": "https://object.example.invalid",
        "aws_access_key_id": "synthetic-access-key",
        "aws_secret_access_key": "synthetic-secret-key",
        "region_name": "kr-standard",
    }


@pytest.mark.asyncio
async def test_database_lineage_gate_returns_only_a_stable_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disposed = False

    class FailingConnection:
        async def __aenter__(self):
            raise SQLAlchemyError(
                "postgresql://user:PRIVATE-PASSWORD@db.example.invalid/private"
            )

        async def __aexit__(self, *args: object) -> None:
            return None

    class FailingEngine:
        def connect(self) -> FailingConnection:
            return FailingConnection()

        async def dispose(self) -> None:
            nonlocal disposed
            disposed = True

    monkeypatch.setattr(
        "tests.ingestion.test_ncp_object_storage.create_async_engine",
        lambda *args, **kwargs: FailingEngine(),
    )

    result = await _load_build_lineage(
        "postgresql://user:PRIVATE-PASSWORD@db.example.invalid/private",
        "organizer-2026-07-11-03a",
    )

    assert result == (None, (), "DATABASE_UNREACHABLE")
    assert disposed is True


@pytest.mark.asyncio
async def test_database_lineage_gate_sanitizes_disposal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingConnection:
        async def __aenter__(self):
            raise SQLAlchemyError("PRIVATE-CONNECTION-DETAIL")

        async def __aexit__(self, *args: object) -> None:
            return None

    class FailingEngine:
        def connect(self) -> FailingConnection:
            return FailingConnection()

        async def dispose(self) -> None:
            raise SQLAlchemyError("PRIVATE-DISPOSAL-DETAIL")

    monkeypatch.setattr(
        "tests.ingestion.test_ncp_object_storage.create_async_engine",
        lambda *args, **kwargs: FailingEngine(),
    )

    assert await _load_build_lineage(
        "postgresql://user:PRIVATE-PASSWORD@db.example.invalid/private",
        "organizer-2026-07-11-03a",
    ) == (None, (), "DATABASE_UNREACHABLE")


@pytest.mark.object_storage
@pytest.mark.ncp_integration
@pytest.mark.skipif(
    not RUN_OBJECT_CHECK,
    reason="explicit private Object Storage gate is disabled",
)
def test_private_object_storage_bytes_match_all_eight_approved_local_objects() -> None:
    data_paths, schema_paths, data_hashes, schema_hashes = _configuration()
    preflight = _preflight_sources(
        data_paths=data_paths,
        schema_paths=schema_paths,
        data_sha256=data_hashes,
        schema_sha256=schema_hashes,
    )
    assert len(preflight.manifest_hash) == 64
    client = _object_storage_client()
    bucket = os.environ["FINANCIAL_AGENT_OBJECT_STORAGE_BUCKET"]

    with tempfile.TemporaryDirectory(prefix="financial-agent-object-test-") as root:
        destination_root = Path(root)
        checked = 0
        for source_code in sorted(SOURCE_SPECS):
            spec = SOURCE_SPECS[source_code]
            for local_path, expected_hash in (
                (data_paths[source_code], data_hashes[source_code]),
                (schema_paths[source_code], schema_hashes[source_code]),
            ):
                verify_local_source(local_path, expected_hash)
                downloaded = download_verified_object(
                    client,
                    bucket=bucket,
                    key=(
                        f"organizer/2026-07-11/{spec.table_id}/"
                        f"{local_path.name}"
                    ),
                    expected_sha256=expected_hash,
                    destination=destination_root / f"object-{checked}",
                )
                assert sha256_path(downloaded) == expected_hash
                checked += 1
    assert checked == 8


@pytest.mark.object_storage
@pytest.mark.ncp_integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_OBJECT_CHECK,
    reason="explicit private Object Storage gate is disabled",
)
async def test_object_hashes_match_the_build_manifest_and_source_records() -> None:
    data_paths, schema_paths, data_hashes, schema_hashes = _configuration()
    preflight = _preflight_sources(
        data_paths=data_paths,
        schema_paths=schema_paths,
        data_sha256=data_hashes,
        schema_sha256=schema_hashes,
    )
    dataset_version = os.getenv(
        "FINANCIAL_AGENT_DATASET_VERSION",
        "organizer-2026-07-11-03a",
    )
    manifest_hash, source_rows, error_code = await _load_build_lineage(
        os.environ["FINANCIAL_AGENT_BUILD_DATABASE_URL"],
        dataset_version,
    )
    if error_code is not None:
        pytest.fail(error_code, pytrace=False)

    assert manifest_hash == preflight.manifest_hash
    assert dict(source_rows) == {
        SOURCE_SPECS[code].data_file_name: data_hashes[code]
        for code in sorted(SOURCE_SPECS)
    }
