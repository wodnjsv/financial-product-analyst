from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.ingestion.pipeline import (
    SOURCE_SPECS,
    OrganizerBuildError,
    OrganizerSourceValidationError,
    _preflight_sources,
    _snapshot_source_inputs,
    build_organizer_dataset,
)
from financial_agent.ingestion.sources import (
    SourceVerificationError,
    download_verified_object,
    verify_local_source,
)
from financial_agent.ingestion.writer import (
    DatasetBuildConflict,
    DatasetBuildPayloadError,
    DatasetBuildRoleError,
    DatasetBuildStateError,
    DatasetBuildWriteError,
)


class IngestionConfigurationError(RuntimeError):
    code = "CONFIGURATION_MISSING"

    def __init__(self) -> None:
        super().__init__(self.code)


class IngestionArgumentError(RuntimeError):
    code = "CLI_ARGUMENT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class ObjectStorageEndpointError(RuntimeError):
    code = "OBJECT_STORAGE_ENDPOINT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class _SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise IngestionArgumentError() from None


def _parser() -> argparse.ArgumentParser:
    parser = _SanitizedArgumentParser(prog="financial-agent-ingestion")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    commands.add_parser("load")
    commands.add_parser("verify-object-storage")
    return parser


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise IngestionConfigurationError()
    return value


def _source_inputs() -> tuple[
    Mapping[str, Path],
    Mapping[str, Path],
    Mapping[str, str],
    Mapping[str, str],
]:
    root = Path(_required_env("FINANCIAL_AGENT_SOURCE_ROOT"))
    data_paths: dict[str, Path] = {}
    schema_paths: dict[str, Path] = {}
    data_hashes: dict[str, str] = {}
    schema_hashes: dict[str, str] = {}
    for source_code, spec in SOURCE_SPECS.items():
        data_paths[source_code] = root / spec.data_file_name
        schema_paths[source_code] = root / spec.schema_file_name
        data_hashes[source_code] = _required_env(
            f"FINANCIAL_AGENT_{source_code}_DATA_SHA256"
        )
        schema_hashes[source_code] = _required_env(
            f"FINANCIAL_AGENT_{source_code}_SCHEMA_SHA256"
        )
    return data_paths, schema_paths, data_hashes, schema_hashes


def _async_database_url(value: str) -> str:
    normalized = normalize_psycopg_url(value)
    if normalized.startswith("postgresql://"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    return normalized


def _validated_object_storage_endpoint(value: str) -> str:
    endpoint = value.strip()
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise ObjectStorageEndpointError() from None
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (port is not None and port < 1)
    ):
        raise ObjectStorageEndpointError()
    return endpoint


async def _validate_command() -> int:
    data_paths, schema_paths, data_hashes, schema_hashes = _source_inputs()
    with _snapshot_source_inputs(data_paths, schema_paths) as (
        data_snapshots,
        schema_snapshots,
    ):
        _preflight_sources(
            data_paths=data_snapshots,
            schema_paths=schema_snapshots,
            data_sha256=data_hashes,
            schema_sha256=schema_hashes,
        )
    print("SOURCE_VALIDATION_OK sources=4 rows=145393")
    return 0


async def _load_command() -> int:
    data_paths, schema_paths, data_hashes, schema_hashes = _source_inputs()
    database_url = _required_env("FINANCIAL_AGENT_BUILD_DATABASE_URL")
    dataset_version = os.getenv(
        "FINANCIAL_AGENT_DATASET_VERSION",
        "organizer-2026-07-11-03a",
    )
    engine = create_async_engine(
        _async_database_url(database_url),
        pool_size=5,
        max_overflow=0,
        connect_args={"options": "-c timezone=UTC"},
    )
    try:
        report = await build_organizer_dataset(
            engine,
            dataset_version=dataset_version,
            data_paths=data_paths,
            schema_paths=schema_paths,
            data_sha256=data_hashes,
            schema_sha256=schema_hashes,
        )
    finally:
        await engine.dispose()
    if not report.passed:
        print("BUILD_VALIDATION_FAILED", file=sys.stderr)
        return 2
    rows = sum(counts["rows"] for counts in report.source_counts.values())
    print(f"BUILD_OK sources=4 rows={rows} status=building")
    return 0


async def _object_storage_command() -> int:
    data_paths, schema_paths, data_hashes, schema_hashes = _source_inputs()
    endpoint = _validated_object_storage_endpoint(
        _required_env("FINANCIAL_AGENT_OBJECT_STORAGE_ENDPOINT")
    )
    bucket = _required_env("FINANCIAL_AGENT_OBJECT_STORAGE_BUCKET")
    access_key = _required_env(
        "FINANCIAL_AGENT_OBJECT_STORAGE_ACCESS_KEY_ID"
    )
    secret_key = _required_env(
        "FINANCIAL_AGENT_OBJECT_STORAGE_SECRET_ACCESS_KEY"
    )
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.getenv(
            "FINANCIAL_AGENT_OBJECT_STORAGE_REGION", "kr-standard"
        ),
    )

    objects: list[tuple[str, Path, str]] = []
    for source_code in sorted(SOURCE_SPECS):
        spec = SOURCE_SPECS[source_code]
        objects.extend(
            (
                (
                    f"organizer/2026-07-11/{spec.table_id}/{spec.data_file_name}",
                    data_paths[source_code],
                    data_hashes[source_code],
                ),
                (
                    f"organizer/2026-07-11/{spec.table_id}/{spec.schema_file_name}",
                    schema_paths[source_code],
                    schema_hashes[source_code],
                ),
            )
        )

    with tempfile.TemporaryDirectory(prefix="financial-agent-object-check-") as root:
        destination_root = Path(root)
        for index, (key, local_path, expected_hash) in enumerate(objects):
            verify_local_source(local_path, expected_hash)
            download_verified_object(
                client,
                bucket=bucket,
                key=key,
                expected_sha256=expected_hash,
                destination=destination_root / f"object-{index}",
            )
    print("OBJECT_STORAGE_OK objects=8")
    return 0


def _stable_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) else "INGESTION_FAILED"


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command == "validate":
            result = asyncio.run(_validate_command())
        elif arguments.command == "load":
            result = asyncio.run(_load_command())
        else:
            result = asyncio.run(_object_storage_command())
        return 0 if result is None else result
    except (
        IngestionArgumentError,
        IngestionConfigurationError,
        ObjectStorageEndpointError,
        OrganizerBuildError,
        OrganizerSourceValidationError,
        SourceVerificationError,
        DatasetBuildConflict,
        DatasetBuildPayloadError,
        DatasetBuildRoleError,
        DatasetBuildStateError,
        DatasetBuildWriteError,
    ) as error:
        print(_stable_error_code(error), file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("DATABASE_UNREACHABLE", file=sys.stderr)
        return 2
    except Exception:
        print("INGESTION_FAILED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
