from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import BinaryIO, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import boto3
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from financial_agent.db.config import DatabaseConfig, DatabaseConfigurationError
from financial_agent.db.engine import create_database_engine
from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.db.repositories.document_targets import DocumentTargetRepository
from financial_agent.db.repositories.documents import (
    DocumentCorpusRepository,
    DocumentCorpusValidationError,
)
from financial_agent.db.schema.catalog import entity
from financial_agent.db.schema.operations import (
    dataset_version as dataset_version_table,
)
from financial_agent.documents import (
    DocumentRole,
    DocumentSourceAuditEntry,
    DocumentSourceAuditReport,
    DocumentSourceAttempt,
    DocumentSourceTarget,
    PublisherRole,
    SectionType,
    SourceAuditStatus,
)
from financial_agent.documents.chunking import WhitespaceTokenCounter
from financial_agent.documents.source_manifest import (
    validate_document_source_report,
    write_document_source_report,
)
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
from financial_agent.ingestion.document_sources.audit import (
    audit_document_sources,
    document_source_audit_passed,
)
from financial_agent.ingestion.document_sources.base import (
    DocumentDiscoveryContext,
    NoRedirectHttpOpener,
)
from financial_agent.ingestion.document_sources.dart import DartDocumentSourceAdapter
from financial_agent.ingestion.document_sources.dart_batch import (
    discover_dart_candidates_by_publisher,
)
from financial_agent.ingestion.document_sources.dart_ingestion import (
    DartCorpusIngestionError,
    DartCorpusIngestionRequest,
    ingest_one_dart_document,
)
from financial_agent.ingestion.document_sources.dart_pipeline import (
    DartProspectusContext,
)
from financial_agent.ingestion.document_sources.dart_publishers import (
    DartPublisherDataError,
    fetch_dart_corporation_codes,
    reconcile_dart_publishers,
)
from financial_agent.ingestion.document_sources.dart_targets import (
    OrganizerDartInventory,
    OrganizerDartTarget,
    build_organizer_dart_inventory,
)
from financial_agent.ingestion.document_sources.registered import (
    RegisteredDocumentSourceAdapter,
    ReviewedAuthorityContext,
)
from financial_agent.ingestion.document_sources.sec import SecDocumentSourceAdapter
from financial_agent.ingestion.sources import (
    SourceVerificationError,
    download_verified_object,
    sha256_path,
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


_DOCUMENT_SOURCE_CUTOFF = date(2026, 8, 24)
_DOCUMENT_AUTHORITY_REGISTRY = (
    Path(__file__).resolve().parents[3]
    / "config"
    / "official-document-authorities.json"
)
_AUDIT_STATUS_ORDER = (
    SourceAuditStatus.DOCUMENT_NOT_FOUND,
    SourceAuditStatus.IDENTIFIER_MISSING,
    SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
    SourceAuditStatus.CREDENTIALS_MISSING,
    SourceAuditStatus.ACCESS_DENIED,
    SourceAuditStatus.RATE_LIMITED,
    SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
    SourceAuditStatus.TERMS_REVIEW_REQUIRED,
    SourceAuditStatus.AFTER_CUTOFF_ONLY,
    SourceAuditStatus.VERSION_UNKNOWN,
    SourceAuditStatus.MEDIA_TYPE_UNSUPPORTED,
)


@dataclass(frozen=True, slots=True)
class _DocumentSourceAuditConfiguration:
    database_url: str
    dataset_version: str
    output_root: Path
    dart_api_key: str | None
    sec_user_agent: str | None
    locator_registry_path: Path | None


@dataclass(frozen=True, slots=True)
class _DocumentSourceAuditExecution:
    report: DocumentSourceAuditReport
    registered_authorities: ReviewedAuthorityContext | None


@dataclass(frozen=True, slots=True)
class _PolicyTargetReconciliation:
    targets: tuple[DocumentSourceTarget, ...]
    unavailable_entries: tuple[DocumentSourceAuditEntry, ...]


@dataclass(frozen=True, slots=True)
class _DartCorpusConfiguration:
    database_url: str
    dataset_version: str
    dart_api_key: str
    temp_root: Path
    publisher_aliases: Mapping[str, str]
    report_path: Path
    limit: int | None
    target_key: str | None


@dataclass(frozen=True, slots=True)
class _DartCorpusRunReport:
    schema_version: str
    generated_at: datetime
    cutoff_date: date
    dataset_version: str
    inventory_hash: str
    organizer_product_count: int
    organizer_target_count: int
    selected_target_count: int
    publisher_binding_count: int
    publisher_failure_count: int
    requested_publisher_count: int
    discovered_document_count: int
    indexed_document_ids: tuple[str, ...]
    indexed_target_ids: tuple[str, ...]
    failed_targets: tuple[tuple[str, str], ...]
    rejected_dart_filing_count: int
    captured_bytes: int
    chunk_count: int
    provisional_selected_token_count: int
    token_counter_identity: str
    deleted_pdf_count: int
    deleted_bytes: int
    quarantined_pdf_count: int
    quarantined_bytes: int
    discarded_failed_artifacts: tuple[tuple[str, str, int, str], ...] = ()


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


class _NoRedirectHttpOpener:
    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirectHandler())

    def open_no_redirect(
        self,
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> BinaryIO:
        request = Request(url, headers=dict(headers), method=method)
        try:
            return cast(BinaryIO, self._opener.open(request, timeout=timeout))
        except HTTPError as error:
            if 300 <= error.code < 400:
                return cast(BinaryIO, error)
            raise


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
    commands.add_parser("audit-document-sources")
    dart_corpus = commands.add_parser("ingest-dart-corpus")
    dart_selection = dart_corpus.add_mutually_exclusive_group()
    dart_selection.add_argument("--limit", type=int)
    dart_selection.add_argument("--target-key")
    capacity = commands.add_parser("measure-stage03b-capacity")
    capacity.add_argument("--full-holdings", required=True, type=int)
    capacity.add_argument("--sample-products", default=100, type=int)
    capacity.add_argument("--current-storage-gib", default=20, type=int)
    return parser


def _load_dart_corpus_configuration(
    arguments: argparse.Namespace,
) -> _DartCorpusConfiguration:
    if arguments.command != "ingest-dart-corpus":
        raise IngestionArgumentError()
    limit = arguments.limit
    target_key = arguments.target_key
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
    ):
        raise IngestionArgumentError()
    if target_key is not None and (
        not isinstance(target_key, str) or not target_key.strip()
    ):
        raise IngestionArgumentError()
    database_url = _required_env("FINANCIAL_AGENT_BUILD_DATABASE_URL").strip()
    try:
        DatabaseConfig(url=database_url)
    except DatabaseConfigurationError:
        raise IngestionArgumentError() from None
    dataset_version = _required_env("FINANCIAL_AGENT_DATASET_VERSION").strip()
    key_file = _required_absolute_file(
        _required_env("FINANCIAL_AGENT_DART_API_KEY_FILE")
    )
    mapping_value = _optional_nonblank_env(
        "FINANCIAL_AGENT_DART_PUBLISHER_MAPPING"
    )
    temp_root = _untracked_absolute_path(
        _required_env("FINANCIAL_AGENT_DART_TEMP_ROOT"),
        require_parent=False,
    )
    report_path = _untracked_absolute_path(
        _required_env("FINANCIAL_AGENT_DART_REPORT"),
        require_parent=True,
    )
    if report_path.exists() and not report_path.is_file():
        raise IngestionArgumentError()
    return _DartCorpusConfiguration(
        database_url=database_url,
        dataset_version=dataset_version,
        dart_api_key=_read_dart_api_key(key_file),
        temp_root=temp_root,
        publisher_aliases=(
            _load_dart_publisher_aliases(_required_absolute_file(mapping_value))
            if mapping_value is not None
            else {}
        ),
        report_path=report_path,
        limit=limit,
        target_key=target_key,
    )


def _required_absolute_file(value: str) -> Path:
    path = Path(value.strip())
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
    ):
        raise IngestionArgumentError()
    return path


def _untracked_absolute_path(value: str, *, require_parent: bool) -> Path:
    path = Path(value.strip())
    repository_root = Path(__file__).resolve().parents[3]
    if not path.is_absolute() or path.is_symlink():
        raise IngestionArgumentError()
    try:
        path.resolve(strict=False).relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise IngestionArgumentError()
    parent = path.parent
    if require_parent and (not parent.is_dir() or parent.is_symlink()):
        raise IngestionArgumentError()
    if path.exists() and not path.is_dir() and not require_parent:
        raise IngestionArgumentError()
    return path


def _read_dart_api_key(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        raise IngestionArgumentError() from None
    matches: list[str] = []
    nonblank = [line.strip() for line in lines if line.strip()]
    if len(nonblank) == 1 and "=" not in nonblank[0]:
        matches.append(nonblank[0])
    else:
        for line in nonblank:
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            normalized_name = re.sub(r"[^A-Z0-9]", "", name.upper())
            if normalized_name not in {
                "OPENDART",
                "FINANCIALAGENTDARTAPIKEY",
            }:
                continue
            secret = value.strip()
            if (
                len(secret) >= 2
                and secret[0] == secret[-1]
                and secret[0] in {"'", '"'}
            ):
                secret = secret[1:-1].strip()
            if secret:
                matches.append(secret)
    if len(matches) != 1:
        raise IngestionArgumentError()
    return matches[0]


def _load_dart_publisher_aliases(path: Path) -> Mapping[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise IngestionArgumentError() from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "aliases"}
        or payload.get("schema_version") != "1.0"
        or not isinstance(payload.get("aliases"), list)
    ):
        raise IngestionArgumentError()
    aliases: dict[str, str] = {}
    for item in payload["aliases"]:
        if not isinstance(item, dict) or set(item) != {
            "manager_entity_id",
            "corp_code",
        }:
            raise IngestionArgumentError()
        manager_id = item["manager_entity_id"]
        corp_code = item["corp_code"]
        if (
            not isinstance(manager_id, str)
            or not manager_id.strip()
            or not isinstance(corp_code, str)
            or re.fullmatch(r"[0-9]{8}", corp_code) is None
            or manager_id in aliases
        ):
            raise IngestionArgumentError()
        aliases[manager_id] = corp_code
    return aliases


def _write_dart_corpus_report(
    report: _DartCorpusRunReport,
    destination: Path,
) -> str:
    def json_value(value: object) -> object:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: json_value(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [json_value(item) for item in value]
        return value

    payload = json.dumps(
        json_value(asdict(report)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    report_hash = hashlib.sha256(payload).hexdigest()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".dart-corpus-report-",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return report_hash


def _optional_nonblank_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    if not value.strip():
        raise IngestionConfigurationError()
    return value.strip()


def _optional_source_credential_env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value is not None and value.strip() else None


def _validated_output_root(value: str) -> Path:
    root = Path(value)
    if not root.is_absolute() or root.is_symlink():
        raise IngestionArgumentError()
    if root.exists() and not root.is_dir():
        raise IngestionArgumentError()
    destination = root / "document-source-audit.json"
    if destination.is_symlink() or (
        destination.exists() and not destination.is_file()
    ):
        raise IngestionArgumentError()
    return root


def _validated_registry_path(value: str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
    ):
        raise IngestionArgumentError()
    return path


def _load_document_source_audit_configuration(
) -> _DocumentSourceAuditConfiguration:
    database_url = _required_env(
        "FINANCIAL_AGENT_DOCUMENT_AUDIT_DATABASE_URL"
    ).strip()
    dataset_version = _required_env("FINANCIAL_AGENT_DATASET_VERSION").strip()
    output_root = _validated_output_root(
        _required_env("FINANCIAL_AGENT_DOCUMENT_AUDIT_OUTPUT_ROOT").strip()
    )
    locator_registry_path = _validated_registry_path(
        _optional_nonblank_env("FINANCIAL_AGENT_DOCUMENT_LOCATOR_REGISTRY")
    )
    try:
        DatabaseConfig(url=database_url)
    except DatabaseConfigurationError:
        raise IngestionArgumentError() from None
    return _DocumentSourceAuditConfiguration(
        database_url=database_url,
        dataset_version=dataset_version,
        output_root=output_root,
        dart_api_key=_optional_source_credential_env(
            "FINANCIAL_AGENT_DART_API_KEY"
        ),
        sec_user_agent=_optional_source_credential_env(
            "FINANCIAL_AGENT_SEC_USER_AGENT"
        ),
        locator_registry_path=locator_registry_path,
    )


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


async def _load_document_audit_scope(
    connection: AsyncConnection,
    dataset_version: str,
) -> tuple[date, datetime]:
    result = await connection.execute(
        sa.select(
            dataset_version_table.c.cutoff_date,
            dataset_version_table.c.created_at,
        ).where(dataset_version_table.c.dataset_version == dataset_version)
    )
    rows = result.mappings().all()
    if len(rows) != 1:
        raise IngestionArgumentError()
    cutoff_date = rows[0].get("cutoff_date")
    generated_at = rows[0].get("created_at")
    if cutoff_date != _DOCUMENT_SOURCE_CUTOFF:
        raise IngestionArgumentError()
    if (
        not isinstance(generated_at, datetime)
        or generated_at.tzinfo is None
        or generated_at.utcoffset() is None
    ):
        raise IngestionArgumentError()
    return cutoff_date, generated_at


async def _list_exact_policy_targets(
    connection: AsyncConnection,
    *,
    dataset_version: str,
    cutoff_date: date,
    registered_authorities: ReviewedAuthorityContext,
) -> _PolicyTargetReconciliation:
    policy_locators = tuple(
        locator
        for locator in registered_authorities.locators
        if locator.required_role
        in {DocumentRole.POLICY_BASE, DocumentRole.OFFICIAL_UPDATE}
        and locator.binding_role == "subject_policy"
    )
    if not policy_locators:
        return _PolicyTargetReconciliation((), ())

    entity_ids = tuple(sorted({locator.entity_id for locator in policy_locators}))
    result = await connection.execute(
        sa.select(
            entity.c.entity_id,
            entity.c.entity_type,
            entity.c.canonical_name,
        ).where(
            entity.c.dataset_version == dataset_version,
            entity.c.entity_id.in_(entity_ids),
        )
    )
    entities: dict[str, tuple[str, str]] = {}
    for row in result.mappings().all():
        entity_id = row.get("entity_id")
        entity_type = row.get("entity_type")
        canonical_name = row.get("canonical_name")
        if (
            not isinstance(entity_id, str)
            or not entity_id.strip()
            or not isinstance(entity_type, str)
            or not entity_type.strip()
            or not isinstance(canonical_name, str)
            or not canonical_name.strip()
            or entity_id in entities
        ):
            raise IngestionArgumentError()
        entities[entity_id] = (entity_type, canonical_name)

    targets: list[DocumentSourceTarget] = []
    unavailable_entries: list[DocumentSourceAuditEntry] = []
    for locator in sorted(
        policy_locators,
        key=lambda item: (item.entity_id, item.required_role.value),
    ):
        database_entity = entities.get(locator.entity_id)
        if database_entity is None:
            target = _policy_target(
                locator,
                dataset_version=dataset_version,
                cutoff_date=cutoff_date,
                entity_type=locator.entity_type,
                canonical_name=None,
            )
            unavailable_entries.append(
                DocumentSourceAuditEntry(
                    target=target,
                    status=SourceAuditStatus.IDENTIFIER_MISSING,
                    reason_code="policy_entity_missing",
                    candidate=None,
                    attempted_source=DocumentSourceAttempt(
                        "REGISTERED", None, None
                    ),
                )
            )
            continue
        entity_type, canonical_name = database_entity
        target = _policy_target(
            locator,
            dataset_version=dataset_version,
            cutoff_date=cutoff_date,
            entity_type=entity_type,
            canonical_name=canonical_name,
        )
        if entity_type != locator.entity_type:
            unavailable_entries.append(
                DocumentSourceAuditEntry(
                    target=target,
                    status=SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
                    reason_code="policy_entity_type_mismatch",
                    candidate=None,
                    attempted_source=DocumentSourceAttempt(
                        "REGISTERED", None, None
                    ),
                )
            )
        else:
            targets.append(target)
    return _PolicyTargetReconciliation(
        tuple(targets),
        tuple(unavailable_entries),
    )


def _policy_target(
    locator: object,
    *,
    dataset_version: str,
    cutoff_date: date,
    entity_type: str,
    canonical_name: str | None,
) -> DocumentSourceTarget:
    return DocumentSourceTarget(
        dataset_version=dataset_version,
        entity_id=locator.entity_id,
        entity_type=entity_type,
        canonical_name=canonical_name,
        product_family=None,
        required_role=locator.required_role,
        binding_role=locator.binding_role,
        identifiers=(),
        cutoff_date=cutoff_date,
    )


def _document_audit_runtime(
    configuration: _DocumentSourceAuditConfiguration,
    opener: NoRedirectHttpOpener,
) -> tuple[RegisteredDocumentSourceAdapter, DocumentDiscoveryContext]:
    registered_adapter = RegisteredDocumentSourceAdapter(
        opener,
        _DOCUMENT_AUTHORITY_REGISTRY,
    )
    context = DocumentDiscoveryContext(
        cutoff_date=_DOCUMENT_SOURCE_CUTOFF,
        dart_api_key=configuration.dart_api_key,
        sec_user_agent=configuration.sec_user_agent,
        locator_registry_path=configuration.locator_registry_path,
    )
    try:
        reviewed_authorities = registered_adapter.reviewed_context(context)
    except (OSError, UnicodeDecodeError, ValueError):
        raise IngestionArgumentError() from None
    return registered_adapter, replace(
        context,
        registered_authorities=reviewed_authorities,
    )


def _audit_document_targets(
    targets: tuple[DocumentSourceTarget, ...],
    *,
    configuration: _DocumentSourceAuditConfiguration,
    opener: NoRedirectHttpOpener,
    generated_at: datetime,
    preliminary_entries: tuple[DocumentSourceAuditEntry, ...] = (),
    registered_adapter: RegisteredDocumentSourceAdapter | None = None,
    context: DocumentDiscoveryContext | None = None,
) -> _DocumentSourceAuditExecution:
    if registered_adapter is None or context is None:
        if registered_adapter is not None or context is not None:
            raise IngestionArgumentError()
        registered_adapter, context = _document_audit_runtime(
            configuration,
            opener,
        )
    preliminary_entries = tuple(
        replace(
            entry,
            attempted_source=registered_adapter.reviewed_attempt(
                entry.target,
                context,
            ),
        )
        for entry in preliminary_entries
    )
    if targets:
        report = audit_document_sources(
            targets,
            (
                DartDocumentSourceAdapter(opener),
                SecDocumentSourceAdapter(opener),
                registered_adapter,
            ),
            context,
            generated_at,
        )
        report = DocumentSourceAuditReport(
            schema_version=report.schema_version,
            generated_at=report.generated_at,
            cutoff_date=report.cutoff_date,
            dataset_version=report.dataset_version,
            entries=(*report.entries, *preliminary_entries),
        )
    else:
        report = DocumentSourceAuditReport(
            schema_version="1.0",
            generated_at=generated_at,
            cutoff_date=_DOCUMENT_SOURCE_CUTOFF,
            dataset_version=configuration.dataset_version,
            entries=preliminary_entries,
        )
    validate_document_source_report(report)
    return _DocumentSourceAuditExecution(
        report=report,
        registered_authorities=context.registered_authorities,
    )


async def _run_document_source_audit(
    configuration: _DocumentSourceAuditConfiguration,
) -> _DocumentSourceAuditExecution:
    opener = _NoRedirectHttpOpener()
    registered_adapter, context = _document_audit_runtime(
        configuration,
        opener,
    )
    engine = create_database_engine(
        DatabaseConfig(url=configuration.database_url),
        read_only=True,
    )
    try:
        async with engine.begin() as connection:
            cutoff_date, generated_at = await _load_document_audit_scope(
                connection,
                configuration.dataset_version,
            )
            targets = await DocumentTargetRepository(connection).list_targets(
                configuration.dataset_version,
                cutoff_date=cutoff_date,
            )
            policy_reconciliation = _PolicyTargetReconciliation((), ())
            if configuration.locator_registry_path is not None:
                assert context.registered_authorities is not None
                policy_reconciliation = await _list_exact_policy_targets(
                    connection,
                    dataset_version=configuration.dataset_version,
                    cutoff_date=cutoff_date,
                    registered_authorities=context.registered_authorities,
                )
    finally:
        await engine.dispose()

    return _audit_document_targets(
        (*targets, *policy_reconciliation.targets),
        configuration=configuration,
        opener=opener,
        generated_at=generated_at,
        preliminary_entries=policy_reconciliation.unavailable_entries,
        registered_adapter=registered_adapter,
        context=context,
    )


def _audit_status_count(
    report: DocumentSourceAuditReport,
    status: SourceAuditStatus,
) -> int:
    return sum(entry.status is status for entry in report.entries)


def _document_source_audit_summary(
    execution: _DocumentSourceAuditExecution,
    report_hash: str,
) -> tuple[bool, str]:
    report = execution.report
    passed = document_source_audit_passed(
        report,
        registered_authorities=execution.registered_authorities,
    )
    target_count = len(report.entries)
    eligible_count = _audit_status_count(report, SourceAuditStatus.ELIGIBLE)
    not_applicable_count = _audit_status_count(
        report,
        SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE,
    )
    if passed:
        return (
            True,
            f"DOCUMENT_SOURCE_AUDIT_OK targets={target_count} "
            f"eligible={eligible_count} not_applicable={not_applicable_count} "
            f"report_hash={report_hash}",
        )

    unavailable_count = target_count - eligible_count - not_applicable_count
    counts = " ".join(
        f"{status.value}={_audit_status_count(report, status)}"
        for status in _AUDIT_STATUS_ORDER
    )
    source_counts = Counter(
        entry.attempted_source.source_code
        for entry in report.entries
        if entry.status
        not in {
            SourceAuditStatus.ELIGIBLE,
            SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE,
        }
        and entry.attempted_source is not None
    )
    sources = (
        ",".join(
            f"{source_code}:{source_counts[source_code]}"
            for source_code in sorted(source_counts)
        )
        if source_counts
        else "none"
    )
    return (
        False,
        f"DOCUMENT_SOURCE_AUDIT_INCOMPLETE targets={target_count} "
        f"eligible={eligible_count} unavailable={unavailable_count} "
        f"{counts} sources={sources} report_hash={report_hash}",
    )


async def _document_source_audit_command() -> int:
    configuration = _load_document_source_audit_configuration()
    execution = await _run_document_source_audit(configuration)
    report_hash = write_document_source_report(
        execution.report,
        configuration.output_root / "document-source-audit.json",
    )
    passed, summary = _document_source_audit_summary(execution, report_hash)
    print(summary, file=sys.stdout if passed else sys.stderr)
    return 0 if passed else 2


async def _load_dart_corpus_inventory(
    configuration: _DartCorpusConfiguration,
):
    engine = create_database_engine(
        DatabaseConfig(
            url=configuration.database_url,
            statement_timeout_ms=180_000,
        )
    )
    try:
        async with engine.connect() as connection:
            server_version = await connection.scalar(
                sa.text("SHOW server_version_num")
            )
            try:
                major_version = int(str(server_version)) // 10_000
            except (TypeError, ValueError):
                raise IngestionArgumentError() from None
            if major_version != 15:
                raise IngestionArgumentError()
            dataset_row = (
                await connection.execute(
                    sa.select(
                        dataset_version_table.c.cutoff_date,
                        dataset_version_table.c.status,
                    ).where(
                        dataset_version_table.c.dataset_version
                        == configuration.dataset_version
                    )
                )
            ).mappings().one_or_none()
            if (
                dataset_row is None
                or dataset_row["cutoff_date"] != _DOCUMENT_SOURCE_CUTOFF
                or dataset_row["status"] != "building"
            ):
                raise IngestionArgumentError()
            repository = DocumentTargetRepository(connection)
            rows = await repository.list_organizer_dart_rows(
                configuration.dataset_version,
                _DOCUMENT_SOURCE_CUTOFF,
            )
    except Exception:
        await engine.dispose()
        raise
    inventory = build_organizer_dart_inventory(
        configuration.dataset_version,
        _DOCUMENT_SOURCE_CUTOFF,
        rows,
    )
    manager_ids = tuple(
        sorted(
            {
                manager_id
                for target in inventory.targets
                for manager_id, _ in target.manager_bindings
            }
        )
    )
    try:
        async with engine.connect() as connection:
            institution_identifiers = await DocumentTargetRepository(
                connection
            ).list_identifiers(
                configuration.dataset_version,
                manager_ids,
            )
    except Exception:
        await engine.dispose()
        raise
    return engine, inventory, institution_identifiers


def _limited_dart_inventory(
    inventory: OrganizerDartInventory,
    limit: int | None,
    target_key: str | None = None,
) -> OrganizerDartInventory:
    if target_key is not None:
        selected = tuple(
            target
            for target in inventory.targets
            if target.target_key == target_key
        )
        if len(selected) != 1:
            raise IngestionArgumentError()
        return replace(inventory, targets=selected)
    if limit is None:
        return inventory
    return replace(inventory, targets=inventory.targets[:limit])


def _partition_dart_inventory(
    inventory: OrganizerDartInventory,
) -> tuple[OrganizerDartInventory, dict[str, str]]:
    failures = {
        target.target_key: target.document_collection_block_reason
        for target in inventory.targets
        if target.document_collection_block_reason is not None
    }
    actionable = tuple(
        target
        for target in inventory.targets
        if target.document_collection_block_reason is None
    )
    return replace(inventory, targets=actionable), failures


def _with_resolved_dart_product_name(
    target: OrganizerDartTarget,
    resolved_product_name: str | None,
) -> OrganizerDartTarget:
    if resolved_product_name is None:
        return target
    canonical_name = target.canonical_name
    if target.representative_entity_id not in target.member_entity_ids:
        member_names = dict(target.member_entity_names)
        canonical_name = member_names[min(target.member_entity_ids)]
    return replace(
        target,
        canonical_name=canonical_name,
        source_product_name=resolved_product_name,
    )


def _merge_dart_targets(
    grouped: tuple[tuple[OrganizerDartTarget, object], ...],
) -> OrganizerDartTarget:
    primary = grouped[0][0]
    managers = tuple(
        sorted(
            {
                manager
                for target, _ in grouped
                for manager in target.manager_bindings
            }
        )
    )
    member_entity_names = tuple(
        sorted(
            {
                member
                for target, _ in grouped
                for member in target.member_entity_names
            }
        )
    )
    member_entity_ids = tuple(entity_id for entity_id, _ in member_entity_names)
    return replace(
        primary,
        canonical_name=member_entity_names[0][1],
        member_entity_ids=member_entity_ids,
        identifiers=tuple(
            sorted(
                {
                    identifier
                    for target, _ in grouped
                    for identifier in target.identifiers
                }
            )
        ),
        manager_bindings=managers,
        member_entity_names=member_entity_names,
    )


def _dart_prospectus_context(
    *,
    configuration: _DartCorpusConfiguration,
    target: OrganizerDartTarget,
    candidate: object,
) -> DartProspectusContext:
    receipt = candidate.accession_or_receipt_id
    published_at = candidate.published_at
    available_at = candidate.available_at
    if (
        receipt is None
        or candidate.document_version is None
        or published_at is None
        or available_at is None
        or len(target.manager_bindings) != 1
    ):
        raise DartCorpusIngestionError("dart_ingestion_context_incomplete")
    manager_id, _ = target.manager_bindings[0]
    document_product_name = target.source_product_name or target.canonical_name
    return DartProspectusContext(
        dataset_version=configuration.dataset_version,
        entity_id=target.representative_entity_id,
        canonical_entity_name=target.canonical_name,
        document_id=f"dart:{receipt}:full-prospectus",
        document_title=f"{document_product_name} 투자설명서",
        document_type="full_prospectus",
        document_version=candidate.document_version,
        source_id=f"source:dart:{receipt}",
        source_object_key=f"documents/dart/{receipt}/full-prospectus.pdf",
        source_content_checksum="0" * 64,
        publisher_id=manager_id,
        publisher_role=PublisherRole.ASSET_MANAGER,
        published_at=published_at,
        available_at=available_at,
        effective_from=(candidate.effective_from or published_at.date()),
        effective_to=candidate.effective_to,
        jurisdiction="KR",
        original_language="ko",
        required_document_role=DocumentRole.PRODUCT_FULL,
        budget_scope_id=target.target_key,
    )


def _quarantine_totals(root: Path) -> tuple[int, int]:
    if not root.exists():
        return 0, 0
    count = 0
    byte_count = 0
    for path in root.rglob("*.pdf"):
        if path.is_symlink() or not path.is_file():
            raise DartCorpusIngestionError("dart_quarantine_path_invalid")
        count += 1
        byte_count += path.stat().st_size
    return count, byte_count


def _discard_failed_dart_pdf(
    root: Path,
    receipt: str,
    reason_code: str,
) -> tuple[str, str, int, str] | None:
    pdf_path = root / f"dart-{receipt}" / "source.pdf"
    if not pdf_path.exists():
        return None
    expected = root.resolve() / f"dart-{receipt}" / "source.pdf"
    if (
        pdf_path.is_symlink()
        or not pdf_path.is_file()
        or pdf_path.resolve() != expected
    ):
        raise DartCorpusIngestionError("dart_quarantine_path_invalid")
    byte_count = pdf_path.stat().st_size
    checksum = sha256_path(pdf_path)
    try:
        pdf_path.unlink()
        pdf_path.parent.rmdir()
    except OSError:
        raise DartCorpusIngestionError("dart_pdf_cleanup_failed") from None
    return receipt, reason_code, byte_count, checksum


async def _run_dart_corpus(
    configuration: _DartCorpusConfiguration,
) -> _DartCorpusRunReport:
    (
        engine,
        full_inventory,
        institution_identifiers,
    ) = await _load_dart_corpus_inventory(configuration)
    inventory = _limited_dart_inventory(
        full_inventory,
        configuration.limit,
        configuration.target_key,
    )
    actionable_inventory, pre_discovery_failures = _partition_dart_inventory(
        inventory
    )
    opener = _NoRedirectHttpOpener()
    repository = DocumentCorpusRepository(engine)
    indexed_target_ids: set[str] = set()
    failed_targets = dict(pre_discovery_failures)
    indexed_document_ids: set[str] = set()
    captured_bytes = 0
    chunk_count = 0
    selected_tokens = 0
    deleted_bytes = 0
    discarded_failed_artifacts: list[tuple[str, str, int, str]] = []
    try:
        if not actionable_inventory.targets:
            quarantined_count, quarantined_bytes = _quarantine_totals(
                configuration.temp_root
            )
            return _DartCorpusRunReport(
                schema_version="1.0",
                generated_at=datetime.now(UTC),
                cutoff_date=_DOCUMENT_SOURCE_CUTOFF,
                dataset_version=configuration.dataset_version,
                inventory_hash=full_inventory.inventory_hash,
                organizer_product_count=full_inventory.product_count,
                organizer_target_count=len(full_inventory.targets),
                selected_target_count=len(inventory.targets),
                publisher_binding_count=0,
                publisher_failure_count=0,
                requested_publisher_count=0,
                discovered_document_count=0,
                indexed_document_ids=(),
                indexed_target_ids=(),
                failed_targets=tuple(sorted(failed_targets.items())),
                rejected_dart_filing_count=0,
                captured_bytes=0,
                chunk_count=0,
                provisional_selected_token_count=0,
                token_counter_identity="WhitespaceTokenCounter",
                deleted_pdf_count=0,
                deleted_bytes=0,
                quarantined_pdf_count=quarantined_count,
                quarantined_bytes=quarantined_bytes,
            )
        selected_manager_ids = {
            manager_id
            for target in actionable_inventory.targets
            for manager_id, _ in target.manager_bindings
        }
        corp_code_zip = fetch_dart_corporation_codes(
            opener, configuration.dart_api_key
        )
        reconciliation = reconcile_dart_publishers(
            inventory=actionable_inventory,
            corp_code_zip=corp_code_zip,
            institution_identifiers=institution_identifiers,
            reviewed_aliases={
                manager_id: corp_code
                for manager_id, corp_code
                in configuration.publisher_aliases.items()
                if manager_id in selected_manager_ids
            },
        )
        discovery = discover_dart_candidates_by_publisher(
            inventory=actionable_inventory,
            reconciliation=reconciliation,
            adapter=DartDocumentSourceAdapter(opener),
            context=DocumentDiscoveryContext(
                cutoff_date=_DOCUMENT_SOURCE_CUTOFF,
                dart_api_key=configuration.dart_api_key,
                sec_user_agent=None,
                locator_registry_path=None,
            ),
        )
        targets = {
            target.target_key: target
            for target in actionable_inventory.targets
        }
        receipts: dict[str, list[tuple[OrganizerDartTarget, object]]] = {}
        for disposition in discovery.dispositions:
            if len(disposition.candidates) != 1:
                failed_targets[disposition.target_key] = (
                    disposition.reason_code or "dart_candidate_count_invalid"
                )
                continue
            candidate = disposition.candidates[0]
            receipt = candidate.accession_or_receipt_id
            if receipt is None:
                failed_targets[disposition.target_key] = (
                    "dart_candidate_receipt_missing"
                )
                continue
            receipts.setdefault(receipt, []).append(
                (
                    _with_resolved_dart_product_name(
                        targets[disposition.target_key],
                        disposition.resolved_product_name,
                    ),
                    candidate,
                )
            )

        fatal_codes = {
            "dart_corpus_readback_mismatch",
            "dart_pdf_cleanup_not_authorized",
            "dart_pdf_cleanup_checksum_mismatch",
            "dart_pdf_cleanup_path_invalid",
            "dart_pdf_cleanup_failed",
            "dart_quarantine_limit_reached",
            "dart_quarantine_path_invalid",
        }
        for receipt in sorted(receipts):
            grouped = tuple(
                sorted(receipts[receipt], key=lambda item: item[0].target_key)
            )
            target = _merge_dart_targets(grouped)
            candidate = grouped[0][1]
            target_keys = tuple(item[0].target_key for item in grouped)
            try:
                context = _dart_prospectus_context(
                    configuration=configuration,
                    target=target,
                    candidate=candidate,
                )
                await ingest_one_dart_document(
                    repository,
                    opener,
                    request=DartCorpusIngestionRequest(
                        run_root=configuration.temp_root,
                        target=target,
                        candidate=candidate,
                        context=context,
                        requested_section_types=frozenset(
                            {
                                SectionType.INVESTMENT_STRATEGY,
                                SectionType.RISK_FACTOR,
                            }
                        ),
                        token_counter=WhitespaceTokenCounter(),
                        maximum_bytes=64 * 1024 * 1024,
                    ),
                )
                persisted = await repository.get_captured_corpus(
                    configuration.dataset_version,
                    context.document_id,
                )
                indexed_document_ids.add(context.document_id)
                indexed_target_ids.update(target_keys)
                captured_bytes += persisted.source_artifact.byte_count
                deleted_bytes += persisted.source_artifact.byte_count
                chunk_count += len(persisted.corpus.chunks)
                selected_tokens += sum(
                    WhitespaceTokenCounter().count(chunk.exact_text)
                    for chunk in persisted.corpus.chunks
                )
            except DartCorpusIngestionError as error:
                if error.code in fatal_codes:
                    raise
                for target_key in target_keys:
                    failed_targets[target_key] = error.code
                discarded = _discard_failed_dart_pdf(
                    configuration.temp_root,
                    receipt,
                    error.code,
                )
                if discarded is not None:
                    discarded_failed_artifacts.append(discarded)
            except (SourceVerificationError, DocumentCorpusValidationError) as error:
                for target_key in target_keys:
                    failed_targets[target_key] = error.code
                discarded = _discard_failed_dart_pdf(
                    configuration.temp_root,
                    receipt,
                    error.code,
                )
                if discarded is not None:
                    discarded_failed_artifacts.append(discarded)

        selected_target_ids = {target.target_key for target in inventory.targets}
        if indexed_target_ids.intersection(failed_targets) or (
            indexed_target_ids | set(failed_targets)
        ) != selected_target_ids:
            raise DartCorpusIngestionError("dart_target_reconciliation_failed")
        quarantined_count, quarantined_bytes = _quarantine_totals(
            configuration.temp_root
        )
        return _DartCorpusRunReport(
            schema_version="1.0",
            generated_at=datetime.now(UTC),
            cutoff_date=_DOCUMENT_SOURCE_CUTOFF,
            dataset_version=configuration.dataset_version,
            inventory_hash=full_inventory.inventory_hash,
            organizer_product_count=full_inventory.product_count,
            organizer_target_count=len(full_inventory.targets),
            selected_target_count=len(inventory.targets),
            publisher_binding_count=len(reconciliation.bindings),
            publisher_failure_count=len(reconciliation.failures),
            requested_publisher_count=len(
                discovery.requested_publisher_codes
            ),
            discovered_document_count=len(receipts),
            indexed_document_ids=tuple(sorted(indexed_document_ids)),
            indexed_target_ids=tuple(sorted(indexed_target_ids)),
            failed_targets=tuple(sorted(failed_targets.items())),
            rejected_dart_filing_count=len(discovery.rejected_filings),
            captured_bytes=captured_bytes,
            chunk_count=chunk_count,
            provisional_selected_token_count=selected_tokens,
            token_counter_identity="WhitespaceTokenCounter",
            deleted_pdf_count=len(indexed_document_ids),
            deleted_bytes=deleted_bytes,
            quarantined_pdf_count=quarantined_count,
            quarantined_bytes=quarantined_bytes,
            discarded_failed_artifacts=tuple(
                sorted(discarded_failed_artifacts)
            ),
        )
    finally:
        await engine.dispose()


async def _dart_corpus_command(arguments: argparse.Namespace) -> int:
    configuration = _load_dart_corpus_configuration(arguments)
    report = await _run_dart_corpus(configuration)
    report_hash = _write_dart_corpus_report(
        report, configuration.report_path
    )
    print(
        "DART_CORPUS_OK "
        f"targets={report.selected_target_count} "
        f"documents={len(report.indexed_document_ids)} "
        f"failed={len(report.failed_targets)} "
        f"quarantined={report.quarantined_pdf_count} "
        f"report_hash={report_hash}"
    )
    return 0 if not report.failed_targets else 2


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
        elif arguments.command == "audit-document-sources":
            result = asyncio.run(_document_source_audit_command())
        elif arguments.command == "ingest-dart-corpus":
            result = asyncio.run(_dart_corpus_command(arguments))
        else:
            result = asyncio.run(_official_object_storage_command())
        return 0 if result is None else result
    except (
        IngestionArgumentError,
        IngestionConfigurationError,
        DatabaseConfigurationError,
        CapacityProbeError,
        ObjectStorageEndpointError,
        OfficialSourceConfigurationError,
        OfficialPipelineError,
        OrganizerBuildError,
        OrganizerSourceValidationError,
        SourceVerificationError,
        DartCorpusIngestionError,
        DartPublisherDataError,
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
