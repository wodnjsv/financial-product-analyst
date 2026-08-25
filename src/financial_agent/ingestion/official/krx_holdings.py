from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from financial_agent.contracts import encode_contract_value
from financial_agent.ingestion.identity import AuthoritativeIdentityIndex
from financial_agent.ingestion.mapping.common import (
    make_record_hash,
    normalize_name,
    stable_id,
)
from financial_agent.ingestion.models import MappedRow, MappingIssue
from financial_agent.ingestion.sources import SourceVerificationError

from .identity import IdentityCandidate, OfficialIdentityIndex
from .models import OfficialSnapshotManifest
from .snapshot import validate_official_snapshot


_SOURCE_CODE = "KRX_ETF_PDF"
_HEADERS = (
    "종목코드",
    "구성종목명",
    "주식수(계약수)",
    "평가금액",
    "시가총액",
    "시가총액 구성비중",
)
_SUMMARY_CODE = "CASH00000001"
_CUTOFF_DATE = date(2026, 8, 24)
_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_SHORT_CODE_PATTERN = re.compile(r"[A-Z0-9]{6}")
_APPROVED_AT = datetime(2026, 8, 22, tzinfo=UTC)
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
_METRICS: dict[str, tuple[str, str | None, str | None]] = {
    "주식수(계약수)": (
        "krx_etf_holding_quantity",
        "share_or_contract",
        None,
    ),
    "평가금액": ("krx_etf_holding_valuation_krw", "KRW", "KRW"),
    "시가총액": ("krx_etf_holding_market_cap_krw", "KRW", "KRW"),
    "시가총액 구성비중": (
        "krx_etf_holding_weight_pct",
        "percentage_point",
        None,
    ),
}
_SUMMARY_METRIC = "krx_etf_creation_cash_amount_krw"


@dataclass(frozen=True, slots=True)
class KrxEtfProductBinding:
    product_entity_id: str
    organizer_isin: str
    krx_short_code: str
    organizer_name: str
    krx_name: str
    name_matches: bool


@dataclass(frozen=True, slots=True)
class KrxEtfBindingResult:
    bindings: tuple[KrxEtfProductBinding, ...]
    organizer_etf_count: int
    invalid_isin_count: int
    unresolved_organizer_count: int
    unmatched_krx_count: int
    name_drift_count: int


def _error(code: str, message: str) -> SourceVerificationError:
    return SourceVerificationError(code, message)


def _with_hash(payload: Mapping[str, object]) -> dict[str, object]:
    record = dict(payload)
    record["record_hash"] = make_record_hash(payload)
    return record


def _tag(value: object) -> dict[str, object]:
    return encode_contract_value(value).model_dump(mode="json")


def _empty_records() -> dict[str, list[Mapping[str, object]]]:
    return {table: [] for table in _TABLES}


def _valid_isin(value: str) -> bool:
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value) is None:
        return False
    expanded = "".join(str(int(character, 36)) for character in value)
    total = 0
    for index, character in enumerate(reversed(expanded)):
        number = int(character) * (2 if index % 2 else 1)
        total += number // 10 + number % 10
    return total % 10 == 0


def parse_krx_etf_pdf_csv(payload: bytes) -> tuple[Mapping[str, str], ...]:
    try:
        text = payload.decode("cp949")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if tuple(reader.fieldnames or ()) != _HEADERS:
            raise ValueError
        rows: list[Mapping[str, str]] = []
        for raw in reader:
            if None in raw or set(raw) != set(_HEADERS):
                raise ValueError
            row = {header: raw[header] for header in _HEADERS}
            if not all(isinstance(value, str) for value in row.values()):
                raise ValueError
            if not normalize_name(row["종목코드"]) or not normalize_name(
                row["구성종목명"]
            ):
                raise ValueError
            rows.append(row)
        return tuple(rows)
    except (UnicodeDecodeError, csv.Error, ValueError):
        raise _error(
            "KRX_ETF_PDF_SCHEMA_MISMATCH",
            "KRX ETF PDF CSV differs from the approved schema",
        ) from None


def build_krx_etf_product_bindings(
    *,
    organizer_rows: Iterable[Mapping[str, object]],
    daily_rows: Iterable[Mapping[str, object]],
    applicable_date: date,
    identity_index: AuthoritativeIdentityIndex,
) -> KrxEtfBindingResult:
    if applicable_date > _CUTOFF_DATE:
        raise _error(
            "KRX_ETF_BINDING_DATE_MISMATCH",
            "KRX ETF binding input exceeds the approved cutoff",
        ) from None
    organizers = tuple(
        row
        for row in organizer_rows
        if normalize_name(str(row.get("pd_grp_no", ""))) == "ETF"
    )
    valid_organizers: list[tuple[str, str, str]] = []
    invalid_count = 0
    for row in organizers:
        isin = normalize_name(str(row.get("pd_itm_no", ""))).upper()
        name = normalize_name(str(row.get("pd_abrv_nm", "")))
        if not _valid_isin(isin):
            invalid_count += 1
            continue
        valid_organizers.append((isin[3:9], isin, name))

    organizer_counts = Counter(code for code, _, _ in valid_organizers)
    if any(count != 1 for count in organizer_counts.values()):
        raise _error(
            "KRX_ETF_BINDING_CONFLICT",
            "organizer ETFs contain a duplicate KRX identity axis",
        ) from None

    historical: list[tuple[str, str]] = []
    for row in daily_rows:
        code = normalize_name(str(row.get("종목코드", ""))).upper()
        name = normalize_name(str(row.get("종목명", "")))
        if _SHORT_CODE_PATTERN.fullmatch(code) is None or not name:
            raise _error(
                "KRX_ETF_BINDING_SCHEMA_MISMATCH",
                "historical KRX ETF identity row is invalid",
            ) from None
        historical.append((code, name))
    historical_counts = Counter(code for code, _ in historical)
    if any(count != 1 for count in historical_counts.values()):
        raise _error(
            "KRX_ETF_BINDING_CONFLICT",
            "historical KRX ETFs contain a duplicate identity axis",
        ) from None

    historical_by_code = dict(historical)
    bindings: list[KrxEtfProductBinding] = []
    for short_code, isin, organizer_name in valid_organizers:
        krx_name = historical_by_code.get(short_code)
        if krx_name is None:
            continue
        resolution = identity_index.resolve("ISIN", isin)
        if (
            resolution.status != "MATCHED"
            or resolution.canonical_identity is None
        ):
            continue
        bindings.append(
            KrxEtfProductBinding(
                product_entity_id=resolution.canonical_identity.entity_id,
                organizer_isin=isin,
                krx_short_code=short_code,
                organizer_name=organizer_name,
                krx_name=krx_name,
                name_matches=normalize_name(organizer_name)
                == normalize_name(krx_name),
            )
        )
    bindings.sort(key=lambda item: item.krx_short_code)
    bound_codes = {binding.krx_short_code for binding in bindings}
    return KrxEtfBindingResult(
        bindings=tuple(bindings),
        organizer_etf_count=len(organizers),
        invalid_isin_count=invalid_count,
        unresolved_organizer_count=len(organizers) - len(bindings),
        unmatched_krx_count=len(historical_by_code.keys() - bound_codes),
        name_drift_count=sum(not binding.name_matches for binding in bindings),
    )


def _parse_decimal(raw: str) -> Decimal | None:
    normalized = normalize_name(raw).replace(",", "")
    if normalized in {"", "-"}:
        return None
    if _DECIMAL_PATTERN.fullmatch(normalized) is None:
        raise _error(
            "KRX_ETF_PDF_VALUE_INVALID",
            "KRX ETF PDF contains an invalid decimal value",
        ) from None
    try:
        value = Decimal(normalized)
    except InvalidOperation:
        raise _error(
            "KRX_ETF_PDF_VALUE_INVALID",
            "KRX ETF PDF contains an invalid decimal value",
        ) from None
    if not value.is_finite():
        raise _error(
            "KRX_ETF_PDF_VALUE_INVALID",
            "KRX ETF PDF contains an invalid decimal value",
        ) from None
    return value


def _publisher_and_source(
    manifest: OfficialSnapshotManifest, manifest_hash: str
) -> tuple[str, str, tuple[dict[str, object], ...]]:
    publisher_id = stable_id("institution", "OFFICIAL_PUBLISHER", "KRX")
    source_id = stable_id("source", manifest.source_code, manifest.snapshot_id)
    publisher = _with_hash(
        {
            "entity_id": publisher_id,
            "entity_type": "institution",
            "canonical_name": "Korea Exchange",
            "normalized_name": "Korea Exchange",
        }
    )
    identifier = _with_hash(
        {
            "identifier_id": stable_id("identifier", "OFFICIAL_PUBLISHER", "KRX"),
            "entity_id": publisher_id,
            "scheme": "OFFICIAL_PUBLISHER_CODE",
            "identifier_value": "KRX",
            "is_primary": True,
            "valid_from": None,
            "valid_to": None,
        }
    )
    source = _with_hash(
        {
            "source_id": source_id,
            "publisher": publisher_id,
            "publisher_type": "exchange",
            "source_title": "KRX ETF Portfolio Deposit File",
            "source_type": "dataset",
            "authority_tier": "official",
            "source_locator_root": manifest.objects[0].object_key,
            "content_checksum": manifest_hash,
            "license_or_usage_note": "official KRX setting/redemption basket",
            "eligible_for_claim": True,
        }
    )
    return publisher_id, source_id, (publisher, identifier, source)


def _add_metric_definition(
    records: dict[str, list[Mapping[str, object]]],
    *,
    metric_id: str,
    source_field: str,
    unit: str | None,
) -> None:
    if any(
        record["metric_id"] == metric_id
        for record in records["observation.metric_definition"]
    ):
        return
    payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "1",
        "semantic_family": "official_krx_etf_pdf",
        "value_kind": "numeric",
        "default_unit": unit,
        "description": json.dumps(
            {
                "coverage": "bounded_unknown",
                "source_field": source_field,
                "source_semantics": "setting_redemption_basket",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "approved_at": _APPROVED_AT,
    }
    payload["definition_hash"] = make_record_hash(payload)
    records["observation.metric_definition"].append(payload)


def _add_observation(
    records: dict[str, list[Mapping[str, object]]],
    *,
    manifest: OfficialSnapshotManifest,
    source_id: str,
    product_id: str,
    relation_id: str | None,
    row_number: int,
    record_key: str,
    column: str,
    metric_id: str,
    raw: str,
    unit: str | None,
    currency: str | None,
) -> None:
    value = _parse_decimal(raw)
    status = "unknown" if value is None else "zero" if value == 0 else "present"
    reason = "SOURCE_VALUE_MISSING" if value is None else None
    observation_id = stable_id(
        "observation", _SOURCE_CODE, f"{record_key}:{column}"
    )
    observation = _with_hash(
        {
            "observation_id": observation_id,
            "entity_id": product_id if relation_id is None else None,
            "relation_id": relation_id,
            "metric_id": metric_id,
            "metric_definition_version": "1",
            "value_status": status,
            "numeric_value": value,
            "text_value": None,
            "boolean_value": None,
            "date_value": None,
            "timestamp_value": None,
            "unit": unit,
            "currency": currency,
            "period_start": None,
            "period_end": None,
            "applicable_date": manifest.applicable_date,
            "published_at": manifest.published_at,
            "available_at": manifest.available_at,
            "vintage_date": manifest.vintage_date,
            "reason_code": reason,
        }
    )
    records["observation.observation_record"].append(observation)
    evidence_id = stable_id("evidence", _SOURCE_CODE, f"{record_key}:{column}")
    records["evidence.evidence_record"].append(
        _with_hash(
            {
                "evidence_id": evidence_id,
                "evidence_kind": "observation",
                "source_id": source_id,
                "subject_id": product_id,
                "predicate_id": metric_id,
                "value_or_object_id": _tag(raw),
                "normalized_value": _tag(value),
                "unit": unit,
                "currency": currency,
                "applicable_date": manifest.applicable_date,
                "valid_from": None,
                "valid_to": None,
                "published_at": manifest.published_at,
                "available_at": manifest.available_at,
                "vintage_date": manifest.vintage_date,
                "locator_type": "tabular",
                "locator_uri_or_object_key": manifest.objects[0].object_key,
                "locator_record_key": record_key,
                "locator_sheet": None,
                "locator_row": row_number,
                "locator_column": column,
                "locator_page": None,
                "locator_section": None,
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


def _add_security(
    records: dict[str, list[Mapping[str, object]]],
    *,
    code: str,
    name: str,
    security_index: OfficialIdentityIndex,
) -> tuple[str, bool]:
    resolution = security_index.resolve_product(
        (IdentityCandidate("KRX_SHORT_ISSUE_CODE", code.upper()),)
    )
    if resolution.status == "conflict":
        raise _error(
            "KRX_ETF_HOLDING_IDENTITY_CONFLICT",
            "KRX ETF holding identity resolves to multiple securities",
        ) from None
    if resolution.status == "exact" and resolution.entity_id is not None:
        return resolution.entity_id, True

    security_id = stable_id(
        "security", _SOURCE_CODE, f"SOURCE_LOCAL:{code}:{normalize_name(name)}"
    )
    normalized_name = normalize_name(name)
    records["catalog.entity"].append(
        _with_hash(
            {
                "entity_id": security_id,
                "entity_type": "security",
                "canonical_name": normalized_name,
                "normalized_name": normalized_name,
            }
        )
    )
    kind = (
        "cash_equivalent"
        if code in {"KRD010010001", "USDZZ0000001"}
        else "derivative"
        if len(code) < 6 or not code.isdigit()
        else "source_local"
    )
    records["catalog.security"].append(
        {
            "entity_id": security_id,
            "security_kind": kind,
            "ticker_display": code,
            "isin_display": None,
        }
    )
    return security_id, False


def _add_holding_relation(
    records: dict[str, list[Mapping[str, object]]],
    *,
    manifest: OfficialSnapshotManifest,
    source_id: str,
    product_id: str,
    security_id: str,
    code: str,
    name: str,
    row_number: int,
) -> str:
    record_key = f"{product_id}:{manifest.applicable_date}:{row_number}:{code}"
    relation_id = stable_id("relation", _SOURCE_CODE, record_key)
    records["relation.relation_record"].append(
        _with_hash(
            {
                "relation_id": relation_id,
                "subject_id": product_id,
                "predicate_id": "holdsSecurity",
                "object_id": security_id,
                "valid_from": manifest.applicable_date,
                "valid_to": manifest.applicable_date,
            }
        )
    )
    evidence_id = stable_id("evidence", _SOURCE_CODE, f"{record_key}:relation")
    records["evidence.evidence_record"].append(
        _with_hash(
            {
                "evidence_id": evidence_id,
                "evidence_kind": "relation",
                "source_id": source_id,
                "subject_id": product_id,
                "predicate_id": "holdsSecurity",
                "value_or_object_id": _tag(security_id),
                "normalized_value": _tag(f"code={code};name={normalize_name(name)}"),
                "unit": None,
                "currency": None,
                "applicable_date": manifest.applicable_date,
                "valid_from": manifest.applicable_date,
                "valid_to": manifest.applicable_date,
                "published_at": manifest.published_at,
                "available_at": manifest.available_at,
                "vintage_date": manifest.vintage_date,
                "locator_type": "tabular",
                "locator_uri_or_object_key": manifest.objects[0].object_key,
                "locator_record_key": record_key,
                "locator_sheet": None,
                "locator_row": row_number,
                "locator_column": "종목코드",
                "locator_page": None,
                "locator_section": None,
                "locator_sentence_start": None,
                "locator_sentence_end": None,
                "raw_value_repr": code,
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
    return relation_id


def _add_scope(
    records: dict[str, list[Mapping[str, object]]],
    *,
    manifest: OfficialSnapshotManifest,
    source_id: str,
    product_id: str,
    status: str,
) -> None:
    records["evidence.evidence_record"].append(
        _with_hash(
            {
                "evidence_id": stable_id(
                    "evidence",
                    _SOURCE_CODE,
                    f"{product_id}:{manifest.applicable_date}:coverage",
                ),
                "evidence_kind": "query_scope",
                "source_id": source_id,
                "subject_id": product_id,
                "predicate_id": "holdsSecurityCoverage",
                "value_or_object_id": _tag(status),
                "normalized_value": _tag(status),
                "unit": None,
                "currency": None,
                "applicable_date": manifest.applicable_date,
                "valid_from": None,
                "valid_to": None,
                "published_at": manifest.published_at,
                "available_at": manifest.available_at,
                "vintage_date": manifest.vintage_date,
                "locator_type": "tabular",
                "locator_uri_or_object_key": manifest.objects[0].object_key,
                "locator_record_key": f"{product_id}:{manifest.applicable_date}",
                "locator_sheet": None,
                "locator_row": 1,
                "locator_column": None,
                "locator_page": None,
                "locator_section": None,
                "locator_sentence_start": None,
                "locator_sentence_end": None,
                "raw_value_repr": status,
                "parser_version": manifest.parser_version,
                "mapping_version": manifest.mapping_version,
                "cutoff_status": "eligible",
                "scope_completeness": "bounded_unknown",
            }
        )
    )


def map_krx_holding_snapshot(
    manifest: OfficialSnapshotManifest,
    rows: Iterable[Mapping[str, str]],
    *,
    binding: KrxEtfProductBinding,
    security_index: OfficialIdentityIndex,
) -> MappedRow:
    if (
        manifest.source_code != _SOURCE_CODE
        or manifest.publisher_code != "KRX"
        or manifest.applicable_date is None
        or len(manifest.objects) != 1
    ):
        raise _error(
            "KRX_ETF_PDF_OBJECT_MISMATCH",
            "KRX ETF PDF manifest differs from the approved object contract",
        ) from None
    manifest_hash = validate_official_snapshot(manifest)
    expected_name = (
        f"{binding.krx_short_code}_{manifest.applicable_date:%Y%m%d}.csv"
    )
    if manifest.objects[0].object_name != expected_name:
        raise _error(
            "KRX_ETF_PDF_OBJECT_MISMATCH",
            "KRX ETF PDF object does not match the bound ETF and date",
        ) from None
    records = _empty_records()
    publisher_id, source_id, base_records = _publisher_and_source(
        manifest, manifest_hash
    )
    records["catalog.entity"].append(base_records[0])
    records["catalog.institution"].append(
        {"entity_id": publisher_id, "institution_kind": "exchange"}
    )
    records["catalog.identifier"].append(base_records[1])
    records["evidence.source_record"].append(base_records[2])

    row_values = tuple(rows)
    issues: list[MappingIssue] = []
    holding_count = 0
    for row_number, row in enumerate(row_values, start=2):
        if tuple(row.keys()) != _HEADERS:
            raise _error(
                "KRX_ETF_PDF_SCHEMA_MISMATCH",
                "KRX ETF PDF row differs from the approved schema",
            ) from None
        code = normalize_name(row["종목코드"]).upper()
        name = normalize_name(row["구성종목명"])
        if code == _SUMMARY_CODE:
            metric_id = _SUMMARY_METRIC
            _add_metric_definition(
                records,
                metric_id=metric_id,
                source_field="시가총액",
                unit="KRW",
            )
            _add_observation(
                records,
                manifest=manifest,
                source_id=source_id,
                product_id=binding.product_entity_id,
                relation_id=None,
                row_number=row_number,
                record_key=(
                    f"{binding.product_entity_id}:"
                    f"{manifest.applicable_date}:summary"
                ),
                column="시가총액",
                metric_id=metric_id,
                raw=row["시가총액"],
                unit="KRW",
                currency="KRW",
            )
            continue

        security_id, strong_identity = _add_security(
            records,
            code=code,
            name=name,
            security_index=security_index,
        )
        if not strong_identity:
            issues.append(
                MappingIssue(
                    source_code=_SOURCE_CODE,
                    row_number=row_number,
                    column="종목코드",
                    code="KRX_ETF_HOLDING_SOURCE_LOCAL_IDENTITY",
                    severity="limited",
                )
            )
        relation_id = _add_holding_relation(
            records,
            manifest=manifest,
            source_id=source_id,
            product_id=binding.product_entity_id,
            security_id=security_id,
            code=code,
            name=name,
            row_number=row_number,
        )
        record_key = ":".join(
            (
                binding.product_entity_id,
                str(manifest.applicable_date),
                str(row_number),
                code,
            )
        )
        for column, (metric_id, unit, currency) in _METRICS.items():
            _add_metric_definition(
                records, metric_id=metric_id, source_field=column, unit=unit
            )
            _add_observation(
                records,
                manifest=manifest,
                source_id=source_id,
                product_id=binding.product_entity_id,
                relation_id=relation_id,
                row_number=row_number,
                record_key=record_key,
                column=column,
                metric_id=metric_id,
                raw=row[column],
                unit=unit,
                currency=currency,
            )
        holding_count += 1

    status = "PARTIALLY_COVERED" if holding_count else "NOT_COVERED"
    _add_scope(
        records,
        manifest=manifest,
        source_id=source_id,
        product_id=binding.product_entity_id,
        status=status,
    )
    return MappedRow(
        row_number=1,
        disposition="limited",
        records_by_table={
            table: tuple(values) for table, values in records.items()
        },
        issues=tuple(issues),
    )
