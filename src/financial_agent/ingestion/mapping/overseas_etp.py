from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Set
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
_SOURCE_CODE = "PREF02N001"
_SOURCE_FILE = "PREF02N001_해외ETF마스터_20260711_datarows.xlsx"
_SOURCE_ID = stable_id("source", _SOURCE_CODE, _SOURCE_FILE)
_MISSING_VALUES = frozenset({None, "", "NULL"})
_INDEX_PLACEHOLDERS = frozenset(
    {
        "Index information is not available",
        "Index is not available",
        "No base index information",
        "N/A",
    }
)
_INDEX_PLACEHOLDER_MARKERS = (
    "not available",
    "not provided",
    "does not provide",
    "unable to provide",
    "unable to obtain",
    "not found",
    "제공하지 않",
    "확인할 수 없",
)
_OPTIONAL_IDENTIFIER_COLUMNS = ("pd_isin_cd", "pd_lipper_id")

_EXPECTED_COLUMNS = (
    "cu_base_index",
    "cu_charge_rt",
    "cu_etn_yn",
    "cu_fund_mgmt_co",
    "cu_index_repl_mthd",
    "cu_index_tracking_yn",
    "cu_inverse_short_yn",
    "cu_lev_fector",
    "cu_strtegy",
    "cu_upt_dt",
    "du_base_dt_match_yn",
    "du_bpr",
    "du_clpr",
    "du_clpr_base_dt",
    "du_clpr_src",
    "du_diff_rt",
    "du_er_1d",
    "du_hpr",
    "du_last_aum",
    "du_last_nav",
    "du_lpr",
    "du_nav_base_dt",
    "du_opr",
    "du_upt_dt",
    "du_val_1d",
    "du_vol_1d",
    "pd_abrv_nm",
    "pd_curr_cd",
    "pd_exg_mkt_cd",
    "pd_grp_no",
    "pd_isin_cd",
    "pd_itm_no",
    "pd_itm_no_ma",
    "pd_lipper_id",
    "pd_lstg_dt",
    "pd_lst_price",
    "pd_lst_stk_cnt",
    "pd_mkt_id",
    "pd_nm",
    "pd_sale_yn",
    "pd_trd_ccy",
    "pd_tr_yn",
    "pd_us_cik",
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
    schema_file_name="PREF02N001_해외ETF마스터_schema.xlsx",
    schema_sheet_name="Sheet1_Schema",
    expected_columns=_EXPECTED_COLUMNS,
    expected_row_count=5_646,
    natural_key=("pd_itm_no",),
    parser_version="1",
    mapping_version="1",
)

IGNORED_COLUMNS: Mapping[str, str] = {
    "cu_lev_fector": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
    "du_diff_rt": "UNTRUSTED_SPARSE_SERIES",
    "du_er_1d": "UNUSABLE_ALL_ZERO_SERIES",
    "pd_lst_price": "UNUSABLE_ALL_ZERO_SERIES",
    "ru_mkt_price": "DUPLICATE_RUNTIME_VALUE_WITHOUT_TIME_BASIS",
    "ru_mkt_volume": "DUPLICATE_RUNTIME_VALUE",
    "wu_core_yn": "NOT_ANSWERABLE",
}
HANDLED_COLUMNS = frozenset(_EXPECTED_COLUMNS) - frozenset(IGNORED_COLUMNS)

_METRIC_SPECS: Mapping[str, tuple[str, str, str | None]] = {
    "cu_charge_rt": ("total_fee_rate", "numeric", "source_defined_rate"),
    "cu_etn_yn": ("is_etn", "boolean", None),
    "cu_fund_mgmt_co": ("provider_name_raw", "text", None),
    "cu_index_repl_mthd": ("index_replication_method", "text", None),
    "cu_index_tracking_yn": ("index_tracking_flag", "boolean", None),
    "cu_inverse_short_yn": ("inverse_short_flag", "boolean", None),
    "cu_strtegy": ("strategy_description", "text", None),
    "cu_upt_dt": ("structure_updated_on", "date", None),
    "du_base_dt_match_yn": ("price_nav_date_match", "boolean", None),
    "du_bpr": ("base_price_raw", "numeric", "source_defined_price"),
    "du_clpr": ("close_price", "numeric", "price_per_share"),
    "du_clpr_base_dt": ("close_price_date", "date", None),
    "du_clpr_src": ("close_price_source_raw", "text", None),
    "du_hpr": ("high_price", "numeric", "price_per_share"),
    "du_last_aum": ("aum", "numeric", "source_defined_amount"),
    "du_last_nav": ("nav_per_share", "numeric", "nav_per_share"),
    "du_lpr": ("low_price", "numeric", "price_per_share"),
    "du_nav_base_dt": ("nav_date", "date", None),
    "du_opr": ("open_price", "numeric", "price_per_share"),
    "du_upt_dt": ("daily_updated_on", "date", None),
    "du_val_1d": ("trading_value_1d", "numeric", "amount"),
    "du_vol_1d": ("trading_volume_1d", "numeric", "shares_or_notes"),
    "pd_abrv_nm": ("ticker", "text", None),
    "pd_curr_cd": ("product_currency", "text", None),
    "pd_exg_mkt_cd": ("exchange_code", "text", "code"),
    "pd_grp_no": ("product_type", "text", None),
    "pd_isin_cd": ("isin", "text", None),
    "pd_itm_no": ("product_id", "text", None),
    "pd_itm_no_ma": ("internal_product_id", "text", None),
    "pd_lipper_id": ("lipper_id", "text", None),
    "pd_lstg_dt": ("listing_date", "date", None),
    "pd_lst_stk_cnt": ("listed_security_count", "numeric", "shares_or_notes"),
    "pd_mkt_id": ("market_country_id", "text", "code"),
    "pd_nm": ("name", "text", None),
    "pd_sale_yn": ("saleable_in_master", "boolean", None),
    "pd_trd_ccy": ("trading_currency", "text", None),
    "pd_tr_yn": ("trading_status_code_raw", "text", "code"),
    "pd_us_cik": ("us_cik_raw", "text", None),
    "wu_inv_ast_type": ("investment_asset_type", "text", None),
    "wu_inv_rgn": ("investment_region", "text", None),
    "wu_upt_dt": ("classification_updated_on", "date", None),
}

_DATE_FIELDS = (
        "cu_upt_dt",
        "du_clpr_base_dt",
        "du_nav_base_dt",
        "du_upt_dt",
        "pd_lstg_dt",
        "wu_upt_dt",
)
_DATE_SENTINELS: Mapping[str, frozenset[str]] = {
    "cu_upt_dt": frozenset(),
    "du_clpr_base_dt": frozenset(),
    "du_nav_base_dt": frozenset(),
    "du_upt_dt": frozenset(),
    "pd_lstg_dt": frozenset({"0"}),
    "wu_upt_dt": frozenset(),
}
_BOOLEAN_VALUES: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {
    "cu_etn_yn": (frozenset({"Y"}), frozenset()),
    "cu_index_tracking_yn": (frozenset({"Y"}), frozenset()),
    "cu_inverse_short_yn": (frozenset({"Y"}), frozenset()),
    "du_base_dt_match_yn": (frozenset({"Y"}), frozenset({"N"})),
    "pd_sale_yn": (frozenset({"1"}), frozenset()),
}
_CU_FIELDS = frozenset(
    {
        "cu_charge_rt",
        "cu_etn_yn",
        "cu_fund_mgmt_co",
        "cu_index_repl_mthd",
        "cu_index_tracking_yn",
        "cu_inverse_short_yn",
        "cu_strtegy",
        "cu_upt_dt",
    }
)
_CLOSE_DATE_FIELDS = frozenset(
    {
        "du_clpr",
        "du_clpr_base_dt",
        "du_clpr_src",
        "du_hpr",
        "du_lpr",
        "du_opr",
        "du_val_1d",
        "du_vol_1d",
    }
)
_NAV_DATE_FIELDS = frozenset({"du_last_nav", "du_nav_base_dt"})
_DAILY_DATE_FIELDS = frozenset(
    {"du_base_dt_match_yn", "du_bpr", "du_last_aum", "du_upt_dt"}
)
_WU_FIELDS = frozenset({"wu_inv_ast_type", "wu_inv_rgn", "wu_upt_dt"})
_TRADING_CURRENCY_FIELDS = frozenset(
    {"du_clpr", "du_hpr", "du_lpr", "du_opr", "du_val_1d"}
)
_PRODUCT_CURRENCY_FIELDS = frozenset({"du_bpr", "du_last_aum", "du_last_nav"})
_PERIOD_END_FIELDS = frozenset({"du_val_1d", "du_vol_1d"})
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


def _normalized_optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    normalized = normalize_name(str(value))
    if not normalized or normalized == "NULL":
        return None
    return normalized


def collect_duplicate_identifier_values(
    rows: Iterable[Mapping[str, object]],
) -> Mapping[str, frozenset[str]]:
    counts = {column: Counter[str]() for column in _OPTIONAL_IDENTIFIER_COLUMNS}
    for row in rows:
        for column in _OPTIONAL_IDENTIFIER_COLUMNS:
            normalized = _normalized_optional_identifier(row.get(column))
            if normalized is not None:
                counts[column][normalized] += 1
    return {
        column: frozenset(
            value for value, count in column_counts.items() if count > 1
        )
        for column, column_counts in counts.items()
    }


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
        "semantic_family": "organizer_overseas_etp",
        "value_kind": value_kind,
        "default_unit": unit,
        "description": f"Organizer PREF02N001 field {column}",
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
        placeholder_values=(
            _INDEX_PLACEHOLDERS if column == "cu_base_index" else frozenset()
        ),
        zero_is_value=True,
    )
    if status != "present":
        return status, normalized, reason
    if column == "cu_base_index" and isinstance(normalized, str):
        folded = normalized.casefold()
        if any(marker in folded for marker in _INDEX_PLACEHOLDER_MARKERS):
            return "placeholder", None, "SOURCE_VALUE_PLACEHOLDER"
    if column in {"pd_curr_cd", "pd_trd_ccy"} and normalized == "000":
        return "inapplicable", None, "SOURCE_VALUE_INAPPLICABLE"
    if column == "pd_grp_no" and normalized not in {"ETF", "ETN"}:
        return "unknown", None, "UNSUPPORTED_PRODUCT_TYPE"
    return status, normalized, reason


def _numeric_result(raw: object) -> tuple[str, object | None, str | None]:
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
    if isinstance(raw, datetime):
        if raw.tzinfo is not None:
            raise ValueError("source date must be timezone-naive")
        return "present", raw.date(), None
    if isinstance(raw, date):
        return "present", raw, None
    if column == "du_nav_base_dt" and isinstance(raw, str):
        source_timestamp_text = normalize_name(raw)
        if re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T]"
            r"[0-9]{2}:[0-9]{2}:[0-9]{2}",
            source_timestamp_text,
        ):
            source_timestamp = datetime.fromisoformat(source_timestamp_text)
            return "present", source_timestamp.date(), None
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
        if evidence_kind == "relation" or column in _DATE_FIELDS
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
    metric_id = f"organizer.pref02n001.{metric_suffix}"
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


def _append_identifier(
    records_by_table: dict[str, list[Mapping[str, object]]],
    *,
    product_id: str,
    scheme: str,
    value: str,
    primary: bool,
) -> None:
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


def map_row(
    row_number: int,
    row: Mapping[str, object],
    *,
    duplicate_identifier_values: Mapping[str, Set[str]],
) -> MappedRow:
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
        product_currency_status, product_currency, _ = _text_result(
            "pd_curr_cd", row.get("pd_curr_cd")
        )
        if product_currency_status != "present":
            product_currency = None
        trading_currency_status, trading_currency, _ = _text_result(
            "pd_trd_ccy", row.get("pd_trd_ccy")
        )
        if trading_currency_status != "present":
            trading_currency = None
        ticker_status, ticker, _ = _text_result(
            "pd_abrv_nm", row.get("pd_abrv_nm")
        )
        if ticker_status != "present":
            ticker = None

        date_results: dict[str, tuple[str, object | None, str | None]] = {}
        for column in _DATE_FIELDS:
            current_column = column
            date_results[column] = _date_result(column, row.get(column))
        for cutoff_column in (
            "cu_upt_dt",
            "du_clpr_base_dt",
            "du_nav_base_dt",
            "du_upt_dt",
            "wu_upt_dt",
        ):
            cutoff_value = date_results[cutoff_column][1]
            if isinstance(cutoff_value, date) and cutoff_value > _CUTOFF_DATE:
                return _quarantined(
                    row_number,
                    cutoff_column,
                    "AFTER_CUTOFF_SOURCE_VALUE",
                    fatal=True,
                )

        cu_date = date_results["cu_upt_dt"][1]
        close_date = date_results["du_clpr_base_dt"][1]
        nav_date = date_results["du_nav_base_dt"][1]
        daily_date = date_results["du_upt_dt"][1]
        wu_date = date_results["wu_upt_dt"][1]
        assert cu_date is None or isinstance(cu_date, date)
        assert close_date is None or isinstance(close_date, date)
        assert nav_date is None or isinstance(nav_date, date)
        assert daily_date is None or isinstance(daily_date, date)
        assert wu_date is None or isinstance(wu_date, date)

        optional_ids = {
            column: _normalized_optional_identifier(row.get(column))
            for column in _OPTIONAL_IDENTIFIER_COLUMNS
        }
        duplicate_flags = {
            column: value is not None
            and value in duplicate_identifier_values.get(column, frozenset())
            for column, value in optional_ids.items()
        }
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
                "product_family": "overseas_etf",
                "primary_currency": product_currency,
            }
        )
        _append_identifier(
            records_by_table,
            product_id=product_id,
            scheme="PREF02_PD_ITM_NO",
            value=record_key,
            primary=True,
        )
        _append_identifier(
            records_by_table,
            product_id=product_id,
            scheme="PREF02_PD_ITM_NO_MA",
            value=internal_key,
            primary=False,
        )
        for column, scheme in (
            ("pd_isin_cd", "ISIN"),
            ("pd_lipper_id", "LIPPER"),
        ):
            value = optional_ids[column]
            if value is not None and not duplicate_flags[column]:
                _append_identifier(
                    records_by_table,
                    product_id=product_id,
                    scheme=scheme,
                    value=value,
                    primary=False,
                )
            elif duplicate_flags[column]:
                _append_issue(
                    issues,
                    row_number=row_number,
                    column=column,
                    code="DUPLICATE_SOURCE_IDENTIFIER",
                )

        if isinstance(ticker, str):
            records_by_table["catalog.alias"].append(
                _with_record_hash(
                    {
                        "alias_id": stable_id(
                            "alias",
                            _SOURCE_CODE,
                            f"{record_key}:pd_abrv_nm:{ticker}",
                        ),
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
        if manager_status == "present" and security_kind == "etf":
            entity, institution, relation, relation_evidence, origin = (
                _relation_records(
                    row_number=row_number,
                    record_key=record_key,
                    product_id=product_id,
                    column="cu_fund_mgmt_co",
                    raw=row.get("cu_fund_mgmt_co"),
                    entity_type="institution",
                    predicate_id="managedBy",
                    institution_kind="asset_manager",
                    applicable_date=cu_date,
                )
            )
            records_by_table["catalog.entity"].append(entity)
            if institution is not None:
                records_by_table["catalog.institution"].append(institution)
            records_by_table["relation.relation_record"].append(relation)
            records_by_table["evidence.evidence_record"].append(relation_evidence)
            records_by_table["evidence.evidence_relation_origin"].append(origin)
        elif security_kind == "etf":
            _append_issue(
                issues,
                row_number=row_number,
                column="cu_fund_mgmt_co",
                code=manager_reason,
            )

        for column in SPEC.expected_columns:
            if column in IGNORED_COLUMNS or column == "cu_base_index":
                continue
            if column == "cu_fund_mgmt_co" and security_kind == "etf":
                continue

            current_column = column
            _, value_kind, unit = _METRIC_SPECS[column]
            raw = row.get(column)
            if value_kind == "numeric":
                status, normalized, reason_code = _numeric_result(raw)
            elif value_kind == "date":
                status, normalized, reason_code = date_results[column]
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
            elif column in _CLOSE_DATE_FIELDS:
                applicable_date = close_date
            elif column in _NAV_DATE_FIELDS:
                applicable_date = nav_date
            elif column in _DAILY_DATE_FIELDS:
                applicable_date = daily_date
            elif column in _WU_FIELDS:
                applicable_date = wu_date
            else:
                applicable_date = None

            if column in _TRADING_CURRENCY_FIELDS:
                currency = trading_currency
            elif column in _PRODUCT_CURRENCY_FIELDS:
                currency = product_currency
            else:
                currency = None
            period_end = close_date if column in _PERIOD_END_FIELDS else None

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
