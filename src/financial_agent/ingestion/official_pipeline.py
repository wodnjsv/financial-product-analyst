from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
import shutil
import tempfile
from typing import Iterator

from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts import canonical_sha256
from financial_agent.ingestion import pipeline as organizer_pipeline
from financial_agent.ingestion.identity import AuthoritativeIdentityIndex
from financial_agent.ingestion.capacity_probe import (
    CapacityProbeError,
    CapacityProbeReport,
    capacity_probe_dataset_state,
    count_nport_holding_relations,
    estimate_stage03b_capacity,
    measure_application_storage_bytes,
    require_capacity_probe_dataset_absent,
)
from financial_agent.ingestion.mapping.common import (
    make_record_hash,
    normalize_name,
    stable_id,
)
from financial_agent.ingestion.official.authority import (
    validate_official_enrichment_scope,
)
from financial_agent.ingestion.official.identity import (
    IdentityCandidate,
    OfficialIdentityIndex,
)
from financial_agent.ingestion.official.krx_holdings import (
    build_krx_etf_product_bindings,
    map_krx_holding_snapshot,
    parse_krx_etf_pdf_csv,
    validate_krx_etf_holding_inventory,
)
from financial_agent.ingestion.official.krx_identity import (
    map_krx_security_basic,
    parse_krx_security_basic,
)
from financial_agent.ingestion.official.sec_nport import (
    NportArchiveLimits,
    NportProductBinding,
    iter_eligible_nport_funds,
    verify_and_extract_nport,
)
from financial_agent.ingestion.official.sec_series_class import (
    build_sec_series_class_index,
    parse_sec_series_class,
)
from financial_agent.ingestion.official.models import (
    OfficialObjectManifest,
    OfficialSnapshotManifest,
)
from financial_agent.ingestion.official.snapshot import (
    _canonical_manifest_bytes,
    validate_official_snapshot,
)
from financial_agent.ingestion.official.ecos_fx import (
    map_ecos_fx,
    parse_ecos_731y001,
)
from financial_agent.ingestion.models import BuildReport, MappedRow
from financial_agent.ingestion.pipeline import (
    CUTOFF_DATE,
    _database_component_hashes,
    _preflight_sources,
    _snapshot_source_inputs,
    write_preflighted_organizer_rows,
)
from financial_agent.ingestion.sources import sha256_path
from financial_agent.ingestion.writer import DatasetBuildWriter


class OfficialPipelineError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OrganizerInputs:
    data_paths: Mapping[str, Path]
    schema_paths: Mapping[str, Path]
    data_sha256: Mapping[str, str]
    schema_sha256: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _PreparedOfficialSource:
    source_code: str
    snapshot_count: int
    row_factories: tuple[Callable[[], Iterable[MappedRow]], ...]


@dataclass(frozen=True, slots=True)
class _OfficialWriteResult:
    source_counts: Mapping[str, Mapping[str, int]]
    issue_counts: Mapping[str, int]
    passed: bool


_OFFICIAL_SOURCE_ORDER = (
    "KRX_KOSPI_BASIC",
    "KRX_KOSDAQ_BASIC",
    "SEC_SERIES_CLASS_20260601",
    "KRX_ETF_PDF",
    "ECOS_731Y001",
    "SEC_NPORT_2026Q2",
)
_SUPPORTED_SOURCES = frozenset(_OFFICIAL_SOURCE_ORDER)
_OFFICIAL_WRITE_RECORD_LIMIT = 100_000


def _ordered_manifests(
    manifests: Sequence[OfficialSnapshotManifest],
) -> tuple[OfficialSnapshotManifest, ...]:
    snapshot_ids: set[str] = set()
    ordered: list[OfficialSnapshotManifest] = []
    for manifest in manifests:
        if manifest.snapshot_id in snapshot_ids:
            raise OfficialPipelineError(
                "OFFICIAL_SNAPSHOT_ID_DUPLICATE"
            ) from None
        snapshot_ids.add(manifest.snapshot_id)
        validate_official_snapshot(manifest)
        ordered.append(manifest)
    ordered.sort(key=lambda item: (item.source_code, item.snapshot_id))
    return tuple(ordered)


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    return date.fromisoformat(value)


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError
    return datetime.fromisoformat(f"{value[:-1]}+00:00")


def _manifest_from_mapping(value: object) -> OfficialSnapshotManifest:
    if not isinstance(value, dict) or set(value) != {
        "applicable_date",
        "available_at",
        "cutoff_date",
        "mapping_version",
        "objects",
        "parser_version",
        "published_at",
        "publisher_code",
        "snapshot_id",
        "source_code",
        "vintage_date",
    }:
        raise ValueError
    raw_objects = value["objects"]
    if not isinstance(raw_objects, list):
        raise ValueError
    objects: list[OfficialObjectManifest] = []
    for raw in raw_objects:
        if not isinstance(raw, dict) or set(raw) != {
            "media_type",
            "object_key",
            "object_name",
            "sha256",
            "size_bytes",
        }:
            raise ValueError
        if (
            not all(
                isinstance(raw[key], str)
                for key in (
                    "media_type",
                    "object_key",
                    "object_name",
                    "sha256",
                )
            )
            or type(raw["size_bytes"]) is not int
        ):
            raise ValueError
        objects.append(
            OfficialObjectManifest(
                object_name=raw["object_name"],
                object_key=raw["object_key"],
                media_type=raw["media_type"],
                size_bytes=raw["size_bytes"],
                sha256=raw["sha256"],
            )
        )
    text_fields = (
        "mapping_version",
        "parser_version",
        "publisher_code",
        "snapshot_id",
        "source_code",
    )
    if not all(isinstance(value[field], str) for field in text_fields):
        raise ValueError
    return OfficialSnapshotManifest(
        source_code=value["source_code"],
        snapshot_id=value["snapshot_id"],
        publisher_code=value["publisher_code"],
        cutoff_date=date.fromisoformat(value["cutoff_date"]),
        applicable_date=_optional_date(value["applicable_date"]),
        published_at=_optional_datetime(value["published_at"]),
        available_at=_optional_datetime(value["available_at"]),
        vintage_date=_optional_date(value["vintage_date"]),
        parser_version=value["parser_version"],
        mapping_version=value["mapping_version"],
        objects=tuple(objects),
    )


def load_official_manifests(
    manifest_root: Path,
) -> tuple[OfficialSnapshotManifest, ...]:
    try:
        if not manifest_root.is_dir():
            raise OSError
        manifests: list[OfficialSnapshotManifest] = []
        for path in sorted(manifest_root.rglob("*.json")):
            payload = path.read_bytes()
            manifest = _manifest_from_mapping(json.loads(payload.decode("utf-8")))
            validate_official_snapshot(manifest)
            if payload != _canonical_manifest_bytes(manifest):
                raise ValueError
            manifests.append(manifest)
        return _ordered_manifests(manifests)
    except OfficialPipelineError:
        raise
    except Exception:
        raise OfficialPipelineError("OFFICIAL_MANIFEST_INVALID") from None


def compose_stage03b_manifest(
    organizer_manifest: Mapping[str, object],
    official_manifests: Sequence[OfficialSnapshotManifest],
) -> Mapping[str, object]:
    ordered = _ordered_manifests(official_manifests)
    if not ordered:
        return dict(organizer_manifest)

    cutoff_text = organizer_manifest.get("cutoff_date")
    if not isinstance(cutoff_text, str) or any(
        manifest.cutoff_date.isoformat() != cutoff_text for manifest in ordered
    ):
        raise OfficialPipelineError("OFFICIAL_CUTOFF_MISMATCH") from None

    combined = dict(organizer_manifest)
    combined["official_snapshots"] = [
        {
            "manifest_sha256": validate_official_snapshot(manifest),
            "snapshot_id": manifest.snapshot_id,
            "source_code": manifest.source_code,
        }
        for manifest in ordered
    ]
    return combined


def compose_stage03b_capacity_probe_manifest(
    organizer_manifest: Mapping[str, object],
    official_manifests: Sequence[OfficialSnapshotManifest],
    *,
    sample_product_count: int,
    full_holding_count: int,
) -> Mapping[str, object]:
    combined = dict(
        compose_stage03b_manifest(organizer_manifest, official_manifests)
    )
    combined["capacity_probe"] = {
        "full_holding_count": full_holding_count,
        "sample_product_count": sample_product_count,
        "sample_selection": "sha256_product_entity_id_v1",
    }
    return combined


def verify_official_snapshot_objects(
    official_manifests: Sequence[OfficialSnapshotManifest],
    object_root: Path,
) -> Mapping[tuple[str, str], Path]:
    ordered = _ordered_manifests(official_manifests)
    try:
        resolved_root = object_root.resolve(strict=True)
    except OSError:
        raise OfficialPipelineError("OFFICIAL_OBJECT_ROOT_MISSING") from None

    verified: dict[tuple[str, str], Path] = {}
    for manifest in ordered:
        for item in manifest.objects:
            candidate = object_root / item.object_key
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                raise OfficialPipelineError("OFFICIAL_OBJECT_MISSING") from None
            if (
                not resolved.is_relative_to(resolved_root)
                or candidate.is_symlink()
                or not resolved.is_file()
            ):
                raise OfficialPipelineError("OFFICIAL_OBJECT_INVALID") from None
            try:
                size_bytes = resolved.stat().st_size
                digest = sha256_path(resolved)
            except OSError:
                raise OfficialPipelineError("OFFICIAL_OBJECT_READ_FAILED") from None
            if size_bytes != item.size_bytes:
                raise OfficialPipelineError("OFFICIAL_OBJECT_SIZE_MISMATCH") from None
            if digest != item.sha256:
                raise OfficialPipelineError("OFFICIAL_OBJECT_HASH_MISMATCH") from None
            verified[(manifest.snapshot_id, item.object_key)] = resolved
    return verified


@contextmanager
def _snapshot_official_inputs(
    official_manifests: Sequence[OfficialSnapshotManifest],
    object_root: Path,
) -> Iterator[Mapping[tuple[str, str], Path]]:
    if not official_manifests:
        yield {}
        return

    verified = verify_official_snapshot_objects(
        official_manifests,
        object_root,
    )
    try:
        with tempfile.TemporaryDirectory(
            prefix="financial-agent-official-snapshot-"
        ) as temporary_root:
            snapshot_root = Path(temporary_root)
            for manifest in _ordered_manifests(official_manifests):
                for item in manifest.objects:
                    destination = snapshot_root / item.object_key
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(
                        verified[(manifest.snapshot_id, item.object_key)],
                        destination,
                    )
            yield verify_official_snapshot_objects(
                official_manifests,
                snapshot_root,
            )
    except OfficialPipelineError:
        raise
    except OSError:
        raise OfficialPipelineError("OFFICIAL_OBJECT_READ_FAILED") from None


def _object_path(
    manifest: OfficialSnapshotManifest,
    verified_paths: Mapping[tuple[str, str], Path],
) -> Path:
    if len(manifest.objects) != 1:
        raise OfficialPipelineError("OFFICIAL_OBJECT_COUNT_INVALID") from None
    item = manifest.objects[0]
    return verified_paths[(manifest.snapshot_id, item.object_key)]


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        raise OfficialPipelineError("OFFICIAL_OBJECT_READ_FAILED") from None


def _prepare_official_sources(
    official_manifests: Sequence[OfficialSnapshotManifest],
    verified_paths: Mapping[tuple[str, str], Path],
    organizer_rows: Mapping[str, tuple[Mapping[str, object], ...]],
    organizer_contexts: Mapping[str, object],
    organizer_identity_index: AuthoritativeIdentityIndex,
    scratch_root: Path,
    nport_matched_product_sample_size: int | None = None,
) -> tuple[_PreparedOfficialSource, ...]:
    grouped: dict[str, list[OfficialSnapshotManifest]] = {}
    for manifest in _ordered_manifests(official_manifests):
        if manifest.source_code not in _SUPPORTED_SOURCES:
            raise OfficialPipelineError("OFFICIAL_SOURCE_UNSUPPORTED") from None
        grouped.setdefault(manifest.source_code, []).append(manifest)
    for source_code, manifests in grouped.items():
        if source_code != "KRX_ETF_PDF" and len(manifests) != 1:
            raise OfficialPipelineError(
                "OFFICIAL_SOURCE_CARDINALITY_INVALID"
            ) from None

    factories_by_source: dict[
        str, list[Callable[[], Iterable[MappedRow]]]
    ] = {source_code: [] for source_code in grouped}

    security_entries: list[tuple[IdentityCandidate, str]] = []
    security_axes: dict[tuple[str, str], set[str]] = {}
    for source_code in ("KRX_KOSPI_BASIC", "KRX_KOSDAQ_BASIC"):
        manifests = grouped.get(source_code, ())
        if not manifests:
            continue
        manifest = manifests[0]
        rows = parse_krx_security_basic(
            _read_bytes(_object_path(manifest, verified_paths)),
            market="KOSPI" if source_code == "KRX_KOSPI_BASIC" else "KOSDAQ",
        )
        for row in rows:
            organizer_resolution = organizer_identity_index.resolve(
                "ISIN", str(row["ISU_CD"])
            )
            if organizer_resolution.status == "AMBIGUOUS":
                continue
            entity_id = (
                organizer_resolution.canonical_identity.entity_id
                if organizer_resolution.status == "MATCHED"
                and organizer_resolution.canonical_identity is not None
                else stable_id(
                    "security", manifest.source_code, str(row["ISU_CD"])
                )
            )
            for scheme, value in (
                ("KRX_STANDARD_ISSUE_CODE", str(row["ISU_CD"])),
                ("KRX_SHORT_ISSUE_CODE", str(row["ISU_SRT_CD"])),
            ):
                security_entries.append(
                    (IdentityCandidate(scheme, value), entity_id)
                )
                security_axes.setdefault((scheme, value), set()).add(entity_id)
        factories_by_source[source_code].append(
            lambda manifest=manifest, rows=rows: map_krx_security_basic(
                manifest,
                rows,
                identity_index=organizer_identity_index,
            )
        )
    if any(len(entity_ids) != 1 for entity_ids in security_axes.values()):
        raise OfficialPipelineError("OFFICIAL_IDENTITY_CONFLICT") from None
    security_index = OfficialIdentityIndex(
        exact_entries=security_entries,
        organizer_index=organizer_identity_index,
    )

    bindings = ()
    holdings_manifests = grouped.get("KRX_ETF_PDF", ())
    if holdings_manifests:
        domestic_rows = organizer_rows.get("PREF01N001")
        binding_manifest = holdings_manifests[0]
        if domestic_rows is None or binding_manifest.applicable_date is None:
            raise OfficialPipelineError("OFFICIAL_DEPENDENCY_MISSING") from None
        if any(
            manifest.applicable_date != binding_manifest.applicable_date
            for manifest in holdings_manifests
        ):
            raise OfficialPipelineError(
                "OFFICIAL_SOURCE_DATE_MISMATCH"
            ) from None
        binding_result = build_krx_etf_product_bindings(
            organizer_rows=domestic_rows,
            daily_rows=(),
            applicable_date=binding_manifest.applicable_date,
            identity_index=organizer_identity_index,
        )
        bindings = binding_result.bindings

    if holdings_manifests:
        assert holdings_manifests[0].applicable_date is not None
        validate_krx_etf_holding_inventory(
            bindings=bindings,
            object_names=(
                manifest.objects[0].object_name
                for manifest in holdings_manifests
            ),
            applicable_date=holdings_manifests[0].applicable_date,
        )
    bindings_by_code = {binding.krx_short_code: binding for binding in bindings}
    for manifest in holdings_manifests:
        path = _object_path(manifest, verified_paths)
        rows = parse_krx_etf_pdf_csv(_read_bytes(path))
        object_name = manifest.objects[0].object_name
        short_code = object_name.split("_", 1)[0]
        binding = bindings_by_code.get(short_code)
        if binding is None:
            raise OfficialPipelineError("OFFICIAL_IDENTITY_UNRESOLVED") from None
        factories_by_source["KRX_ETF_PDF"].append(
            lambda manifest=manifest, rows=rows, binding=binding: iter(
                (
                    map_krx_holding_snapshot(
                        manifest,
                        rows,
                        binding=binding,
                        security_index=security_index,
                    ),
                )
            )
        )

    ecos_manifests = grouped.get("ECOS_731Y001", ())
    if ecos_manifests:
        manifest = ecos_manifests[0]
        rows = parse_ecos_731y001(
            _read_bytes(_object_path(manifest, verified_paths))
        )
        mapped = map_ecos_fx(manifest, rows)
        factories_by_source["ECOS_731Y001"].append(
            lambda mapped=mapped: iter(mapped)
        )

    series_index = None
    series_manifests = grouped.get("SEC_SERIES_CLASS_20260601", ())
    if series_manifests:
        series_manifest = series_manifests[0]
        series_rows = parse_sec_series_class(
            _read_bytes(_object_path(series_manifest, verified_paths))
        )
        series_index = build_sec_series_class_index(
            series_manifest,
            series_rows,
        )
        source_row = _sec_series_source_row(series_manifest)
        factories_by_source["SEC_SERIES_CLASS_20260601"].append(
            lambda source_row=source_row: iter((source_row,))
        )

    nport_manifests = grouped.get("SEC_NPORT_2026Q2", ())
    if nport_manifests:
        if series_index is None:
            raise OfficialPipelineError("OFFICIAL_DEPENDENCY_MISSING") from None
        overseas_rows = organizer_rows.get("PREF02N001")
        organizer_context = organizer_contexts.get("PREF02N001")
        if overseas_rows is None or organizer_context is None:
            raise OfficialPipelineError("OFFICIAL_DEPENDENCY_MISSING") from None
        bindings_by_product: dict[str, NportProductBinding] = {}
        for row_number, row in enumerate(overseas_rows, start=2):
            record_key = normalize_name(str(row.get("pd_itm_no", "")))
            if record_key in {"", "NULL"}:
                continue
            resolution = organizer_identity_index.resolve(
                "PREF02_PD_ITM_NO", record_key
            )
            if (
                resolution.status != "MATCHED"
                or resolution.canonical_identity is None
            ):
                continue
            product_id = resolution.canonical_identity.entity_id
            mapped = organizer_pipeline._map_source_row(
                "PREF02N001",
                row_number,
                row,
                organizer_context,
                organizer_identity_index,
            )
            if not any(
                entity.get("entity_id") == product_id
                and entity.get("entity_type") == "product"
                for entity in mapped.records_by_table.get(
                    "catalog.entity", ()
                )
            ):
                continue
            cik = normalize_name(str(row.get("pd_us_cik", "")))
            ticker = normalize_name(str(row.get("pd_abrv_nm", "")))
            if any(value in {"", "NULL"} for value in (cik, ticker)):
                continue
            binding = NportProductBinding(
                product_entity_id=product_id,
                cik=cik,
                class_ticker=ticker,
            )
            existing = bindings_by_product.get(product_id)
            if existing is not None and existing != binding:
                raise OfficialPipelineError("OFFICIAL_IDENTITY_CONFLICT") from None
            bindings_by_product[product_id] = binding
        nport_manifest = nport_manifests[0]
        files = verify_and_extract_nport(
            _object_path(nport_manifest, verified_paths),
            scratch_root / nport_manifest.snapshot_id,
            NportArchiveLimits(),
        )
        bindings = tuple(
            bindings_by_product[key] for key in sorted(bindings_by_product)
        )
        factories_by_source["SEC_NPORT_2026Q2"].append(
            lambda files=files, manifest=nport_manifest, bindings=bindings: (
                iter_eligible_nport_funds(
                    files,
                    CUTOFF_DATE,
                    manifest=manifest,
                    series_class_index=series_index,
                    product_bindings=bindings,
                    security_identity_index=security_index,
                    matched_product_sample_size=(
                        nport_matched_product_sample_size
                    ),
                )
            )
        )

    return tuple(
        _PreparedOfficialSource(
            source_code=source_code,
            snapshot_count=len(grouped[source_code]),
            row_factories=tuple(factories_by_source[source_code]),
        )
        for source_code in _OFFICIAL_SOURCE_ORDER
        if source_code in grouped
    )


def _with_hash(payload: Mapping[str, object]) -> dict[str, object]:
    record = dict(payload)
    record["record_hash"] = make_record_hash(payload)
    return record


def _sec_series_source_row(
    manifest: OfficialSnapshotManifest,
) -> MappedRow:
    publisher_id = stable_id("institution", "OFFICIAL_PUBLISHER", "SEC")
    source_id = stable_id("source", manifest.source_code, manifest.snapshot_id)
    return MappedRow(
        row_number=0,
        disposition="accepted",
        records_by_table={
            "catalog.entity": (
                _with_hash(
                    {
                        "entity_id": publisher_id,
                        "entity_type": "institution",
                        "canonical_name": "U.S. Securities and Exchange Commission",
                        "normalized_name": "U.S. Securities and Exchange Commission",
                    }
                ),
            ),
            "catalog.institution": (
                {
                    "entity_id": publisher_id,
                    "institution_kind": "regulator",
                },
            ),
            "catalog.identifier": (
                _with_hash(
                    {
                        "identifier_id": stable_id(
                            "identifier", "OFFICIAL_PUBLISHER", "SEC"
                        ),
                        "entity_id": publisher_id,
                        "scheme": "OFFICIAL_PUBLISHER_CODE",
                        "identifier_value": "SEC",
                        "is_primary": True,
                        "valid_from": None,
                        "valid_to": None,
                    }
                ),
            ),
            "evidence.source_record": (
                _with_hash(
                    {
                        "source_id": source_id,
                        "publisher": publisher_id,
                        "publisher_type": "regulator",
                        "source_title": (
                            "SEC Investment Company Series and Class Report"
                        ),
                        "source_type": "dataset",
                        "authority_tier": "official",
                        "source_locator_root": manifest.objects[0].object_key,
                        "content_checksum": validate_official_snapshot(manifest),
                        "license_or_usage_note": "official SEC public report",
                        "eligible_for_claim": True,
                    }
                ),
            ),
        },
        issues=(),
    )


def _organizer_rows_for_official(
    data_paths: Mapping[str, Path],
    source_codes: set[str],
) -> Mapping[str, tuple[Mapping[str, object], ...]]:
    required: set[str] = set()
    if "KRX_ETF_PDF" in source_codes:
        required.add("PREF01N001")
    if "SEC_NPORT_2026Q2" in source_codes:
        required.add("PREF02N001")
    rows: dict[str, tuple[Mapping[str, object], ...]] = {}
    for source_code in sorted(required):
        spec = organizer_pipeline.SOURCE_SPECS[source_code]
        rows[source_code] = tuple(
            organizer_pipeline.iter_workbook_rows(
                data_paths[source_code],
                spec,
            )
        )
    return rows


def validate_stage03b_inputs(
    *,
    organizer_inputs: OrganizerInputs,
    official_manifests: Sequence[OfficialSnapshotManifest],
    official_object_root: Path,
) -> str:
    with _snapshot_source_inputs(
        organizer_inputs.data_paths,
        organizer_inputs.schema_paths,
    ) as (data_paths, schema_paths):
        preflight = _preflight_sources(
            data_paths=data_paths,
            schema_paths=schema_paths,
            data_sha256=organizer_inputs.data_sha256,
            schema_sha256=organizer_inputs.schema_sha256,
        )
        with _snapshot_official_inputs(
            official_manifests,
            official_object_root,
        ) as verified_paths:
            combined_manifest = compose_stage03b_manifest(
                preflight.manifest,
                official_manifests,
            )
            with tempfile.TemporaryDirectory(
                prefix="financial-agent-official-validation-"
            ) as temporary_root:
                _prepare_official_sources(
                    official_manifests,
                    verified_paths,
                    _organizer_rows_for_official(
                        data_paths,
                        {
                            manifest.source_code
                            for manifest in official_manifests
                        },
                    ),
                    preflight.contexts,
                    preflight.identity_index,
                    Path(temporary_root),
                )
            return canonical_sha256(combined_manifest)


def _coverage_statuses(row: MappedRow) -> tuple[str, ...]:
    statuses: list[str] = []
    for evidence in row.records_by_table.get("evidence.evidence_record", ()):
        if (
            evidence.get("evidence_kind") == "query_scope"
            and evidence.get("predicate_id") == "holdsSecurityCoverage"
        ):
            status = evidence.get("raw_value_repr")
            if status in {
                "COVERED",
                "PARTIALLY_COVERED",
                "NOT_COVERED",
                "CONFLICT",
            }:
                statuses.append(str(status))
    return tuple(statuses)


async def _write_official_sources(
    writer: DatasetBuildWriter,
    *,
    dataset_version: str,
    sources: Sequence[_PreparedOfficialSource],
    batch_size: int,
) -> _OfficialWriteResult:
    source_counts: dict[str, dict[str, int]] = {}
    issue_counts: Counter[str] = Counter()
    passed = True
    for source in sources:
        counts = {
            "COVERED": 0,
            "CONFLICT": 0,
            "NOT_COVERED": 0,
            "PARTIALLY_COVERED": 0,
            "accepted": 0,
            "fatal": 0,
            "limited": 0,
            "quarantined": 0,
            "rows": 0,
            "snapshots": source.snapshot_count,
        }
        batch: list[MappedRow] = []
        batch_record_count = 0
        for factory in source.row_factories:
            for row in factory():
                validate_official_enrichment_scope(source.source_code, row)
                counts["rows"] += 1
                counts[row.disposition] += 1
                for status in _coverage_statuses(row):
                    counts[status] += 1
                fatal = False
                for issue in row.issues:
                    issue_counts[issue.code] += 1
                    fatal = fatal or issue.severity == "fatal"
                if fatal:
                    counts["fatal"] += 1
                    passed = False
                row_record_count = sum(
                    len(records) for records in row.records_by_table.values()
                )
                if (
                    batch
                    and batch_record_count + row_record_count
                    > _OFFICIAL_WRITE_RECORD_LIMIT
                ):
                    await writer.write_rows(dataset_version, batch)
                    batch = []
                    batch_record_count = 0
                batch.append(row)
                batch_record_count += row_record_count
                if len(batch) == batch_size:
                    await writer.write_rows(dataset_version, batch)
                    batch = []
                    batch_record_count = 0
        if batch:
            await writer.write_rows(dataset_version, batch)
        source_counts[source.source_code] = counts
    return _OfficialWriteResult(
        source_counts=source_counts,
        issue_counts=dict(issue_counts),
        passed=passed,
    )


async def build_stage03b_dataset(
    engine: AsyncEngine,
    *,
    dataset_version: str,
    organizer_inputs: OrganizerInputs,
    official_manifests: Sequence[OfficialSnapshotManifest],
    official_object_root: Path,
    batch_size: int = 1000,
) -> BuildReport:
    if batch_size < 1:
        raise OfficialPipelineError("BUILD_BATCH_SIZE_INVALID") from None

    with _snapshot_source_inputs(
        organizer_inputs.data_paths,
        organizer_inputs.schema_paths,
    ) as (data_paths, schema_paths):
        preflight = _preflight_sources(
            data_paths=data_paths,
            schema_paths=schema_paths,
            data_sha256=organizer_inputs.data_sha256,
            schema_sha256=organizer_inputs.schema_sha256,
        )
        with _snapshot_official_inputs(
            official_manifests,
            official_object_root,
        ) as verified_paths:
            combined_manifest = compose_stage03b_manifest(
                preflight.manifest,
                official_manifests,
            )
            manifest_hash = canonical_sha256(combined_manifest)
            with tempfile.TemporaryDirectory(
                prefix="financial-agent-official-build-"
            ) as temporary_root:
                prepared_sources = _prepare_official_sources(
                    official_manifests,
                    verified_paths,
                    _organizer_rows_for_official(
                        data_paths,
                        {
                            manifest.source_code
                            for manifest in official_manifests
                        },
                    ),
                    preflight.contexts,
                    preflight.identity_index,
                    Path(temporary_root),
                )

                writer = DatasetBuildWriter(engine)
                await writer.create_building_dataset(
                    dataset_version,
                    manifest_hash,
                    CUTOFF_DATE,
                )
                organizer_result = await write_preflighted_organizer_rows(
                    writer,
                    dataset_version=dataset_version,
                    data_paths=data_paths,
                    preflight=preflight,
                    batch_size=batch_size,
                )
                official_result = await _write_official_sources(
                    writer,
                    dataset_version=dataset_version,
                    sources=prepared_sources,
                    batch_size=batch_size,
                )
                table_counts = await writer.table_counts(dataset_version)
                component_hashes = await _database_component_hashes(
                    engine,
                    dataset_version,
                )
        source_counts = dict(organizer_result.source_counts)
        source_counts.update(official_result.source_counts)
        issue_counts = Counter(organizer_result.issue_counts)
        issue_counts.update(official_result.issue_counts)
        return BuildReport(
            dataset_version=dataset_version,
            cutoff_date=CUTOFF_DATE,
            dataset_manifest_hash=manifest_hash,
            source_counts=source_counts,
            table_counts=table_counts,
            issue_counts=dict(issue_counts),
            component_hashes=component_hashes,
            passed=organizer_result.passed and official_result.passed,
        )


async def build_stage03b_capacity_probe(
    engine: AsyncEngine,
    *,
    dataset_version: str,
    organizer_inputs: OrganizerInputs,
    official_manifests: Sequence[OfficialSnapshotManifest],
    official_object_root: Path,
    sample_product_count: int,
    full_holding_count: int,
    current_storage_gib: int,
    batch_size: int = 1000,
) -> CapacityProbeReport:
    if (
        batch_size < 1
        or sample_product_count < 1
        or full_holding_count < 1
        or current_storage_gib < 1
    ):
        raise CapacityProbeError("CAPACITY_PROBE_INPUT_INVALID") from None
    source_codes = {manifest.source_code for manifest in official_manifests}
    if not {
        "SEC_SERIES_CLASS_20260601",
        "SEC_NPORT_2026Q2",
    }.issubset(source_codes):
        raise CapacityProbeError("CAPACITY_PROBE_SOURCE_MISSING") from None

    await require_capacity_probe_dataset_absent(engine, dataset_version)
    with _snapshot_source_inputs(
        organizer_inputs.data_paths,
        organizer_inputs.schema_paths,
    ) as (data_paths, schema_paths):
        preflight = _preflight_sources(
            data_paths=data_paths,
            schema_paths=schema_paths,
            data_sha256=organizer_inputs.data_sha256,
            schema_sha256=organizer_inputs.schema_sha256,
        )
        with _snapshot_official_inputs(
            official_manifests,
            official_object_root,
        ) as verified_paths:
            combined_manifest = compose_stage03b_capacity_probe_manifest(
                preflight.manifest,
                official_manifests,
                sample_product_count=sample_product_count,
                full_holding_count=full_holding_count,
            )
            manifest_hash = canonical_sha256(combined_manifest)
            with tempfile.TemporaryDirectory(
                prefix="financial-agent-capacity-probe-"
            ) as temporary_root:
                prepared_sources = _prepare_official_sources(
                    official_manifests,
                    verified_paths,
                    _organizer_rows_for_official(
                        data_paths,
                        source_codes,
                    ),
                    preflight.contexts,
                    preflight.identity_index,
                    Path(temporary_root),
                    nport_matched_product_sample_size=sample_product_count,
                )
                nport_sources = tuple(
                    source
                    for source in prepared_sources
                    if source.source_code == "SEC_NPORT_2026Q2"
                )
                base_sources = tuple(
                    source
                    for source in prepared_sources
                    if source.source_code != "SEC_NPORT_2026Q2"
                )
                if len(nport_sources) != 1:
                    raise CapacityProbeError(
                        "CAPACITY_PROBE_SOURCE_MISSING"
                    ) from None

                storage_before = await measure_application_storage_bytes(engine)
                writer = DatasetBuildWriter(engine)
                await writer.create_building_dataset(
                    dataset_version,
                    manifest_hash,
                    CUTOFF_DATE,
                )
                organizer_result = await write_preflighted_organizer_rows(
                    writer,
                    dataset_version=dataset_version,
                    data_paths=data_paths,
                    preflight=preflight,
                    batch_size=batch_size,
                )
                base_result = await _write_official_sources(
                    writer,
                    dataset_version=dataset_version,
                    sources=base_sources,
                    batch_size=batch_size,
                )
                storage_after_base = await measure_application_storage_bytes(
                    engine
                )
                nport_result = await _write_official_sources(
                    writer,
                    dataset_version=dataset_version,
                    sources=nport_sources,
                    batch_size=batch_size,
                )
                storage_after_sample = await measure_application_storage_bytes(
                    engine
                )

    sampled_products = int(
        nport_result.source_counts["SEC_NPORT_2026Q2"]["rows"]
    )
    sampled_holdings = await count_nport_holding_relations(
        engine, dataset_version
    )
    status, active = await capacity_probe_dataset_state(engine, dataset_version)
    base_bytes = storage_after_base - storage_before
    sampled_nport_bytes = storage_after_sample - storage_after_base
    if (
        sampled_products != sample_product_count
        or sampled_holdings < 1
        or base_bytes < 1
        or sampled_nport_bytes < 1
        or not organizer_result.passed
        or not base_result.passed
        or not nport_result.passed
        or status != "building"
        or active
    ):
        raise CapacityProbeError("CAPACITY_PROBE_MEASUREMENT_INVALID") from None
    estimate = estimate_stage03b_capacity(
        base_bytes=base_bytes,
        sampled_nport_bytes=sampled_nport_bytes,
        sampled_holding_count=sampled_holdings,
        full_holding_count=full_holding_count,
        current_storage_gib=current_storage_gib,
    )
    return CapacityProbeReport(
        sample_product_count=sampled_products,
        sample_holding_count=sampled_holdings,
        storage_before_bytes=storage_before,
        base_bytes=base_bytes,
        sampled_nport_bytes=sampled_nport_bytes,
        dataset_status=status,
        active=active,
        estimate=estimate,
    )
