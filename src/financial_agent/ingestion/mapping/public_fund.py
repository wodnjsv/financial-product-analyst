from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from financial_agent.contracts import encode_contract_value
from financial_agent.ingestion.models import MappedRow, MappingIssue, SourceSpec

from .common import (
    classify_value,
    make_record_hash,
    normalize_name,
    parse_decimal,
    stable_id,
)


_CUTOFF_DATE = date(2026, 8, 24)
_DEFINITION_APPROVED_AT = datetime(2026, 8, 24, tzinfo=UTC)
_SOURCE_CODE = "PRFD01N001"
_SOURCE_FILE = "prfd01n001_data.xlsx"
_SOURCE_ID = stable_id("source", _SOURCE_CODE, _SOURCE_FILE)
_MISSING_VALUES = frozenset({None, "", "NULL"})
_REPRESENTATIVE_SENTINELS = frozenset({"KR0000000000", "000000000000"})
_IDENTIFIER_SENTINELS: Mapping[str, frozenset[str]] = {
    "fss_itm_no": frozenset({"000000000000"}),
    "ksd_itm_no": frozenset({"KR0000000000", "000000000000"}),
    "std_itm_no": frozenset(),
    "mtco_itm_no": frozenset(),
}
_OPTIONAL_IDENTIFIER_COLUMNS = (
    "fss_itm_no",
    "ksd_itm_no",
    "mtco_itm_no",
    "std_itm_no",
)

_EXPECTED_COLUMNS = (
    "bmrk_eng_nm",
    "bmrk_nm",
    "bns_bpr",
    "curr_cd",
    "exchdg_yn",
    "fd_daily_bas_dt",
    "fd_estb_ctry_cd",
    "fd_ivst_rgn_desc",
    "fd_last_dstb_actg_bss_dt",
    "fd_last_dstb_actg_eot_dt",
    "fd_last_dstb_r",
    "fd_mm18_ern_r",
    "fd_mm1_ern_r",
    "fd_mm3_ern_r",
    "fd_mm6_ern_r",
    "fd_nast_suma",
    "fd_price_bas_dt",
    "fd_prsv_r",
    "fd_sbpr",
    "fd_set_pcd",
    "fd_wk1_ern_r",
    "fd_yr1_ern_r",
    "fd_yr2_ern_r",
    "fd_yr3_ern_r",
    "fd_yr5_ern_r",
    "frc_bpr_itm_yn",
    "fss_itm_no",
    "han_clas_fee_type",
    "han_clas_nm",
    "han_clas_policies",
    "han_clas_sales_channel",
    "hdge_fd_yn",
    "int_dvd_desc",
    "itm_abrv_nm",
    "itm_eabrv_nm",
    "itm_eng_nm",
    "itm_nm",
    "itm_no",
    "kofia_fd_ccd",
    "ksd_itm_no",
    "mtco_itm_no",
    "ofsfd_yn",
    "ofwk_trus_rwrd_r",
    "or_attr_desc",
    "or_co_rwrd_r",
    "or_co_xtn_itt_cd",
    "ovrs_fd_desc",
    "pers_corp_desc",
    "pfiv_sale_cntl_tcd",
    "prfd_attr_cds",
    "prfd_attr_cnt",
    "prfd_attr_search_text",
    "prvo_fd_desc",
    "prvo_pbff_desc",
    "rptt_ksd_itm_no",
    "sale_co_rwrd_r",
    "sale_yn",
    "std_itm_no",
    "thco_sale_yn",
    "trusc_rwrd_r",
    "trusc_xtn_itt_cd",
    "zrin_attr_nms",
    "zrin_btyp_cd",
    "zrin_btyp_nm",
    "zrin_dmst_bd_cmst_rt",
    "zrin_dmst_stk_cmst_rt",
    "zrin_etc_ast_cmst_rt",
    "zrin_fd_cmst_rt",
    "zrin_fd_ivst_risk_gcd",
    "zrin_fd_ivst_risk_grd_nm",
    "zrin_liqt_cmst_rt",
    "zrin_ovrs_bd_cmst_rt",
    "zrin_ovrs_stk_cmst_rt",
    "zrin_pcd",
    "zrin_ptn_nm",
)

SPEC = SourceSpec(
    source_code=_SOURCE_CODE,
    table_id=_SOURCE_CODE,
    data_file_name=_SOURCE_FILE,
    data_sheet_name="data",
    schema_file_name="prfd01n001_schema.xlsx",
    schema_sheet_name="schema",
    expected_columns=_EXPECTED_COLUMNS,
    expected_row_count=23_676,
    natural_key=("itm_no",),
    parser_version="1",
    mapping_version="2",
)

IGNORED_COLUMNS: Mapping[str, str] = {}
HANDLED_COLUMNS = frozenset(_EXPECTED_COLUMNS)

_RETURN_FIELDS = frozenset(
    {
        "fd_wk1_ern_r",
        "fd_mm1_ern_r",
        "fd_mm3_ern_r",
        "fd_mm6_ern_r",
        "fd_mm18_ern_r",
        "fd_yr1_ern_r",
        "fd_yr2_ern_r",
        "fd_yr3_ern_r",
        "fd_yr5_ern_r",
    }
)
_METRIC_SPECS: Mapping[str, tuple[str, str, str | None]] = {
    "bmrk_eng_nm": ("benchmark_english_raw", "text", None),
    "bmrk_nm": ("benchmark_raw", "text", None),
    "curr_cd": ("currency", "text", None),
    "exchdg_yn": ("currency_hedged", "boolean", None),
    "fd_estb_ctry_cd": ("establishment_country_code_raw", "text", "code"),
    "fd_ivst_rgn_desc": ("investment_region", "text", None),
    "fd_mm18_ern_r": ("cumulative_return_18m", "numeric", "percentage_point"),
    "fd_mm1_ern_r": ("cumulative_return_1m", "numeric", "percentage_point"),
    "fd_mm3_ern_r": ("cumulative_return_3m", "numeric", "percentage_point"),
    "fd_mm6_ern_r": ("cumulative_return_6m", "numeric", "percentage_point"),
    "fd_nast_suma": ("net_assets", "numeric", "source_defined_amount"),
    "fd_set_pcd": ("establishment_type_code_raw", "text", "code"),
    "fd_wk1_ern_r": ("cumulative_return_1w", "numeric", "percentage_point"),
    "fd_yr1_ern_r": ("cumulative_return_1y", "numeric", "percentage_point"),
    "fd_yr2_ern_r": ("cumulative_return_2y", "numeric", "percentage_point"),
    "fd_yr3_ern_r": ("cumulative_return_3y", "numeric", "percentage_point"),
    "fd_yr5_ern_r": ("cumulative_return_5y", "numeric", "percentage_point"),
    "frc_bpr_itm_yn": ("foreign_currency_base_price", "boolean", None),
    "fss_itm_no": ("fss_product_id", "text", None),
    "hdge_fd_yn": ("is_hedge_fund", "boolean", None),
    "int_dvd_desc": ("interest_dividend_class", "text", None),
    "itm_abrv_nm": ("short_name_ko", "text", None),
    "itm_eabrv_nm": ("short_name_en", "text", None),
    "itm_eng_nm": ("name_en_raw", "text", None),
    "itm_nm": ("name", "text", None),
    "itm_no": ("product_id", "text", None),
    "kofia_fd_ccd": ("kofia_classification_code_raw", "text", "code"),
    "ksd_itm_no": ("ksd_product_id", "text", None),
    "mtco_itm_no": ("manager_product_id", "text", None),
    "ofsfd_yn": ("is_offshore_fund", "boolean", None),
    "or_attr_desc": ("management_attribute", "text", None),
    "ovrs_fd_desc": ("overseas_fund_class", "text", None),
    "pers_corp_desc": ("investor_type", "text", None),
    "pfiv_sale_cntl_tcd": (
        "professional_sale_control_code_raw",
        "text",
        "code",
    ),
    "prfd_attr_cd": ("attribute_row_code", "text", "code"),
    "prvo_fd_desc": ("private_fund_detail", "text", None),
    "prvo_pbff_desc": ("public_private_class", "text", None),
    "sale_yn": ("sale_status", "text", None),
    "std_itm_no": ("standard_product_id", "text", None),
    "thco_sale_yn": ("sold_by_provider", "boolean", None),
    "trusc_xtn_itt_cd": ("trustee_institution_code_raw", "text", "code"),
    "zrin_fd_ivst_risk_gcd": ("risk_grade_code", "text", "code"),
    "zrin_fd_ivst_risk_grd_nm": ("risk_grade_name", "text", None),
}
_BOOLEAN_VALUES: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {
    "exchdg_yn": (frozenset({"Y"}), frozenset({"N"})),
    "frc_bpr_itm_yn": (frozenset({"1"}), frozenset({"0"})),
    "hdge_fd_yn": (frozenset({"1"}), frozenset({"0"})),
    "ofsfd_yn": (frozenset({"1"}), frozenset({"0"})),
    "thco_sale_yn": (frozenset({"Y"}), frozenset()),
}
_RELATION_FIELDS = frozenset({"or_co_xtn_itt_cd", "rptt_ksd_itm_no"})
_FATAL_CONFLICT_COLUMNS = frozenset(
    {
        "curr_cd",
        "fss_itm_no",
        "itm_abrv_nm",
        "itm_eabrv_nm",
        "itm_eng_nm",
        "itm_nm",
        "ksd_itm_no",
        "mtco_itm_no",
        "or_co_xtn_itt_cd",
        "rptt_ksd_itm_no",
        "std_itm_no",
    }
)
_TABLES = (
    "catalog.entity",
    "catalog.product",
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


@dataclass(frozen=True)
class PublicFundRepeatAnalysis:
    canonical_record_keys: Mapping[str, str]
    conflicting_columns: Mapping[str, frozenset[str]]
    duplicate_identifier_values: Mapping[str, frozenset[str]]


def _normalized_token(value: object) -> str:
    if value is None:
        return ""
    return normalize_name(str(value))


def _raw_record_key(row: Mapping[str, object]) -> str | None:
    item = _normalized_token(row.get("itm_no"))
    attribute = _normalized_token(row.get("prfd_attr_cd"))
    risk = _normalized_token(row.get("zrin_fd_ivst_risk_gcd"))
    if not item or item == "NULL" or not attribute or attribute == "NULL":
        return None
    if not risk:
        return None
    return f"{item}|{attribute}|{risk}"


def _comparison_value(value: object) -> object:
    if isinstance(value, str):
        return normalize_name(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _identifier_count_key(
    column: str,
    row: Mapping[str, object],
) -> str | None:
    value = _normalized_token(row.get(column))
    if not value or value == "NULL" or value in _IDENTIFIER_SENTINELS[column]:
        return None
    if column == "mtco_itm_no":
        manager = _normalized_token(row.get("or_co_xtn_itt_cd"))
        if not manager or manager == "NULL":
            return None
        return f"{manager}|{value}"
    return value


def analyze_repeated_fund_rows(
    rows: Iterable[Mapping[str, object]],
) -> PublicFundRepeatAnalysis:
    canonical_record_keys: dict[str, str] = {}
    first_values: dict[str, dict[str, object]] = {}
    conflicts: dict[str, set[str]] = defaultdict(set)
    identifier_owners: dict[str, dict[str, set[str]]] = {
        column: defaultdict(set) for column in _OPTIONAL_IDENTIFIER_COLUMNS
    }

    for row in rows:
        item = _normalized_token(row.get("itm_no"))
        record_key = _raw_record_key(row)
        if not item or item == "NULL" or record_key is None:
            continue
        canonical_record_keys.setdefault(item, record_key)
        if item not in first_values:
            first_values[item] = {
                column: _comparison_value(row.get(column))
                for column in SPEC.expected_columns
                if column != "prfd_attr_cd"
            }
        else:
            for column, first_value in first_values[item].items():
                if _comparison_value(row.get(column)) != first_value:
                    conflicts[item].add(column)
        for column in _OPTIONAL_IDENTIFIER_COLUMNS:
            identifier_key = _identifier_count_key(column, row)
            if identifier_key is not None:
                identifier_owners[column][identifier_key].add(item)

    duplicate_identifier_values = {
        column: frozenset(
            value for value, owners in values.items() if len(owners) > 1
        )
        for column, values in identifier_owners.items()
    }
    return PublicFundRepeatAnalysis(
        canonical_record_keys=canonical_record_keys,
        conflicting_columns={
            item: frozenset(columns) for item, columns in conflicts.items()
        },
        duplicate_identifier_values=duplicate_identifier_values,
    )


def _tag(value: object) -> Mapping[str, object]:
    return encode_contract_value(value).model_dump(mode="json")


def _with_record_hash(payload: Mapping[str, object]) -> dict[str, object]:
    record = dict(payload)
    record["record_hash"] = make_record_hash(payload)
    return record


def _raw_value_repr(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


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


def _metric_definition(
    column: str,
    metric_id: str,
    value_kind: str,
    unit: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "1",
        "semantic_family": "organizer_public_fund",
        "value_kind": value_kind,
        "default_unit": unit,
        "description": f"Organizer PRFD01N001 field {column}",
        "approved_at": _DEFINITION_APPROVED_AT,
    }
    payload["definition_hash"] = make_record_hash(payload)
    return payload


def _text_result(
    column: str,
    raw: object,
) -> tuple[str, object | None, str | None]:
    text = raw if isinstance(raw, str) or raw is None else str(raw)
    placeholders = _IDENTIFIER_SENTINELS.get(column, frozenset())
    if column == "kofia_fd_ccd":
        placeholders = frozenset({"00000000000000000000"})
    status, normalized, reason = classify_value(
        text,
        missing_values=_MISSING_VALUES,
        placeholder_values=placeholders,
        zero_is_value=True,
    )
    if status != "present":
        return status, normalized, reason
    assert isinstance(normalized, str)
    if column == "bmrk_eng_nm" and normalized.isdecimal():
        return "unknown", None, "NON_NAME_BENCHMARK_VALUE"
    if column == "itm_eng_nm" and (
        normalized.isdecimal() or normalized == "0" or len(normalized) > 240
    ):
        return "unknown", None, "NON_NAME_SOURCE_VALUE"
    if column == "fd_estb_ctry_cd" and normalized == "000":
        return "unknown", None, "UNDEFINED_SOURCE_CODE"
    if column == "or_attr_desc" and normalized == "06":
        return "unknown", None, "UNKNOWN_CODE_06"
    if column == "sale_yn" and normalized not in {"판매중", "판매완료"}:
        return "unknown", None, "UNDEFINED_SALE_STATUS"
    if column == "zrin_fd_ivst_risk_gcd" and normalized not in {
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
    }:
        return "unknown", None, "UNDEFINED_RISK_GRADE"
    if column == "curr_cd" and normalized == "000":
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
        zero_is_value=True,
    )
    if status in {"present", "zero"}:
        normalized = parse_decimal(normalized)
        if normalized == 0:
            status = "zero"
    if (
        column in _RETURN_FIELDS
        and isinstance(normalized, Decimal)
        and (normalized < Decimal("-100") or normalized > Decimal("1000"))
    ):
        return "unknown", None, "RETURN_OUTLIER"
    return status, normalized, reason


def _boolean_result(
    column: str,
    raw: object,
) -> tuple[str, object | None, str | None]:
    status, normalized, reason = _text_result(column, raw)
    if status != "present" or not isinstance(normalized, str):
        return status, normalized, reason
    true_values, false_values = _BOOLEAN_VALUES[column]
    if normalized in true_values:
        return "present", True, None
    if normalized in false_values:
        return "present", False, None
    return "unknown", None, "UNDEFINED_BOOLEAN_CODE"


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


def _evidence_record(
    *,
    row_number: int,
    locator_record_key: str,
    evidence_seed: str,
    subject_id: str,
    predicate_id: str,
    column: str,
    raw: object,
    normalized: object | None,
    status: str,
    evidence_kind: str,
    unit: str | None,
    currency: str | None,
) -> dict[str, object]:
    evidence_value = normalized if status in {"present", "zero"} else None
    source_value = evidence_value if evidence_kind == "relation" else raw
    if status not in {"present", "zero"}:
        source_value = None
    payload: dict[str, object] = {
        "evidence_id": stable_id("evidence", _SOURCE_CODE, evidence_seed),
        "evidence_kind": evidence_kind,
        "source_id": _SOURCE_ID,
        "subject_id": subject_id,
        "predicate_id": predicate_id,
        "value_or_object_id": _tag(source_value),
        "normalized_value": _tag(evidence_value),
        "unit": unit,
        "currency": currency,
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
    return _with_record_hash(payload)


def _observation_records(
    *,
    row_number: int,
    locator_record_key: str,
    observation_seed: str,
    evidence_seed: str,
    product_id: str,
    column: str,
    raw: object,
    status: str,
    normalized: object | None,
    reason_code: str | None,
    value_kind: str,
    unit: str | None,
    currency: str | None,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    metric_suffix, _, _ = _METRIC_SPECS[column]
    metric_id = f"organizer.prfd01n001.{metric_suffix}"
    observation_id = stable_id("observation", _SOURCE_CODE, observation_seed)
    observation = _with_record_hash(
        {
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
            "applicable_date": None,
            "published_at": None,
            "available_at": None,
            "vintage_date": _CUTOFF_DATE,
            "reason_code": reason_code,
        }
    )
    evidence = _evidence_record(
        row_number=row_number,
        locator_record_key=locator_record_key,
        evidence_seed=evidence_seed,
        subject_id=product_id,
        predicate_id=metric_id,
        column=column,
        raw=raw,
        normalized=normalized,
        status=status,
        evidence_kind="observation",
        unit=unit,
        currency=currency,
    )
    definition = _metric_definition(column, metric_id, value_kind, unit)
    origin = {
        "evidence_id": evidence["evidence_id"],
        "observation_id": observation_id,
    }
    return definition, observation, evidence, origin


def _relation_records(
    *,
    row_number: int,
    locator_record_key: str,
    evidence_seed: str,
    relation_seed: str,
    subject_id: str,
    predicate_id: str,
    object_id: str,
    column: str,
    raw: object,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    relation_id = stable_id("relation", _SOURCE_CODE, relation_seed)
    relation = _with_record_hash(
        {
            "relation_id": relation_id,
            "subject_id": subject_id,
            "predicate_id": predicate_id,
            "object_id": object_id,
            "valid_from": None,
            "valid_to": None,
        }
    )
    evidence = _evidence_record(
        row_number=row_number,
        locator_record_key=locator_record_key,
        evidence_seed=evidence_seed,
        subject_id=subject_id,
        predicate_id=predicate_id,
        column=column,
        raw=raw,
        normalized=object_id,
        status="present",
        evidence_kind="relation",
        unit=None,
        currency=None,
    )
    origin = {"evidence_id": evidence["evidence_id"], "relation_id": relation_id}
    return relation, evidence, origin


def _append_issue(
    issues: list[MappingIssue],
    *,
    row_number: int,
    column: str,
    code: str | None,
) -> None:
    issues.append(
        MappingIssue(
            source_code=_SOURCE_CODE,
            row_number=row_number,
            column=column,
            code=code or "SOURCE_VALUE_UNKNOWN",
            severity="limited",
        )
    )


def _append_identifier(
    records_by_table: dict[str, list[Mapping[str, object]]],
    *,
    product_id: str,
    scheme: str,
    value: str,
    primary: bool,
) -> None:
    records_by_table["catalog.identifier"].append(
        _with_record_hash(
            {
                "identifier_id": stable_id(
                    "identifier", _SOURCE_CODE, f"{scheme}:{value}"
                ),
                "entity_id": product_id,
                "scheme": scheme,
                "identifier_value": value,
                "is_primary": primary,
                "valid_from": None,
                "valid_to": None,
            }
        )
    )


def _append_alias(
    records_by_table: dict[str, list[Mapping[str, object]]],
    *,
    product_id: str,
    item: str,
    column: str,
    value: str,
) -> None:
    records_by_table["catalog.alias"].append(
        _with_record_hash(
            {
                "alias_id": stable_id(
                    "alias", _SOURCE_CODE, f"{item}:{column}:{value}"
                ),
                "entity_id": product_id,
                "alias_text": value,
                "normalized_alias_text": value,
                "valid_from": None,
                "valid_to": None,
            }
        )
    )


def map_row(
    row_number: int,
    row: Mapping[str, object],
    *,
    repeat_analysis: PublicFundRepeatAnalysis,
) -> MappedRow:
    item = _normalized_token(row.get("itm_no"))
    if not item or item == "NULL":
        return _quarantined(row_number, "itm_no", "MISSING_NATURAL_KEY")
    attribute = _normalized_token(row.get("prfd_attr_cd"))
    if not attribute or attribute == "NULL":
        return _quarantined(row_number, "prfd_attr_cd", "MISSING_NATURAL_KEY")
    raw_record_key = _raw_record_key(row)
    if raw_record_key is None:
        return _quarantined(
            row_number,
            "zrin_fd_ivst_risk_gcd",
            "MISSING_NATURAL_KEY",
        )
    canonical_name = _normalized_token(row.get("itm_nm"))
    if not canonical_name or canonical_name == "NULL":
        return _quarantined(row_number, "itm_nm", "MISSING_REQUIRED_NAME")

    conflicts = repeat_analysis.conflicting_columns.get(item, frozenset())
    fatal_conflicts = sorted(conflicts & _FATAL_CONFLICT_COLUMNS)
    if fatal_conflicts:
        return _quarantined(
            row_number,
            fatal_conflicts[0],
            "CONFLICTING_SHARE_CLASS_IDENTITY",
            fatal=True,
        )
    is_canonical = repeat_analysis.canonical_record_keys.get(item) == raw_record_key
    records_by_table = _empty_records()
    issues: list[MappingIssue] = []
    product_id = stable_id("product", _SOURCE_CODE, item)
    current_column = "curr_cd"

    try:
        currency_status, currency, _ = _text_result("curr_cd", row.get("curr_cd"))
        if currency_status != "present":
            currency = None

        if is_canonical:
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
                    "product_family": "public_fund",
                    "primary_currency": currency,
                }
            )
            _append_identifier(
                records_by_table,
                product_id=product_id,
                scheme="PRFD_ITM_NO",
                value=item,
                primary=True,
            )

            for column, scheme in (
                ("fss_itm_no", "FSS_FUND"),
                ("ksd_itm_no", "KSD_PRODUCT"),
            ):
                value = _identifier_count_key(column, row)
                if value is None:
                    continue
                if value in repeat_analysis.duplicate_identifier_values.get(
                    column, frozenset()
                ):
                    _append_issue(
                        issues,
                        row_number=row_number,
                        column=column,
                        code="DUPLICATE_SOURCE_IDENTIFIER",
                    )
                else:
                    _append_identifier(
                        records_by_table,
                        product_id=product_id,
                        scheme=scheme,
                        value=value,
                        primary=False,
                    )

            manager_code = _normalized_token(row.get("or_co_xtn_itt_cd"))
            manager_product = _normalized_token(row.get("mtco_itm_no"))
            manager_identifier_key = _identifier_count_key("mtco_itm_no", row)
            if manager_identifier_key is not None:
                if manager_identifier_key in (
                    repeat_analysis.duplicate_identifier_values.get(
                        "mtco_itm_no", frozenset()
                    )
                ):
                    _append_issue(
                        issues,
                        row_number=row_number,
                        column="mtco_itm_no",
                        code="DUPLICATE_SOURCE_IDENTIFIER",
                    )
                else:
                    _append_identifier(
                        records_by_table,
                        product_id=product_id,
                        scheme=f"MANAGER_SCOPED_PRODUCT:{manager_code}",
                        value=manager_product,
                        primary=False,
                    )

            standard_value = _identifier_count_key("std_itm_no", row)
            if standard_value is not None:
                if standard_value in (
                    repeat_analysis.duplicate_identifier_values.get(
                        "std_itm_no", frozenset()
                    )
                ):
                    _append_issue(
                        issues,
                        row_number=row_number,
                        column="std_itm_no",
                        code="DUPLICATE_SOURCE_IDENTIFIER",
                    )
                else:
                    _append_identifier(
                        records_by_table,
                        product_id=product_id,
                        scheme="PRFD_STANDARD_PRODUCT",
                        value=standard_value,
                        primary=False,
                    )

            for column in ("itm_abrv_nm", "itm_eabrv_nm", "itm_eng_nm"):
                status, normalized, reason = _text_result(column, row.get(column))
                if status == "present" and isinstance(normalized, str):
                    _append_alias(
                        records_by_table,
                        product_id=product_id,
                        item=item,
                        column=column,
                        value=normalized,
                    )
                elif status != "present":
                    _append_issue(
                        issues,
                        row_number=row_number,
                        column=column,
                        code=reason,
                    )

            manager_status, manager_value, manager_reason = _text_result(
                "or_co_xtn_itt_cd", row.get("or_co_xtn_itt_cd")
            )
            if manager_status == "present" and isinstance(manager_value, str):
                manager_id = stable_id("institution", _SOURCE_CODE, manager_value)
                records_by_table["catalog.entity"].append(
                    _with_record_hash(
                        {
                            "entity_id": manager_id,
                            "entity_type": "institution",
                            "canonical_name": manager_value,
                            "normalized_name": manager_value,
                        }
                    )
                )
                records_by_table["catalog.institution"].append(
                    {"entity_id": manager_id, "institution_kind": "asset_manager"}
                )
                relation, relation_evidence, origin = _relation_records(
                    row_number=row_number,
                    locator_record_key=raw_record_key,
                    evidence_seed=f"{item}:or_co_xtn_itt_cd",
                    relation_seed=f"{item}:managedBy:{manager_id}",
                    subject_id=product_id,
                    predicate_id="managedBy",
                    object_id=manager_id,
                    column="or_co_xtn_itt_cd",
                    raw=row.get("or_co_xtn_itt_cd"),
                )
                records_by_table["relation.relation_record"].append(relation)
                records_by_table["evidence.evidence_record"].append(
                    relation_evidence
                )
                records_by_table["evidence.evidence_relation_origin"].append(origin)
            else:
                _append_issue(
                    issues,
                    row_number=row_number,
                    column="or_co_xtn_itt_cd",
                    code=manager_reason,
                )

            representative = _normalized_token(row.get("rptt_ksd_itm_no"))
            if (
                representative
                and representative != "NULL"
                and representative not in _REPRESENTATIVE_SENTINELS
            ):
                representative_id = stable_id(
                    "product", _SOURCE_CODE, f"representative:{representative}"
                )
                records_by_table["catalog.entity"].append(
                    _with_record_hash(
                        {
                            "entity_id": representative_id,
                            "entity_type": "product",
                            "canonical_name": representative,
                            "normalized_name": representative,
                        }
                    )
                )
                records_by_table["catalog.product"].append(
                    {
                        "entity_id": representative_id,
                        "product_family": "public_fund",
                        "primary_currency": None,
                    }
                )
                relation, relation_evidence, origin = _relation_records(
                    row_number=row_number,
                    locator_record_key=raw_record_key,
                    evidence_seed=f"{item}:rptt_ksd_itm_no",
                    relation_seed=(
                        f"{representative}:hasShareClass:{product_id}"
                    ),
                    subject_id=representative_id,
                    predicate_id="hasShareClass",
                    object_id=product_id,
                    column="rptt_ksd_itm_no",
                    raw=row.get("rptt_ksd_itm_no"),
                )
                records_by_table["relation.relation_record"].append(relation)
                records_by_table["evidence.evidence_record"].append(
                    relation_evidence
                )
                records_by_table["evidence.evidence_relation_origin"].append(origin)
            else:
                _append_issue(
                    issues,
                    row_number=row_number,
                    column="rptt_ksd_itm_no",
                    code=(
                        "SOURCE_VALUE_MISSING"
                        if not representative or representative == "NULL"
                        else "SOURCE_VALUE_PLACEHOLDER"
                    ),
                )

        for column in SPEC.expected_columns:
            if column in _RELATION_FIELDS:
                continue
            is_attribute = column == "prfd_attr_cd"
            is_conflict = column in conflicts
            if not is_canonical and not is_attribute and not is_conflict:
                continue

            current_column = column
            _, value_kind, unit = _METRIC_SPECS[column]
            raw = row.get(column)
            if is_conflict:
                status, normalized, reason_code = (
                    "unknown",
                    None,
                    "SOURCE_VALUE_CONFLICT",
                )
            elif value_kind == "numeric":
                status, normalized, reason_code = _numeric_result(column, raw)
            elif value_kind == "boolean":
                status, normalized, reason_code = _boolean_result(column, raw)
            else:
                status, normalized, reason_code = _text_result(column, raw)

            if status not in {"present", "zero"}:
                _append_issue(
                    issues,
                    row_number=row_number,
                    column=column,
                    code=reason_code,
                )

            observation_seed = (
                f"{raw_record_key}:{column}"
                if is_attribute
                else f"{item}:{column}"
            )
            evidence_seed = (
                f"{raw_record_key}:{column}"
                if is_attribute or is_conflict
                else f"{item}:{column}"
            )
            field_currency = currency if column == "fd_nast_suma" else None
            definition, observation, evidence, origin = _observation_records(
                row_number=row_number,
                locator_record_key=raw_record_key,
                observation_seed=observation_seed,
                evidence_seed=evidence_seed,
                product_id=product_id,
                column=column,
                raw=raw,
                status=status,
                normalized=normalized,
                reason_code=reason_code,
                value_kind=value_kind,
                unit=unit,
                currency=field_currency,
            )
            records_by_table["observation.metric_definition"].append(definition)
            records_by_table["observation.observation_record"].append(observation)
            records_by_table["evidence.evidence_record"].append(evidence)
            records_by_table["evidence.evidence_observation_origin"].append(origin)
    except (TypeError, ValueError):
        return _quarantined(row_number, current_column, "INVALID_SOURCE_VALUE")

    return MappedRow(
        row_number=row_number,
        disposition="limited" if issues else "accepted",
        records_by_table={
            table: tuple(table_records)
            for table, table_records in records_by_table.items()
        },
        issues=tuple(issues),
    )
