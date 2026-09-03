from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from financial_agent.contracts import encode_contract_value
from financial_agent.ingestion.identity import AuthoritativeIdentityIndex
from financial_agent.ingestion.models import MappedRow, MappingIssue, SourceSpec

from .asset_managers import (
    append_asset_manager_catalog_records,
    resolve_etf_asset_manager,
)
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
_SOURCE_CODE = "PREF01N001"
_SOURCE_FILE = "pref01n001_data.xlsx"
_SOURCE_ID = stable_id("source", _SOURCE_CODE, _SOURCE_FILE)
_MISSING_VALUES = frozenset({None, "", "NULL"})
_INDEX_PLACEHOLDERS = frozenset(
    {"없음", "미제공", "제공되지 않음", "해당없음", "N/A"}
)

_EXPECTED_COLUMNS = (
    "cu_base_index",
    "cu_charge_etc_rt",
    "cu_charge_rt",
    "cu_fund_mgmt_co",
    "cu_lev_fector",
    "cu_strtegy",
    "cu_upt_dt",
    "du_bpr",
    "du_chas_errt",
    "du_chas_errt_base_dt",
    "du_clpr",
    "du_diff_rt",
    "du_diff_rt_base_dt",
    "du_er_1d",
    "du_er_1m",
    "du_er_1y",
    "du_er_3m",
    "du_er_6m",
    "du_er_ytd",
    "du_hpr",
    "du_last_aum",
    "du_last_nav",
    "du_lpr",
    "du_nav_base_dt",
    "du_nav_rnf_amt",
    "du_nav_yday",
    "du_upt_dt",
    "du_val_1d",
    "du_val_1m",
    "du_val_5d",
    "du_vlty_1m",
    "du_vlty_1y",
    "du_vlty_3m",
    "du_vlty_6m",
    "du_vlty_base_dt",
    "du_vol_1d",
    "du_vol_avg_1m",
    "du_vol_avg_5d",
    "fn_average_coupon",
    "fn_average_maturity",
    "fn_average_quality",
    "fn_base_dt",
    "fn_effective_duration",
    "fn_effective_maturity",
    "fn_modified_duration",
    "fn_nominal_maturity",
    "fn_portfolio_dt",
    "pd_abrv_nm",
    "pd_circ_net_tamt",
    "pd_circ_stk_cnt",
    "pd_curr_cd",
    "pd_curr_nm",
    "pd_divd_amt_ann",
    "pd_divd_amt_pshr",
    "pd_dvid_base_dt",
    "pd_dvid_cycl",
    "pd_dvid_inc_dist",
    "pd_dvid_nav",
    "pd_dvid_pay_cnt",
    "pd_dvid_pay_months",
    "pd_dvid_prc_base_dt",
    "pd_dvid_tax_basis",
    "pd_dvid_yield",
    "pd_exg_mkt_cd",
    "pd_exg_mkt_nm",
    "pd_grp_no",
    "pd_isin_cd",
    "pd_itm_no",
    "pd_itm_no_ma",
    "pd_lst_stk_cnt",
    "pd_lste_dt",
    "pd_lstg_dt",
    "pd_mkt_id",
    "pd_mkt_nm",
    "pd_net_tamt",
    "pd_nm",
    "pd_pen_risk_nm",
    "pd_pen_tr_yn",
    "pd_ric",
    "pd_risk_cd",
    "pd_risk_nm",
    "pd_sale_yn",
    "pd_sect_cd",
    "pd_spac_yn",
    "pd_stk_cnt",
    "pd_ticker",
    "pd_tr_yn",
    "ref_ast_type",
    "ref_base_dt",
    "ref_base_index",
    "ref_fund_mgmt_co",
    "ref_geo_focus",
    "ru_mkt_price",
    "ru_mkt_volume",
    "wu_core_yn",
    "wu_inv_ast_type",
    "wu_inv_rgn",
    "wu_upt_dt",
)

SPEC = SourceSpec(
    source_code=_SOURCE_CODE,
    table_id=_SOURCE_CODE,
    data_file_name=_SOURCE_FILE,
    data_sheet_name="data",
    schema_file_name="pref01n001_schema.xlsx",
    schema_sheet_name="schema",
    expected_columns=_EXPECTED_COLUMNS,
    expected_row_count=1_780,
    natural_key=("pd_itm_no",),
    parser_version="1",
    mapping_version="2",
)

IGNORED_COLUMNS: Mapping[str, str] = {}
HANDLED_COLUMNS = frozenset(_EXPECTED_COLUMNS)
EVIDENCE_ONLY_COLUMNS = frozenset(
    {
        "du_lpr",
        "fn_average_quality",
        "pd_mkt_id",
        "pd_risk_cd",
        "pd_sect_cd",
        "ru_mkt_price",
        "ru_mkt_volume",
    }
)

_METRIC_SPECS: Mapping[str, tuple[str, str, str | None]] = {
    "cu_base_index": ("base_index_raw", "text", None),
    "cu_charge_etc_rt": ("other_expense_rate", "numeric", "percentage_point"),
    "cu_charge_rt": ("total_fee_rate", "numeric", "percentage_point"),
    "cu_fund_mgmt_co": ("fund_manager_raw", "text", None),
    "cu_lev_fector": ("leverage_factor", "numeric", "multiple"),
    "cu_strtegy": ("strategy_raw", "text", None),
    "cu_upt_dt": ("structure_updated_on", "date", None),
    "du_bpr": ("base_price", "numeric", "price_per_share"),
    "du_chas_errt": ("tracking_error", "numeric", "percentage_point"),
    "du_chas_errt_base_dt": ("tracking_error_as_of", "date", None),
    "du_clpr": ("close_price", "numeric", "price_per_share"),
    "du_diff_rt": ("premium_discount_rate", "numeric", "percentage_point"),
    "du_diff_rt_base_dt": ("premium_discount_as_of", "date", None),
    "du_er_1d": ("cumulative_return_1d", "numeric", "percentage_point"),
    "du_er_1m": ("cumulative_return_1m", "numeric", "percentage_point"),
    "du_er_1y": ("cumulative_return_1y", "numeric", "percentage_point"),
    "du_er_3m": ("cumulative_return_3m", "numeric", "percentage_point"),
    "du_er_6m": ("cumulative_return_6m", "numeric", "percentage_point"),
    "du_er_ytd": ("cumulative_return_ytd", "numeric", "percentage_point"),
    "du_hpr": ("high_price", "numeric", "price_per_share"),
    "du_last_aum": ("aum", "numeric", "source_defined_amount"),
    "du_last_nav": ("nav_per_share", "numeric", "nav_per_share"),
    "du_lpr": ("lpr_raw", "numeric", "source_defined_price"),
    "du_nav_base_dt": ("nav_as_of", "date", None),
    "du_nav_rnf_amt": ("nav_change_amount", "numeric", "amount_per_share"),
    "du_nav_yday": ("previous_nav_per_share", "numeric", "nav_per_share"),
    "du_upt_dt": ("daily_updated_on", "date", None),
    "du_val_1d": ("trading_value_1d", "numeric", "amount"),
    "du_val_1m": ("average_trading_value_1m", "numeric", "amount"),
    "du_val_5d": ("average_trading_value_5d", "numeric", "amount"),
    "du_vlty_1m": ("annualized_volatility_1m", "numeric", "percentage_point_annualized"),
    "du_vlty_1y": ("annualized_volatility_1y", "numeric", "percentage_point_annualized"),
    "du_vlty_3m": ("annualized_volatility_3m", "numeric", "percentage_point_annualized"),
    "du_vlty_6m": ("annualized_volatility_6m", "numeric", "percentage_point_annualized"),
    "du_vlty_base_dt": ("volatility_as_of", "date", None),
    "du_vol_1d": ("trading_volume_1d", "numeric", "shares_or_notes"),
    "du_vol_avg_1m": ("average_trading_volume_1m", "numeric", "shares_or_notes"),
    "du_vol_avg_5d": ("average_trading_volume_5d", "numeric", "shares_or_notes"),
    "fn_average_coupon": ("portfolio_average_coupon", "numeric", "percentage_point"),
    "fn_average_maturity": ("portfolio_average_maturity", "numeric", "year"),
    "fn_average_quality": ("portfolio_average_quality_raw", "text", "source_scale"),
    "fn_base_dt": ("fundamentals_as_of", "date", None),
    "fn_effective_duration": ("effective_duration", "numeric", "year"),
    "fn_effective_maturity": ("effective_maturity", "numeric", "year"),
    "fn_modified_duration": ("modified_duration", "numeric", "year"),
    "fn_nominal_maturity": ("nominal_maturity", "numeric", "year"),
    "fn_portfolio_dt": ("portfolio_as_of", "date", None),
    "pd_abrv_nm": ("short_name", "text", None),
    "pd_circ_net_tamt": ("circulating_net_assets", "numeric", "amount"),
    "pd_circ_stk_cnt": ("circulating_security_count", "numeric", "shares_or_notes"),
    "pd_curr_cd": ("product_currency", "text", None),
    "pd_curr_nm": ("product_currency_name", "text", None),
    "pd_divd_amt_ann": ("estimated_annual_distribution", "numeric", "amount_per_share"),
    "pd_divd_amt_pshr": ("distribution_per_share", "numeric", "amount_per_share"),
    "pd_dvid_base_dt": ("distribution_as_of", "date", None),
    "pd_dvid_cycl": ("distribution_cycle", "text", None),
    "pd_dvid_inc_dist": ("source_distribution_amount", "numeric", "source_defined_amount"),
    "pd_dvid_nav": ("distribution_calculation_nav", "numeric", "nav_per_share"),
    "pd_dvid_pay_cnt": ("annual_distribution_count", "numeric", "count"),
    "pd_dvid_pay_months": ("distribution_payment_months", "text", None),
    "pd_dvid_prc_base_dt": ("distribution_nav_as_of", "date", None),
    "pd_dvid_tax_basis": ("distribution_tax_basis", "text", None),
    "pd_dvid_yield": ("annualized_distribution_yield", "numeric", "percentage_point_annualized"),
    "pd_exg_mkt_cd": ("exchange_code", "text", "code"),
    "pd_exg_mkt_nm": ("exchange_name", "text", None),
    "pd_grp_no": ("product_type", "text", None),
    "pd_isin_cd": ("isin_raw", "text", None),
    "pd_itm_no": ("product_id", "text", None),
    "pd_itm_no_ma": ("internal_product_id", "text", None),
    "pd_lst_stk_cnt": ("listed_security_count", "numeric", "shares_or_notes"),
    "pd_lste_dt": ("trading_end_date", "date", None),
    "pd_lstg_dt": ("listing_date", "date", None),
    "pd_mkt_id": ("market_code_raw", "text", "code"),
    "pd_mkt_nm": ("market_name", "text", None),
    "pd_net_tamt": ("net_assets", "numeric", "amount"),
    "pd_nm": ("name", "text", None),
    "pd_pen_risk_nm": ("pension_risk_class", "text", None),
    "pd_pen_tr_yn": ("pension_trade_eligible", "boolean", None),
    "pd_ric": ("refinitiv_ric", "text", None),
    "pd_risk_cd": ("risk_grade_code_raw", "text", "code"),
    "pd_risk_nm": ("risk_grade_name", "text", None),
    "pd_sale_yn": ("saleable_in_master", "boolean", None),
    "pd_sect_cd": ("sector_code_raw", "text", "code"),
    "pd_spac_yn": ("is_spac", "boolean", None),
    "pd_stk_cnt": ("security_count", "numeric", "shares_or_notes"),
    "pd_ticker": ("refinitiv_ticker", "text", None),
    "pd_tr_yn": ("trading_suspended", "boolean", None),
    "ref_ast_type": ("refinitiv_asset_type", "text", None),
    "ref_base_dt": ("refinitiv_as_of", "date", None),
    "ref_base_index": ("refinitiv_base_index_raw", "text", None),
    "ref_fund_mgmt_co": ("refinitiv_fund_manager_raw", "text", None),
    "ref_geo_focus": ("refinitiv_geographic_focus", "text", None),
    "ru_mkt_price": ("runtime_market_price_raw", "numeric", "price"),
    "ru_mkt_volume": ("runtime_market_volume_raw", "numeric", "shares_or_notes"),
    "wu_core_yn": ("internal_core_flag", "boolean", None),
    "wu_inv_ast_type": ("investment_asset_type", "text", None),
    "wu_inv_rgn": ("investment_region", "text", None),
    "wu_upt_dt": ("classification_updated_on", "date", None),
}

_DATE_FIELDS = frozenset(
    {
        "cu_upt_dt",
        "du_chas_errt_base_dt",
        "du_diff_rt_base_dt",
        "du_nav_base_dt",
        "du_upt_dt",
        "du_vlty_base_dt",
        "fn_base_dt",
        "fn_portfolio_dt",
        "pd_dvid_base_dt",
        "pd_dvid_prc_base_dt",
        "pd_lste_dt",
        "pd_lstg_dt",
        "ref_base_dt",
        "wu_upt_dt",
    }
)
_CUTOFF_DATE_FIELDS = _DATE_FIELDS - {"pd_lste_dt"}
_BOOLEAN_VALUES: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {
    "pd_pen_tr_yn": (frozenset({"Y"}), frozenset({"N"})),
    "pd_sale_yn": (frozenset({"1"}), frozenset({"0"})),
    "pd_spac_yn": (frozenset({"Y"}), frozenset({"N"})),
    "pd_tr_yn": (frozenset({"1"}), frozenset({"0"})),
    "wu_core_yn": (frozenset({"Y"}), frozenset({"N"})),
}
_RELATION_FIELDS = frozenset(
    {"cu_base_index", "cu_fund_mgmt_co", "ref_base_index", "ref_fund_mgmt_co"}
)
_RETURN_FIELDS = frozenset(
    {"du_er_1d", "du_er_1m", "du_er_1y", "du_er_3m", "du_er_6m", "du_er_ytd"}
)
_VOLATILITY_FIELDS = frozenset(
    {"du_vlty_1m", "du_vlty_1y", "du_vlty_3m", "du_vlty_6m"}
)
_PERIOD_END_FIELDS = _RETURN_FIELDS | _VOLATILITY_FIELDS | frozenset(
    {
        "du_val_1d",
        "du_val_1m",
        "du_val_5d",
        "du_vol_1d",
        "du_vol_avg_1m",
        "du_vol_avg_5d",
        "pd_dvid_pay_cnt",
        "pd_dvid_pay_months",
        "pd_dvid_yield",
    }
)
_CURRENCY_FIELDS = frozenset(
    {
        "du_bpr",
        "du_clpr",
        "du_hpr",
        "du_last_aum",
        "du_last_nav",
        "du_lpr",
        "du_nav_rnf_amt",
        "du_nav_yday",
        "du_val_1d",
        "du_val_1m",
        "du_val_5d",
        "pd_circ_net_tamt",
        "pd_divd_amt_ann",
        "pd_divd_amt_pshr",
        "pd_dvid_inc_dist",
        "pd_dvid_nav",
        "pd_net_tamt",
        "ru_mkt_price",
    }
)
_DU_DATE_FIELDS = frozenset(
    {
        "du_clpr",
        "du_er_1d",
        "du_er_1m",
        "du_er_1y",
        "du_er_3m",
        "du_er_6m",
        "du_er_ytd",
        "du_hpr",
        "du_last_aum",
        "du_lpr",
        "du_val_1d",
        "du_val_1m",
        "du_val_5d",
        "du_vol_1d",
        "du_vol_avg_1m",
        "du_vol_avg_5d",
        "pd_circ_net_tamt",
        "pd_circ_stk_cnt",
        "pd_lst_stk_cnt",
        "pd_net_tamt",
        "pd_pen_risk_nm",
        "pd_pen_tr_yn",
        "pd_risk_cd",
        "pd_risk_nm",
        "pd_sale_yn",
        "pd_spac_yn",
        "pd_stk_cnt",
        "pd_tr_yn",
    }
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
    "evidence.evidence_record",
    "evidence.evidence_observation_origin",
    "evidence.evidence_relation_origin",
)


@dataclass(frozen=True, slots=True)
class DomesticEtpAnalysis:
    duplicate_internal_ids: frozenset[str]
    duplicate_rics: frozenset[str]

    def identifier_is_unique(self, column: str, value: str) -> bool:
        normalized = normalize_name(value).upper()
        if column == "pd_itm_no_ma":
            return normalized not in self.duplicate_internal_ids
        if column == "pd_ric":
            return normalized not in self.duplicate_rics
        raise KeyError(column)


def _source_text(row: Mapping[str, object], column: str) -> str:
    raw = row.get(column)
    if raw is None:
        return ""
    return normalize_name(str(raw))


def analyze_domestic_etp_rows(
    rows: Iterable[Mapping[str, object]],
) -> DomesticEtpAnalysis:
    internal_ids: Counter[str] = Counter()
    rics: Counter[str] = Counter()
    for row in rows:
        for column, counter in (("pd_itm_no_ma", internal_ids), ("pd_ric", rics)):
            value = _source_text(row, column).upper()
            if value not in {"", "NULL"}:
                counter[value] += 1
    return DomesticEtpAnalysis(
        duplicate_internal_ids=frozenset(
            value for value, count in internal_ids.items() if count > 1
        ),
        duplicate_rics=frozenset(
            value for value, count in rics.items() if count > 1
        ),
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
    if status != "present":
        return status, normalized, reason
    if column in {"cu_base_index", "ref_base_index"} and normalized in _INDEX_PLACEHOLDERS:
        return "placeholder", None, "SOURCE_VALUE_PLACEHOLDER"
    if column == "pd_grp_no" and normalized not in {"ETF", "ETN"}:
        return "unknown", None, "UNSUPPORTED_PRODUCT_TYPE"
    if column == "pd_dvid_cycl" and normalized not in {"A", "Q", "M", "S"}:
        return "unknown", None, "UNDEFINED_DISTRIBUTION_CYCLE"
    return status, normalized, reason


def _numeric_result(
    raw: object,
) -> tuple[str, object | None, str | None]:
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
    column: str,
    raw: object,
) -> tuple[str, object | None, str | None]:
    sentinels = frozenset({"99991231"}) if column == "pd_lste_dt" else frozenset()
    if isinstance(raw, datetime):
        parsed = raw.date()
        return "present", parsed, None
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
) -> dict[str, object]:
    semantic_family = (
        "organizer_domestic_etp_evidence_only"
        if column in EVIDENCE_ONLY_COLUMNS
        else "organizer_domestic_etp"
    )
    payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "2",
        "semantic_family": semantic_family,
        "value_kind": value_kind,
        "default_unit": unit,
        "description": f"Organizer PREF01N001 field {column}",
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
) -> dict[str, object]:
    evidence_value = normalized if status in {"present", "zero"} else None
    source_value = evidence_value
    payload: dict[str, object] = {
        "evidence_id": stable_id("evidence", _SOURCE_CODE, f"{record_key}:{column}"),
        "evidence_kind": evidence_kind,
        "source_id": _SOURCE_ID,
        "subject_id": subject_id,
        "predicate_id": predicate_id,
        "value_or_object_id": _tag(source_value),
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
    value_kind: str,
    unit: str | None,
    currency: str | None,
    applicable_date: date | None,
    period_end: date | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    metric_suffix, _, _ = _METRIC_SPECS[column]
    metric_id = f"organizer.pref01n001.{metric_suffix}"
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
    _, value_kind, unit = _METRIC_SPECS[column]
    definition, observation, evidence, origin = _observation_records(
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


def _append_relation(
    records_by_table: dict[str, list[Mapping[str, object]]],
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    predicate_id: str,
    object_type: str,
    object_name: str,
    source_columns: tuple[tuple[str, object, date | None], ...],
    institution_kind: str | None = None,
    object_id_override: str | None = None,
) -> None:
    object_key = (
        f"{institution_kind}:{object_name}"
        if object_type == "institution" and institution_kind is not None
        else object_name
    )
    object_id = object_id_override or stable_id(
        object_type, _SOURCE_CODE, object_key
    )
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
    valid_dates = tuple(item[2] for item in source_columns if item[2] is not None)
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
                "valid_from": max(valid_dates) if valid_dates else None,
                "valid_to": None,
            }
        )
    )
    for column, raw, applicable_date in source_columns:
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


def _applicable_date(
    column: str,
    date_values: Mapping[str, date | None],
) -> date | None:
    if column in _DATE_FIELDS:
        value = date_values[column]
        return value if value is not None and value <= _CUTOFF_DATE else None
    if column.startswith("cu_"):
        return date_values["cu_upt_dt"]
    if column == "du_bpr" or column in {"du_last_nav", "du_nav_rnf_amt", "du_nav_yday"}:
        return date_values["du_nav_base_dt"] or date_values["du_upt_dt"]
    if column == "du_chas_errt":
        return date_values["du_chas_errt_base_dt"]
    if column == "du_diff_rt":
        return date_values["du_diff_rt_base_dt"]
    if column in _VOLATILITY_FIELDS:
        return date_values["du_vlty_base_dt"]
    if column in _DU_DATE_FIELDS:
        return date_values["du_upt_dt"]
    if column.startswith("fn_"):
        return date_values["fn_base_dt"] or date_values["fn_portfolio_dt"]
    if column == "pd_dvid_nav":
        return date_values["pd_dvid_prc_base_dt"]
    if column.startswith("pd_dvid_") or column.startswith("pd_divd_"):
        return date_values["pd_dvid_base_dt"]
    if column.startswith("ref_"):
        return date_values["ref_base_dt"]
    if column.startswith("wu_") or column == "pd_sect_cd":
        return date_values["wu_upt_dt"]
    return None


def _parsed_value(
    column: str,
    raw: object,
    date_results: Mapping[str, tuple[str, object | None, str | None]],
) -> tuple[str, object | None, str | None]:
    _, value_kind, _ = _METRIC_SPECS[column]
    if value_kind == "date":
        return date_results[column]
    if value_kind == "numeric":
        return _numeric_result(raw)
    if value_kind == "boolean":
        return _boolean_result(column, raw)
    return _text_result(column, raw)


def _append_relation_fallback(
    records_by_table: dict[str, list[Mapping[str, object]]],
    issues: list[MappingIssue],
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    column: str,
    row: Mapping[str, object],
    status: str,
    normalized: object | None,
    reason: str | None,
    applicable_date: date | None,
    conflict: bool = False,
) -> None:
    issue_code = "SOURCE_RELATION_VALUE_CONFLICT" if conflict else reason
    if conflict or status not in {"present", "zero"}:
        _append_issue(
            issues,
            row_number=row_number,
            column=column,
            code=issue_code,
        )
    _append_observation(
        records_by_table,
        row_number=row_number,
        record_key=record_key,
        product_id=product_id,
        column=column,
        raw=row.get(column),
        status=status,
        normalized=normalized,
        reason_code=reason if status not in {"present", "zero"} else None,
        currency=None,
        applicable_date=applicable_date,
        period_end=None,
    )


def map_row(
    row_number: int,
    row: Mapping[str, object],
    *,
    analysis: DomesticEtpAnalysis,
    identity_index: AuthoritativeIdentityIndex,
) -> MappedRow:
    record_key = _source_text(row, "pd_itm_no")
    if not record_key or record_key.upper() == "NULL":
        return _quarantined(row_number, "pd_itm_no", "MISSING_NATURAL_KEY")
    canonical_name = _source_text(row, "pd_nm")
    if not canonical_name or canonical_name.upper() == "NULL":
        return _quarantined(row_number, "pd_nm", "MISSING_REQUIRED_NAME")

    resolution = identity_index.resolve("PREF01_PD_ITM_NO", record_key)
    if resolution.status != "MATCHED" or resolution.canonical_identity is None:
        return _quarantined(
            row_number,
            "pd_itm_no",
            "IDENTITY_RESOLUTION_FAILED",
            fatal=True,
        )
    product_id = resolution.canonical_identity.entity_id
    records_by_table = _empty_records()
    issues: list[MappingIssue] = []
    current_column = "pd_grp_no"

    try:
        group_status, group_value, group_reason = _text_result(
            "pd_grp_no", row.get("pd_grp_no")
        )
        if group_status != "present" or not isinstance(group_value, str):
            return _quarantined(
                row_number,
                "pd_grp_no",
                group_reason or "UNSUPPORTED_PRODUCT_TYPE",
                fatal=True,
            )
        expected_role = f"Domestic{group_value}"
        if expected_role not in resolution.canonical_identity.roles:
            return _quarantined(
                row_number,
                "pd_grp_no",
                "IDENTITY_ROLE_MISMATCH",
                fatal=True,
            )

        date_results = {
            column: _date_result(column, row.get(column)) for column in _DATE_FIELDS
        }
        date_values = {
            column: result[1] if isinstance(result[1], date) else None
            for column, result in date_results.items()
        }
        for column in _CUTOFF_DATE_FIELDS:
            current_column = column
            value = date_values[column]
            if value is not None and value > _CUTOFF_DATE:
                return _quarantined(
                    row_number,
                    column,
                    "AFTER_CUTOFF_SOURCE_VALUE",
                    fatal=True,
                )

        currency_status, currency_value, _ = _text_result(
            "pd_curr_cd", row.get("pd_curr_cd")
        )
        primary_currency = (
            currency_value.upper()
            if currency_status == "present"
            and isinstance(currency_value, str)
            and len(currency_value) == 3
            and currency_value.isalpha()
            else None
        )
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
                "product_family": "domestic_etf",
                "primary_currency": primary_currency,
            }
        )
        _append_identifier(
            records_by_table,
            product_id=product_id,
            scheme="PREF01_PD_ITM_NO",
            value=record_key.upper(),
            primary=True,
        )

        emitted_isins: set[str] = set()
        for column, candidate in (
            ("pd_itm_no", record_key.upper()),
            ("pd_isin_cd", _source_text(row, "pd_isin_cd").upper()),
        ):
            if candidate in {"", "NULL"} or candidate in emitted_isins:
                continue
            isin_resolution = identity_index.resolve("ISIN", candidate)
            if isin_resolution.status == "NOT_FOUND" and column == "pd_itm_no":
                continue
            if (
                isin_resolution.status != "MATCHED"
                or isin_resolution.canonical_identity is None
                or isin_resolution.canonical_identity.entity_id != product_id
            ):
                return _quarantined(
                    row_number,
                    column,
                    "IDENTITY_RESOLUTION_FAILED",
                    fatal=True,
                )
            _append_identifier(
                records_by_table,
                product_id=product_id,
                scheme="ISIN",
                value=candidate,
                primary=False,
            )
            emitted_isins.add(candidate)

        for column, scheme in (
            ("pd_itm_no_ma", "PREF01_PD_ITM_NO_MA"),
            ("pd_ric", "REFINITIV_RIC"),
        ):
            value = _source_text(row, column).upper()
            if value in {"", "NULL"}:
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

        aliases: set[str] = set()
        for column in ("pd_abrv_nm", "pd_ticker"):
            status, normalized, _ = _text_result(column, row.get(column))
            if status != "present" or not isinstance(normalized, str):
                continue
            normalized_alias = normalized.upper()
            if normalized_alias in aliases:
                continue
            aliases.add(normalized_alias)
            records_by_table["catalog.alias"].append(
                _with_record_hash(
                    {
                        "alias_id": stable_id(
                            "alias", _SOURCE_CODE, f"{record_key}:{normalized_alias}"
                        ),
                        "entity_id": product_id,
                        "alias_text": normalized,
                        "normalized_alias_text": normalized_alias,
                        "valid_from": None,
                        "valid_to": None,
                    }
                )
            )

        relation_consumed: set[str] = set()
        index_results = {
            column: _text_result(column, row.get(column))
            for column in ("cu_base_index", "ref_base_index")
        }
        present_indexes = {
            column: value
            for column, (status, value, _) in index_results.items()
            if status == "present" and isinstance(value, str)
        }
        if len(set(present_indexes.values())) > 1:
            for column in ("cu_base_index", "ref_base_index"):
                status, normalized, reason = index_results[column]
                _append_relation_fallback(
                    records_by_table,
                    issues,
                    row_number=row_number,
                    record_key=record_key,
                    product_id=product_id,
                    column=column,
                    row=row,
                    status=status,
                    normalized=normalized,
                    reason=reason,
                    applicable_date=(
                        date_values["cu_upt_dt"]
                        if column == "cu_base_index"
                        else date_values["ref_base_dt"]
                    ),
                    conflict=True,
                )
                relation_consumed.add(column)
        elif present_indexes:
            object_name = next(iter(present_indexes.values()))
            source_columns = tuple(
                (
                    column,
                    row.get(column),
                    date_values["cu_upt_dt"]
                    if column == "cu_base_index"
                    else date_values["ref_base_dt"],
                )
                for column in ("cu_base_index", "ref_base_index")
                if column in present_indexes
            )
            _append_relation(
                records_by_table,
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                predicate_id="tracksIndex",
                object_type="index",
                object_name=object_name,
                source_columns=source_columns,
            )
            relation_consumed.update(present_indexes)

        manager_columns = ("cu_fund_mgmt_co", "ref_fund_mgmt_co")
        manager_results = {
            column: _text_result(column, row.get(column)) for column in manager_columns
        }
        if group_value == "ETF":
            manager_resolution = resolve_etf_asset_manager(
                manager_results["cu_fund_mgmt_co"][1],
                manager_results["ref_fund_mgmt_co"][1],
            )
            if manager_resolution.identity is not None:
                manager_id = append_asset_manager_catalog_records(
                    records_by_table,
                    identity=manager_resolution.identity,
                    accepted_aliases=manager_resolution.accepted_aliases,
                )
                source_columns = tuple(
                    (
                        column,
                        row.get(column),
                        date_values["cu_upt_dt"]
                        if column == "cu_fund_mgmt_co"
                        else date_values["ref_base_dt"],
                    )
                    for column in manager_resolution.supporting_fields
                )
                _append_relation(
                    records_by_table,
                    row_number=row_number,
                    record_key=record_key,
                    product_id=product_id,
                    predicate_id="managedBy",
                    object_type="institution",
                    object_name=manager_resolution.identity.canonical_name,
                    source_columns=source_columns,
                    institution_kind="asset_manager",
                    object_id_override=manager_id,
                )
                relation_consumed.update(manager_resolution.supporting_fields)
            for column in manager_resolution.fallback_fields:
                status, normalized, reason = manager_results[column]
                _append_relation_fallback(
                    records_by_table,
                    issues,
                    row_number=row_number,
                    record_key=record_key,
                    product_id=product_id,
                    column=column,
                    row=row,
                    status=status,
                    normalized=normalized,
                    reason=reason,
                    applicable_date=(
                        date_values["cu_upt_dt"]
                        if column == "cu_fund_mgmt_co"
                        else date_values["ref_base_dt"]
                    ),
                    conflict=manager_resolution.status == "conflict",
                )
                relation_consumed.add(column)
        else:
            status, normalized, _ = manager_results["cu_fund_mgmt_co"]
            if status == "present" and isinstance(normalized, str):
                _append_relation(
                    records_by_table,
                    row_number=row_number,
                    record_key=record_key,
                    product_id=product_id,
                    predicate_id="issuedBy",
                    object_type="institution",
                    object_name=normalized,
                    source_columns=(
                        (
                            "cu_fund_mgmt_co",
                            row.get("cu_fund_mgmt_co"),
                            date_values["cu_upt_dt"],
                        ),
                    ),
                    institution_kind="issuer",
                )
                relation_consumed.add("cu_fund_mgmt_co")

        for column in _RELATION_FIELDS - relation_consumed:
            status, normalized, reason = (
                index_results[column]
                if column in index_results
                else manager_results[column]
            )
            _append_relation_fallback(
                records_by_table,
                issues,
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                column=column,
                row=row,
                status=status,
                normalized=normalized,
                reason=reason,
                applicable_date=_applicable_date(column, date_values),
            )

        for column in SPEC.expected_columns:
            if column in _RELATION_FIELDS:
                continue
            current_column = column
            raw = row.get(column)
            status, normalized, reason_code = _parsed_value(
                column, raw, date_results
            )
            if status not in {"present", "zero"}:
                _append_issue(
                    issues,
                    row_number=row_number,
                    column=column,
                    code=reason_code,
                )
            applicable_date = _applicable_date(column, date_values)
            period_end = applicable_date if column in _PERIOD_END_FIELDS else None
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
