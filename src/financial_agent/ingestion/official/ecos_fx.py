from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from financial_agent.contracts import encode_contract_value
from financial_agent.ingestion.mapping.common import make_record_hash, stable_id
from financial_agent.ingestion.models import MappedRow
from financial_agent.ingestion.sources import SourceVerificationError

from .models import OfficialSnapshotManifest
from .snapshot import validate_official_snapshot


ECOS_ITEMS = {
    "0000001": "KRW_PER_USD",
    "0000002": "KRW_PER_100_JPY",
    "0000003": "KRW_PER_EUR",
    "0000053": "KRW_PER_CNY",
}

_ITEM_DEFINITIONS = {
    "0000001": {
        "item_name": "원/미국달러(매매기준율)",
        "metric_id": "ecos_731y001_krw_per_usd",
        "base_currency": "USD",
        "base_units": 1,
    },
    "0000002": {
        "item_name": "원/일본엔(100엔)",
        "metric_id": "ecos_731y001_krw_per_100_jpy",
        "base_currency": "JPY",
        "base_units": 100,
    },
    "0000003": {
        "item_name": "원/유로",
        "metric_id": "ecos_731y001_krw_per_eur",
        "base_currency": "EUR",
        "base_units": 1,
    },
    "0000053": {
        "item_name": "원/위안(매매기준율)",
        "metric_id": "ecos_731y001_krw_per_cny",
        "base_currency": "CNY",
        "base_units": 1,
    },
}
_FIELDS = (
    "STAT_CODE",
    "ITEM_CODE1",
    "ITEM_NAME1",
    "UNIT_NAME",
    "TIME",
    "DATA_VALUE",
)
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
_DECIMAL_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_APPROVED_AT = datetime(2026, 8, 22, tzinfo=UTC)
_RATE_TYPE = "ecos_731y001_daily_exchange_rate"


def _error(code: str, message: str) -> SourceVerificationError:
    return SourceVerificationError(code, message)


def _with_hash(payload: Mapping[str, object]) -> dict[str, object]:
    record = dict(payload)
    record["record_hash"] = make_record_hash(payload)
    return record


def _parse_date(value: str) -> date:
    if re.fullmatch(r"[0-9]{8}", value) is None:
        raise ValueError
    return datetime.strptime(value, "%Y%m%d").date()


def _parse_decimal(value: str) -> Decimal:
    if _DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError from None
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError
    return parsed


def parse_ecos_731y001(payload: bytes) -> tuple[Mapping[str, object], ...]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
        search = decoded["StatisticSearch"]
        raw_rows = search["row"]
        if not isinstance(decoded, dict) or not isinstance(search, dict):
            raise TypeError
        if not isinstance(raw_rows, list) or not raw_rows:
            raise TypeError
    except Exception:
        raise _error(
            "ECOS_FX_SCHEMA_MISMATCH",
            "ECOS exchange-rate response differs from the approved schema",
        ) from None

    rows: list[Mapping[str, object]] = []
    observed_items: set[str] = set()
    observed_keys: set[tuple[str, str]] = set()
    for raw_row in raw_rows:
        try:
            if not isinstance(raw_row, dict):
                raise TypeError
            row = {field: raw_row[field] for field in _FIELDS}
            if not all(isinstance(value, str) and value for value in row.values()):
                raise TypeError
            stat_code = str(row["STAT_CODE"])
            item_code = str(row["ITEM_CODE1"])
            if stat_code != "731Y001":
                raise TypeError
            if item_code not in _ITEM_DEFINITIONS:
                continue
            item_definition = _ITEM_DEFINITIONS[item_code]
            if (
                row["ITEM_NAME1"] != item_definition["item_name"]
                or row["UNIT_NAME"] != "원"
            ):
                raise TypeError
            _parse_date(str(row["TIME"]))
        except (KeyError, TypeError, ValueError):
            raise _error(
                "ECOS_FX_SCHEMA_MISMATCH",
                "ECOS exchange-rate response differs from the approved schema",
            ) from None

        try:
            _parse_decimal(str(row["DATA_VALUE"]))
        except ValueError:
            raise _error(
                "ECOS_FX_VALUE_INVALID",
                "ECOS exchange-rate value is not an approved decimal",
            ) from None

        natural_key = (item_code, str(row["TIME"]))
        if natural_key in observed_keys:
            raise _error(
                "ECOS_FX_DUPLICATE_OBSERVATION",
                "ECOS exchange-rate response contains a duplicate item date",
            ) from None
        observed_keys.add(natural_key)
        observed_items.add(item_code)
        rows.append(row)

    if observed_items != set(ECOS_ITEMS):
        raise _error(
            "ECOS_FX_COVERAGE_INCOMPLETE",
            "ECOS exchange-rate response does not cover all approved items",
        ) from None
    return tuple(rows)


def _canonical_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _metric_description(item_code: str) -> str:
    definition = _ITEM_DEFINITIONS[item_code]
    return json.dumps(
        {
            "base_currency": definition["base_currency"],
            "base_units": definition["base_units"],
            "item_code": item_code,
            "quote_currency": "KRW",
            "rate_type": _RATE_TYPE,
            "stat_code": "731Y001",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalized_evidence(item_code: str, value: Decimal) -> str:
    definition = _ITEM_DEFINITIONS[item_code]
    return ";".join(
        (
            f"base_currency={definition['base_currency']}",
            f"base_units={definition['base_units']}",
            f"item_code={item_code}",
            "quote_currency=KRW",
            f"rate_type={_RATE_TYPE}",
            "stat_code=731Y001",
            f"value={_canonical_decimal(value)}",
        )
    )


def _publisher_records(
    manifest: OfficialSnapshotManifest,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    publisher_id = stable_id("institution", "OFFICIAL_PUBLISHER", "BOK")
    entity = _with_hash(
        {
            "entity_id": publisher_id,
            "entity_type": "institution",
            "canonical_name": "Bank of Korea",
            "normalized_name": "Bank of Korea",
        }
    )
    institution = {
        "entity_id": publisher_id,
        "institution_kind": "central_bank",
    }
    identifier = _with_hash(
        {
            "identifier_id": stable_id(
                "identifier", "OFFICIAL_PUBLISHER", "BOK"
            ),
            "entity_id": publisher_id,
            "scheme": "OFFICIAL_PUBLISHER_CODE",
            "identifier_value": "BOK",
            "is_primary": True,
            "valid_from": None,
            "valid_to": None,
        }
    )
    return entity, institution, identifier


def _source_record(
    manifest: OfficialSnapshotManifest, *, publisher_id: str
) -> tuple[dict[str, object], str]:
    source_id = stable_id("source", manifest.source_code, manifest.snapshot_id)
    manifest_hash = validate_official_snapshot(manifest)
    source = _with_hash(
        {
            "source_id": source_id,
            "publisher": publisher_id,
            "publisher_type": "central_bank",
            "source_title": "ECOS 731Y001 official daily exchange rates",
            "source_type": "dataset",
            "authority_tier": "official",
            "source_locator_root": manifest.objects[0].object_key,
            "content_checksum": manifest_hash,
            "license_or_usage_note": "official Bank of Korea ECOS data",
            "eligible_for_claim": True,
        }
    )
    return source, source_id


def _mapped_row(
    manifest: OfficialSnapshotManifest,
    *,
    row_number: int,
    row: Mapping[str, object],
) -> MappedRow:
    records: dict[str, list[Mapping[str, object]]] = {
        table: [] for table in _TABLES
    }
    item_code = str(row["ITEM_CODE1"])
    observation_date = _parse_date(str(row["TIME"]))
    numeric_value = _parse_decimal(str(row["DATA_VALUE"]))
    definition = _ITEM_DEFINITIONS[item_code]
    metric_id = str(definition["metric_id"])
    record_key = f"731Y001:{item_code}:{row['TIME']}"

    publisher, institution, identifier = _publisher_records(manifest)
    source, source_id = _source_record(
        manifest, publisher_id=str(publisher["entity_id"])
    )
    records["catalog.entity"].append(publisher)
    records["catalog.institution"].append(institution)
    records["catalog.identifier"].append(identifier)
    records["evidence.source_record"].append(source)

    metric_payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "1",
        "semantic_family": "official_fx_rate",
        "value_kind": "numeric",
        "default_unit": "KRW",
        "description": _metric_description(item_code),
        "approved_at": _APPROVED_AT,
    }
    metric_payload["definition_hash"] = make_record_hash(metric_payload)
    records["observation.metric_definition"].append(metric_payload)

    observation_id = stable_id(
        "observation", manifest.source_code, record_key
    )
    observation = _with_hash(
        {
            "observation_id": observation_id,
            "entity_id": publisher["entity_id"],
            "relation_id": None,
            "metric_id": metric_id,
            "metric_definition_version": "1",
            "value_status": "present",
            "numeric_value": numeric_value,
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
            "reason_code": None,
        }
    )
    records["observation.observation_record"].append(observation)

    evidence_id = stable_id("evidence", manifest.source_code, record_key)
    evidence = _with_hash(
        {
            "evidence_id": evidence_id,
            "evidence_kind": "observation",
            "source_id": source_id,
            "subject_id": publisher["entity_id"],
            "predicate_id": metric_id,
            "value_or_object_id": encode_contract_value(
                str(row["DATA_VALUE"])
            ).model_dump(mode="json"),
            "normalized_value": encode_contract_value(
                _normalized_evidence(item_code, numeric_value)
            ).model_dump(mode="json"),
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
            "locator_column": "DATA_VALUE",
            "locator_page": None,
            "locator_section": "StatisticSearch.row",
            "locator_sentence_start": None,
            "locator_sentence_end": None,
            "raw_value_repr": str(row["DATA_VALUE"]),
            "parser_version": manifest.parser_version,
            "mapping_version": manifest.mapping_version,
            "cutoff_status": "eligible",
            "scope_completeness": None,
        }
    )
    records["evidence.evidence_record"].append(evidence)
    records["evidence.evidence_observation_origin"].append(
        {"evidence_id": evidence_id, "observation_id": observation_id}
    )

    return MappedRow(
        row_number=row_number,
        disposition="accepted",
        records_by_table={
            table: tuple(table_records)
            for table, table_records in records.items()
        },
        issues=(),
    )


def map_ecos_fx(
    manifest: OfficialSnapshotManifest,
    rows: Iterable[Mapping[str, object]],
) -> tuple[MappedRow, ...]:
    if (
        manifest.source_code != "ECOS_731Y001"
        or manifest.publisher_code != "BOK"
    ):
        raise _error(
            "ECOS_FX_SOURCE_MISMATCH",
            "ECOS exchange-rate manifest source is invalid",
        ) from None
    validate_official_snapshot(manifest)

    latest: dict[str, tuple[date, int, Mapping[str, object]]] = {}
    for row_number, row in enumerate(tuple(rows), start=1):
        try:
            item_code = str(row["ITEM_CODE1"])
            observation_date = _parse_date(str(row["TIME"]))
            if item_code not in ECOS_ITEMS:
                raise KeyError
        except (KeyError, ValueError):
            raise _error(
                "ECOS_FX_SCHEMA_MISMATCH",
                "ECOS exchange-rate row differs from the approved schema",
            ) from None
        if observation_date > manifest.cutoff_date:
            continue
        existing = latest.get(item_code)
        if existing is None or observation_date > existing[0]:
            latest[item_code] = (observation_date, row_number, row)

    if set(latest) != set(ECOS_ITEMS):
        raise _error(
            "ECOS_FX_COVERAGE_INCOMPLETE",
            "ECOS exchange-rate snapshot has no cutoff-eligible row "
            "for every item",
        ) from None

    return tuple(
        _mapped_row(
            manifest,
            row_number=latest[item_code][1],
            row=latest[item_code][2],
        )
        for item_code in ECOS_ITEMS
    )
