from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal

from financial_agent.contracts import encode_contract_value
from financial_agent.ingestion.models import MappedRow, MappingIssue, SourceSpec

from .common import (
    classify_value,
    make_record_hash,
    normalize_name,
    parse_decimal,
    parse_yyyymmdd,
    stable_id,
)


_CUTOFF_DATE = date(2026, 7, 11)
_DEFINITION_APPROVED_AT = datetime(2026, 8, 20, tzinfo=UTC)
_SOURCE_CODE = "PRBD01N001"
_SOURCE_ID = stable_id(
    "source",
    _SOURCE_CODE,
    "PRBD01N001_국내채권마스터_20260711_datarows.xlsx",
)
_MISSING_VALUES = frozenset({None, "", "NULL"})

_EXPECTED_COLUMNS = (
    "PD_NO",
    "PD_EXG_MKT",
    "PD_NM",
    "PD_ABRV_NM",
    "PD_ENG_NM",
    "PD_ABRV_ENG_NM",
    "PD_CTRY_CD",
    "PD_PBCM",
    "STD_PD_MCLS_NM",
    "STD_PD_SCLS_NM",
    "BD_KND",
    "CURR_CD",
    "ISU_BAL_AMT",
    "ISU_DT",
    "MAT_DT",
    "SRFC_IRT",
    "PD_EVCO_CRD_GRD",
    "PD_RISK_GCD",
    "PD_STD_INFO_UPDATE",
    "BUY_YIELD",
    "CORP_PRETAX_YIELD",
    "CORP_AFTER_TAX_YIELD",
    "AFTER_TAX_YIELD",
    "PREF_TAX_YIELD",
    "AVG_ANNUAL_TAX_YIELD",
    "DEPO_EQUIV_YIELD_154",
    "BUYABLE_QUANTITY",
    "REMAINING_DAYS",
    "DUR",
    "COV",
    "NDY_DUR",
    "NDY_COV",
    "EVAL_PRICE",
    "APPLIED_YIELD",
    "DIRTY",
    "NDY_EVAL_PRICE",
    "NDY_APPLIED_YIELD",
    "NDY_DIRTY",
    "CRD_GRD",
    "CRD_GRD_DT",
)

SPEC = SourceSpec(
    source_code=_SOURCE_CODE,
    table_id=_SOURCE_CODE,
    data_file_name="PRBD01N001_국내채권마스터_20260711_datarows.xlsx",
    data_sheet_name="datarows",
    schema_file_name="PRBD01N001_국내채권마스터_schema.xlsx",
    schema_sheet_name="Sheet1_Schema",
    expected_columns=_EXPECTED_COLUMNS,
    expected_row_count=42_394,
    natural_key=("PD_NO",),
    parser_version="1",
    mapping_version="1",
)

IGNORED_COLUMNS: Mapping[str, str] = {
    "AVG_ANNUAL_TAX_YIELD": "UNUSABLE_ALL_ZERO_SERIES",
    "REMAINING_DAYS": "NO_TRUSTED_TIME_BASIS",
}
HANDLED_COLUMNS = frozenset(_EXPECTED_COLUMNS) - frozenset(IGNORED_COLUMNS)

_METRIC_SPECS: Mapping[str, tuple[str, str, str | None]] = {
    "PD_NO": ("product_id", "text", None),
    "PD_EXG_MKT": ("exchange_market_type", "text", None),
    "PD_NM": ("name_ko", "text", None),
    "PD_ABRV_NM": ("short_name_ko", "text", None),
    "PD_ENG_NM": ("name_en", "text", None),
    "PD_ABRV_ENG_NM": ("short_name_en", "text", None),
    "PD_CTRY_CD": ("country_code_raw", "text", None),
    "STD_PD_MCLS_NM": ("product_major_class", "text", None),
    "STD_PD_SCLS_NM": ("product_subclass", "text", None),
    "BD_KND": ("bond_kind", "text", None),
    "CURR_CD": ("currency", "text", None),
    "ISU_BAL_AMT": ("issue_balance", "numeric", "source_defined_amount"),
    "ISU_DT": ("issue_date", "date", None),
    "MAT_DT": ("maturity_date", "date", None),
    "SRFC_IRT": ("coupon_rate", "numeric", "percentage_point"),
    "PD_EVCO_CRD_GRD": ("credit_grade_raw", "text", None),
    "PD_RISK_GCD": ("risk_grade_code", "text", None),
    "PD_STD_INFO_UPDATE": ("standard_info_updated_on", "date", None),
    "BUY_YIELD": ("buy_yield", "numeric", "percentage_point"),
    "CORP_PRETAX_YIELD": (
        "corporate_pretax_yield",
        "numeric",
        "percentage_point",
    ),
    "CORP_AFTER_TAX_YIELD": (
        "corporate_after_tax_yield",
        "numeric",
        "percentage_point",
    ),
    "AFTER_TAX_YIELD": ("after_tax_yield", "numeric", "percentage_point"),
    "PREF_TAX_YIELD": (
        "preferential_tax_yield",
        "numeric",
        "percentage_point",
    ),
    "DEPO_EQUIV_YIELD_154": (
        "deposit_equivalent_yield_154",
        "numeric",
        "percentage_point",
    ),
    "BUYABLE_QUANTITY": (
        "buyable_quantity",
        "numeric",
        "source_defined_quantity",
    ),
    "DUR": ("duration_raw", "numeric", "source_defined"),
    "COV": ("convexity_raw", "numeric", "source_defined"),
    "NDY_DUR": (
        "next_business_day_duration_raw",
        "numeric",
        "source_defined",
    ),
    "NDY_COV": (
        "next_business_day_convexity_raw",
        "numeric",
        "source_defined",
    ),
    "EVAL_PRICE": (
        "evaluation_price_raw",
        "numeric",
        "source_defined_price",
    ),
    "APPLIED_YIELD": (
        "applied_yield_raw",
        "numeric",
        "source_defined",
    ),
    "DIRTY": ("dirty_price_raw", "numeric", "source_defined_price"),
    "NDY_EVAL_PRICE": (
        "next_business_day_evaluation_price_raw",
        "numeric",
        "source_defined_price",
    ),
    "NDY_APPLIED_YIELD": (
        "next_business_day_applied_yield_raw",
        "numeric",
        "source_defined",
    ),
    "NDY_DIRTY": (
        "next_business_day_dirty_price_raw",
        "numeric",
        "source_defined_price",
    ),
    "CRD_GRD": ("credit_grade_representative", "text", None),
    "CRD_GRD_DT": ("credit_grade_as_of", "date", None),
}

_DATE_SENTINELS: Mapping[str, frozenset[str]] = {
    "ISU_DT": frozenset({"0"}),
    "MAT_DT": frozenset({"0", "99991231"}),
    "PD_STD_INFO_UPDATE": frozenset({"0"}),
    "CRD_GRD_DT": frozenset({"0"}),
}
_ZERO_MEANING_UNKNOWN = frozenset({"NDY_EVAL_PRICE", "NDY_DIRTY"})
_CURRENCY_FIELDS = frozenset(
    {"ISU_BAL_AMT", "EVAL_PRICE", "DIRTY", "NDY_EVAL_PRICE", "NDY_DIRTY"}
)
_ALIAS_FIELDS = ("PD_ABRV_NM", "PD_ENG_NM", "PD_ABRV_ENG_NM")
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
    "evidence.evidence_record",
    "evidence.evidence_observation_origin",
    "evidence.evidence_relation_origin",
)


def _tag(value: object) -> Mapping[str, object]:
    return encode_contract_value(value).model_dump(mode="json")


def _with_record_hash(payload: Mapping[str, object]) -> dict[str, object]:
    record = dict(payload)
    record["record_hash"] = make_record_hash(payload)
    return record


def _metric_definition(
    column: str,
    metric_id: str,
    value_kind: str,
    unit: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "1",
        "semantic_family": "organizer_domestic_bond",
        "value_kind": value_kind,
        "default_unit": unit,
        "description": f"Organizer PRBD01N001 field {column}",
        "approved_at": _DEFINITION_APPROVED_AT,
    }
    payload["definition_hash"] = make_record_hash(payload)
    return payload


def _raw_value_repr(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _text_result(
    column: str,
    raw: object,
) -> tuple[str, object | None, str | None]:
    text = raw if isinstance(raw, str) or raw is None else str(raw)
    status, normalized, reason = classify_value(
        text,
        missing_values=_MISSING_VALUES,
        placeholder_values=frozenset(),
        zero_is_value=True,
    )
    if status == "present" and column == "CURR_CD" and normalized == "000":
        return "unknown", None, "UNDEFINED_CURRENCY_CODE"
    return status, normalized, reason


def _numeric_result(
    column: str,
    raw: object,
) -> tuple[str, object | None, str | None]:
    status, normalized, reason = classify_value(
        raw,
        missing_values=_MISSING_VALUES,
        placeholder_values=frozenset(),
        zero_is_value=column not in _ZERO_MEANING_UNKNOWN,
    )
    if status in {"present", "zero"}:
        normalized = parse_decimal(normalized)
    return status, normalized, reason


def _date_result(
    column: str,
    raw: object,
) -> tuple[str, object | None, str | None]:
    sentinels = _DATE_SENTINELS[column]
    token = normalize_name(str(raw)) if raw is not None else None
    if token in sentinels:
        return "placeholder", None, "SOURCE_VALUE_PLACEHOLDER"

    status, _, reason = classify_value(
        raw,
        missing_values=_MISSING_VALUES,
        placeholder_values=sentinels,
        zero_is_value=False,
    )
    if status != "present":
        return status, None, reason
    return "present", parse_yyyymmdd(raw, sentinels=sentinels), None


def _typed_values(
    value_kind: str,
    status: str,
    normalized: object | None,
) -> dict[str, object | None]:
    values: dict[str, object | None] = {
        "numeric_value": None,
        "text_value": None,
        "boolean_value": None,
        "date_value": None,
        "timestamp_value": None,
    }
    if status == "present":
        values[f"{value_kind}_value"] = normalized
    elif status == "zero":
        values["numeric_value"] = normalized
    return values


def _empty_records() -> dict[str, list[Mapping[str, object]]]:
    return {table: [] for table in _TABLES}


def _quarantined(
    row_number: int,
    column: str,
    code: str,
    *,
    fatal: bool = False,
) -> MappedRow:
    return MappedRow(
        row_number=row_number,
        disposition="quarantined",
        records_by_table={table: () for table in _TABLES},
        issues=(
            MappingIssue(
                source_code=_SOURCE_CODE,
                row_number=row_number,
                column=column,
                code=code,
                severity="fatal" if fatal else "quarantined",
            ),
        ),
    )


def _observation_and_evidence(
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    column: str,
    raw: object,
    status: str,
    normalized: object | None,
    reason_code: str | None,
    value_kind: str,
    unit: str | None,
    currency: str | None,
    applicable_date: date | None,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    metric_suffix, _, _ = _METRIC_SPECS[column]
    metric_id = f"organizer.prbd01n001.{metric_suffix}"
    observation_id = stable_id("observation", _SOURCE_CODE, f"{record_key}:{column}")
    evidence_id = stable_id("evidence", _SOURCE_CODE, f"{record_key}:{column}")

    observation_payload: dict[str, object] = {
        "observation_id": observation_id,
        "entity_id": product_id,
        "relation_id": None,
        "metric_id": metric_id,
        "metric_definition_version": "1",
        "value_status": status,
        **_typed_values(value_kind, status, normalized),
        "unit": unit,
        "currency": currency,
        "period_start": None,
        "period_end": None,
        "applicable_date": applicable_date,
        "published_at": None,
        "available_at": None,
        "vintage_date": _CUTOFF_DATE,
        "reason_code": reason_code,
    }
    observation_record = _with_record_hash(observation_payload)

    evidence_value = normalized if status in {"present", "zero"} else None
    evidence_applicable_date = (
        applicable_date
        if applicable_date is None or applicable_date <= _CUTOFF_DATE
        else None
    )
    evidence_payload: dict[str, object] = {
        "evidence_id": evidence_id,
        "evidence_kind": "observation",
        "source_id": _SOURCE_ID,
        "subject_id": product_id,
        "predicate_id": metric_id,
        "value_or_object_id": _tag(
            raw if status in {"present", "zero"} else None
        ),
        "normalized_value": _tag(evidence_value),
        "unit": unit,
        "currency": currency,
        "applicable_date": evidence_applicable_date,
        "valid_from": None,
        "valid_to": None,
        "published_at": None,
        "available_at": None,
        "vintage_date": _CUTOFF_DATE,
        "locator_type": "tabular",
        "locator_uri_or_object_key": SPEC.data_file_name,
        "locator_record_key": record_key,
        "locator_sheet": SPEC.data_sheet_name,
        "locator_row": row_number,
        "locator_column": column,
        "locator_page": None,
        "locator_section": None,
        "locator_sentence_start": None,
        "locator_sentence_end": None,
        "raw_value_repr": _raw_value_repr(raw),
        "parser_version": SPEC.parser_version,
        "mapping_version": SPEC.mapping_version,
        "cutoff_status": "eligible",
        "scope_completeness": None,
    }
    evidence_record = _with_record_hash(evidence_payload)
    origin = {"evidence_id": evidence_id, "observation_id": observation_id}
    definition = _metric_definition(column, metric_id, value_kind, unit)
    return definition, observation_record, evidence_record, origin


def _issuer_records(
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    raw: object,
) -> tuple[
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
]:
    status, normalized, _ = _text_result("PD_PBCM", raw)
    if status != "present" or not isinstance(normalized, str):
        return (), (), (), (), ()

    issuer_id = stable_id("institution", _SOURCE_CODE, normalized)
    issuer_entity = _with_record_hash(
        {
            "entity_id": issuer_id,
            "entity_type": "institution",
            "canonical_name": normalized,
            "normalized_name": normalized,
        }
    )
    institution = {"entity_id": issuer_id, "institution_kind": "issuer"}
    relation_id = stable_id(
        "relation",
        _SOURCE_CODE,
        f"{record_key}:issuedBy:{issuer_id}",
    )
    relation = _with_record_hash(
        {
            "relation_id": relation_id,
            "subject_id": product_id,
            "predicate_id": "issuedBy",
            "object_id": issuer_id,
            "valid_from": None,
            "valid_to": None,
        }
    )
    evidence_id = stable_id("evidence", _SOURCE_CODE, f"{record_key}:PD_PBCM")
    evidence = _with_record_hash(
        {
            "evidence_id": evidence_id,
            "evidence_kind": "relation",
            "source_id": _SOURCE_ID,
            "subject_id": product_id,
            "predicate_id": "issuedBy",
            "value_or_object_id": _tag(issuer_id),
            "normalized_value": _tag(issuer_id),
            "unit": None,
            "currency": None,
            "applicable_date": None,
            "valid_from": None,
            "valid_to": None,
            "published_at": None,
            "available_at": None,
            "vintage_date": _CUTOFF_DATE,
            "locator_type": "tabular",
            "locator_uri_or_object_key": SPEC.data_file_name,
            "locator_record_key": record_key,
            "locator_sheet": SPEC.data_sheet_name,
            "locator_row": row_number,
            "locator_column": "PD_PBCM",
            "locator_page": None,
            "locator_section": None,
            "locator_sentence_start": None,
            "locator_sentence_end": None,
            "raw_value_repr": _raw_value_repr(raw),
            "parser_version": SPEC.parser_version,
            "mapping_version": SPEC.mapping_version,
            "cutoff_status": "eligible",
            "scope_completeness": None,
        }
    )
    origin = {"evidence_id": evidence_id, "relation_id": relation_id}
    return (issuer_entity,), (institution,), (relation,), (evidence,), (origin,)


def map_row(row_number: int, row: Mapping[str, object]) -> MappedRow:
    raw_key = row.get("PD_NO")
    record_key = normalize_name(raw_key) if isinstance(raw_key, str) else ""
    if not record_key or record_key == "NULL":
        return _quarantined(row_number, "PD_NO", "MISSING_NATURAL_KEY")

    raw_name = row.get("PD_NM")
    canonical_name = normalize_name(raw_name) if isinstance(raw_name, str) else ""
    if not canonical_name or canonical_name == "NULL":
        return _quarantined(row_number, "PD_NM", "MISSING_REQUIRED_NAME")

    records_by_table = _empty_records()
    issues: list[MappingIssue] = []
    product_id = stable_id("product", _SOURCE_CODE, record_key)
    current_column = "CURR_CD"

    try:
        currency_status, primary_currency, _ = _text_result(
            "CURR_CD", row.get("CURR_CD")
        )
        if currency_status != "present":
            primary_currency = None

        product_entity = _with_record_hash(
            {
                "entity_id": product_id,
                "entity_type": "product",
                "canonical_name": canonical_name,
                "normalized_name": canonical_name,
            }
        )
        records_by_table["catalog.entity"].append(product_entity)
        records_by_table["catalog.product"].append(
            {
                "entity_id": product_id,
                "product_family": "domestic_bond",
                "primary_currency": primary_currency,
            }
        )
        records_by_table["catalog.security"].append(
            {
                "entity_id": product_id,
                "security_kind": "bond",
                "ticker_display": None,
                "isin_display": None,
            }
        )
        identifier_id = stable_id(
            "identifier", _SOURCE_CODE, f"PRBD_PD_NO:{record_key}"
        )
        records_by_table["catalog.identifier"].append(
            _with_record_hash(
                {
                    "identifier_id": identifier_id,
                    "entity_id": product_id,
                    "scheme": "PRBD_PD_NO",
                    "identifier_value": record_key,
                    "is_primary": True,
                    "valid_from": None,
                    "valid_to": None,
                }
            )
        )

        for column in _ALIAS_FIELDS:
            status, normalized, _ = _text_result(column, row.get(column))
            if status == "present" and isinstance(normalized, str):
                alias_id = stable_id(
                    "alias",
                    _SOURCE_CODE,
                    f"{record_key}:{column}:{normalized}",
                )
                records_by_table["catalog.alias"].append(
                    _with_record_hash(
                        {
                            "alias_id": alias_id,
                            "entity_id": product_id,
                            "alias_text": normalized,
                            "normalized_alias_text": normalized,
                            "valid_from": None,
                            "valid_to": None,
                        }
                    )
                )

        (
            issuer_entities,
            institutions,
            relations,
            relation_evidence,
            relation_origins,
        ) = _issuer_records(
            row_number=row_number,
            record_key=record_key,
            product_id=product_id,
            raw=row.get("PD_PBCM"),
        )
        records_by_table["catalog.entity"].extend(issuer_entities)
        records_by_table["catalog.institution"].extend(institutions)
        records_by_table["relation.relation_record"].extend(relations)
        records_by_table["evidence.evidence_record"].extend(relation_evidence)
        records_by_table["evidence.evidence_relation_origin"].extend(
            relation_origins
        )
        if not relations:
            issues.append(
                MappingIssue(
                    source_code=_SOURCE_CODE,
                    row_number=row_number,
                    column="PD_PBCM",
                    code="SOURCE_VALUE_MISSING",
                    severity="limited",
                )
            )

        date_results: dict[str, tuple[str, object | None, str | None]] = {}
        for date_column in _DATE_SENTINELS:
            current_column = date_column
            date_results[date_column] = _date_result(
                date_column, row.get(date_column)
            )
        for cutoff_column in ("PD_STD_INFO_UPDATE", "CRD_GRD_DT"):
            cutoff_value = date_results[cutoff_column][1]
            if isinstance(cutoff_value, date) and cutoff_value > _CUTOFF_DATE:
                return _quarantined(
                    row_number,
                    cutoff_column,
                    "AFTER_CUTOFF_SOURCE_VALUE",
                    fatal=True,
                )
        credit_grade_date = date_results["CRD_GRD_DT"][1]
        for column in SPEC.expected_columns:
            if column in IGNORED_COLUMNS or column == "PD_PBCM":
                continue

            current_column = column
            _, value_kind, unit = _METRIC_SPECS[column]
            raw = row.get(column)
            if value_kind == "numeric":
                status, normalized, reason_code = _numeric_result(column, raw)
            elif value_kind == "date":
                status, normalized, reason_code = date_results[column]
            else:
                status, normalized, reason_code = _text_result(column, raw)

            if status not in {"present", "zero"}:
                issues.append(
                    MappingIssue(
                        source_code=_SOURCE_CODE,
                        row_number=row_number,
                        column=column,
                        code=reason_code or "SOURCE_VALUE_UNKNOWN",
                        severity="limited",
                    )
                )

            applicable_date = (
                normalized if value_kind == "date" else None
            )
            if column == "CRD_GRD" and isinstance(credit_grade_date, date):
                applicable_date = credit_grade_date
            currency = (
                primary_currency
                if column in _CURRENCY_FIELDS
                and isinstance(primary_currency, str)
                else None
            )
            definition, observation, evidence, origin = (
                _observation_and_evidence(
                    row_number=row_number,
                    record_key=record_key,
                    product_id=product_id,
                    column=column,
                    raw=raw,
                    status=status,
                    normalized=normalized,
                    reason_code=reason_code,
                    value_kind=value_kind,
                    unit=unit,
                    currency=currency,
                    applicable_date=applicable_date,
                )
            )
            records_by_table["observation.metric_definition"].append(definition)
            records_by_table["observation.observation_record"].append(observation)
            records_by_table["evidence.evidence_record"].append(evidence)
            records_by_table["evidence.evidence_observation_origin"].append(origin)
    except (TypeError, ValueError):
        return _quarantined(
            row_number,
            current_column,
            "INVALID_SOURCE_VALUE",
        )

    return MappedRow(
        row_number=row_number,
        disposition="limited" if issues else "accepted",
        records_by_table={
            table: tuple(table_records)
            for table, table_records in records_by_table.items()
        },
        issues=tuple(issues),
    )
