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
from financial_agent.ingestion.capacity_probe import (
    CapacityProbeError,
    measure_database_acceptance,
    require_current_rebaseline_acceptance,
)
from financial_agent.ingestion.pipeline import (
    SOURCE_SPECS,
    OrganizerBuildError,
    OrganizerSourceValidationError,
    _preflight_sources,
    _snapshot_source_inputs,
    build_organizer_dataset,
)
from financial_agent.ingestion.official_pipeline import (
    OrganizerInputs,
    OfficialPipelineError,
    build_stage03b_capacity_probe,
    build_stage03b_dataset,
    load_official_manifests,
    validate_stage03b_inputs,
)
from financial_agent.ingestion.official.capture import (
    capture_approved_official_sources,
    load_capture_configuration,
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


class OfficialSourceConfigurationError(RuntimeError):
    code = "OFFICIAL_SOURCE_CONFIGURATION_MISSING"

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
    commands.add_parser("capture-official")
    commands.add_parser("validate-official")
    commands.add_parser("load-stage03b")
    commands.add_parser("verify-official-object-storage")
    capacity = commands.add_parser("measure-stage03b-capacity")
    capacity.add_argument("--full-holdings", required=True, type=int)
    capacity.add_argument("--sample-products", default=100, type=int)
    capacity.add_argument("--current-storage-gib", default=20, type=int)
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


def _official_inputs():
    manifest_root = Path(
        _required_env("FINANCIAL_AGENT_OFFICIAL_MANIFEST_ROOT")
    )
    manifests = load_official_manifests(manifest_root)
    if not manifests:
        raise OfficialSourceConfigurationError() from None
    return manifests, Path(_required_env("FINANCIAL_AGENT_SOURCE_ROOT"))


def _organizer_inputs() -> OrganizerInputs:
    data_paths, schema_paths, data_hashes, schema_hashes = _source_inputs()
    return OrganizerInputs(
        data_paths=data_paths,
        schema_paths=schema_paths,
        data_sha256=data_hashes,
        schema_sha256=schema_hashes,
    )


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


def _object_storage_client():
    endpoint = _validated_object_storage_endpoint(
        _required_env("FINANCIAL_AGENT_OBJECT_STORAGE_ENDPOINT")
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=_required_env(
            "FINANCIAL_AGENT_OBJECT_STORAGE_ACCESS_KEY_ID"
        ),
        aws_secret_access_key=_required_env(
            "FINANCIAL_AGENT_OBJECT_STORAGE_SECRET_ACCESS_KEY"
        ),
        region_name=os.getenv(
            "FINANCIAL_AGENT_OBJECT_STORAGE_REGION", "kr-standard"
        ),
    )


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
        "organizer-2026-08-24-rebaseline",
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
    bucket = _required_env("FINANCIAL_AGENT_OBJECT_STORAGE_BUCKET")
    client = _object_storage_client()

    objects: list[tuple[str, Path, str]] = []
    for source_code in sorted(SOURCE_SPECS):
        spec = SOURCE_SPECS[source_code]
        objects.extend(
            (
                (
                    f"organizer/2026-08-24/{spec.table_id}/{spec.data_file_name}",
                    data_paths[source_code],
                    data_hashes[source_code],
                ),
                (
                    f"organizer/2026-08-24/{spec.table_id}/{spec.schema_file_name}",
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


async def _capture_official_command() -> int:
    configuration = load_capture_configuration(os.environ)
    result = capture_approved_official_sources(configuration)
    print(
        f"OFFICIAL_CAPTURE_OK sources={result.source_count} "
        f"objects={result.object_count} bytes={result.total_bytes} "
        f"eligible={result.eligible_start}..{result.eligible_end}"
    )
    return 0


async def _validate_official_command() -> int:
    organizer_inputs = _organizer_inputs()
    manifests, object_root = _official_inputs()
    validate_stage03b_inputs(
        organizer_inputs=organizer_inputs,
        official_manifests=manifests,
        official_object_root=object_root,
    )
    object_count = sum(len(manifest.objects) for manifest in manifests)
    print(
        f"OFFICIAL_VALIDATION_OK snapshots={len(manifests)} "
        f"objects={object_count}"
    )
    return 0


async def _load_stage03b_command() -> int:
    organizer_inputs = _organizer_inputs()
    manifests, object_root = _official_inputs()
    database_url = _required_env("FINANCIAL_AGENT_BUILD_DATABASE_URL")
    dataset_version = os.getenv(
        "FINANCIAL_AGENT_DATASET_VERSION",
        "combined-2026-08-24-rebaseline",
    )
    engine = create_async_engine(
        _async_database_url(database_url),
        pool_size=5,
        max_overflow=0,
        connect_args={"options": "-c timezone=UTC"},
    )
    acceptance = None
    try:
        report = await build_stage03b_dataset(
            engine,
            dataset_version=dataset_version,
            organizer_inputs=organizer_inputs,
            official_manifests=manifests,
            official_object_root=object_root,
        )
        if report.passed:
            acceptance = await measure_database_acceptance(engine, report)
            require_current_rebaseline_acceptance(acceptance)
    finally:
        await engine.dispose()
    if not report.passed:
        print("BUILD_VALIDATION_FAILED", file=sys.stderr)
        return 2
    if acceptance is None:
        raise CapacityProbeError("DATABASE_ACCEPTANCE_GATE_FAILED") from None
    rows = sum(counts["rows"] for counts in report.source_counts.values())
    print(
        f"STAGE03B_BUILD_OK sources={len(report.source_counts)} "
        f"rows={rows} status={acceptance.dataset_status} "
        f"active={int(acceptance.active)} "
        f"acceptance={acceptance.reproducibility_hash} "
        f"products={acceptance.canonical_product_count} "
        f"exact_reused={acceptance.exact_reused_identity_count} "
        f"ambiguous_pairs={acceptance.aligned_ambiguous_pair_count}"
    )
    return 0


async def _capacity_probe_command(arguments: argparse.Namespace) -> int:
    organizer_inputs = _organizer_inputs()
    manifests, object_root = _official_inputs()
    database_url = _required_env("FINANCIAL_AGENT_BUILD_DATABASE_URL")
    dataset_version = _required_env("FINANCIAL_AGENT_DATASET_VERSION")
    engine = create_async_engine(
        _async_database_url(database_url),
        pool_size=5,
        max_overflow=0,
        connect_args={"options": "-c timezone=UTC"},
    )
    try:
        report = await build_stage03b_capacity_probe(
            engine,
            dataset_version=dataset_version,
            organizer_inputs=organizer_inputs,
            official_manifests=manifests,
            official_object_root=object_root,
            sample_product_count=arguments.sample_products,
            full_holding_count=arguments.full_holdings,
            current_storage_gib=arguments.current_storage_gib,
        )
    finally:
        await engine.dispose()
    print(
        "CAPACITY_PROBE_OK "
        f"sample_products={report.sample_product_count} "
        f"sample_holdings={report.sample_holding_count} "
        f"base_bytes={report.base_bytes} "
        f"sample_nport_bytes={report.sampled_nport_bytes} "
        f"projected_bytes={report.estimate.projected_total_bytes} "
        f"safety_bytes={report.estimate.safety_adjusted_bytes} "
        f"current_gib={arguments.current_storage_gib} "
        f"recommended_gib={report.estimate.recommended_storage_gib} "
        f"additional_gib={report.estimate.additional_storage_gib} "
        f"status={report.dataset_status} active={int(report.active)}"
    )
    return 0


async def _official_object_storage_command() -> int:
    manifests, _ = _official_inputs()
    bucket = _required_env("FINANCIAL_AGENT_OBJECT_STORAGE_BUCKET")
    client = _object_storage_client()
    object_count = 0
    with tempfile.TemporaryDirectory(
        prefix="financial-agent-official-object-check-"
    ) as root:
        destination_root = Path(root)
        for manifest in manifests:
            for item in manifest.objects:
                destination = destination_root / f"object-{object_count}"
                download_verified_object(
                    client,
                    bucket=bucket,
                    key=item.object_key,
                    expected_sha256=item.sha256,
                    destination=destination,
                )
                if destination.stat().st_size != item.size_bytes:
                    raise OfficialPipelineError(
                        "OFFICIAL_OBJECT_SIZE_MISMATCH"
                    ) from None
                object_count += 1
    print(
        f"OFFICIAL_OBJECT_STORAGE_OK snapshots={len(manifests)} "
        f"objects={object_count}"
    )
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
        elif arguments.command == "verify-object-storage":
            result = asyncio.run(_object_storage_command())
        elif arguments.command == "capture-official":
            result = asyncio.run(_capture_official_command())
        elif arguments.command == "validate-official":
            result = asyncio.run(_validate_official_command())
        elif arguments.command == "load-stage03b":
            result = asyncio.run(_load_stage03b_command())
        elif arguments.command == "measure-stage03b-capacity":
            result = asyncio.run(_capacity_probe_command(arguments))
        else:
            result = asyncio.run(_official_object_storage_command())
        return 0 if result is None else result
    except (
        IngestionArgumentError,
        IngestionConfigurationError,
        CapacityProbeError,
        ObjectStorageEndpointError,
        OfficialSourceConfigurationError,
        OfficialPipelineError,
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
