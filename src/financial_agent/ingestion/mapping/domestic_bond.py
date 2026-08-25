from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from financial_agent.contracts import encode_contract_value
from financial_agent.ingestion.identity import AuthoritativeIdentityIndex
from financial_agent.ingestion.models import MappedRow, MappingIssue, SourceSpec

from .common import (
    classify_value,
    make_record_hash,
    normalize_name,
    parse_decimal,
    parse_tristate,
    parse_yyyymmdd,
    stable_id,
)


_CUTOFF_DATE = date(2026, 8, 24)
_DEFINITION_APPROVED_AT = datetime(2026, 8, 24, tzinfo=UTC)
_SOURCE_CODE = "PRBD01N001"
_SOURCE_FILE = "prbd01n001_data.xlsx"
_SOURCE_ID = stable_id("source", _SOURCE_CODE, _SOURCE_FILE)
_MISSING_VALUES = frozenset({None, "", "NULL"})

_EXPECTED_COLUMNS = (
    "after_tax_yield",
    "applied_yield",
    "avg_annual_tax_yield",
    "bdbns_abl_chnl_nm",
    "bdbns_abl_chnl_tcd",
    "bd_inrt_tcd",
    "bd_intp_tcd",
    "bd_knd",
    "bd_ofr_tcd",
    "bd_tisu_a",
    "buyable_quantity",
    "buy_yield",
    "corp_after_tax_yield",
    "corp_pretax_yield",
    "cov",
    "crd_grd",
    "crd_grd_dt",
    "curr_cd",
    "depo_equiv_yield_154",
    "depo_equiv_yield_495",
    "dirty",
    "dur",
    "eval_price",
    "exg_close_price",
    "exg_close_price_base_dt",
    "exg_close_yield",
    "exrt_grte_ern_r",
    "exrt_grte_ern_r_tcd",
    "exrt_rpy_r",
    "info_base_dt",
    "info_seq",
    "isu_bal_amt",
    "isu_dt",
    "mat_dt",
    "ndy_applied_yield",
    "ndy_cov",
    "ndy_dirty",
    "ndy_dur",
    "ndy_eval_price",
    "pd_abrv_eng_nm",
    "pd_abrv_nm",
    "pd_ctry_cd",
    "pd_eng_nm",
    "pd_exg_mkt",
    "pd_nm",
    "pd_no",
    "pd_pbcm",
    "pd_pen_tr_yn",
    "pd_risk_gcd",
    "pd_risk_nm",
    "pd_std_info_update",
    "pref_tax_yield",
    "remaining_days",
    "sale_yield_base_dt",
    "srfc_irt",
    "std_pd_mcls_nm",
    "std_pd_scls_nm",
    "trade_price",
)

SPEC = SourceSpec(
    source_code=_SOURCE_CODE,
    table_id=_SOURCE_CODE,
    data_file_name=_SOURCE_FILE,
    data_sheet_name="data",
    schema_file_name="prbd01n001_schema.xlsx",
    schema_sheet_name="schema",
    expected_columns=_EXPECTED_COLUMNS,
    expected_row_count=21_882,
    natural_key=("pd_no", "pd_exg_mkt", "info_base_dt", "info_seq"),
    parser_version="1",
    mapping_version="2",
)

IGNORED_COLUMNS: Mapping[str, str] = {
    "buyable_quantity": "INVALID_BY_ORGANIZER_NOTICE",
}
HANDLED_COLUMNS = frozenset(_EXPECTED_COLUMNS) - frozenset(IGNORED_COLUMNS)

_METRIC_SPECS: Mapping[str, tuple[str, str, str | None]] = {
    "after_tax_yield": ("after_tax_yield", "numeric", "percentage_point"),
    "applied_yield": ("applied_yield", "numeric", "percentage_point"),
    "avg_annual_tax_yield": (
        "average_annual_after_tax_yield",
        "numeric",
        "percentage_point",
    ),
    "bdbns_abl_chnl_nm": ("tradable_channel_name", "text", None),
    "bdbns_abl_chnl_tcd": (
        "tradable_channel_code_raw",
        "text",
        "code",
    ),
    "bd_inrt_tcd": ("interest_rate_type", "text", None),
    "bd_intp_tcd": ("interest_payment_type", "text", None),
    "bd_knd": ("bond_kind", "text", None),
    "bd_ofr_tcd": ("offering_type", "text", None),
    "bd_tisu_a": (
        "total_issuance_amount",
        "numeric",
        "source_defined_amount",
    ),
    "buy_yield": ("buy_yield", "numeric", "percentage_point"),
    "corp_after_tax_yield": (
        "corporate_after_tax_yield",
        "numeric",
        "percentage_point",
    ),
    "corp_pretax_yield": (
        "corporate_pretax_yield",
        "numeric",
        "percentage_point",
    ),
    "cov": ("convexity", "numeric", "source_defined"),
    "crd_grd": ("credit_grade_representative", "text", None),
    "crd_grd_dt": ("credit_grade_as_of", "date", None),
    "curr_cd": ("currency", "text", None),
    "depo_equiv_yield_154": (
        "deposit_equivalent_yield_154",
        "numeric",
        "percentage_point",
    ),
    "depo_equiv_yield_495": (
        "deposit_equivalent_yield_495",
        "numeric",
        "percentage_point",
    ),
    "dirty": ("dirty_price", "numeric", "source_defined_price"),
    "dur": ("duration", "numeric", "source_defined"),
    "eval_price": (
        "evaluation_price",
        "numeric",
        "source_defined_price",
    ),
    "exg_close_price": (
        "exchange_close_price",
        "numeric",
        "source_defined_price",
    ),
    "exg_close_price_base_dt": ("exchange_close_as_of", "date", None),
    "exg_close_yield": (
        "exchange_close_yield",
        "numeric",
        "percentage_point",
    ),
    "exrt_grte_ern_r": (
        "maturity_guaranteed_yield",
        "numeric",
        "percentage_point",
    ),
    "exrt_grte_ern_r_tcd": (
        "maturity_guaranteed_yield_type_raw",
        "text",
        "code",
    ),
    "exrt_rpy_r": (
        "maturity_redemption_rate",
        "numeric",
        "percentage_point",
    ),
    "info_base_dt": ("information_as_of", "date", None),
    "isu_bal_amt": ("issue_balance", "numeric", "source_defined_amount"),
    "isu_dt": ("issue_date", "date", None),
    "mat_dt": ("maturity_date", "date", None),
    "ndy_applied_yield": (
        "next_day_applied_yield",
        "numeric",
        "percentage_point",
    ),
    "ndy_cov": ("next_day_convexity", "numeric", "source_defined"),
    "ndy_dirty": (
        "next_day_dirty_price",
        "numeric",
        "source_defined_price",
    ),
    "ndy_dur": ("next_day_duration", "numeric", "source_defined"),
    "ndy_eval_price": (
        "next_day_evaluation_price",
        "numeric",
        "source_defined_price",
    ),
    "pd_abrv_eng_nm": ("short_name_en", "text", None),
    "pd_abrv_nm": ("short_name_ko", "text", None),
    "pd_ctry_cd": ("country_code_raw", "text", "code"),
    "pd_eng_nm": ("name_en", "text", None),
    "pd_exg_mkt": ("exchange_market_type", "text", None),
    "pd_nm": ("name", "text", None),
    "pd_no": ("product_id", "text", None),
    "pd_pen_tr_yn": ("pension_eligible", "boolean", None),
    "pd_risk_gcd": ("risk_grade_code_raw", "text", "code"),
    "pd_risk_nm": ("risk_grade_name", "text", None),
    "pd_std_info_update": ("standard_info_updated_on", "date", None),
    "pref_tax_yield": (
        "preferential_tax_yield",
        "numeric",
        "percentage_point",
    ),
    "remaining_days": ("remaining_days", "numeric", "day"),
    "sale_yield_base_dt": ("sale_yield_as_of", "date", None),
    "srfc_irt": ("coupon_rate", "numeric", "percentage_point"),
    "std_pd_mcls_nm": ("product_major_class", "text", None),
    "std_pd_scls_nm": ("product_subclass", "text", None),
    "trade_price": ("trade_price", "numeric", "source_defined_price"),
}

_PRODUCT_STATIC_FIELDS = frozenset(
    {
        "bd_inrt_tcd",
        "bd_intp_tcd",
        "bd_knd",
        "bd_ofr_tcd",
        "bd_tisu_a",
        "curr_cd",
        "exrt_grte_ern_r",
        "exrt_grte_ern_r_tcd",
        "exrt_rpy_r",
        "isu_dt",
        "mat_dt",
        "pd_abrv_eng_nm",
        "pd_abrv_nm",
        "pd_ctry_cd",
        "pd_eng_nm",
        "pd_nm",
        "pd_no",
        "pd_pbcm",
        "srfc_irt",
        "std_pd_mcls_nm",
        "std_pd_scls_nm",
    }
)
_DATE_FIELDS = (
    "crd_grd_dt",
    "exg_close_price_base_dt",
    "info_base_dt",
    "isu_dt",
    "mat_dt",
    "pd_std_info_update",
    "sale_yield_base_dt",
)
_DATE_SENTINELS: Mapping[str, frozenset[str]] = {
    column: frozenset({"0", "00000000"}) for column in _DATE_FIELDS
}
_DATE_SENTINELS = {
    **_DATE_SENTINELS,
    "mat_dt": frozenset({"0", "00000000", "99991231"}),
}
_CUTOFF_DATE_FIELDS = (
    "info_base_dt",
    "sale_yield_base_dt",
    "exg_close_price_base_dt",
    "pd_std_info_update",
    "crd_grd_dt",
)
_SALE_DATE_FIELDS = frozenset(
    {
        "after_tax_yield",
        "avg_annual_tax_yield",
        "bdbns_abl_chnl_nm",
        "bdbns_abl_chnl_tcd",
        "buy_yield",
        "corp_after_tax_yield",
        "corp_pretax_yield",
        "depo_equiv_yield_154",
        "depo_equiv_yield_495",
        "pref_tax_yield",
        "trade_price",
    }
)
_STANDARD_INFO_DATE_FIELDS = frozenset(
    {"applied_yield", "cov", "dirty", "dur", "eval_price", "isu_bal_amt"}
)
_EXCHANGE_CLOSE_FIELDS = frozenset({"exg_close_price", "exg_close_yield"})
_CURRENCY_FIELDS = frozenset(
    {
        "bd_tisu_a",
        "dirty",
        "eval_price",
        "exg_close_price",
        "isu_bal_amt",
        "ndy_dirty",
        "ndy_eval_price",
        "trade_price",
    }
)
_ALIAS_FIELDS = ("pd_abrv_nm", "pd_eng_nm", "pd_abrv_eng_nm")
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


@dataclass(frozen=True, slots=True)
class DomesticBondAnalysis:
    static_conflicts: frozenset[tuple[str, str]]

    def conflicts(self, product_key: str, column: str) -> bool:
        return (product_key, column) in self.static_conflicts


def _tag(value: object) -> Mapping[str, object]:
    return encode_contract_value(value).model_dump(mode="json")  # type: ignore[arg-type]


def _source_value_for_contract(value: object) -> object:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("source numeric value must be finite")
        return Decimal(str(value))
    return value


def _source_signature(value: object) -> str:
    return json.dumps(
        _tag(_source_value_for_contract(value)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _required_token(value: object) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    normalized = normalize_name(str(value))
    return "" if normalized.upper() == "NULL" else normalized


def analyze_bond_rows(
    rows: Iterable[Mapping[str, object]],
) -> DomesticBondAnalysis:
    values: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        product_key = _required_token(row.get("pd_no"))
        if not product_key:
            continue
        for column in _PRODUCT_STATIC_FIELDS:
            values[(product_key, column)].add(
                _source_signature(row.get(column))
            )
    return DomesticBondAnalysis(
        static_conflicts=frozenset(
            key for key, signatures in values.items() if len(signatures) > 1
        )
    )


def _with_record_hash(payload: Mapping[str, object]) -> dict[str, object]:
    record = dict(payload)
    record["record_hash"] = make_record_hash(payload)
    return record


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
    if status == "present" and column == "curr_cd" and normalized == "000":
        return "unknown", None, "UNDEFINED_CURRENCY_CODE"
    return status, normalized, reason


def _numeric_result(raw: object) -> tuple[str, object | None, str | None]:
    status, normalized, reason = classify_value(
        raw,
        missing_values=_MISSING_VALUES,
        placeholder_values=frozenset(),
        zero_is_value=True,
    )
    if status in {"present", "zero"}:
        normalized = _source_value_for_contract(normalized)
        normalized = parse_decimal(normalized)
    return status, normalized, reason


def _boolean_result(raw: object) -> tuple[str, object | None, str | None]:
    status, _, reason = classify_value(
        raw,
        missing_values=_MISSING_VALUES,
        placeholder_values=frozenset(),
        zero_is_value=False,
    )
    if status != "present":
        return status, None, reason
    parsed = parse_tristate(
        raw,
        true_values=frozenset({"Y"}),
        false_values=frozenset({"N"}),
    )
    if parsed is None:
        return "unknown", None, "SOURCE_BOOLEAN_UNRECOGNIZED"
    return "present", parsed, None


def _date_result(
    column: str,
    raw: object,
) -> tuple[str, object | None, str | None]:
    sentinels = _DATE_SENTINELS[column]
    status, _, reason = classify_value(
        raw,
        missing_values=_MISSING_VALUES,
        placeholder_values=sentinels,
        zero_is_value=False,
    )
    if status != "present":
        return status, None, reason
    return (
        "present",
        parse_yyyymmdd(raw, sentinels=sentinels),
        None,
    )


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


def _metric_definition(
    column: str,
    metric_id: str,
    value_kind: str,
    unit: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "2",
        "semantic_family": "organizer_domestic_bond",
        "value_kind": value_kind,
        "default_unit": unit,
        "description": f"Organizer PRBD01N001 field {column}",
        "approved_at": _DEFINITION_APPROVED_AT,
    }
    payload["definition_hash"] = make_record_hash(payload)
    return payload


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


def _source_record_key(
    row_number: int,
    row: Mapping[str, object],
) -> tuple[str, Mapping[str, str]] | MappedRow:
    components: dict[str, str] = {}
    for column in SPEC.natural_key:
        token = _required_token(row.get(column))
        if not token:
            return _quarantined(row_number, column, "MISSING_NATURAL_KEY")
        components[column] = token
    return (
        json.dumps(
            components,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        components,
    )


def _applicable_date(
    column: str,
    normalized: object | None,
    date_values: Mapping[str, date | None],
) -> date | None:
    if column in _DATE_FIELDS:
        return normalized if isinstance(normalized, date) else None
    if column in _SALE_DATE_FIELDS:
        return date_values["sale_yield_base_dt"] or date_values["info_base_dt"]
    if column in _STANDARD_INFO_DATE_FIELDS:
        return date_values["pd_std_info_update"] or date_values["info_base_dt"]
    if column in _EXCHANGE_CLOSE_FIELDS:
        return date_values["exg_close_price_base_dt"]
    if column == "crd_grd":
        return date_values["crd_grd_dt"]
    if column in _PRODUCT_STATIC_FIELDS:
        return None
    return date_values["info_base_dt"]


def _observation_and_evidence(
    *,
    row_number: int,
    locator_record_key: str,
    observation_key: str,
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
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    metric_suffix, _, _ = _METRIC_SPECS[column]
    metric_id = f"organizer.prbd01n001.{metric_suffix}"
    observation_id = stable_id(
        "observation", _SOURCE_CODE, f"{observation_key}:{column}"
    )
    evidence_id = stable_id(
        "evidence", _SOURCE_CODE, f"{locator_record_key}:{column}"
    )
    observation = _with_record_hash(
        {
            "observation_id": observation_id,
            "entity_id": product_id,
            "relation_id": None,
            "metric_id": metric_id,
            "metric_definition_version": "2",
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
    )
    evidence_value = normalized if status in {"present", "zero"} else None
    evidence = _with_record_hash(
        {
            "evidence_id": evidence_id,
            "evidence_kind": "observation",
            "source_id": _SOURCE_ID,
            "subject_id": product_id,
            "predicate_id": metric_id,
            "value_or_object_id": _tag(evidence_value),
            "normalized_value": _tag(evidence_value),
            "unit": unit,
            "currency": currency,
            "applicable_date": (
                applicable_date
                if applicable_date is None or applicable_date <= _CUTOFF_DATE
                else None
            ),
            "valid_from": None,
            "valid_to": None,
            "published_at": None,
            "available_at": None,
            "vintage_date": _CUTOFF_DATE,
            "locator_type": "tabular",
            "locator_uri_or_object_key": SPEC.data_file_name,
            "locator_record_key": locator_record_key,
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
    )
    return (
        _metric_definition(column, metric_id, value_kind, unit),
        observation,
        evidence,
        {"evidence_id": evidence_id, "observation_id": observation_id},
    )


def _issuer_records(
    *,
    row_number: int,
    locator_record_key: str,
    product_key: str,
    product_id: str,
    raw: object,
) -> tuple[
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
]:
    status, normalized, _ = _text_result("pd_pbcm", raw)
    if status != "present" or not isinstance(normalized, str):
        return (), (), (), (), ()
    issuer_id = stable_id("institution", _SOURCE_CODE, normalized)
    relation_id = stable_id(
        "relation", _SOURCE_CODE, f"{product_key}:issuedBy:{issuer_id}"
    )
    evidence_id = stable_id(
        "evidence", _SOURCE_CODE, f"{locator_record_key}:pd_pbcm"
    )
    return (
        (
            _with_record_hash(
                {
                    "entity_id": issuer_id,
                    "entity_type": "institution",
                    "canonical_name": normalized,
                    "normalized_name": normalized,
                }
            ),
        ),
        ({"entity_id": issuer_id, "institution_kind": "issuer"},),
        (
            _with_record_hash(
                {
                    "relation_id": relation_id,
                    "subject_id": product_id,
                    "predicate_id": "issuedBy",
                    "object_id": issuer_id,
                    "valid_from": None,
                    "valid_to": None,
                }
            ),
        ),
        (
            _with_record_hash(
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
                    "locator_record_key": locator_record_key,
                    "locator_sheet": SPEC.data_sheet_name,
                    "locator_row": row_number,
                    "locator_column": "pd_pbcm",
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
            ),
        ),
        ({"evidence_id": evidence_id, "relation_id": relation_id},),
    )


def map_row(
    row_number: int,
    row: Mapping[str, object],
    *,
    analysis: DomesticBondAnalysis,
    identity_index: AuthoritativeIdentityIndex,
) -> MappedRow:
    source_key_result = _source_record_key(row_number, row)
    if isinstance(source_key_result, MappedRow):
        return source_key_result
    locator_record_key, key_components = source_key_result
    product_key = key_components["pd_no"]

    resolution = identity_index.resolve("PRBD_PD_NO", product_key)
    if resolution.status != "MATCHED" or resolution.canonical_identity is None:
        return _quarantined(
            row_number,
            "pd_no",
            "IDENTITY_RESOLUTION_FAILED",
            fatal=True,
        )
    product_id = resolution.canonical_identity.entity_id

    name_conflict = analysis.conflicts(product_key, "pd_nm")
    raw_name = row.get("pd_nm")
    canonical_name = (
        normalize_name(raw_name) if isinstance(raw_name, str) else ""
    )
    if name_conflict:
        canonical_name = product_key
    elif not canonical_name or canonical_name.upper() == "NULL":
        return _quarantined(row_number, "pd_nm", "MISSING_REQUIRED_NAME")

    records_by_table = _empty_records()
    issues: list[MappingIssue] = []
    current_column = "info_base_dt"

    try:
        date_results = {
            column: _date_result(column, row.get(column))
            for column in _DATE_FIELDS
        }
        date_values: dict[str, date | None] = {
            column: result[1] if isinstance(result[1], date) else None
            for column, result in date_results.items()
        }
        for column in _CUTOFF_DATE_FIELDS:
            if date_values[column] is not None and date_values[column] > _CUTOFF_DATE:
                return _quarantined(
                    row_number,
                    column,
                    "AFTER_CUTOFF_SOURCE_VALUE",
                    fatal=True,
                )

        currency_conflict = analysis.conflicts(product_key, "curr_cd")
        currency_status, primary_currency, _ = _text_result(
            "curr_cd", row.get("curr_cd")
        )
        if currency_conflict or currency_status != "present":
            primary_currency = None

        records_by_table["catalog.entity"].append(
            _with_record_hash(
                {
                    "entity_id": product_id,
                    "entity_type": "product",
                    "canonical_name": canonical_name,
                    "normalized_name": canonical_name,
                }
            )
        )
        records_by_table["catalog.product"].append(
            {
                "entity_id": product_id,
                "product_family": "domestic_bond",
                "primary_currency": primary_currency,
            }
        )
        records_by_table["catalog.identifier"].append(
            _with_record_hash(
                {
                    "identifier_id": stable_id(
                        "identifier",
                        _SOURCE_CODE,
                        f"PRBD_PD_NO:{product_key}",
                    ),
                    "entity_id": product_id,
                    "scheme": "PRBD_PD_NO",
                    "identifier_value": product_key,
                    "is_primary": True,
                    "valid_from": None,
                    "valid_to": None,
                }
            )
        )

        for column in _ALIAS_FIELDS:
            if analysis.conflicts(product_key, column):
                continue
            status, normalized, _ = _text_result(column, row.get(column))
            if status == "present" and isinstance(normalized, str):
                records_by_table["catalog.alias"].append(
                    _with_record_hash(
                        {
                            "alias_id": stable_id(
                                "alias",
                                _SOURCE_CODE,
                                f"{product_key}:{column}:{normalized}",
                            ),
                            "entity_id": product_id,
                            "alias_text": normalized,
                            "normalized_alias_text": normalized,
                            "valid_from": None,
                            "valid_to": None,
                        }
                    )
                )

        if analysis.conflicts(product_key, "pd_pbcm"):
            issues.append(
                MappingIssue(
                    source_code=_SOURCE_CODE,
                    row_number=row_number,
                    column="pd_pbcm",
                    code="SOURCE_STATIC_VALUE_CONFLICT",
                    severity="limited",
                )
            )
        else:
            (
                issuer_entities,
                institutions,
                relations,
                relation_evidence,
                relation_origins,
            ) = _issuer_records(
                row_number=row_number,
                locator_record_key=locator_record_key,
                product_key=product_key,
                product_id=product_id,
                raw=row.get("pd_pbcm"),
            )
            records_by_table["catalog.entity"].extend(issuer_entities)
            records_by_table["catalog.institution"].extend(institutions)
            records_by_table["relation.relation_record"].extend(relations)
            records_by_table["evidence.evidence_record"].extend(
                relation_evidence
            )
            records_by_table["evidence.evidence_relation_origin"].extend(
                relation_origins
            )
            if not relations:
                issues.append(
                    MappingIssue(
                        source_code=_SOURCE_CODE,
                        row_number=row_number,
                        column="pd_pbcm",
                        code="SOURCE_VALUE_MISSING",
                        severity="limited",
                    )
                )

        for column in SPEC.expected_columns:
            if column not in _METRIC_SPECS:
                continue
            current_column = column
            metric_suffix, value_kind, unit = _METRIC_SPECS[column]
            del metric_suffix
            raw = row.get(column)
            if value_kind == "numeric":
                status, normalized, reason_code = _numeric_result(raw)
            elif value_kind == "date":
                status, normalized, reason_code = date_results[column]
            elif value_kind == "boolean":
                status, normalized, reason_code = _boolean_result(raw)
            else:
                status, normalized, reason_code = _text_result(column, raw)

            static_conflict = analysis.conflicts(product_key, column)
            if static_conflict:
                status = "unknown"
                normalized = None
                reason_code = "SOURCE_STATIC_VALUE_CONFLICT"

            applicable_date = _applicable_date(
                column,
                normalized,
                date_values,
            )
            if static_conflict:
                applicable_date = None
            if (
                column in _EXCHANGE_CLOSE_FIELDS
                and status in {"present", "zero"}
                and applicable_date is None
            ):
                status = "unknown"
                normalized = None
                reason_code = "SOURCE_APPLICABLE_DATE_MISSING"

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

            observation_key = (
                product_key
                if column in _PRODUCT_STATIC_FIELDS
                else locator_record_key
            )
            currency = (
                primary_currency
                if column in _CURRENCY_FIELDS
                and isinstance(primary_currency, str)
                else None
            )
            definition, observation, evidence, origin = (
                _observation_and_evidence(
                    row_number=row_number,
                    locator_record_key=locator_record_key,
                    observation_key=observation_key,
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
            records_by_table["observation.metric_definition"].append(
                definition
            )
            records_by_table["observation.observation_record"].append(
                observation
            )
            records_by_table["evidence.evidence_record"].append(evidence)
            records_by_table["evidence.evidence_observation_origin"].append(
                origin
            )
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
