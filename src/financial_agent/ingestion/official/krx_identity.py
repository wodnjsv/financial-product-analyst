from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime

from financial_agent.contracts import encode_contract_value
from financial_agent.ingestion.identity import AuthoritativeIdentityIndex
from financial_agent.ingestion.mapping.common import (
    make_record_hash,
    normalize_name,
    stable_id,
)
from financial_agent.ingestion.models import MappedRow, MappingIssue
from financial_agent.ingestion.sources import SourceVerificationError

from .models import OfficialSnapshotManifest
from .snapshot import validate_official_snapshot


_FIELDS = ("ISU_CD", "ISU_SRT_CD", "ISU_NM", "ISU_ABBRV", "ISU_ENG_NM")
_METRICS = {
    "ISU_CD": "official.krx.security.krx_standard_issue_code",
    "ISU_SRT_CD": "official.krx.security.krx_short_issue_code",
    "ISU_NM": "official.krx.security.name_ko",
    "ISU_ABBRV": "official.krx.security.short_name_ko",
    "ISU_ENG_NM": "official.krx.security.name_en",
}
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
_APPROVED_AT = datetime(2026, 8, 22, tzinfo=UTC)


def _error() -> SourceVerificationError:
    return SourceVerificationError(
        "KRX_BASIC_SCHEMA_MISMATCH",
        "KRX security basic response differs from the approved schema",
    )


def parse_krx_security_basic(
    payload: bytes, *, market: str
) -> tuple[Mapping[str, object], ...]:
    if market not in {"KOSPI", "KOSDAQ"}:
        raise _error() from None
    try:
        decoded = json.loads(payload.decode("utf-8"))
        raw_rows = decoded["OutBlock_1"]
        if not isinstance(decoded, dict) or not isinstance(raw_rows, list):
            raise TypeError
        rows: list[Mapping[str, object]] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                raise TypeError
            row = {field: raw_row[field] for field in _FIELDS}
            if not all(isinstance(value, str) and value for value in row.values()):
                raise TypeError
            if re.fullmatch(r"[A-Z0-9]{12}", str(row["ISU_CD"])) is None:
                raise TypeError
            if re.fullmatch(r"[A-Z0-9]{6}", str(row["ISU_SRT_CD"])) is None:
                raise TypeError
            rows.append(row)
        if not rows:
            raise TypeError
        return tuple(rows)
    except Exception:
        raise _error() from None


def _with_hash(payload: Mapping[str, object]) -> dict[str, object]:
    record = dict(payload)
    record["record_hash"] = make_record_hash(payload)
    return record


def _empty_records() -> dict[str, list[Mapping[str, object]]]:
    return {table: [] for table in _TABLES}


def _quarantined(
    source_code: str,
    row_number: int,
    column: str,
    code: str = "DUPLICATE_OFFICIAL_IDENTIFIER",
) -> MappedRow:
    return MappedRow(
        row_number=row_number,
        disposition="quarantined",
        records_by_table={table: () for table in _TABLES},
        issues=(
            MappingIssue(
                source_code=source_code,
                row_number=row_number,
                column=column,
                code=code,
                severity="quarantined",
            ),
        ),
    )


def _publisher_and_source(
    manifest: OfficialSnapshotManifest,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    str,
]:
    publisher_id = stable_id(
        "institution", "OFFICIAL_PUBLISHER", manifest.publisher_code
    )
    source_id = stable_id("source", manifest.source_code, manifest.snapshot_id)
    manifest_hash = validate_official_snapshot(manifest)
    publisher = _with_hash(
        {
            "entity_id": publisher_id,
            "entity_type": "institution",
            "canonical_name": "Korea Exchange",
            "normalized_name": "Korea Exchange",
        }
    )
    institution = {
        "entity_id": publisher_id,
        "institution_kind": "exchange",
    }
    source = _with_hash(
        {
            "source_id": source_id,
            "publisher": publisher_id,
            "publisher_type": "exchange",
            "source_title": f"{manifest.source_code} official snapshot",
            "source_type": "dataset",
            "authority_tier": "official",
            "source_locator_root": manifest.objects[0].object_key,
            "content_checksum": manifest_hash,
            "license_or_usage_note": "official KRX data",
            "eligible_for_claim": True,
        }
    )
    return publisher, institution, source, source_id


def _text_fact_records(
    manifest: OfficialSnapshotManifest,
    *,
    source_id: str,
    row_number: int,
    record_key: str,
    subject_id: str,
    field: str,
    value: str,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    metric_id = _METRICS[field]
    definition_payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "1",
        "semantic_family": "official_krx_security_identity",
        "value_kind": "text",
        "default_unit": None,
        "description": f"KRX security basic field {field}",
        "approved_at": _APPROVED_AT,
    }
    definition_payload["definition_hash"] = make_record_hash(definition_payload)

    normalized = normalize_name(value)
    observation_id = stable_id(
        "observation", manifest.source_code, f"{record_key}:{field}"
    )
    observation = _with_hash(
        {
            "observation_id": observation_id,
            "entity_id": subject_id,
            "relation_id": None,
            "metric_id": metric_id,
            "metric_definition_version": "1",
            "value_status": "present",
            "numeric_value": None,
            "text_value": normalized,
            "boolean_value": None,
            "date_value": None,
            "timestamp_value": None,
            "unit": None,
            "currency": None,
            "period_start": None,
            "period_end": None,
            "applicable_date": manifest.applicable_date,
            "published_at": manifest.published_at,
            "available_at": manifest.available_at,
            "vintage_date": manifest.vintage_date,
            "reason_code": None,
        }
    )
    evidence_id = stable_id(
        "evidence", manifest.source_code, f"{record_key}:{field}"
    )
    evidence = _with_hash(
        {
            "evidence_id": evidence_id,
            "evidence_kind": "observation",
            "source_id": source_id,
            "subject_id": subject_id,
            "predicate_id": metric_id,
            "value_or_object_id": encode_contract_value(value).model_dump(mode="json"),
            "normalized_value": encode_contract_value(normalized).model_dump(
                mode="json"
            ),
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
            "locator_record_key": record_key,
            "locator_sheet": None,
            "locator_row": row_number,
            "locator_column": field,
            "locator_page": None,
            "locator_section": None,
            "locator_sentence_start": None,
            "locator_sentence_end": None,
            "raw_value_repr": value,
            "parser_version": manifest.parser_version,
            "mapping_version": manifest.mapping_version,
            "cutoff_status": "eligible",
            "scope_completeness": None,
        }
    )
    origin = {"evidence_id": evidence_id, "observation_id": observation_id}
    return definition_payload, observation, evidence, origin


def _mapped_row(
    manifest: OfficialSnapshotManifest,
    *,
    row_number: int,
    row: Mapping[str, object],
    identity_index: AuthoritativeIdentityIndex | None,
) -> MappedRow:
    records = _empty_records()
    standard_code = str(row["ISU_CD"])
    short_code = str(row["ISU_SRT_CD"])
    canonical_name = normalize_name(str(row["ISU_NM"]))
    resolution = (
        identity_index.resolve("ISIN", standard_code)
        if identity_index is not None
        else None
    )
    if resolution is not None and resolution.status == "AMBIGUOUS":
        return _quarantined(
            manifest.source_code,
            row_number,
            "ISU_CD",
            "ORGANIZER_IDENTITY_AMBIGUOUS",
        )
    reused = (
        resolution is not None
        and resolution.status == "MATCHED"
        and resolution.canonical_identity is not None
    )
    entity_id = (
        resolution.canonical_identity.entity_id
        if reused
        and resolution is not None
        and resolution.canonical_identity is not None
        else stable_id("security", manifest.source_code, standard_code)
    )
    publisher, institution, source, source_id = _publisher_and_source(manifest)
    records["catalog.entity"].append(publisher)
    if not reused:
        records["catalog.entity"].append(
            _with_hash(
                {
                    "entity_id": entity_id,
                    "entity_type": "security",
                    "canonical_name": canonical_name,
                    "normalized_name": canonical_name,
                }
            )
        )
    records["catalog.institution"].append(institution)
    if not reused:
        records["catalog.security"].append(
            {
                "entity_id": entity_id,
                "security_kind": "listed_equity",
                "ticker_display": short_code,
                "isin_display": None,
            }
        )
    records["evidence.source_record"].append(source)

    for scheme, value, primary in (
        ("KRX_STANDARD_ISSUE_CODE", standard_code, True),
        ("KRX_SHORT_ISSUE_CODE", short_code, False),
    ):
        records["catalog.identifier"].append(
            _with_hash(
                {
                    "identifier_id": stable_id(
                        "identifier", manifest.source_code, f"{scheme}:{value}"
                    ),
                    "entity_id": entity_id,
                    "scheme": scheme,
                    "identifier_value": value,
                    "is_primary": primary,
                    "valid_from": None,
                    "valid_to": None,
                }
            )
        )

    for field in ("ISU_ABBRV", "ISU_ENG_NM"):
        value = normalize_name(str(row[field]))
        records["catalog.alias"].append(
            _with_hash(
                {
                    "alias_id": stable_id(
                        "alias", manifest.source_code, f"{standard_code}:{field}:{value}"
                    ),
                    "entity_id": entity_id,
                    "alias_text": value,
                    "normalized_alias_text": value,
                    "valid_from": None,
                    "valid_to": None,
                }
            )
        )

    for field in _FIELDS:
        definition, observation, evidence, origin = _text_fact_records(
            manifest,
            source_id=source_id,
            row_number=row_number,
            record_key=standard_code,
            subject_id=entity_id,
            field=field,
            value=str(row[field]),
        )
        records["observation.metric_definition"].append(definition)
        records["observation.observation_record"].append(observation)
        records["evidence.evidence_record"].append(evidence)
        records["evidence.evidence_observation_origin"].append(origin)

    return MappedRow(
        row_number=row_number,
        disposition="accepted",
        records_by_table={
            table: tuple(table_records) for table, table_records in records.items()
        },
        issues=(),
    )


def map_krx_security_basic(
    manifest: OfficialSnapshotManifest,
    rows: Iterable[Mapping[str, object]],
    *,
    identity_index: AuthoritativeIdentityIndex | None = None,
) -> Iterator[MappedRow]:
    if manifest.source_code not in {"KRX_KOSPI_BASIC", "KRX_KOSDAQ_BASIC"}:
        raise SourceVerificationError(
            "KRX_BASIC_SOURCE_MISMATCH",
            "KRX security basic manifest source is invalid",
        ) from None
    validate_official_snapshot(manifest)
    materialized = tuple(rows)
    standard_counts = Counter(str(row["ISU_CD"]) for row in materialized)
    short_counts = Counter(str(row["ISU_SRT_CD"]) for row in materialized)
    for row_number, row in enumerate(materialized, start=1):
        if standard_counts[str(row["ISU_CD"])] > 1:
            yield _quarantined(manifest.source_code, row_number, "ISU_CD")
        elif short_counts[str(row["ISU_SRT_CD"])] > 1:
            yield _quarantined(manifest.source_code, row_number, "ISU_SRT_CD")
        else:
            yield _mapped_row(
                manifest,
                row_number=row_number,
                row=row,
                identity_index=identity_index,
            )
