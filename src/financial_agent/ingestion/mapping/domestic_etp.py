from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
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
_KST = timezone(timedelta(hours=9))
_SOURCE_CODE = "PREF01N001"
_SOURCE_FILE = "PREF01N001_국내ETF마스터_20260711_datarows.xlsx"
_SOURCE_ID = stable_id("source", _SOURCE_CODE, _SOURCE_FILE)
_MISSING_VALUES = frozenset({None, "", "NULL"})
_INDEX_PLACEHOLDERS = frozenset({"없음", "미제공", "제공되지 않음", "해당없음", "N/A"})

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
    "du_clpr",
    "du_diff_rt",
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
    "du_nav_rnf_amt",
    "du_nav_yday",
    "du_upt_dt",
    "du_val_1d",
    "du_val_1m",
    "du_val_5d",
    "du_vol_1d",
    "du_vol_avg_1m",
    "du_vol_avg_5d",
    "nru_mkt_diff_rt",
    "nru_mkt_inav",
    "pd_abrv_nm",
    "pd_circ_net_tamt",
    "pd_circ_stk_cnt",
    "pd_curr_cd",
    "pd_curr_nm",
    "pd_divd_amt_pshr",
    "pd_dvid_cycl",
    "pd_dvid_yield",
    "pd_exg_mkt_cd",
    "pd_exg_mkt_nm",
    "pd_grp_no",
    "pd_itm_no",
    "pd_itm_no_ma",
    "pd_lst_price",
    "pd_lst_stk_cnt",
    "pd_lste_dt",
    "pd_lstg_dt",
    "pd_mkt_id",
    "pd_mkt_nm",
    "pd_nav_pshr",
    "pd_net_ast_pshr",
    "pd_net_prft_pshr",
    "pd_net_rt_ast_pshr",
    "pd_net_tamt",
    "pd_nm",
    "pd_pen_risk_nm",
    "pd_pen_tr_yn",
    "pd_risk_cd",
    "pd_risk_nm",
    "pd_sale_yn",
    "pd_sect_cd",
    "pd_sect_nm",
    "pd_spac_yn",
    "pd_stk_cnt",
    "pd_tr_yn",
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
    data_sheet_name="datarows",
    schema_file_name="PREF01N001_국내ETF마스터_schema.xlsx",
    schema_sheet_name="Sheet1_Schema",
    expected_columns=_EXPECTED_COLUMNS,
    expected_row_count=1_734,
    natural_key=("pd_itm_no",),
    parser_version="1",
    mapping_version="1",
)

IGNORED_COLUMNS: Mapping[str, str] = {
    "cu_charge_etc_rt": "UNUSABLE_ALL_ZERO_SERIES",
    "du_chas_errt": "UNUSABLE_ALL_ZERO_SERIES",
    "du_diff_rt": "UNUSABLE_ALL_ZERO_SERIES",
    "du_nav_rnf_amt": "FAILED_DERIVATION_CHECK",
    "nru_mkt_diff_rt": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
    "nru_mkt_inav": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
    "pd_divd_amt_pshr": "UNUSABLE_ALL_ZERO_SERIES",
    "pd_dvid_cycl": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
    "pd_dvid_yield": "UNUSABLE_ALL_ZERO_SERIES",
    "pd_lst_price": "UNUSABLE_ALL_ZERO_SERIES",
    "pd_net_ast_pshr": "UNUSABLE_ALL_ZERO_SERIES",
    "pd_net_prft_pshr": "UNUSABLE_ALL_ZERO_SERIES",
    "pd_net_rt_ast_pshr": "UNUSABLE_ALL_ZERO_SERIES",
    "pd_sect_nm": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
    "pd_spac_yn": "NOT_ANSWERABLE",
    "ru_mkt_price": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
    "ru_mkt_volume": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
}
HANDLED_COLUMNS = frozenset(_EXPECTED_COLUMNS) - frozenset(IGNORED_COLUMNS)

_METRIC_SPECS: Mapping[str, tuple[str, str, str | None]] = {
    "cu_charge_rt": ("total_fee_rate", "numeric", "percentage_point"),
    "cu_lev_fector": ("leverage_factor", "numeric", "multiple"),
    "cu_strtegy": ("strategy_raw", "text", None),
    "cu_upt_dt": ("structure_updated_on", "date", None),
    "du_bpr": ("base_price", "numeric", "price_per_share"),
    "du_clpr": ("close_price", "numeric", "price_per_share"),
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
    "du_nav_yday": ("previous_nav_per_share", "numeric", "nav_per_share"),
    "du_upt_dt": ("daily_updated_at", "timestamp", None),
    "du_val_1d": ("trading_value_1d", "numeric", "amount"),
    "du_val_1m": ("average_trading_value_1m", "numeric", "amount"),
    "du_val_5d": ("average_trading_value_5d", "numeric", "amount"),
    "du_vol_1d": ("trading_volume_1d", "numeric", "shares_or_notes"),
    "du_vol_avg_1m": (
        "average_trading_volume_1m",
        "numeric",
        "shares_or_notes",
    ),
    "du_vol_avg_5d": (
        "average_trading_volume_5d",
        "numeric",
        "shares_or_notes",
    ),
    "pd_abrv_nm": ("short_name", "text", None),
    "pd_circ_net_tamt": ("circulating_net_assets", "numeric", "amount"),
    "pd_circ_stk_cnt": (
        "circulating_security_count",
        "numeric",
        "shares_or_notes",
    ),
    "pd_curr_cd": ("product_currency", "text", None),
    "pd_curr_nm": ("product_currency_name", "text", None),
    "pd_exg_mkt_cd": ("exchange_code", "text", "code"),
    "pd_exg_mkt_nm": ("exchange_name", "text", None),
    "pd_grp_no": ("product_type", "text", None),
    "pd_itm_no": ("product_id", "text", None),
    "pd_itm_no_ma": ("internal_product_id", "text", None),
    "pd_lst_stk_cnt": ("listed_security_count", "numeric", "shares_or_notes"),
    "pd_lste_dt": ("trading_end_date", "date", None),
    "pd_lstg_dt": ("listing_date", "date", None),
    "pd_mkt_id": ("market_code", "text", "code"),
    "pd_mkt_nm": ("market_name", "text", None),
    "pd_nav_pshr": ("net_asset_value_per_share", "numeric", "nav_per_share"),
    "pd_net_tamt": ("net_assets", "numeric", "amount"),
    "pd_nm": ("name", "text", None),
    "pd_pen_risk_nm": ("pension_risk_class", "text", None),
    "pd_pen_tr_yn": ("pension_trade_eligible", "boolean", None),
    "pd_risk_cd": ("risk_grade_code", "text", "code"),
    "pd_risk_nm": ("risk_grade_name", "text", None),
    "pd_sale_yn": ("saleable_in_master", "boolean", None),
    "pd_sect_cd": ("sector_code_raw", "text", "code"),
    "pd_stk_cnt": ("stock_count_raw", "numeric", "shares_or_notes"),
    "pd_tr_yn": ("trading_suspended", "boolean", None),
    "wu_core_yn": ("internal_core_flag", "boolean", None),
    "wu_inv_ast_type": ("investment_asset_type", "text", None),
    "wu_inv_rgn": ("investment_region", "text", None),
    "wu_upt_dt": ("classification_updated_on", "date", None),
}

_DATE_SENTINELS: Mapping[str, frozenset[str]] = {
    "cu_upt_dt": frozenset(),
    "pd_lste_dt": frozenset({"99991231"}),
    "pd_lstg_dt": frozenset(),
    "wu_upt_dt": frozenset(),
}
_BOOLEAN_VALUES: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {
    "pd_pen_tr_yn": (frozenset({"Y"}), frozenset({"N"})),
    "pd_sale_yn": (frozenset({"1"}), frozenset({"0"})),
    "pd_tr_yn": (frozenset({"1"}), frozenset({"0"})),
    "wu_core_yn": (frozenset({"Y"}), frozenset({"N"})),
}
_RETURN_FIELDS = frozenset(
    {"du_er_1d", "du_er_1m", "du_er_1y", "du_er_3m", "du_er_6m", "du_er_ytd"}
)
_CU_FIELDS = frozenset(
    {"cu_charge_rt", "cu_lev_fector", "cu_strtegy", "cu_upt_dt"}
)
_DU_FIELDS = frozenset(
    column for column in _METRIC_SPECS if column.startswith("du_")
)
_DU_DATED_PD_FIELDS = frozenset(
    {
        "pd_circ_net_tamt",
        "pd_circ_stk_cnt",
        "pd_nav_pshr",
        "pd_net_tamt",
        "pd_stk_cnt",
    }
)
_WU_FIELDS = frozenset(
    {"wu_core_yn", "wu_inv_ast_type", "wu_inv_rgn", "wu_upt_dt"}
)
_PERIOD_END_FIELDS = _RETURN_FIELDS | frozenset(
    {
        "du_val_1d",
        "du_val_1m",
        "du_val_5d",
        "du_vol_1d",
        "du_vol_avg_1m",
        "du_vol_avg_5d",
    }
)
_KRW_FIELDS = frozenset(
    {
        "du_bpr",
        "du_clpr",
        "du_hpr",
        "du_last_aum",
        "du_last_nav",
        "du_lpr",
        "du_nav_yday",
        "du_val_1d",
        "du_val_1m",
        "du_val_5d",
        "pd_circ_net_tamt",
        "pd_nav_pshr",
        "pd_net_tamt",
    }
)
_RELATION_FIELDS = frozenset({"cu_base_index", "cu_fund_mgmt_co"})
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
        "semantic_family": "organizer_domestic_etp",
        "value_kind": value_kind,
        "default_unit": unit,
        "description": f"Organizer PREF01N001 field {column}",
        "approved_at": _DEFINITION_APPROVED_AT,
    }
    payload["definition_hash"] = make_record_hash(payload)
    return payload


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
    if column == "cu_base_index" and normalized in _INDEX_PLACEHOLDERS:
        return "placeholder", None, "SOURCE_VALUE_PLACEHOLDER"
    if column == "cu_strtegy" and normalized == "C":
        return "unknown", None, "UNDEFINED_STRATEGY_CODE"
    if column == "pd_curr_cd" and normalized in {"000", "CURR_CD_000"}:
        return "inapplicable", None, "SOURCE_VALUE_INAPPLICABLE"
    if column == "pd_pen_risk_nm" and normalized == "N":
        return "inapplicable", None, "SOURCE_VALUE_INAPPLICABLE"
    if column == "pd_grp_no" and normalized not in {"ETF", "ETN"}:
        return "unknown", None, "UNSUPPORTED_PRODUCT_TYPE"
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
    if column in _RETURN_FIELDS and normalized == Decimal("-100"):
        return "placeholder", None, "RETURN_SENTINEL_CANDIDATE"
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


def _timestamp_result(
    raw: object,
) -> tuple[str, object | None, str | None, date | None]:
    if raw is None or (isinstance(raw, str) and normalize_name(raw) in {"", "NULL"}):
        return "missing", None, "SOURCE_VALUE_MISSING", None
    if isinstance(raw, (bool, float)):
        raise TypeError("timestamp source value has an unsupported type")

    if isinstance(raw, datetime):
        if raw.tzinfo is not None:
            raise ValueError("source timestamp must be timezone-naive")
        local_value = raw
    elif isinstance(raw, date):
        local_value = datetime.combine(raw, datetime.min.time())
    elif isinstance(raw, str):
        token = normalize_name(raw)
        try:
            local_value = datetime.fromisoformat(token)
        except ValueError:
            parsed_date = parse_yyyymmdd(token, sentinels=frozenset())
            if parsed_date is None:
                raise ValueError("source timestamp is invalid") from None
            local_value = datetime.combine(parsed_date, datetime.min.time())
        if local_value.tzinfo is not None:
            raise ValueError("source timestamp must be timezone-naive")
    else:
        raise TypeError("timestamp source value has an unsupported type")

    normalized = local_value.replace(tzinfo=_KST).astimezone(UTC)
    return "present", normalized, None, local_value.date()


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
    source_value = (
        evidence_value
        if column == "du_upt_dt" or evidence_kind == "relation"
        else raw
    )
    if status not in {"present", "zero"}:
        source_value = None
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


def _relation_records(
    *,
    row_number: int,
    record_key: str,
    product_id: str,
    column: str,
    raw: object,
    entity_type: str,
    predicate_id: str,
    applicable_date: date | None,
    institution_kind: str | None = None,
) -> tuple[
    dict[str, object],
    dict[str, object] | None,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    status, normalized, _ = _text_result(column, raw)
    if status != "present" or not isinstance(normalized, str):
        raise ValueError("relation source value must be present")

    object_id = stable_id(entity_type, _SOURCE_CODE, normalized)
    entity = _with_record_hash(
        {
            "entity_id": object_id,
            "entity_type": entity_type,
            "canonical_name": normalized,
            "normalized_name": normalized,
        }
    )
    institution = None
    if entity_type == "institution" and institution_kind is not None:
        institution = {
            "entity_id": object_id,
            "institution_kind": institution_kind,
        }
    relation_id = stable_id(
        "relation",
        _SOURCE_CODE,
        f"{record_key}:{predicate_id}:{object_id}",
    )
    relation = _with_record_hash(
        {
            "relation_id": relation_id,
            "subject_id": product_id,
            "predicate_id": predicate_id,
            "object_id": object_id,
            "valid_from": applicable_date,
            "valid_to": None,
        }
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
    origin = {"evidence_id": evidence["evidence_id"], "relation_id": relation_id}
    return entity, institution, relation, evidence, origin


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
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    metric_suffix, _, _ = _METRIC_SPECS[column]
    metric_id = f"organizer.pref01n001.{metric_suffix}"
    observation_id = stable_id("observation", _SOURCE_CODE, f"{record_key}:{column}")
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
            "period_end": period_end,
            "applicable_date": applicable_date,
            "published_at": None,
            "available_at": None,
            "vintage_date": _CUTOFF_DATE,
            "reason_code": reason_code,
        }
    )
    evidence_applicable_date = (
        applicable_date
        if applicable_date is None or applicable_date <= _CUTOFF_DATE
        else None
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
        applicable_date=evidence_applicable_date,
    )
    origin = {
        "evidence_id": evidence["evidence_id"],
        "observation_id": observation_id,
    }
    definition = _metric_definition(column, metric_id, value_kind, unit)
    return definition, observation, evidence, origin


def _required_text(row: Mapping[str, object], column: str) -> str:
    raw = row.get(column)
    return normalize_name(raw) if isinstance(raw, str) else ""


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


def map_row(row_number: int, row: Mapping[str, object]) -> MappedRow:
    record_key = _required_text(row, "pd_itm_no")
    if not record_key or record_key == "NULL":
        return _quarantined(row_number, "pd_itm_no", "MISSING_NATURAL_KEY")
    internal_key = _required_text(row, "pd_itm_no_ma")
    if not internal_key or internal_key == "NULL":
        return _quarantined(row_number, "pd_itm_no_ma", "MISSING_NATURAL_KEY")
    canonical_name = _required_text(row, "pd_nm")
    if not canonical_name or canonical_name == "NULL":
        return _quarantined(row_number, "pd_nm", "MISSING_REQUIRED_NAME")

    records_by_table = _empty_records()
    issues: list[MappingIssue] = []
    product_id = stable_id("product", _SOURCE_CODE, record_key)
    current_column = "pd_grp_no"

    try:
        group_status, group_value, group_reason = _text_result(
            "pd_grp_no", row.get("pd_grp_no")
        )
        security_kind = (
            group_value.lower()
            if group_status == "present" and isinstance(group_value, str)
            else "unknown"
        )

        currency_status, primary_currency, _ = _text_result(
            "pd_curr_cd", row.get("pd_curr_cd")
        )
        if currency_status != "present":
            primary_currency = None

        ticker_status, ticker, _ = _text_result(
            "pd_abrv_nm", row.get("pd_abrv_nm")
        )
        if ticker_status != "present":
            ticker = None

        current_column = "cu_upt_dt"
        cu_date_result = _date_result("cu_upt_dt", row.get("cu_upt_dt"))
        current_column = "du_upt_dt"
        du_timestamp_result = _timestamp_result(row.get("du_upt_dt"))
        current_column = "wu_upt_dt"
        wu_date_result = _date_result("wu_upt_dt", row.get("wu_upt_dt"))
        current_column = "pd_lstg_dt"
        listing_date_result = _date_result("pd_lstg_dt", row.get("pd_lstg_dt"))
        current_column = "pd_lste_dt"
        end_date_result = _date_result("pd_lste_dt", row.get("pd_lste_dt"))

        cu_date = cu_date_result[1] if isinstance(cu_date_result[1], date) else None
        du_date = du_timestamp_result[3]
        wu_date = wu_date_result[1] if isinstance(wu_date_result[1], date) else None
        for cutoff_column, cutoff_value in (
            ("cu_upt_dt", cu_date),
            ("du_upt_dt", du_date),
            ("wu_upt_dt", wu_date),
        ):
            if cutoff_value is not None and cutoff_value > _CUTOFF_DATE:
                return _quarantined(
                    row_number,
                    cutoff_column,
                    "AFTER_CUTOFF_SOURCE_VALUE",
                    fatal=True,
                )

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
                "product_family": "domestic_etf",
                "primary_currency": primary_currency,
            }
        )
        for scheme, value, primary in (
            ("PREF01_PD_ITM_NO", record_key, True),
            ("PREF01_PD_ITM_NO_MA", internal_key, False),
        ):
            identifier_id = stable_id("identifier", _SOURCE_CODE, f"{scheme}:{value}")
            records_by_table["catalog.identifier"].append(
                _with_record_hash(
                    {
                        "identifier_id": identifier_id,
                        "entity_id": product_id,
                        "scheme": scheme,
                        "identifier_value": value,
                        "is_primary": primary,
                        "valid_from": None,
                        "valid_to": None,
                    }
                )
            )

        if isinstance(ticker, str):
            alias_id = stable_id(
                "alias", _SOURCE_CODE, f"{record_key}:pd_abrv_nm:{ticker}"
            )
            records_by_table["catalog.alias"].append(
                _with_record_hash(
                    {
                        "alias_id": alias_id,
                        "entity_id": product_id,
                        "alias_text": ticker,
                        "normalized_alias_text": ticker,
                        "valid_from": None,
                        "valid_to": None,
                    }
                )
            )

        index_status, _, index_reason = _text_result(
            "cu_base_index", row.get("cu_base_index")
        )
        if index_status == "present":
            entity, _, relation, relation_evidence, origin = _relation_records(
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                column="cu_base_index",
                raw=row.get("cu_base_index"),
                entity_type="index",
                predicate_id="tracksIndex",
                applicable_date=cu_date,
            )
            records_by_table["catalog.entity"].append(entity)
            records_by_table["relation.relation_record"].append(relation)
            records_by_table["evidence.evidence_record"].append(relation_evidence)
            records_by_table["evidence.evidence_relation_origin"].append(origin)
        else:
            _append_issue(
                issues,
                row_number=row_number,
                column="cu_base_index",
                code=index_reason,
            )

        manager_status, _, manager_reason = _text_result(
            "cu_fund_mgmt_co", row.get("cu_fund_mgmt_co")
        )
        if manager_status == "present" and security_kind in {"etf", "etn"}:
            predicate_id = "managedBy" if security_kind == "etf" else "issuedBy"
            institution_kind = (
                "asset_manager" if security_kind == "etf" else "issuer"
            )
            (
                entity,
                institution,
                relation,
                relation_evidence,
                origin,
            ) = _relation_records(
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                column="cu_fund_mgmt_co",
                raw=row.get("cu_fund_mgmt_co"),
                entity_type="institution",
                predicate_id=predicate_id,
                institution_kind=institution_kind,
                applicable_date=cu_date,
            )
            records_by_table["catalog.entity"].append(entity)
            if institution is not None:
                records_by_table["catalog.institution"].append(institution)
            records_by_table["relation.relation_record"].append(relation)
            records_by_table["evidence.evidence_record"].append(relation_evidence)
            records_by_table["evidence.evidence_relation_origin"].append(origin)
        else:
            _append_issue(
                issues,
                row_number=row_number,
                column="cu_fund_mgmt_co",
                code=manager_reason if manager_status != "present" else group_reason,
            )

        date_results = {
            "cu_upt_dt": cu_date_result,
            "pd_lstg_dt": listing_date_result,
            "pd_lste_dt": end_date_result,
            "wu_upt_dt": wu_date_result,
        }
        for column in SPEC.expected_columns:
            if column in IGNORED_COLUMNS or column in _RELATION_FIELDS:
                continue

            current_column = column
            _, value_kind, unit = _METRIC_SPECS[column]
            raw = row.get(column)
            local_date: date | None = None
            if value_kind == "numeric":
                status, normalized, reason_code = _numeric_result(column, raw)
            elif value_kind == "date":
                status, normalized, reason_code = date_results[column]
            elif value_kind == "timestamp":
                status, normalized, reason_code, local_date = du_timestamp_result
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

            if value_kind == "date" and isinstance(normalized, date):
                applicable_date = normalized
            elif column in _CU_FIELDS:
                applicable_date = cu_date
            elif column in _DU_FIELDS or column in _DU_DATED_PD_FIELDS:
                applicable_date = local_date or du_date
            elif column in _WU_FIELDS:
                applicable_date = wu_date
            else:
                applicable_date = None
            period_end = du_date if column in _PERIOD_END_FIELDS else None
            currency = "KRW" if column in _KRW_FIELDS else None

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
