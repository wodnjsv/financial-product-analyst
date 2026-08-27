from __future__ import annotations

import re
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
    parse_yyyymmdd,
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
    "mtco_itm_no": frozenset(),
    "std_itm_no": frozenset(),
}
_OPTIONAL_IDENTIFIER_COLUMNS = (
    "fss_itm_no",
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
EVIDENCE_ONLY_COLUMNS = frozenset(
    {
        "bmrk_eng_nm",
        "fd_estb_ctry_cd",
        "fd_set_pcd",
        "kofia_fd_ccd",
        "pfiv_sale_cntl_tcd",
        "trusc_xtn_itt_cd",
        "zrin_btyp_cd",
        "zrin_fd_ivst_risk_gcd",
        "zrin_pcd",
    }
)

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
_COMPOSITION_FIELDS = frozenset(
    {
        "zrin_dmst_bd_cmst_rt",
        "zrin_dmst_stk_cmst_rt",
        "zrin_etc_ast_cmst_rt",
        "zrin_fd_cmst_rt",
        "zrin_liqt_cmst_rt",
        "zrin_ovrs_bd_cmst_rt",
        "zrin_ovrs_stk_cmst_rt",
    }
)
_METRIC_SPECS: Mapping[str, tuple[str, str, str | None]] = {
    "bmrk_eng_nm": ("benchmark_english_raw", "text", None),
    "bmrk_nm": ("benchmark_raw", "text", None),
    "bns_bpr": ("trading_base_price", "numeric", "price_per_unit"),
    "curr_cd": ("currency", "text", None),
    "exchdg_yn": ("currency_hedged", "boolean", None),
    "fd_daily_bas_dt": ("daily_information_as_of", "date", None),
    "fd_estb_ctry_cd": ("establishment_country_code_raw", "text", "code"),
    "fd_ivst_rgn_desc": ("investment_region", "text", None),
    "fd_last_dstb_actg_bss_dt": ("last_distribution_accounting_start", "date", None),
    "fd_last_dstb_actg_eot_dt": ("last_distribution_accounting_end", "date", None),
    "fd_last_dstb_r": ("last_distribution_rate", "numeric", "percentage_point"),
    "fd_mm18_ern_r": ("cumulative_return_18m", "numeric", "percentage_point"),
    "fd_mm1_ern_r": ("cumulative_return_1m", "numeric", "percentage_point"),
    "fd_mm3_ern_r": ("cumulative_return_3m", "numeric", "percentage_point"),
    "fd_mm6_ern_r": ("cumulative_return_6m", "numeric", "percentage_point"),
    "fd_nast_suma": ("net_assets", "numeric", "source_defined_amount"),
    "fd_price_bas_dt": ("price_return_as_of", "date", None),
    "fd_prsv_r": ("preservation_rate", "numeric", "percentage_point"),
    "fd_sbpr": ("market_valuation_amount", "numeric", "amount"),
    "fd_set_pcd": ("establishment_type_code_raw", "text", "code"),
    "fd_wk1_ern_r": ("cumulative_return_1w", "numeric", "percentage_point"),
    "fd_yr1_ern_r": ("cumulative_return_1y", "numeric", "percentage_point"),
    "fd_yr2_ern_r": ("cumulative_return_2y", "numeric", "percentage_point"),
    "fd_yr3_ern_r": ("cumulative_return_3y", "numeric", "percentage_point"),
    "fd_yr5_ern_r": ("cumulative_return_5y", "numeric", "percentage_point"),
    "frc_bpr_itm_yn": ("foreign_currency_base_price", "boolean", None),
    "fss_itm_no": ("fss_product_id", "text", None),
    "han_clas_fee_type": ("share_class_fee_type", "text", None),
    "han_clas_nm": ("share_class_name", "text", None),
    "han_clas_policies": ("share_class_policies", "text", None),
    "han_clas_sales_channel": ("share_class_sales_channel", "text", None),
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
    "ofwk_trus_rwrd_r": ("administration_fee_rate", "numeric", "source_rate"),
    "or_attr_desc": ("management_attribute", "text", None),
    "or_co_rwrd_r": ("manager_fee_rate", "numeric", "source_rate"),
    "or_co_xtn_itt_cd": ("manager_code_raw", "text", "code"),
    "ovrs_fd_desc": ("overseas_fund_class", "text", None),
    "pers_corp_desc": ("investor_type", "text", None),
    "pfiv_sale_cntl_tcd": ("professional_sale_control_code_raw", "text", "code"),
    "prfd_attr_cds": ("attribute_codes_raw", "text", None),
    "prfd_attr_cnt": ("attribute_count", "numeric", "count"),
    "prfd_attr_search_text": ("attribute_search_text", "text", None),
    "prvo_fd_desc": ("private_fund_detail", "text", None),
    "prvo_pbff_desc": ("public_private_class", "text", None),
    "rptt_ksd_itm_no": ("representative_fund_id_raw", "text", None),
    "sale_co_rwrd_r": ("sales_fee_rate", "numeric", "source_rate"),
    "sale_yn": ("sale_status", "text", None),
    "std_itm_no": ("standard_product_id", "text", None),
    "thco_sale_yn": ("sold_by_provider", "boolean", None),
    "trusc_rwrd_r": ("trustee_fee_rate", "numeric", "source_rate"),
    "trusc_xtn_itt_cd": ("trustee_institution_code_raw", "text", "code"),
    "zrin_attr_nms": ("zeroin_attribute_names_raw", "text", None),
    "zrin_btyp_cd": ("zeroin_major_type_code_raw", "text", "code"),
    "zrin_btyp_nm": ("zeroin_major_type_name", "text", None),
    "zrin_dmst_bd_cmst_rt": ("domestic_bond_weight", "numeric", "percentage_point"),
    "zrin_dmst_stk_cmst_rt": ("domestic_equity_weight", "numeric", "percentage_point"),
    "zrin_etc_ast_cmst_rt": ("other_asset_weight", "numeric", "percentage_point"),
    "zrin_fd_cmst_rt": ("fund_weight", "numeric", "percentage_point"),
    "zrin_fd_ivst_risk_gcd": ("risk_grade_code_raw", "text", "code"),
    "zrin_fd_ivst_risk_grd_nm": ("risk_grade_name", "text", None),
    "zrin_liqt_cmst_rt": ("liquidity_weight", "numeric", "percentage_point"),
    "zrin_ovrs_bd_cmst_rt": ("overseas_bond_weight", "numeric", "percentage_point"),
    "zrin_ovrs_stk_cmst_rt": ("overseas_equity_weight", "numeric", "percentage_point"),
    "zrin_pcd": ("zeroin_type_code_raw", "text", "code"),
    "zrin_ptn_nm": ("zeroin_type_name", "text", None),
}

_DATE_FIELDS = frozenset(
    {
        "fd_daily_bas_dt",
        "fd_last_dstb_actg_bss_dt",
        "fd_last_dstb_actg_eot_dt",
        "fd_price_bas_dt",
    }
)
_BOOLEAN_VALUES: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {
    "exchdg_yn": (frozenset({"Y"}), frozenset({"N"})),
    "frc_bpr_itm_yn": (frozenset({"1"}), frozenset({"0"})),
    "hdge_fd_yn": (frozenset({"1"}), frozenset({"0"})),
    "ofsfd_yn": (frozenset({"1"}), frozenset({"0"})),
    "thco_sale_yn": (frozenset({"Y"}), frozenset({"N"})),
}
_RELATION_FIELDS = frozenset({"bmrk_nm", "or_co_xtn_itt_cd", "rptt_ksd_itm_no"})
_PRICE_DATE_FIELDS = frozenset(
    {"bns_bpr", "fd_sbpr", "frc_bpr_itm_yn"}
) | _RETURN_FIELDS
_DAILY_DATE_FIELDS = frozenset(
    {
        "exchdg_yn",
        "fd_ivst_rgn_desc",
        "fd_nast_suma",
        "fd_prsv_r",
        "han_clas_sales_channel",
        "hdge_fd_yn",
        "int_dvd_desc",
        "ofsfd_yn",
        "ofwk_trus_rwrd_r",
        "or_attr_desc",
        "or_co_rwrd_r",
        "or_co_xtn_itt_cd",
        "ovrs_fd_desc",
        "pers_corp_desc",
        "pfiv_sale_cntl_tcd",
        "prvo_fd_desc",
        "prvo_pbff_desc",
        "sale_co_rwrd_r",
        "sale_yn",
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
    }
)
_CURRENCY_FIELDS = frozenset({"bns_bpr", "fd_nast_suma", "fd_sbpr"})
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


@dataclass(frozen=True, slots=True)
class PublicFundAnalysis:
    duplicate_identifier_values: Mapping[str, frozenset[str]]
    cycle_items: frozenset[str]

    def identifier_is_unique(
        self,
        column: str,
        value: str,
        manager: str | None = None,
    ) -> bool:
        normalized = normalize_name(value).upper()
        key = (
            f"{normalize_name(manager).upper()}|{normalized}"
            if column == "mtco_itm_no" and manager is not None
            else normalized
        )
        return key not in self.duplicate_identifier_values.get(column, frozenset())


def _normalized_token(value: object) -> str:
    if value is None:
        return ""
    return normalize_name(str(value))


def _identifier_value(column: str, value: object) -> str | None:
    token = _normalized_token(value).upper()
    if token in {"", "NULL"} or token in _IDENTIFIER_SENTINELS.get(
        column, frozenset()
    ):
        return None
    return token


def analyze_public_fund_rows(
    rows: Iterable[Mapping[str, object]],
) -> PublicFundAnalysis:
    materialized = tuple(rows)
    owners: dict[str, dict[str, set[str]]] = {
        column: defaultdict(set) for column in _OPTIONAL_IDENTIFIER_COLUMNS
    }
    ksd_owners: dict[str, set[str]] = defaultdict(set)
    references: dict[str, str] = {}
    for row in materialized:
        item = _identifier_value("itm_no", row.get("itm_no"))
        if item is None:
            continue
        for column in _OPTIONAL_IDENTIFIER_COLUMNS:
            value = _identifier_value(column, row.get(column))
            if value is None:
                continue
            key = value
            if column == "mtco_itm_no":
                manager = _normalized_token(row.get("or_co_xtn_itt_cd")).upper()
                if not manager or manager == "NULL":
                    continue
                key = f"{manager}|{value}"
            owners[column][key].add(item)
        ksd = _identifier_value("ksd_itm_no", row.get("ksd_itm_no"))
        if ksd is not None:
            ksd_owners[ksd].add(item)
        representative = _normalized_token(row.get("rptt_ksd_itm_no")).upper()
        if representative not in {"", "NULL"} | _REPRESENTATIVE_SENTINELS:
            references[item] = representative

    graph: dict[str, str] = {}
    for item, representative in references.items():
        targets = ksd_owners.get(representative, set())
        if len(targets) == 1:
            graph[item] = next(iter(targets))

    cycle_items: set[str] = set()
    visited: set[str] = set()
    for start in graph:
        if start in visited:
            continue
        order: list[str] = []
        positions: dict[str, int] = {}
        node = start
        while node in graph and node not in visited:
            if node in positions:
                cycle_items.update(order[positions[node] :])
                break
            positions[node] = len(order)
            order.append(node)
            node = graph[node]
        visited.update(order)

    return PublicFundAnalysis(
        duplicate_identifier_values={
            column: frozenset(
                value for value, item_owners in values.items() if len(item_owners) > 1
            )
            for column, values in owners.items()
        },
        cycle_items=frozenset(cycle_items),
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


def _append_issue(
    issues: list[MappingIssue],
    *,
    row_number: int,
    column: str | None,
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


def _text_result(
    column: str,
    raw: object,
) -> tuple[str, object | None, str | None]:
    text = raw if isinstance(raw, str) or raw is None else str(raw)
    placeholders = _IDENTIFIER_SENTINELS.get(column, frozenset())
    if column == "rptt_ksd_itm_no":
        placeholders = _REPRESENTATIVE_SENTINELS
    status, normalized, reason = classify_value(
        text,
        missing_values=_MISSING_VALUES,
        placeholder_values=placeholders,
        zero_is_value=True,
    )
    if status != "present":
        return status, normalized, reason
    if column == "curr_cd" and normalized == "000":
        return "unknown", None, "UNDEFINED_CURRENCY_CODE"
    if column in {"bmrk_eng_nm", "itm_eng_nm"} and isinstance(normalized, str):
        if normalized.isdecimal() or len(normalized) > 240:
            return "unknown", None, "NON_NAME_SOURCE_VALUE"
    return status, normalized, reason


def _numeric_result(raw: object) -> tuple[str, object | None, str | None]:
    status, normalized, reason = classify_value(
        raw,
        missing_values=_MISSING_VALUES,
        placeholder_values=frozenset(),
        zero_is_value=True,
    )
    if status not in {"present", "zero"}:
        return status, normalized, reason
    decimal_input = Decimal(str(normalized)) if isinstance(normalized, float) else normalized
    parsed = parse_decimal(decimal_input)
    return ("zero" if parsed == 0 else "present"), parsed, None


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


def _date_result(
    raw: object,
) -> tuple[str, object | None, str | None]:
    sentinels = frozenset({"0", "00000000"})
    if isinstance(raw, datetime):
        if raw.tzinfo is not None:
            raise ValueError("source date must be timezone-naive")
        return "present", raw.date(), None
    if isinstance(raw, date):
        return "present", raw, None
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
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
    if isinstance(raw, str):
        normalized = normalize_name(raw)
        if len(normalized) >= 10 and normalized[4] == "-" and normalized[7] == "-":
            try:
                return "present", date.fromisoformat(normalized[:10]), None
            except ValueError:
                pass
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


def _metric_definition(
    column: str,
    metric_id: str,
    value_kind: str,
    unit: str | None,
    *,
    evidence_only: bool | None = None,
) -> dict[str, object]:
    is_evidence_only = column in EVIDENCE_ONLY_COLUMNS if evidence_only is None else evidence_only
    payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "2",
        "semantic_family": (
            "organizer_public_fund_evidence_only"
            if is_evidence_only
            else "organizer_public_fund"
        ),
        "value_kind": value_kind,
        "default_unit": unit,
        "description": f"Organizer PRFD01N001 field {column}",
        "approved_at": _DEFINITION_APPROVED_AT,
    }
    payload["definition_hash"] = make_record_hash(payload)
    return payload


def _evidence_record(
    *,
    row_number: int,
    record_key: str,
    subject_id: str,
    predicate_id: str,
    column: str,
    raw: object,
    normalized: object | None,
    status: str,
    evidence_kind: str,
    unit: str | None,
    currency: str | None,
    applicable_date: date | None,
    identity_suffix: str | None = None,
) -> dict[str, object]:
    evidence_value = normalized if status in {"present", "zero"} else None
    evidence_key = f"{record_key}:{column}"
    if identity_suffix is not None:
        evidence_key = f"{evidence_key}:{identity_suffix}"
    payload: dict[str, object] = {
        "evidence_id": stable_id("evidence", _SOURCE_CODE, evidence_key),
        "evidence_kind": evidence_kind,
        "source_id": _SOURCE_ID,
        "subject_id": subject_id,
        "predicate_id": predicate_id,
        "value_or_object_id": _tag(evidence_value),
        "normalized_value": _tag(evidence_value),
        "unit": unit,
        "currency": currency,
        "applicable_date": applicable_date,
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
        "cutoff_status": "inapplicable" if status == "inapplicable" else "eligible",
        "scope_completeness": None,
    }
    return _with_record_hash(payload)


def _observation_records(
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    column: str,
    raw: object,
    status: str,
    normalized: object | None,
    reason_code: str | None,
    currency: str | None,
    applicable_date: date | None,
    period_end: date | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    metric_suffix, value_kind, unit = _METRIC_SPECS[column]
    metric_id = f"organizer.prfd01n001.{metric_suffix}"
    observation_id = stable_id("observation", _SOURCE_CODE, f"{record_key}:{column}")
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
            "period_end": period_end,
            "applicable_date": applicable_date,
            "published_at": None,
            "available_at": None,
            "vintage_date": _CUTOFF_DATE,
            "reason_code": reason_code,
        }
    )
    evidence = _evidence_record(
        row_number=row_number,
        record_key=record_key,
        subject_id=product_id,
        predicate_id=metric_id,
        column=column,
        raw=raw,
        normalized=normalized,
        status=status,
        evidence_kind="observation",
        unit=unit,
        currency=currency,
        applicable_date=applicable_date,
    )
    return (
        _metric_definition(column, metric_id, value_kind, unit),
        observation,
        evidence,
        {"evidence_id": evidence["evidence_id"], "observation_id": observation_id},
    )


def _append_observation(
    records_by_table: dict[str, list[Mapping[str, object]]],
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    column: str,
    raw: object,
    status: str,
    normalized: object | None,
    reason_code: str | None,
    currency: str | None,
    applicable_date: date | None,
    period_end: date | None,
) -> None:
    definition, observation, evidence, origin = _observation_records(
        row_number=row_number,
        record_key=record_key,
        product_id=product_id,
        column=column,
        raw=raw,
        status=status,
        normalized=normalized,
        reason_code=reason_code,
        currency=currency,
        applicable_date=applicable_date,
        period_end=period_end,
    )
    records_by_table["observation.metric_definition"].append(definition)
    records_by_table["observation.observation_record"].append(observation)
    records_by_table["evidence.evidence_record"].append(evidence)
    records_by_table["evidence.evidence_observation_origin"].append(origin)


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
                "identifier_id": stable_id("identifier", _SOURCE_CODE, f"{scheme}:{value}"),
                "entity_id": product_id,
                "scheme": scheme,
                "identifier_value": value,
                "is_primary": primary,
                "valid_from": None,
                "valid_to": None,
            }
        )
    )


def _append_standard_relation(
    records_by_table: dict[str, list[Mapping[str, object]]],
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    column: str,
    raw: object,
    predicate_id: str,
    object_type: str,
    object_name: str,
    applicable_date: date | None,
    institution_kind: str | None = None,
) -> None:
    object_key = (
        f"{institution_kind}:{object_name}"
        if object_type == "institution" and institution_kind is not None
        else object_name
    )
    object_id = stable_id(object_type, _SOURCE_CODE, object_key)
    records_by_table["catalog.entity"].append(
        _with_record_hash(
            {
                "entity_id": object_id,
                "entity_type": object_type,
                "canonical_name": object_name,
                "normalized_name": object_name,
            }
        )
    )
    if object_type == "institution" and institution_kind is not None:
        records_by_table["catalog.institution"].append(
            {"entity_id": object_id, "institution_kind": institution_kind}
        )
    relation_id = stable_id(
        "relation", _SOURCE_CODE, f"{record_key}:{predicate_id}:{object_id}"
    )
    records_by_table["relation.relation_record"].append(
        _with_record_hash(
            {
                "relation_id": relation_id,
                "subject_id": product_id,
                "predicate_id": predicate_id,
                "object_id": object_id,
                "valid_from": applicable_date,
                "valid_to": None,
            }
        )
    )
    evidence = _evidence_record(
        row_number=row_number,
        record_key=record_key,
        subject_id=product_id,
        predicate_id=predicate_id,
        column=column,
        raw=raw,
        normalized=object_id,
        status="present",
        evidence_kind="relation",
        unit=None,
        currency=None,
        applicable_date=applicable_date,
    )
    records_by_table["evidence.evidence_record"].append(evidence)
    records_by_table["evidence.evidence_relation_origin"].append(
        {"evidence_id": evidence["evidence_id"], "relation_id": relation_id}
    )


def _append_share_class_relation(
    records_by_table: dict[str, list[Mapping[str, object]]],
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    representative_id: str,
    representative_value: str,
    raw: object,
) -> None:
    relation_id = stable_id(
        "relation", _SOURCE_CODE, f"{representative_id}:hasShareClass:{product_id}"
    )
    records_by_table["relation.relation_record"].append(
        _with_record_hash(
            {
                "relation_id": relation_id,
                "subject_id": representative_id,
                "predicate_id": "hasShareClass",
                "object_id": product_id,
                "valid_from": None,
                "valid_to": None,
            }
        )
    )
    evidence = _evidence_record(
        row_number=row_number,
        record_key=record_key,
        subject_id=representative_id,
        predicate_id="hasShareClass",
        column="rptt_ksd_itm_no",
        raw=raw,
        normalized=product_id,
        status="present",
        evidence_kind="relation",
        unit=None,
        currency=None,
        applicable_date=None,
    )
    records_by_table["evidence.evidence_record"].append(evidence)
    records_by_table["evidence.evidence_relation_origin"].append(
        {"evidence_id": evidence["evidence_id"], "relation_id": relation_id}
    )


def _clear_benchmark(value: str) -> bool:
    if len(value) > 160 or "\n" in value or "\r" in value:
        return False
    if re.search(r"[0-9]+(?:\.[0-9]+)?\s*%", value):
        return False
    folded = value.casefold()
    return not any(marker in folded for marker in (" + ", " / ", ";", " 및 ", " and "))


def _parsed_value(
    column: str,
    raw: object,
    date_results: Mapping[str, tuple[str, object | None, str | None]],
) -> tuple[str, object | None, str | None]:
    _, value_kind, _ = _METRIC_SPECS[column]
    if value_kind == "date":
        return date_results[column]
    if value_kind == "numeric":
        status, normalized, reason = _numeric_result(raw)
        if column == "prfd_attr_cnt" and isinstance(normalized, Decimal):
            if normalized != normalized.to_integral_value():
                return "unknown", None, "INVALID_ATTRIBUTE_COUNT"
        return status, normalized, reason
    if value_kind == "boolean":
        return _boolean_result(column, raw)
    return _text_result(column, raw)


def _applicable_date(
    column: str,
    date_values: Mapping[str, date | None],
) -> date | None:
    if column in _DATE_FIELDS:
        return date_values[column]
    if column in _PRICE_DATE_FIELDS:
        return date_values["fd_price_bas_dt"]
    if column == "fd_last_dstb_r":
        return date_values["fd_last_dstb_actg_eot_dt"]
    if column in _DAILY_DATE_FIELDS:
        return date_values["fd_daily_bas_dt"]
    return None


def _append_relation_fallback(
    records_by_table: dict[str, list[Mapping[str, object]]],
    issues: list[MappingIssue],
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    column: str,
    raw: object,
    status: str,
    normalized: object | None,
    reason_code: str | None,
    applicable_date: date | None,
    issue_code: str | None = None,
) -> None:
    issue_reason = issue_code or reason_code
    if issue_code is not None or status not in {"present", "zero"}:
        _append_issue(
            issues,
            row_number=row_number,
            column=column,
            code=issue_reason,
        )
    _append_observation(
        records_by_table,
        row_number=row_number,
        record_key=record_key,
        product_id=product_id,
        column=column,
        raw=raw,
        status=status,
        normalized=normalized,
        reason_code=(
            reason_code if status not in {"present", "zero"} else None
        ),
        currency=None,
        applicable_date=applicable_date,
        period_end=None,
    )


def _parse_ordered_list(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    token = normalize_name(str(raw))
    if not token or token == "NULL":
        return ()
    values: list[str] = []
    seen: set[str] = set()
    for part in token.split(","):
        value = normalize_name(part)
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return tuple(values)


def _append_repeated_list_observations(
    records_by_table: dict[str, list[Mapping[str, object]]],
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    column: str,
    raw: object,
    values: tuple[str, ...],
    applicable_date: date | None,
) -> None:
    if not values:
        return
    metric_suffix = (
        "attribute_code" if column == "prfd_attr_cds" else "zeroin_attribute_name"
    )
    metric_id = f"organizer.prfd01n001.{metric_suffix}"
    records_by_table["observation.metric_definition"].append(
        _metric_definition(column, metric_id, "text", None, evidence_only=False)
    )
    for position, value in enumerate(values):
        observation_id = stable_id(
            "observation",
            _SOURCE_CODE,
            f"{record_key}:{column}:item:{position}:{value}",
        )
        records_by_table["observation.observation_record"].append(
            _with_record_hash(
                {
                    "observation_id": observation_id,
                    "entity_id": product_id,
                    "relation_id": None,
                    "metric_id": metric_id,
                    "metric_definition_version": "2",
                    "value_status": "present",
                    **_typed_values("text", "present", value),
                    "unit": None,
                    "currency": None,
                    "period_start": None,
                    "period_end": None,
                    "applicable_date": applicable_date,
                    "published_at": None,
                    "available_at": None,
                    "vintage_date": _CUTOFF_DATE,
                    "reason_code": None,
                }
            )
        )
        item_evidence = _evidence_record(
            row_number=row_number,
            record_key=record_key,
            subject_id=product_id,
            predicate_id=metric_id,
            column=column,
            raw=raw,
            normalized=value,
            status="present",
            evidence_kind="observation",
            unit=None,
            currency=None,
            applicable_date=applicable_date,
            identity_suffix=f"item:{position}:{value}",
        )
        records_by_table["evidence.evidence_record"].append(item_evidence)
        records_by_table["evidence.evidence_observation_origin"].append(
            {
                "evidence_id": item_evidence["evidence_id"],
                "observation_id": observation_id,
            }
        )


def map_row(
    row_number: int,
    row: Mapping[str, object],
    *,
    analysis: PublicFundAnalysis,
    identity_index: AuthoritativeIdentityIndex,
) -> MappedRow:
    record_key = _identifier_value("itm_no", row.get("itm_no"))
    if record_key is None:
        return _quarantined(row_number, "itm_no", "MISSING_NATURAL_KEY")
    canonical_name = _normalized_token(row.get("itm_nm"))
    if not canonical_name or canonical_name.upper() == "NULL":
        return _quarantined(row_number, "itm_nm", "MISSING_REQUIRED_NAME")

    resolution = identity_index.resolve("PRFD_ITM_NO", record_key)
    if resolution.status != "MATCHED" or resolution.canonical_identity is None:
        return _quarantined(
            row_number,
            "itm_no",
            "IDENTITY_RESOLUTION_FAILED",
            fatal=True,
        )
    product_id = resolution.canonical_identity.entity_id
    overlap_owner = resolution.canonical_identity.owner_source_code == "PREF01N001"
    records_by_table = _empty_records()
    issues: list[MappingIssue] = []
    current_column = "fd_daily_bas_dt"

    try:
        date_results = {}
        for column in _DATE_FIELDS:
            current_column = column
            date_results[column] = _date_result(row.get(column))
        date_values = {
            column: result[1] if isinstance(result[1], date) else None
            for column, result in date_results.items()
        }
        for column, value in date_values.items():
            if value is not None and value > _CUTOFF_DATE:
                return _quarantined(
                    row_number,
                    column,
                    "AFTER_CUTOFF_SOURCE_VALUE",
                    fatal=True,
                )

        currency_status, currency_value, _ = _text_result(
            "curr_cd", row.get("curr_cd")
        )
        primary_currency = (
            currency_value.upper()
            if currency_status == "present"
            and isinstance(currency_value, str)
            and len(currency_value) == 3
            and currency_value.isalpha()
            else None
        )
        if not overlap_owner:
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
                    "primary_currency": primary_currency,
                }
            )

        _append_identifier(
            records_by_table,
            product_id=product_id,
            scheme="PRFD_ITM_NO",
            value=record_key,
            primary=True,
        )
        for column, scheme in (
            ("fss_itm_no", "FSS_FUND"),
            ("std_itm_no", "PRFD_STANDARD_PRODUCT"),
        ):
            value = _identifier_value(column, row.get(column))
            if value is None:
                continue
            if analysis.identifier_is_unique(column, value):
                _append_identifier(
                    records_by_table,
                    product_id=product_id,
                    scheme=scheme,
                    value=value,
                    primary=False,
                )
            else:
                _append_issue(
                    issues,
                    row_number=row_number,
                    column=column,
                    code="DUPLICATE_IDENTIFIER_NOT_PROMOTED",
                )

        manager_code = _normalized_token(row.get("or_co_xtn_itt_cd")).upper()
        manager_product = _identifier_value("mtco_itm_no", row.get("mtco_itm_no"))
        if manager_product is not None and manager_code not in {"", "NULL"}:
            if analysis.identifier_is_unique(
                "mtco_itm_no", manager_product, manager_code
            ):
                _append_identifier(
                    records_by_table,
                    product_id=product_id,
                    scheme=f"MANAGER_SCOPED_PRODUCT:{manager_code}",
                    value=manager_product,
                    primary=False,
                )
            else:
                _append_issue(
                    issues,
                    row_number=row_number,
                    column="mtco_itm_no",
                    code="DUPLICATE_IDENTIFIER_NOT_PROMOTED",
                )

        ksd_value = _identifier_value("ksd_itm_no", row.get("ksd_itm_no"))
        if ksd_value is not None:
            ksd_resolution = identity_index.resolve("KSD_PRODUCT", ksd_value)
            if (
                ksd_resolution.status == "MATCHED"
                and ksd_resolution.canonical_identity is not None
                and ksd_resolution.canonical_identity.entity_id == product_id
            ):
                _append_identifier(
                    records_by_table,
                    product_id=product_id,
                    scheme="KSD_PRODUCT",
                    value=ksd_value,
                    primary=False,
                )
            else:
                _append_issue(
                    issues,
                    row_number=row_number,
                    column="ksd_itm_no",
                    code="AMBIGUOUS_IDENTIFIER_NOT_PROMOTED",
                )
            isin_resolution = identity_index.resolve("ISIN", ksd_value)
            if (
                not overlap_owner
                and isin_resolution.status == "MATCHED"
                and isin_resolution.canonical_identity is not None
                and isin_resolution.canonical_identity.entity_id == product_id
            ):
                _append_identifier(
                    records_by_table,
                    product_id=product_id,
                    scheme="ISIN",
                    value=ksd_value,
                    primary=False,
                )

        aliases: set[str] = set()
        for column in ("han_clas_nm", "itm_abrv_nm", "itm_eabrv_nm", "itm_eng_nm"):
            status, normalized, _ = _text_result(column, row.get(column))
            if status != "present" or not isinstance(normalized, str):
                continue
            alias_key = normalized.casefold()
            if alias_key in aliases:
                continue
            aliases.add(alias_key)
            records_by_table["catalog.alias"].append(
                _with_record_hash(
                    {
                        "alias_id": stable_id(
                            "alias", _SOURCE_CODE, f"{record_key}:{alias_key}"
                        ),
                        "entity_id": product_id,
                        "alias_text": normalized,
                        "normalized_alias_text": alias_key,
                        "valid_from": None,
                        "valid_to": None,
                    }
                )
            )

        relation_consumed: set[str] = set()
        benchmark_status, benchmark_name, benchmark_reason = _text_result(
            "bmrk_nm", row.get("bmrk_nm")
        )
        if (
            benchmark_status == "present"
            and isinstance(benchmark_name, str)
            and _clear_benchmark(benchmark_name)
        ):
            _append_standard_relation(
                records_by_table,
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                column="bmrk_nm",
                raw=row.get("bmrk_nm"),
                predicate_id="tracksIndex",
                object_type="index",
                object_name=benchmark_name,
                applicable_date=None,
            )
            relation_consumed.add("bmrk_nm")

        manager_status, manager_name, manager_reason = _text_result(
            "or_co_xtn_itt_cd", row.get("or_co_xtn_itt_cd")
        )
        if manager_status == "present" and isinstance(manager_name, str):
            _append_standard_relation(
                records_by_table,
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                column="or_co_xtn_itt_cd",
                raw=row.get("or_co_xtn_itt_cd"),
                predicate_id="managedBy",
                object_type="institution",
                object_name=manager_name,
                applicable_date=date_values["fd_daily_bas_dt"],
                institution_kind="asset_manager",
            )
            relation_consumed.add("or_co_xtn_itt_cd")

        (
            representative_status,
            representative_value,
            representative_reason,
        ) = _text_result("rptt_ksd_itm_no", row.get("rptt_ksd_itm_no"))
        representative_issue: str | None = None
        if representative_status == "present" and isinstance(representative_value, str):
            representative_key = representative_value.upper()
            representative_resolution = identity_index.resolve(
                "KSD_PRODUCT", representative_key
            )
            if (
                representative_resolution.status == "MATCHED"
                and representative_resolution.canonical_identity is not None
            ):
                representative_id = representative_resolution.canonical_identity.entity_id
                if representative_id == product_id:
                    representative_issue = "SELF_REFERENTIAL_SHARE_CLASS"
                elif record_key in analysis.cycle_items:
                    representative_issue = "SHARE_CLASS_CYCLE"
                else:
                    _append_share_class_relation(
                        records_by_table,
                        row_number=row_number,
                        record_key=record_key,
                        product_id=product_id,
                        representative_id=representative_id,
                        representative_value=representative_key,
                        raw=row.get("rptt_ksd_itm_no"),
                    )
                    relation_consumed.add("rptt_ksd_itm_no")
            elif representative_resolution.status == "AMBIGUOUS":
                representative_issue = "AMBIGUOUS_REPRESENTATIVE_FUND"
            else:
                representative_id = stable_id(
                    "product", _SOURCE_CODE, f"representative:{representative_key}"
                )
                records_by_table["catalog.entity"].append(
                    _with_record_hash(
                        {
                            "entity_id": representative_id,
                            "entity_type": "product",
                            "canonical_name": representative_key,
                            "normalized_name": representative_key,
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
                _append_share_class_relation(
                    records_by_table,
                    row_number=row_number,
                    record_key=record_key,
                    product_id=product_id,
                    representative_id=representative_id,
                    representative_value=representative_key,
                    raw=row.get("rptt_ksd_itm_no"),
                )
                relation_consumed.add("rptt_ksd_itm_no")

        relation_results = {
            "bmrk_nm": (benchmark_status, benchmark_name, benchmark_reason, None),
            "or_co_xtn_itt_cd": (
                manager_status,
                manager_name,
                manager_reason,
                date_values["fd_daily_bas_dt"],
            ),
            "rptt_ksd_itm_no": (
                representative_status,
                representative_value,
                representative_reason,
                None,
            ),
        }
        for column in _RELATION_FIELDS - relation_consumed:
            status, normalized, reason, applicable_date = relation_results[column]
            issue_code = representative_issue if column == "rptt_ksd_itm_no" else None
            if column == "bmrk_nm" and status == "present" and not _clear_benchmark(
                str(normalized)
            ):
                issue_code = "AMBIGUOUS_BENCHMARK_TEXT"
            _append_relation_fallback(
                records_by_table,
                issues,
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                column=column,
                raw=row.get(column),
                status=status,
                normalized=normalized,
                reason_code=reason,
                applicable_date=applicable_date,
                issue_code=issue_code,
            )

        parsed_values: dict[str, tuple[str, object | None, str | None]] = {}
        for column in SPEC.expected_columns:
            if column in _RELATION_FIELDS:
                continue
            current_column = column
            raw = row.get(column)
            result = _parsed_value(column, raw, date_results)
            parsed_values[column] = result
            status, normalized, reason_code = result
            if status not in {"present", "zero"}:
                _append_issue(
                    issues,
                    row_number=row_number,
                    column=column,
                    code=reason_code,
                )
            applicable_date = _applicable_date(column, date_values)
            period_end = (
                applicable_date
                if column in _RETURN_FIELDS or column == "fd_last_dstb_r"
                else None
            )
            currency = primary_currency if column in _CURRENCY_FIELDS else None
            _append_observation(
                records_by_table,
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                column=column,
                raw=raw,
                status=status,
                normalized=normalized,
                reason_code=reason_code,
                currency=currency,
                applicable_date=applicable_date,
                period_end=period_end,
            )

        attribute_codes = _parse_ordered_list(row.get("prfd_attr_cds"))
        attribute_names = _parse_ordered_list(row.get("zrin_attr_nms"))
        _append_repeated_list_observations(
            records_by_table,
            row_number=row_number,
            record_key=record_key,
            product_id=product_id,
            column="prfd_attr_cds",
            raw=row.get("prfd_attr_cds"),
            values=attribute_codes,
            applicable_date=None,
        )
        _append_repeated_list_observations(
            records_by_table,
            row_number=row_number,
            record_key=record_key,
            product_id=product_id,
            column="zrin_attr_nms",
            raw=row.get("zrin_attr_nms"),
            values=attribute_names,
            applicable_date=date_values["fd_daily_bas_dt"],
        )
        count_status, declared_count, _ = parsed_values["prfd_attr_cnt"]
        if (
            count_status in {"present", "zero"}
            and isinstance(declared_count, Decimal)
            and int(declared_count) != len(attribute_codes)
        ):
            _append_issue(
                issues,
                row_number=row_number,
                column="prfd_attr_cnt",
                code="ATTRIBUTE_COUNT_MISMATCH",
            )

        composition = [parsed_values[column] for column in _COMPOSITION_FIELDS]
        if all(status in {"present", "zero"} for status, _, _ in composition):
            total = sum(
                (value for _, value, _ in composition if isinstance(value, Decimal)),
                Decimal(0),
            )
            if total != Decimal(100):
                _append_issue(
                    issues,
                    row_number=row_number,
                    column=None,
                    code="ASSET_COMPOSITION_SUM_MISMATCH",
                )
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
