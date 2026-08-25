from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from financial_agent.contracts import encode_contract_value
from financial_agent.ingestion.mapping.common import make_record_hash, stable_id
from financial_agent.ingestion.models import MappedRow, MappingIssue
from financial_agent.ingestion.sources import SourceVerificationError

from .krx_holdings import KrxEtfProductBinding
from .models import OfficialSnapshotManifest
from .snapshot import validate_official_snapshot


_SOURCE_CODE = "KRX_ETF_DAILY"
_FIELDS = ("BAS_DD", "ISU_CD", "ISU_NM", "TDD_CLSPRC", "NAV")
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
_METRICS = {
    "TDD_CLSPRC": "krx_etf_market_close_krw",
    "NAV": "krx_etf_nav_per_share_krw",
}
_DECIMAL_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_SHORT_CODE_PATTERN = re.compile(r"[A-Z0-9]{6}")
_APPROVED_AT = datetime(2026, 8, 22, tzinfo=UTC)


def _error(code: str, message: str) -> SourceVerificationError:
    return SourceVerificationError(code, message)


def _with_hash(payload: Mapping[str, object]) -> dict[str, object]:
    record = dict(payload)
    record["record_hash"] = make_record_hash(payload)
    return record


def _empty_records() -> dict[str, list[Mapping[str, object]]]:
    return {table: [] for table in _TABLES}


def _tag(value: object) -> dict[str, object]:
    return encode_contract_value(value).model_dump(mode="json")


def _parse_date(value: str) -> date:
    if re.fullmatch(r"[0-9]{8}", value) is None:
        raise ValueError
    return datetime.strptime(value, "%Y%m%d").date()


def _parse_decimal(value: str, *, allow_missing: bool) -> Decimal | None:
    if allow_missing and value == "":
        return None
    if _DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError from None
    if not parsed.is_finite() or parsed < 0:
        raise ValueError
    return parsed


def parse_krx_etf_daily(
    payload: bytes,
) -> tuple[Mapping[str, object], ...]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise TypeError
        raw_rows = decoded["OutBlock_1"]
        if not isinstance(raw_rows, list) or not raw_rows:
            raise TypeError
    except Exception:
        raise _error(
            "KRX_ETF_DAILY_SCHEMA_MISMATCH",
            "KRX ETF daily response differs from the approved schema",
        ) from None

    rows: list[Mapping[str, object]] = []
    observed_keys: set[tuple[str, str]] = set()
    for raw_row in raw_rows:
        try:
            if not isinstance(raw_row, dict):
                raise TypeError
            row = {field: raw_row[field] for field in _FIELDS}
            if not all(isinstance(value, str) for value in row.values()):
                raise TypeError
            if (
                _SHORT_CODE_PATTERN.fullmatch(str(row["ISU_CD"])) is None
                or not str(row["ISU_NM"]).strip()
            ):
                raise TypeError
            _parse_date(str(row["BAS_DD"]))
        except (KeyError, TypeError, ValueError):
            raise _error(
                "KRX_ETF_DAILY_SCHEMA_MISMATCH",
                "KRX ETF daily response differs from the approved schema",
            ) from None

        try:
            _parse_decimal(str(row["TDD_CLSPRC"]), allow_missing=False)
            _parse_decimal(str(row["NAV"]), allow_missing=True)
        except ValueError:
            raise _error(
                "KRX_ETF_DAILY_VALUE_INVALID",
                "KRX ETF daily response contains an invalid decimal value",
            ) from None

        natural_key = (str(row["ISU_CD"]), str(row["BAS_DD"]))
        if natural_key in observed_keys:
            raise _error(
                "KRX_ETF_DAILY_DUPLICATE_OBSERVATION",
                "KRX ETF daily response contains a duplicate product date",
            ) from None
        observed_keys.add(natural_key)
        rows.append(row)
    return tuple(rows)


def select_latest_eligible_krx_date(
    available_dates: Iterable[date], cutoff: date
) -> date:
    eligible = tuple(value for value in available_dates if value <= cutoff)
    if not eligible:
        raise _error(
            "KRX_ETF_DAILY_NO_ELIGIBLE_DATE",
            "KRX ETF daily response has no eligible cutoff date",
        ) from None
    return max(eligible)


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
            "identifier_id": stable_id(
                "identifier", "OFFICIAL_PUBLISHER", "KRX"
            ),
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
            "source_title": "KRX ETF daily trading information",
            "source_type": "dataset",
            "authority_tier": "official",
            "source_locator_root": manifest.objects[0].object_key,
            "content_checksum": manifest_hash,
            "license_or_usage_note": "official KRX ETF daily market data",
            "eligible_for_claim": True,
        }
    )
    return publisher_id, source_id, (publisher, identifier, source)


def _metric_definition(column: str) -> dict[str, object]:
    metric_id = _METRICS[column]
    payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "1",
        "semantic_family": "official_krx_etf_market",
        "value_kind": "numeric",
        "default_unit": "KRW",
        "description": json.dumps(
            {
                "source_field": column,
                "source_semantics": (
                    "market_close_per_share"
                    if column == "TDD_CLSPRC"
                    else "nav_per_share"
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        "approved_at": _APPROVED_AT,
    }
    payload["definition_hash"] = make_record_hash(payload)
    return payload


def _add_market_observation(
    records: dict[str, list[Mapping[str, object]]],
    *,
    manifest: OfficialSnapshotManifest,
    source_id: str,
    binding: KrxEtfProductBinding,
    row: Mapping[str, object],
    row_number: int,
    observation_date: date,
    column: str,
) -> None:
    metric_id = _METRICS[column]
    raw = str(row[column])
    value = _parse_decimal(raw, allow_missing=column == "NAV")
    status = "unknown" if value is None else "zero" if value == 0 else "present"
    reason = "SOURCE_VALUE_MISSING" if value is None else None
    record_key = f"{row['ISU_CD']}:{row['BAS_DD']}"
    observation_id = stable_id(
        "observation", _SOURCE_CODE, f"{record_key}:{column}"
    )
    records["observation.observation_record"].append(
        _with_hash(
            {
                "observation_id": observation_id,
                "entity_id": binding.product_entity_id,
                "relation_id": None,
                "metric_id": metric_id,
                "metric_definition_version": "1",
                "value_status": status,
                "numeric_value": value,
                "text_value": None,
                "boolean_value": None,
                "date_value": None,
                "timestamp_value": None,
                "unit": "KRW",
                "currency": "KRW",
                "period_start": None,
                "period_end": None,
                "applicable_date": observation_date,
                "published_at": manifest.published_at,
                "available_at": manifest.available_at,
                "vintage_date": manifest.vintage_date,
                "reason_code": reason,
            }
        )
    )

    evidence_id = stable_id(
        "evidence", _SOURCE_CODE, f"{record_key}:{column}"
    )
    records["evidence.evidence_record"].append(
        _with_hash(
            {
                "evidence_id": evidence_id,
                "evidence_kind": "observation",
                "source_id": source_id,
                "subject_id": binding.product_entity_id,
                "predicate_id": metric_id,
                "value_or_object_id": _tag(raw),
                "normalized_value": _tag(value),
                "unit": "KRW",
                "currency": "KRW",
                "applicable_date": observation_date,
                "valid_from": None,
                "valid_to": None,
                "published_at": manifest.published_at,
                "available_at": manifest.available_at,
                "vintage_date": manifest.vintage_date,
                "locator_type": "json",
                "locator_uri_or_object_key": manifest.objects[0].object_key,
                "locator_record_key": record_key,
                "locator_sheet": None,
                "locator_row": row_number,
                "locator_column": column,
                "locator_page": None,
                "locator_section": "OutBlock_1",
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


def _limited_row(row_number: int) -> MappedRow:
    return MappedRow(
        row_number=row_number,
        disposition="limited",
        records_by_table={table: () for table in _TABLES},
        issues=(
            MappingIssue(
                source_code=_SOURCE_CODE,
                row_number=row_number,
                column="ISU_CD",
                code="KRX_ETF_DAILY_LINK_BLOCKED",
                severity="limited",
            ),
        ),
    )


def map_krx_etf_daily(
    manifest: OfficialSnapshotManifest,
    rows: Iterable[Mapping[str, object]],
    *,
    bindings: Iterable[KrxEtfProductBinding],
) -> tuple[MappedRow, ...]:
    if (
        manifest.source_code != _SOURCE_CODE
        or manifest.publisher_code != "KRX"
        or manifest.applicable_date is None
        or len(manifest.objects) != 1
    ):
        raise _error(
            "KRX_ETF_DAILY_OBJECT_MISMATCH",
            "KRX ETF daily manifest differs from the approved object contract",
        ) from None
    manifest_hash = validate_official_snapshot(manifest)

    materialized = tuple(rows)
    parsed_rows: list[tuple[date, int, Mapping[str, object]]] = []
    seen: set[tuple[str, date]] = set()
    for row_number, row in enumerate(materialized, start=1):
        try:
            if tuple(row.keys()) != _FIELDS:
                raise ValueError
            observation_date = _parse_date(str(row["BAS_DD"]))
            code = str(row["ISU_CD"])
            if _SHORT_CODE_PATTERN.fullmatch(code) is None:
                raise ValueError
            _parse_decimal(str(row["TDD_CLSPRC"]), allow_missing=False)
            _parse_decimal(str(row["NAV"]), allow_missing=True)
        except (KeyError, ValueError):
            raise _error(
                "KRX_ETF_DAILY_SCHEMA_MISMATCH",
                "KRX ETF daily row differs from the approved schema",
            ) from None
        key = (code, observation_date)
        if key in seen:
            raise _error(
                "KRX_ETF_DAILY_DUPLICATE_OBSERVATION",
                "KRX ETF daily response contains a duplicate product date",
            ) from None
        seen.add(key)
        parsed_rows.append((observation_date, row_number, row))

    selected_date = select_latest_eligible_krx_date(
        (item[0] for item in parsed_rows), manifest.cutoff_date
    )
    if manifest.applicable_date != selected_date or any(
        observation_date != selected_date
        for observation_date, _, _ in parsed_rows
    ):
        raise _error(
            "KRX_ETF_DAILY_OBJECT_MISMATCH",
            "KRX ETF daily object date differs from selected rows",
        ) from None

    bindings_by_code: dict[str, KrxEtfProductBinding] = {}
    product_ids: set[str] = set()
    for binding in bindings:
        if (
            binding.krx_short_code in bindings_by_code
            or binding.product_entity_id in product_ids
        ):
            raise _error(
                "KRX_ETF_DAILY_IDENTITY_CONFLICT",
                "KRX ETF daily binding contains a duplicate identity axis",
            ) from None
        bindings_by_code[binding.krx_short_code] = binding
        product_ids.add(binding.product_entity_id)

    mapped: list[MappedRow] = []
    for observation_date, row_number, row in parsed_rows:
        if observation_date != selected_date:
            continue
        binding = bindings_by_code.get(str(row["ISU_CD"]))
        if binding is None:
            mapped.append(_limited_row(row_number))
            continue

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
        for column in _METRICS:
            records["observation.metric_definition"].append(
                _metric_definition(column)
            )
            _add_market_observation(
                records,
                manifest=manifest,
                source_id=source_id,
                binding=binding,
                row=row,
                row_number=row_number,
                observation_date=observation_date,
                column=column,
            )
        mapped.append(
            MappedRow(
                row_number=row_number,
                disposition="accepted",
                records_by_table={
                    table: tuple(values) for table, values in records.items()
                },
                issues=(),
            )
        )
    return tuple(mapped)
