from __future__ import annotations

import codecs
import csv
import json
import re
import shutil
import stat
import tempfile
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

from financial_agent.contracts import encode_contract_value
from financial_agent.ingestion.mapping.common import (
    make_record_hash,
    normalize_name,
    stable_id,
)
from financial_agent.ingestion.models import MappedRow, MappingIssue
from financial_agent.ingestion.sources import SourceVerificationError

from .identity import IdentityResolution, OfficialIdentityIndex
from .models import OfficialSnapshotManifest
from .snapshot import validate_official_snapshot


_REQUIRED_HEADERS = {
    "SUBMISSION.tsv": {
        "ACCESSION_NUMBER",
        "FILING_DATE",
        "SUB_TYPE",
        "REPORT_DATE",
    },
    "REGISTRANT.tsv": {
        "ACCESSION_NUMBER",
        "CIK",
        "REGISTRANT_NAME",
        "LEI",
    },
    "FUND_REPORTED_INFO.tsv": {
        "ACCESSION_NUMBER",
        "SERIES_NAME",
        "SERIES_ID",
        "SERIES_LEI",
    },
    "FUND_REPORTED_HOLDING.tsv": {
        "ACCESSION_NUMBER",
        "HOLDING_ID",
        "ISSUER_NAME",
        "ISSUER_TITLE",
        "ISSUER_CUSIP",
        "BALANCE",
        "UNIT",
        "OTHER_UNIT_DESC",
        "CURRENCY_CODE",
        "CURRENCY_VALUE",
        "PERCENTAGE",
        "PAYOFF_PROFILE",
        "ASSET_CAT",
        "OTHER_ASSET",
        "INVESTMENT_COUNTRY",
        "DERIVATIVE_CAT",
    },
    "IDENTIFIERS.tsv": {
        "HOLDING_ID",
        "IDENTIFIERS_ID",
        "IDENTIFIER_ISIN",
        "IDENTIFIER_TICKER",
        "OTHER_IDENTIFIER",
        "OTHER_IDENTIFIER_DESC",
    },
}
_STREAM_CHUNK_BYTES = 1024 * 1024
_MAXIMUM_COMPRESSION_RATIO = 200
_SOURCE_CODE = "SEC_NPORT_2026Q2"
_SERIES_SOURCE_CODE = "SEC_SERIES_CLASS_20260601"
_APPROVED_PACKAGE_DATE = date(2026, 6, 30)
_APPROVED_AT = datetime(2026, 8, 22, tzinfo=UTC)
_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_CIK_PATTERN = re.compile(r"[0-9]{1,10}")
_SERIES_PATTERN = re.compile(r"S[0-9]{9}")
_TABLES = (
    "catalog.entity",
    "catalog.product",
    "catalog.security",
    "catalog.institution",
    "catalog.identifier",
    "catalog.alias",
    "relation.relation_record",
    "observation.metric_definition",
    "observation.observation_record",
    "evidence.source_record",
    "evidence.evidence_record",
    "evidence.evidence_observation_origin",
    "evidence.evidence_relation_origin",
)
_METRICS: dict[str, tuple[str, str, str | None]] = {
    "BALANCE": ("official_holding_balance", "numeric", None),
    "CURRENCY_CODE": ("official_holding_currency", "text", None),
    "CURRENCY_VALUE": ("official_holding_currency_value", "numeric", "amount"),
    "PERCENTAGE": (
        "official_holding_weight_pct",
        "numeric",
        "percentage_point",
    ),
    "ASSET_CAT": ("official_holding_asset_category", "text", None),
    "INVESTMENT_COUNTRY": (
        "official_holding_investment_country",
        "text",
        None,
    ),
}


@dataclass(frozen=True, slots=True)
class NportArchiveLimits:
    maximum_archive_bytes: int = 805_306_368
    maximum_expanded_bytes: int = 8_589_934_592
    maximum_members: int = 64

    def __post_init__(self) -> None:
        if (
            self.maximum_archive_bytes <= 0
            or self.maximum_expanded_bytes <= 0
            or self.maximum_members <= 0
        ):
            raise ValueError("N-PORT archive limits must be positive")


@dataclass(frozen=True, slots=True)
class NportProductBinding:
    product_entity_id: str
    cik: str
    class_ticker: str

    def __post_init__(self) -> None:
        if not all(
            normalize_name(value)
            for value in (self.product_entity_id, self.cik, self.class_ticker)
        ):
            raise ValueError("N-PORT product binding fields must be non-empty")


def _error(code: str, message: str) -> SourceVerificationError:
    return SourceVerificationError(code, message)


def _validate_members(
    members: list[zipfile.ZipInfo], limits: NportArchiveLimits
) -> dict[str, zipfile.ZipInfo]:
    if len(members) > limits.maximum_members:
        raise _error(
            "SEC_NPORT_LIMIT_EXCEEDED",
            "SEC N-PORT archive exceeds the approved member limit",
        )

    names: set[str] = set()
    required_casefold = {name.casefold(): name for name in _REQUIRED_HEADERS}
    total_expanded = 0
    by_name: dict[str, zipfile.ZipInfo] = {}
    for member in members:
        name = member.filename
        pure_name = PurePosixPath(name)
        unix_mode = member.external_attr >> 16
        if (
            not name
            or "\\" in name
            or pure_name.is_absolute()
            or len(pure_name.parts) != 1
            or pure_name.name in {".", ".."}
            or member.is_dir()
            or stat.S_ISLNK(unix_mode)
            or member.flag_bits & 0x1
        ):
            raise _error(
                "SEC_NPORT_ARCHIVE_INVALID",
                "SEC N-PORT archive contains an unsafe member",
            )
        if name in names:
            raise _error(
                "SEC_NPORT_ARCHIVE_INVALID",
                "SEC N-PORT archive contains a duplicate member",
            )
        names.add(name)
        expected_case = required_casefold.get(name.casefold())
        if expected_case is not None and name != expected_case:
            raise _error(
                "SEC_NPORT_ARCHIVE_INVALID",
                "SEC N-PORT archive contains an unexpected file-name case",
            )
        if member.file_size < 0 or member.compress_size < 0:
            raise _error(
                "SEC_NPORT_ARCHIVE_INVALID",
                "SEC N-PORT archive contains invalid member metadata",
            )
        if member.file_size and (
            member.compress_size == 0
            or member.file_size
            > member.compress_size * _MAXIMUM_COMPRESSION_RATIO
        ):
            raise _error(
                "SEC_NPORT_LIMIT_EXCEEDED",
                "SEC N-PORT archive has a suspicious compression ratio",
            )
        total_expanded += member.file_size
        if total_expanded > limits.maximum_expanded_bytes:
            raise _error(
                "SEC_NPORT_LIMIT_EXCEEDED",
                "SEC N-PORT archive exceeds the approved expanded-size limit",
            )
        by_name[name] = member

    if not set(_REQUIRED_HEADERS).issubset(names):
        raise _error(
            "SEC_NPORT_FILES_MISSING",
            "SEC N-PORT archive is missing an approved required file",
        )
    return by_name


def _copy_utf8_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    destination: Path,
    limits: NportArchiveLimits,
) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    copied = 0
    try:
        with archive.open(member, "r") as source, destination.open("wb") as output:
            while True:
                chunk = source.read(_STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > member.file_size or copied > limits.maximum_expanded_bytes:
                    raise _error(
                        "SEC_NPORT_LIMIT_EXCEEDED",
                        "SEC N-PORT member exceeds its approved size",
                    )
                decoder.decode(chunk, final=False)
                output.write(chunk)
            decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        raise _error(
            "SEC_NPORT_TSV_INVALID",
            "SEC N-PORT required file is not valid UTF-8 TSV",
        ) from None
    if copied != member.file_size:
        raise _error(
            "SEC_NPORT_ARCHIVE_INVALID",
            "SEC N-PORT member size differs from ZIP metadata",
        )


def _validate_header(name: str, path: Path) -> None:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream, delimiter="\t")
            header = next(reader)
    except (UnicodeDecodeError, OSError, StopIteration, csv.Error):
        raise _error(
            "SEC_NPORT_TSV_INVALID",
            "SEC N-PORT required file is not valid UTF-8 TSV",
        ) from None
    if (
        not header
        or len(header) != len(set(header))
        or not _REQUIRED_HEADERS[name].issubset(header)
    ):
        raise _error(
            "SEC_NPORT_TSV_INVALID",
            "SEC N-PORT required file header differs from the approved schema",
        ) from None


def verify_and_extract_nport(
    archive: Path,
    destination: Path,
    limits: NportArchiveLimits,
) -> Mapping[str, Path]:
    if destination.exists():
        raise _error(
            "SEC_NPORT_DESTINATION_EXISTS",
            "SEC N-PORT extraction destination already exists",
        ) from None
    try:
        if not archive.is_file() or archive.stat().st_size > limits.maximum_archive_bytes:
            raise _error(
                "SEC_NPORT_LIMIT_EXCEEDED",
                "SEC N-PORT archive exceeds the approved archive-size limit",
            )
    except SourceVerificationError:
        raise
    except OSError:
        raise _error(
            "SEC_NPORT_ARCHIVE_INVALID",
            "SEC N-PORT archive is unavailable",
        ) from None

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=".sec-nport-", dir=destination.parent
        )
    )
    try:
        with zipfile.ZipFile(archive, "r") as package:
            members = _validate_members(package.infolist(), limits)
            for name in _REQUIRED_HEADERS:
                output = temporary / name
                _copy_utf8_member(package, members[name], output, limits)
                _validate_header(name, output)
        if destination.exists():
            raise _error(
                "SEC_NPORT_DESTINATION_EXISTS",
                "SEC N-PORT extraction destination already exists",
            )
        temporary.replace(destination)
        return {name: destination / name for name in _REQUIRED_HEADERS}
    except SourceVerificationError as error:
        shutil.rmtree(temporary, ignore_errors=True)
        raise error from None
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile, zipfile.LargeZipFile):
        shutil.rmtree(temporary, ignore_errors=True)
        raise _error(
            "SEC_NPORT_ARCHIVE_INVALID",
            "SEC N-PORT archive could not be safely extracted",
        ) from None


@dataclass(frozen=True, slots=True)
class _TsvRow:
    row_number: int
    values: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _Filing:
    accession: str
    filing_date: date
    report_date: date
    sub_type: str
    cik: str
    submission: _TsvRow
    registrant: _TsvRow
    fund: _TsvRow


def _with_hash(payload: Mapping[str, object]) -> dict[str, object]:
    record = dict(payload)
    record["record_hash"] = make_record_hash(payload)
    return record


def _tag(value: object) -> dict[str, object]:
    return encode_contract_value(value).model_dump(mode="json")


def _empty_records() -> dict[str, list[Mapping[str, object]]]:
    return {table: [] for table in _TABLES}


def _iter_tsv(files: Mapping[str, Path], name: str) -> Iterator[_TsvRow]:
    path = files.get(name)
    if path is None:
        raise _error(
            "SEC_NPORT_FILES_MISSING",
            "SEC N-PORT mapping input is missing an approved required file",
        ) from None
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            header = tuple(reader.fieldnames or ())
            if (
                not header
                or len(header) != len(set(header))
                or not _REQUIRED_HEADERS[name].issubset(header)
            ):
                raise ValueError
            for row_number, raw in enumerate(reader, start=2):
                if None in raw or set(raw) != set(header):
                    raise ValueError
                if any(not isinstance(value, str) for value in raw.values()):
                    raise ValueError
                yield _TsvRow(row_number, dict(raw))
    except SourceVerificationError:
        raise
    except (OSError, UnicodeDecodeError, csv.Error, ValueError):
        raise _error(
            "SEC_NPORT_TSV_INVALID",
            "SEC N-PORT required file differs from the approved TSV schema",
        ) from None


def _read_tsv(files: Mapping[str, Path], name: str) -> tuple[_TsvRow, ...]:
    return tuple(_iter_tsv(files, name))


def _unique_by(
    rows: Iterable[_TsvRow],
    key_fields: tuple[str, ...],
) -> dict[tuple[str, ...], _TsvRow]:
    indexed: dict[tuple[str, ...], _TsvRow] = {}
    for row in rows:
        key = tuple(row.values[field] for field in key_fields)
        if not all(key) or key in indexed:
            raise _error(
                "SEC_NPORT_DUPLICATE_KEY",
                "SEC N-PORT snapshot contains a missing or duplicate primary key",
            ) from None
        indexed[key] = row
    return indexed


def _parse_iso_date(value: str) -> date:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError
    return date.fromisoformat(value)


def _normalize_cik(value: str) -> str:
    normalized = normalize_name(value)
    if _CIK_PATTERN.fullmatch(normalized) is None:
        raise ValueError
    return normalized.lstrip("0") or "0"


def _parse_decimal(value: str) -> Decimal:
    if _DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError from None
    if not parsed.is_finite():
        raise ValueError
    return parsed


def _valid_isin(value: str) -> bool:
    normalized = normalize_name(value).upper()
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", normalized) is None:
        return False
    expanded = "".join(str(int(character, 36)) for character in normalized)
    total = 0
    for index, character in enumerate(reversed(expanded)):
        number = int(character) * (2 if index % 2 else 1)
        total += number // 10 + number % 10
    return total % 10 == 0


def _valid_cusip(value: str) -> bool:
    normalized = normalize_name(value).upper()
    if re.fullmatch(r"[A-Z0-9*@#]{9}", normalized) is None:
        return False

    def value_of(character: str) -> int:
        if character.isdigit():
            return int(character)
        if character.isalpha():
            return ord(character) - ord("A") + 10
        return {"*": 36, "@": 37, "#": 38}[character]

    total = 0
    for index, character in enumerate(normalized[:8]):
        value = value_of(character) * (2 if index % 2 else 1)
        total += value // 10 + value % 10
    return (10 - total % 10) % 10 == int(normalized[8])


def _valid_lei(value: str) -> bool:
    normalized = normalize_name(value).upper()
    if re.fullmatch(r"[A-Z0-9]{18}[0-9]{2}", normalized) is None:
        return False
    expanded = "".join(str(int(character, 36)) for character in normalized)
    return int(expanded) % 97 == 1


def _filing_datetime(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _available_at(
    manifest: OfficialSnapshotManifest, filing_date: date
) -> datetime:
    filing_at = _filing_datetime(filing_date)
    if manifest.available_at is None:
        return filing_at
    return max(manifest.available_at, filing_at)


def _validate_manifest(
    manifest: OfficialSnapshotManifest, cutoff: date
) -> str:
    if (
        manifest.source_code != _SOURCE_CODE
        or manifest.publisher_code != "SEC"
        or cutoff != manifest.cutoff_date
        or manifest.published_at is None
        or manifest.available_at is None
        or manifest.published_at.date() != _APPROVED_PACKAGE_DATE
        or manifest.available_at.date() != _APPROVED_PACKAGE_DATE
    ):
        raise _error(
            "SEC_NPORT_SOURCE_MISMATCH",
            "SEC N-PORT manifest differs from the approved 2026 Q2 source",
        ) from None
    return validate_official_snapshot(manifest)


def _load_filings(
    files: Mapping[str, Path], cutoff: date
) -> tuple[tuple[_Filing, ...], frozenset[str]]:
    submissions = _read_tsv(files, "SUBMISSION.tsv")
    registrants = _read_tsv(files, "REGISTRANT.tsv")
    funds = _read_tsv(files, "FUND_REPORTED_INFO.tsv")

    submission_by_key = _unique_by(submissions, ("ACCESSION_NUMBER",))
    registrant_by_key = _unique_by(registrants, ("ACCESSION_NUMBER",))
    fund_by_key = _unique_by(funds, ("ACCESSION_NUMBER",))

    submission_accessions = {key[0] for key in submission_by_key}
    if (
        {key[0] for key in registrant_by_key} != submission_accessions
        or {key[0] for key in fund_by_key} != submission_accessions
    ):
        raise _error(
            "SEC_NPORT_REFERENTIAL_INTEGRITY",
            "SEC N-PORT snapshot contains an orphan structural key",
        ) from None

    parsed: list[_Filing] = []
    for key, submission in submission_by_key.items():
        accession = key[0]
        try:
            filing_date = _parse_iso_date(submission.values["FILING_DATE"])
            report_date = _parse_iso_date(submission.values["REPORT_DATE"])
            subtype = normalize_name(submission.values["SUB_TYPE"]).upper()
            registrant = registrant_by_key[(accession,)]
            fund = fund_by_key[(accession,)]
            cik = _normalize_cik(registrant.values["CIK"])
            series_id = normalize_name(fund.values["SERIES_ID"]).upper()
            if _SERIES_PATTERN.fullmatch(series_id) is None:
                raise ValueError
        except (KeyError, ValueError):
            raise _error(
                "SEC_NPORT_ROW_INVALID",
                "SEC N-PORT filing row contains an invalid approved field",
            ) from None
        if (
            subtype in {"NPORT-P", "NPORT-P/A"}
            and report_date <= cutoff
            and filing_date <= cutoff
        ):
            parsed.append(
                _Filing(
                    accession=accession,
                    filing_date=filing_date,
                    report_date=report_date,
                    sub_type=subtype,
                    cik=cik,
                    submission=submission,
                    registrant=registrant,
                    fund=fund,
                )
            )

    selected_by_report: dict[tuple[str, str, date], _Filing] = {}
    for filing in parsed:
        key = (
            filing.cik,
            normalize_name(filing.fund.values["SERIES_ID"]).upper(),
            filing.report_date,
        )
        current = selected_by_report.get(key)
        if current is None or (
            filing.filing_date,
            filing.accession,
        ) > (current.filing_date, current.accession):
            selected_by_report[key] = filing

    latest_by_series: dict[tuple[str, str], _Filing] = {}
    for (cik, series_id, _), filing in selected_by_report.items():
        key = (cik, series_id)
        current = latest_by_series.get(key)
        if current is None or (
            filing.report_date,
            filing.filing_date,
            filing.accession,
        ) > (current.report_date, current.filing_date, current.accession):
            latest_by_series[key] = filing

    return tuple(latest_by_series.values()), frozenset(submission_accessions)


def _load_selected_holdings(
    files: Mapping[str, Path],
    *,
    submission_accessions: frozenset[str],
    selected_accessions: frozenset[str],
) -> tuple[
    dict[str, tuple[_TsvRow, ...]],
    dict[str, tuple[_TsvRow, ...]],
]:
    holding_keys: set[tuple[str, str]] = set()
    holding_ids: set[str] = set()
    selected_holdings: dict[str, list[_TsvRow]] = {}
    selected_holding_ids: set[str] = set()
    for holding in _iter_tsv(files, "FUND_REPORTED_HOLDING.tsv"):
        accession = holding.values["ACCESSION_NUMBER"]
        holding_id = holding.values["HOLDING_ID"]
        key = (accession, holding_id)
        if (
            not accession
            or not holding_id
            or accession not in submission_accessions
            or key in holding_keys
            or holding_id in holding_ids
        ):
            code = (
                "SEC_NPORT_REFERENTIAL_INTEGRITY"
                if accession not in submission_accessions
                else "SEC_NPORT_DUPLICATE_KEY"
            )
            raise _error(
                code,
                "SEC N-PORT snapshot contains an invalid holding key",
            ) from None
        holding_keys.add(key)
        holding_ids.add(holding_id)
        if accession in selected_accessions:
            selected_holdings.setdefault(accession, []).append(holding)
            selected_holding_ids.add(holding_id)

    identifier_keys: set[tuple[str, str]] = set()
    selected_identifiers: dict[str, list[_TsvRow]] = {}
    for identifier in _iter_tsv(files, "IDENTIFIERS.tsv"):
        holding_id = identifier.values["HOLDING_ID"]
        identifiers_id = identifier.values["IDENTIFIERS_ID"]
        key = (holding_id, identifiers_id)
        if not holding_id or not identifiers_id or key in identifier_keys:
            raise _error(
                "SEC_NPORT_DUPLICATE_KEY",
                "SEC N-PORT snapshot contains an invalid identifier key",
            ) from None
        if holding_id not in holding_ids:
            raise _error(
                "SEC_NPORT_REFERENTIAL_INTEGRITY",
                "SEC N-PORT snapshot contains an orphan structural key",
            ) from None
        identifier_keys.add(key)
        if holding_id in selected_holding_ids:
            selected_identifiers.setdefault(holding_id, []).append(identifier)
    return (
        {key: tuple(value) for key, value in selected_holdings.items()},
        {key: tuple(value) for key, value in selected_identifiers.items()},
    )


def _publisher_and_source_records(
    manifest: OfficialSnapshotManifest, manifest_hash: str
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    publisher_id = stable_id("institution", "OFFICIAL_PUBLISHER", "SEC")
    publisher = _with_hash(
        {
            "entity_id": publisher_id,
            "entity_type": "institution",
            "canonical_name": "U.S. Securities and Exchange Commission",
            "normalized_name": "U.S. Securities and Exchange Commission",
        }
    )
    institution = {
        "entity_id": publisher_id,
        "institution_kind": "regulator",
    }
    identifier = _with_hash(
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
    )
    source = _with_hash(
        {
            "source_id": stable_id(
                "source", manifest.source_code, manifest.snapshot_id
            ),
            "publisher": publisher_id,
            "publisher_type": "regulator",
            "source_title": "SEC Form N-PORT 2026 Q2 public data set",
            "source_type": "dataset",
            "authority_tier": "official",
            "source_locator_root": manifest.objects[0].object_key,
            "content_checksum": manifest_hash,
            "license_or_usage_note": "official SEC public data set",
            "eligible_for_claim": True,
        }
    )
    return publisher, institution, identifier, source


def _add_base_records(
    records: dict[str, list[Mapping[str, object]]],
    manifest: OfficialSnapshotManifest,
    manifest_hash: str,
) -> str:
    publisher, institution, identifier, source = _publisher_and_source_records(
        manifest, manifest_hash
    )
    records["catalog.entity"].append(publisher)
    records["catalog.institution"].append(institution)
    records["catalog.identifier"].append(identifier)
    records["evidence.source_record"].append(source)
    return str(source["source_id"])


def _add_manager(
    records: dict[str, list[Mapping[str, object]]],
    *,
    manifest: OfficialSnapshotManifest,
    source_id: str,
    product_id: str,
    filing: _Filing,
) -> None:
    name = normalize_name(filing.registrant.values["REGISTRANT_NAME"])
    manager_id = stable_id("institution", _SOURCE_CODE, f"CIK:{filing.cik}")
    records["catalog.entity"].append(
        _with_hash(
            {
                "entity_id": manager_id,
                "entity_type": "institution",
                "canonical_name": name or f"SEC registrant {filing.cik}",
                "normalized_name": name or f"SEC registrant {filing.cik}",
            }
        )
    )
    records["catalog.institution"].append(
        {"entity_id": manager_id, "institution_kind": "asset_manager"}
    )
    identifiers = [("SEC_CIK", filing.cik, True)]
    lei = normalize_name(filing.registrant.values["LEI"]).upper()
    if lei and _valid_lei(lei):
        identifiers.append(("LEI", lei, True))
    for scheme, value, primary in identifiers:
        records["catalog.identifier"].append(
            _with_hash(
                {
                    "identifier_id": stable_id(
                        "identifier", _SOURCE_CODE, f"{scheme}:{value}"
                    ),
                    "entity_id": manager_id,
                    "scheme": scheme,
                    "identifier_value": value,
                    "is_primary": primary,
                    "valid_from": None,
                    "valid_to": None,
                }
            )
        )

    relation_id = stable_id(
        "relation", _SOURCE_CODE, f"{product_id}:managedBy:{manager_id}"
    )
    records["relation.relation_record"].append(
        _with_hash(
            {
                "relation_id": relation_id,
                "subject_id": product_id,
                "predicate_id": "managedBy",
                "object_id": manager_id,
                "valid_from": filing.report_date,
                "valid_to": None,
            }
        )
    )
    evidence_id = stable_id(
        "evidence", _SOURCE_CODE, f"{filing.accession}:managedBy"
    )
    records["evidence.evidence_record"].append(
        _with_hash(
            {
                "evidence_id": evidence_id,
                "evidence_kind": "relation",
                "source_id": source_id,
                "subject_id": product_id,
                "predicate_id": "managedBy",
                "value_or_object_id": _tag(manager_id),
                "normalized_value": _tag(f"cik={filing.cik}"),
                "unit": None,
                "currency": None,
                "applicable_date": filing.report_date,
                "valid_from": None,
                "valid_to": None,
                "published_at": _filing_datetime(filing.filing_date),
                "available_at": _available_at(manifest, filing.filing_date),
                "vintage_date": manifest.vintage_date,
                "locator_type": "tabular",
                "locator_uri_or_object_key": (
                    f"{manifest.objects[0].object_key}#REGISTRANT.tsv"
                ),
                "locator_record_key": filing.accession,
                "locator_sheet": None,
                "locator_row": filing.registrant.row_number,
                "locator_column": "CIK",
                "locator_page": None,
                "locator_section": "REGISTRANT.tsv",
                "locator_sentence_start": None,
                "locator_sentence_end": None,
                "raw_value_repr": filing.registrant.values["CIK"],
                "parser_version": manifest.parser_version,
                "mapping_version": manifest.mapping_version,
                "cutoff_status": "eligible",
                "scope_completeness": None,
            }
        )
    )
    records["evidence.evidence_relation_origin"].append(
        {"evidence_id": evidence_id, "relation_id": relation_id}
    )


def _identifier_values(
    rows: tuple[_TsvRow, ...], field: str
) -> set[str]:
    return {
        normalize_name(row.values[field]).upper()
        for row in rows
        if normalize_name(row.values[field])
    }


def _security_resolution(
    manifest: OfficialSnapshotManifest,
    holding: _TsvRow,
    identifiers: tuple[_TsvRow, ...],
    isin_counts: Counter[str],
    cusip_counts: Counter[str],
) -> tuple[str, str | None, str | None, bool]:
    isins = {
        value
        for value in _identifier_values(identifiers, "IDENTIFIER_ISIN")
        if _valid_isin(value)
    }
    cusip = normalize_name(holding.values["ISSUER_CUSIP"]).upper()
    if len(isins) == 1:
        isin = next(iter(isins))
        if isin_counts[isin] == 1:
            return (
                stable_id("security", _SOURCE_CODE, f"ISIN:{isin}"),
                "ISIN",
                isin,
                True,
            )
    if cusip and _valid_cusip(cusip) and cusip_counts[cusip] == 1:
        return (
            stable_id("security", _SOURCE_CODE, f"CUSIP:{cusip}"),
            "CUSIP",
            cusip,
            True,
        )
    return (
        stable_id(
            "security",
            _SOURCE_CODE,
            f"{manifest.snapshot_id}:{holding.values['HOLDING_ID']}",
        ),
        None,
        None,
        False,
    )


def _add_security(
    records: dict[str, list[Mapping[str, object]]],
    *,
    holding: _TsvRow,
    identifier_rows: tuple[_TsvRow, ...],
    security_id: str,
    identifier_scheme: str | None,
    identifier_value: str | None,
) -> None:
    name = normalize_name(
        holding.values["ISSUER_TITLE"] or holding.values["ISSUER_NAME"]
    )
    tickers = sorted(_identifier_values(identifier_rows, "IDENTIFIER_TICKER"))
    ticker = tickers[0] if len(tickers) == 1 else None
    asset_category = normalize_name(holding.values["ASSET_CAT"]).upper()
    derivative = normalize_name(holding.values["DERIVATIVE_CAT"]).upper()
    kind = f"derivative:{derivative}" if derivative else f"asset:{asset_category or 'unknown'}"
    records["catalog.entity"].append(
        _with_hash(
            {
                "entity_id": security_id,
                "entity_type": "security",
                "canonical_name": name or f"N-PORT holding {holding.values['HOLDING_ID']}",
                "normalized_name": name or f"N-PORT holding {holding.values['HOLDING_ID']}",
            }
        )
    )
    records["catalog.security"].append(
        {
            "entity_id": security_id,
            "security_kind": kind,
            "ticker_display": ticker,
            "isin_display": identifier_value if identifier_scheme == "ISIN" else None,
        }
    )
    if identifier_scheme is not None and identifier_value is not None:
        records["catalog.identifier"].append(
            _with_hash(
                {
                    "identifier_id": stable_id(
                        "identifier",
                        _SOURCE_CODE,
                        f"{identifier_scheme}:{identifier_value}",
                    ),
                    "entity_id": security_id,
                    "scheme": identifier_scheme,
                    "identifier_value": identifier_value,
                    "is_primary": True,
                    "valid_from": None,
                    "valid_to": None,
                }
            )
        )
    if ticker:
        records["catalog.alias"].append(
            _with_hash(
                {
                    "alias_id": stable_id(
                        "alias", _SOURCE_CODE, f"{security_id}:TICKER:{ticker}"
                    ),
                    "entity_id": security_id,
                    "alias_text": ticker,
                    "normalized_alias_text": ticker,
                    "valid_from": None,
                    "valid_to": None,
                }
            )
        )


def _add_holding_relation(
    records: dict[str, list[Mapping[str, object]]],
    *,
    manifest: OfficialSnapshotManifest,
    source_id: str,
    product_id: str,
    security_id: str,
    filing: _Filing,
    holding: _TsvRow,
    identifier_rows: tuple[_TsvRow, ...],
    identifier_scheme: str | None,
    identifier_value: str | None,
) -> str:
    key = f"{filing.accession}:{holding.values['HOLDING_ID']}"
    relation_id = stable_id("relation", _SOURCE_CODE, f"{product_id}:{key}")
    records["relation.relation_record"].append(
        _with_hash(
            {
                "relation_id": relation_id,
                "subject_id": product_id,
                "predicate_id": "holdsSecurity",
                "object_id": security_id,
                "valid_from": filing.report_date,
                "valid_to": None,
            }
        )
    )
    evidence_id = stable_id("evidence", _SOURCE_CODE, f"{key}:holdsSecurity")
    series_id = normalize_name(filing.fund.values["SERIES_ID"]).upper()
    records["evidence.evidence_record"].append(
        _with_hash(
            {
                "evidence_id": evidence_id,
                "evidence_kind": "relation",
                "source_id": source_id,
                "subject_id": product_id,
                "predicate_id": "holdsSecurity",
                "value_or_object_id": _tag(security_id),
                "normalized_value": _tag(
                    ";".join(
                        (
                            f"accession={filing.accession}",
                            f"holding_id={holding.values['HOLDING_ID']}",
                            f"series_id={series_id}",
                            f"sub_type={filing.sub_type}",
                        )
                    )
                ),
                "unit": None,
                "currency": None,
                "applicable_date": filing.report_date,
                "valid_from": None,
                "valid_to": None,
                "published_at": _filing_datetime(filing.filing_date),
                "available_at": _available_at(manifest, filing.filing_date),
                "vintage_date": manifest.vintage_date,
                "locator_type": "tabular",
                "locator_uri_or_object_key": (
                    f"{manifest.objects[0].object_key}#FUND_REPORTED_HOLDING.tsv"
                ),
                "locator_record_key": key,
                "locator_sheet": None,
                "locator_row": holding.row_number,
                "locator_column": "HOLDING_ID",
                "locator_page": None,
                "locator_section": "FUND_REPORTED_HOLDING.tsv",
                "locator_sentence_start": None,
                "locator_sentence_end": None,
                "raw_value_repr": holding.values["HOLDING_ID"],
                "parser_version": manifest.parser_version,
                "mapping_version": manifest.mapping_version,
                "cutoff_status": "eligible",
                "scope_completeness": None,
            }
        )
    )
    records["evidence.evidence_relation_origin"].append(
        {"evidence_id": evidence_id, "relation_id": relation_id}
    )
    if identifier_scheme is not None and identifier_value is not None:
        matching = next(
            (
                row
                for row in identifier_rows
                if identifier_scheme == "ISIN"
                and normalize_name(row.values["IDENTIFIER_ISIN"]).upper()
                == identifier_value
            ),
            None,
        )
        locator_row = (
            matching.row_number if matching is not None else holding.row_number
        )
        locator_file = (
            "IDENTIFIERS.tsv"
            if matching is not None
            else "FUND_REPORTED_HOLDING.tsv"
        )
        locator_column = (
            "IDENTIFIER_ISIN" if matching is not None else "ISSUER_CUSIP"
        )
        identifier_evidence_id = stable_id(
            "evidence", _SOURCE_CODE, f"{key}:{identifier_scheme}"
        )
        records["evidence.evidence_record"].append(
            _with_hash(
                {
                    "evidence_id": identifier_evidence_id,
                    "evidence_kind": "relation",
                    "source_id": source_id,
                    "subject_id": product_id,
                    "predicate_id": "holdsSecurity",
                    "value_or_object_id": _tag(security_id),
                    "normalized_value": _tag(
                        f"{identifier_scheme}={identifier_value}"
                    ),
                    "unit": None,
                    "currency": None,
                    "applicable_date": filing.report_date,
                    "valid_from": None,
                    "valid_to": None,
                    "published_at": _filing_datetime(filing.filing_date),
                    "available_at": _available_at(manifest, filing.filing_date),
                    "vintage_date": manifest.vintage_date,
                    "locator_type": "tabular",
                    "locator_uri_or_object_key": (
                        f"{manifest.objects[0].object_key}#{locator_file}"
                    ),
                    "locator_record_key": key,
                    "locator_sheet": None,
                    "locator_row": locator_row,
                    "locator_column": locator_column,
                    "locator_page": None,
                    "locator_section": locator_file,
                    "locator_sentence_start": None,
                    "locator_sentence_end": None,
                    "raw_value_repr": identifier_value,
                    "parser_version": manifest.parser_version,
                    "mapping_version": manifest.mapping_version,
                    "cutoff_status": "eligible",
                    "scope_completeness": None,
                }
            )
        )
        records["evidence.evidence_relation_origin"].append(
            {
                "evidence_id": identifier_evidence_id,
                "relation_id": relation_id,
            }
        )
    return relation_id


def _add_metric_definition(
    records: dict[str, list[Mapping[str, object]]],
    column: str,
) -> None:
    metric_id, value_kind, default_unit = _METRICS[column]
    if any(
        row["metric_id"] == metric_id
        for row in records["observation.metric_definition"]
    ):
        return
    payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "1",
        "semantic_family": "official_holding",
        "value_kind": value_kind,
        "default_unit": default_unit,
        "description": json.dumps(
            {
                "source_code": _SOURCE_CODE,
                "source_field": column,
                "target": "holdsSecurity",
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        "approved_at": _APPROVED_AT,
    }
    payload["definition_hash"] = make_record_hash(payload)
    records["observation.metric_definition"].append(payload)


def _add_holding_observations(
    records: dict[str, list[Mapping[str, object]]],
    *,
    manifest: OfficialSnapshotManifest,
    source_id: str,
    product_id: str,
    relation_id: str,
    filing: _Filing,
    holding: _TsvRow,
) -> None:
    key = f"{filing.accession}:{holding.values['HOLDING_ID']}"
    currency = normalize_name(holding.values["CURRENCY_CODE"]).upper()
    for column, (metric_id, value_kind, default_unit) in _METRICS.items():
        _add_metric_definition(records, column)
        raw = holding.values[column]
        numeric_value: Decimal | None = None
        text_value: str | None = None
        status = "present"
        reason_code = None
        if value_kind == "numeric":
            numeric_value = _parse_decimal(raw)
            if numeric_value == 0:
                status = "zero"
        else:
            text_value = normalize_name(raw).upper()
            if not text_value:
                status = "unknown"
                reason_code = "SOURCE_VALUE_MISSING"
                text_value = None
        unit = default_unit
        if column == "BALANCE":
            unit = normalize_name(holding.values["UNIT"]) or None
        observation_id = stable_id(
            "observation", _SOURCE_CODE, f"{key}:{column}"
        )
        observation = _with_hash(
            {
                "observation_id": observation_id,
                "entity_id": None,
                "relation_id": relation_id,
                "metric_id": metric_id,
                "metric_definition_version": "1",
                "value_status": status,
                "numeric_value": numeric_value,
                "text_value": text_value,
                "boolean_value": None,
                "date_value": None,
                "timestamp_value": None,
                "unit": unit,
                "currency": currency if column in {"CURRENCY_CODE", "CURRENCY_VALUE"} else None,
                "period_start": None,
                "period_end": None,
                "applicable_date": filing.report_date,
                "published_at": _filing_datetime(filing.filing_date),
                "available_at": _available_at(manifest, filing.filing_date),
                "vintage_date": manifest.vintage_date,
                "reason_code": reason_code,
            }
        )
        records["observation.observation_record"].append(observation)
        evidence_id = stable_id("evidence", _SOURCE_CODE, f"{key}:{column}")
        normalized = numeric_value if numeric_value is not None else text_value
        records["evidence.evidence_record"].append(
            _with_hash(
                {
                    "evidence_id": evidence_id,
                    "evidence_kind": "observation",
                    "source_id": source_id,
                    "subject_id": product_id,
                    "predicate_id": metric_id,
                    "value_or_object_id": _tag(raw),
                    "normalized_value": _tag(normalized),
                    "unit": unit,
                    "currency": currency if column in {"CURRENCY_CODE", "CURRENCY_VALUE"} else None,
                    "applicable_date": filing.report_date,
                    "valid_from": None,
                    "valid_to": None,
                    "published_at": _filing_datetime(filing.filing_date),
                    "available_at": _available_at(manifest, filing.filing_date),
                    "vintage_date": manifest.vintage_date,
                    "locator_type": "tabular",
                    "locator_uri_or_object_key": (
                        f"{manifest.objects[0].object_key}#FUND_REPORTED_HOLDING.tsv"
                    ),
                    "locator_record_key": key,
                    "locator_sheet": None,
                    "locator_row": holding.row_number,
                    "locator_column": column,
                    "locator_page": None,
                    "locator_section": "FUND_REPORTED_HOLDING.tsv",
                    "locator_sentence_start": None,
                    "locator_sentence_end": None,
                    "raw_value_repr": raw,
                    "parser_version": manifest.parser_version,
                    "mapping_version": manifest.mapping_version,
                    "cutoff_status": "eligible",
                    "scope_completeness": None,
                }
            )
        )
        records["evidence.evidence_observation_origin"].append(
            {"evidence_id": evidence_id, "observation_id": observation_id}
        )


def _add_query_scope(
    records: dict[str, list[Mapping[str, object]]],
    *,
    manifest: OfficialSnapshotManifest,
    source_id: str,
    product_id: str,
    row_number: int,
    status: str,
    filing: _Filing | None,
) -> None:
    key = filing.accession if filing is not None else f"binding:{row_number}"
    records["evidence.evidence_record"].append(
        _with_hash(
            {
                "evidence_id": stable_id(
                    "evidence", _SOURCE_CODE, f"{product_id}:{key}:coverage"
                ),
                "evidence_kind": "query_scope",
                "source_id": source_id,
                "subject_id": product_id,
                "predicate_id": "holdsSecurityCoverage",
                "value_or_object_id": _tag(status),
                "normalized_value": _tag(status),
                "unit": None,
                "currency": None,
                "applicable_date": filing.report_date if filing else None,
                "valid_from": None,
                "valid_to": None,
                "published_at": (
                    _filing_datetime(filing.filing_date) if filing else manifest.published_at
                ),
                "available_at": (
                    _available_at(manifest, filing.filing_date)
                    if filing
                    else manifest.available_at
                ),
                "vintage_date": manifest.vintage_date,
                "locator_type": "tabular",
                "locator_uri_or_object_key": (
                    f"{manifest.objects[0].object_key}#SUBMISSION.tsv"
                ),
                "locator_record_key": key,
                "locator_sheet": None,
                "locator_row": filing.submission.row_number if filing else row_number,
                "locator_column": "ACCESSION_NUMBER" if filing else None,
                "locator_page": None,
                "locator_section": "SUBMISSION.tsv",
                "locator_sentence_start": None,
                "locator_sentence_end": None,
                "raw_value_repr": status,
                "parser_version": manifest.parser_version,
                "mapping_version": manifest.mapping_version,
                "cutoff_status": "eligible",
                "scope_completeness": (
                    "closed_world" if status == "COVERED" else "bounded_unknown"
                ),
            }
        )
    )


def iter_eligible_nport_funds(
    files: Mapping[str, Path],
    cutoff: date,
    *,
    manifest: OfficialSnapshotManifest,
    series_class_index: OfficialIdentityIndex,
    product_bindings: Iterable[NportProductBinding],
) -> Iterator[MappedRow]:
    manifest_hash = _validate_manifest(manifest, cutoff)
    filings, submission_accessions = _load_filings(files, cutoff)
    filing_by_series = {
        (
            filing.cik,
            stable_id(
                "product",
                _SERIES_SOURCE_CODE,
                normalize_name(filing.fund.values["SERIES_ID"]).upper(),
            ),
        ): filing
        for filing in filings
    }

    binding_selections: list[
        tuple[int, NportProductBinding, IdentityResolution, _Filing | None]
    ] = []
    for binding_number, binding in enumerate(tuple(product_bindings), start=1):
        resolution = series_class_index.resolve_compound_product(
            "SEC_CIK_CLASS_TICKER", (binding.cik, binding.class_ticker)
        )
        try:
            binding_cik = _normalize_cik(binding.cik)
        except ValueError:
            binding_cik = ""
        filing = (
            filing_by_series.get((binding_cik, resolution.entity_id))
            if resolution.status == "exact" and resolution.entity_id is not None
            else None
        )
        binding_selections.append(
            (binding_number, binding, resolution, filing)
        )
    selected_accessions = frozenset(
        filing.accession
        for _, _, _, filing in binding_selections
        if filing is not None
    )
    holdings_by_accession, identifiers_by_holding = _load_selected_holdings(
        files,
        submission_accessions=submission_accessions,
        selected_accessions=selected_accessions,
    )

    selected_holdings = tuple(
        holding
        for holdings in holdings_by_accession.values()
        for holding in holdings
    )
    isin_counts: Counter[str] = Counter()
    cusip_counts: Counter[str] = Counter()
    for holding in selected_holdings:
        identifier_rows = identifiers_by_holding.get(
            holding.values["HOLDING_ID"], ()
        )
        for value in _identifier_values(identifier_rows, "IDENTIFIER_ISIN"):
            if _valid_isin(value):
                isin_counts[value] += 1
        cusip = normalize_name(holding.values["ISSUER_CUSIP"]).upper()
        if cusip and _valid_cusip(cusip):
            cusip_counts[cusip] += 1

    for binding_number, binding, resolution, filing in binding_selections:
        records = _empty_records()
        source_id = _add_base_records(records, manifest, manifest_hash)
        issues: list[MappingIssue] = []
        if filing is None:
            issues.append(
                MappingIssue(
                    source_code=_SOURCE_CODE,
                    row_number=binding_number,
                    column=None,
                    code=resolution.issue_code or "SEC_NPORT_NO_ELIGIBLE_FILING",
                    severity="limited",
                )
            )
            _add_query_scope(
                records,
                manifest=manifest,
                source_id=source_id,
                product_id=binding.product_entity_id,
                row_number=binding_number,
                status="NOT_COVERED",
                filing=None,
            )
            yield MappedRow(
                row_number=binding_number,
                disposition="limited",
                records_by_table={
                    table: tuple(values) for table, values in records.items()
                },
                issues=tuple(issues),
            )
            continue

        _add_manager(
            records,
            manifest=manifest,
            source_id=source_id,
            product_id=binding.product_entity_id,
            filing=filing,
        )
        product_holdings = holdings_by_accession.get(filing.accession, ())
        all_strong = True
        all_valid = True
        for holding in product_holdings:
            identifier_rows = identifiers_by_holding.get(
                holding.values["HOLDING_ID"], ()
            )
            try:
                for numeric_column in ("BALANCE", "CURRENCY_VALUE", "PERCENTAGE"):
                    _parse_decimal(holding.values[numeric_column])
                currency = normalize_name(holding.values["CURRENCY_CODE"]).upper()
                if re.fullmatch(r"[A-Z]{3}", currency) is None:
                    raise ValueError
            except ValueError:
                all_valid = False
                issues.append(
                    MappingIssue(
                        source_code=_SOURCE_CODE,
                        row_number=holding.row_number,
                        column="PERCENTAGE",
                        code="SEC_NPORT_HOLDING_VALUE_INVALID",
                        severity="limited",
                    )
                )
                continue
            security_id, scheme, value, strong = _security_resolution(
                manifest,
                holding,
                identifier_rows,
                isin_counts,
                cusip_counts,
            )
            all_strong = all_strong and strong
            _add_security(
                records,
                holding=holding,
                identifier_rows=identifier_rows,
                security_id=security_id,
                identifier_scheme=scheme,
                identifier_value=value,
            )
            relation_id = _add_holding_relation(
                records,
                manifest=manifest,
                source_id=source_id,
                product_id=binding.product_entity_id,
                security_id=security_id,
                filing=filing,
                holding=holding,
                identifier_rows=identifier_rows,
                identifier_scheme=scheme,
                identifier_value=value,
            )
            _add_holding_observations(
                records,
                manifest=manifest,
                source_id=source_id,
                product_id=binding.product_entity_id,
                relation_id=relation_id,
                filing=filing,
                holding=holding,
            )

        status = (
            "COVERED"
            if all_valid and all_strong
            else "PARTIALLY_COVERED"
        )
        _add_query_scope(
            records,
            manifest=manifest,
            source_id=source_id,
            product_id=binding.product_entity_id,
            row_number=binding_number,
            status=status,
            filing=filing,
        )
        yield MappedRow(
            row_number=binding_number,
            disposition="accepted" if status == "COVERED" else "limited",
            records_by_table={
                table: tuple(values) for table, values in records.items()
            },
            issues=tuple(issues),
        )
