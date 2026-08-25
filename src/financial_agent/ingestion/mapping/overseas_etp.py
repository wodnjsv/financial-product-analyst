from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Set
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
_SOURCE_CODE = "PREF02N001"
_SOURCE_FILE = "pref02n001_data.xlsx"
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
_OPTIONAL_IDENTIFIER_COLUMNS = (
    "pd_isin_cd",
    "pd_lipper_id",
    "pd_itm_no_ma",
)

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
    data_sheet_name="data",
    schema_file_name="pref02n001_schema.xlsx",
    schema_sheet_name="schema",
    expected_columns=_EXPECTED_COLUMNS,
    expected_row_count=6_037,
    natural_key=("pd_itm_no",),
    parser_version="1",
    mapping_version="2",
)

IGNORED_COLUMNS: Mapping[str, str] = {}
HANDLED_COLUMNS = frozenset(_EXPECTED_COLUMNS)
EVIDENCE_ONLY_COLUMNS = frozenset(
    {
        "du_clpr_src",
        "pd_exg_mkt_cd",
        "pd_mkt_id",
        "pd_us_cik",
        "ru_mkt_price",
        "ru_mkt_volume",
    }
)

_METRIC_SPECS: Mapping[str, tuple[str, str, str | None]] = {
    "cu_base_index": ("base_index_raw", "text", None),
    "cu_charge_rt": ("total_fee_rate", "numeric", "percentage_point"),
    "cu_etn_yn": ("is_etn", "boolean", None),
    "cu_fund_mgmt_co": ("provider_name_raw", "text", None),
    "cu_index_repl_mthd": ("index_replication_method", "text", None),
    "cu_index_tracking_yn": ("index_tracking_flag", "boolean", None),
    "cu_inverse_short_yn": ("inverse_short_flag", "boolean", None),
    "cu_lev_fector": ("leverage_factor", "numeric", "multiple"),
    "cu_strtegy": ("strategy_description", "text", None),
    "cu_upt_dt": ("structure_updated_on", "date", None),
    "du_base_dt_match_yn": ("price_nav_date_match", "boolean", None),
    "du_bpr": ("base_price", "numeric", "price_per_share"),
    "du_clpr": ("close_price", "numeric", "price_per_share"),
    "du_clpr_base_dt": ("close_price_as_of", "date", None),
    "du_clpr_src": ("close_price_source_raw", "text", None),
    "du_diff_rt": ("premium_discount_rate", "numeric", "percentage_point"),
    "du_er_1d": ("cumulative_return_1d", "numeric", "percentage_point"),
    "du_hpr": ("high_price", "numeric", "price_per_share"),
    "du_last_aum": ("aum", "numeric", "amount"),
    "du_last_nav": ("nav_per_share", "numeric", "nav_per_share"),
    "du_lpr": ("low_price", "numeric", "price_per_share"),
    "du_nav_base_dt": ("nav_as_of", "date", None),
    "du_opr": ("open_price", "numeric", "price_per_share"),
    "du_upt_dt": ("daily_updated_on", "date", None),
    "du_val_1d": ("trading_value_1d", "numeric", "amount"),
    "du_vol_1d": ("trading_volume_1d", "numeric", "shares_or_notes"),
    "pd_abrv_nm": ("ticker", "text", None),
    "pd_curr_cd": ("product_currency", "text", None),
    "pd_exg_mkt_cd": ("exchange_code_raw", "text", "code"),
    "pd_grp_no": ("product_type", "text", None),
    "pd_isin_cd": ("isin_raw", "text", None),
    "pd_itm_no": ("product_id", "text", None),
    "pd_itm_no_ma": ("internal_product_id", "text", None),
    "pd_lipper_id": ("lipper_id", "text", None),
    "pd_lstg_dt": ("listing_date", "date", None),
    "pd_lst_price": ("face_value", "numeric", "amount"),
    "pd_lst_stk_cnt": ("listed_security_count", "numeric", "shares_or_notes"),
    "pd_mkt_id": ("market_country_code_raw", "text", "code"),
    "pd_nm": ("name", "text", None),
    "pd_sale_yn": ("saleable_in_master", "boolean", None),
    "pd_trd_ccy": ("trading_currency", "text", None),
    "pd_tr_yn": ("trading_suspended", "boolean", None),
    "pd_us_cik": ("us_cik_raw", "text", None),
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
        "du_clpr_base_dt",
        "du_nav_base_dt",
        "du_upt_dt",
        "pd_lstg_dt",
        "wu_upt_dt",
    }
)
_BOOLEAN_VALUES: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {
    "cu_etn_yn": (frozenset({"Y"}), frozenset({"N"})),
    "cu_index_tracking_yn": (frozenset({"Y"}), frozenset({"N"})),
    "cu_inverse_short_yn": (frozenset({"Y"}), frozenset({"N"})),
    "du_base_dt_match_yn": (frozenset({"Y"}), frozenset({"N"})),
    "pd_sale_yn": (frozenset({"1"}), frozenset({"0"})),
    "pd_tr_yn": (frozenset({"1"}), frozenset({"0"})),
    "wu_core_yn": (frozenset({"Y"}), frozenset({"N"})),
}
_RELATION_FIELDS = frozenset({"cu_base_index", "cu_fund_mgmt_co"})
_CLOSE_DATE_FIELDS = frozenset(
    {
        "du_clpr",
        "du_clpr_src",
        "du_er_1d",
        "du_hpr",
        "du_lpr",
        "du_opr",
        "du_val_1d",
        "du_vol_1d",
    }
)
_NAV_DATE_FIELDS = frozenset({"du_bpr", "du_last_aum", "du_last_nav"})
_DAILY_DATE_FIELDS = frozenset(
    {"du_base_dt_match_yn", "pd_lst_stk_cnt", "pd_sale_yn", "pd_tr_yn"}
)
_TRADING_CURRENCY_FIELDS = frozenset(
    {"du_clpr", "du_hpr", "du_lpr", "du_opr", "du_val_1d", "ru_mkt_price"}
)
_PRODUCT_CURRENCY_FIELDS = frozenset(
    {"du_bpr", "du_last_aum", "du_last_nav", "pd_lst_price"}
)
_PERIOD_END_FIELDS = frozenset({"du_er_1d", "du_val_1d", "du_vol_1d"})
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
    normalized = normalize_name(str(value)).upper()
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
    sentinels = (
        frozenset({"0", "00000000"})
        if column == "pd_lstg_dt"
        else frozenset()
    )
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
) -> dict[str, object]:
    semantic_family = (
        "organizer_overseas_etp_evidence_only"
        if column in EVIDENCE_ONLY_COLUMNS
        else "organizer_overseas_etp"
    )
    payload: dict[str, object] = {
        "metric_id": metric_id,
        "definition_version": "2",
        "semantic_family": semantic_family,
        "value_kind": value_kind,
        "default_unit": unit,
        "description": f"Organizer PREF02N001 field {column}",
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
    payload: dict[str, object] = {
        "evidence_id": stable_id("evidence", _SOURCE_CODE, f"{record_key}:{column}"),
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
    metric_id = f"organizer.pref02n001.{metric_suffix}"
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


def _append_relation(
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


def _applicable_date(
    column: str,
    date_values: Mapping[str, date | None],
    *,
    price_nav_mismatch: bool,
) -> date | None:
    if column in _DATE_FIELDS:
        return date_values[column]
    if column.startswith("cu_"):
        return date_values["cu_upt_dt"]
    if column == "du_diff_rt":
        return None if price_nav_mismatch else date_values["du_clpr_base_dt"]
    if column in _CLOSE_DATE_FIELDS:
        return date_values["du_clpr_base_dt"]
    if column in _NAV_DATE_FIELDS:
        return date_values["du_nav_base_dt"] or date_values["du_upt_dt"]
    if column in _DAILY_DATE_FIELDS:
        return date_values["du_upt_dt"]
    if column.startswith("wu_"):
        return date_values["wu_upt_dt"]
    return None


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
) -> None:
    if status not in {"present", "zero"}:
        _append_issue(
            issues,
            row_number=row_number,
            column=column,
            code=reason,
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
        reason_code=reason,
        currency=None,
        applicable_date=applicable_date,
        period_end=None,
    )


def map_row(
    row_number: int,
    row: Mapping[str, object],
    *,
    duplicate_identifier_values: Mapping[str, Set[str]],
    identity_index: AuthoritativeIdentityIndex,
) -> MappedRow:
    record_key = _normalized_optional_identifier(row.get("pd_itm_no"))
    if record_key is None:
        return _quarantined(row_number, "pd_itm_no", "MISSING_NATURAL_KEY")
    canonical_name = normalize_name(str(row.get("pd_nm") or ""))
    if not canonical_name or canonical_name.upper() == "NULL":
        return _quarantined(row_number, "pd_nm", "MISSING_REQUIRED_NAME")

    resolution = identity_index.resolve("PREF02_PD_ITM_NO", record_key)
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
        if f"Overseas{group_value}" not in resolution.canonical_identity.roles:
            return _quarantined(
                row_number,
                "pd_grp_no",
                "IDENTITY_ROLE_MISMATCH",
                fatal=True,
            )

        date_results = {}
        for column in _DATE_FIELDS:
            current_column = column
            date_results[column] = _date_result(column, row.get(column))
        date_values = {
            column: result[1] if isinstance(result[1], date) else None
            for column, result in date_results.items()
        }
        for column, value in date_values.items():
            current_column = column
            if value is not None and value > _CUTOFF_DATE:
                return _quarantined(
                    row_number,
                    column,
                    "AFTER_CUTOFF_SOURCE_VALUE",
                    fatal=True,
                )

        product_currency_status, product_currency_value, _ = _text_result(
            "pd_curr_cd", row.get("pd_curr_cd")
        )
        product_currency = (
            product_currency_value.upper()
            if product_currency_status == "present"
            and isinstance(product_currency_value, str)
            and len(product_currency_value) == 3
            and product_currency_value.isalpha()
            else None
        )
        trading_currency_status, trading_currency_value, _ = _text_result(
            "pd_trd_ccy", row.get("pd_trd_ccy")
        )
        trading_currency = (
            trading_currency_value.upper()
            if trading_currency_status == "present"
            and isinstance(trading_currency_value, str)
            and len(trading_currency_value) == 3
            and trading_currency_value.isalpha()
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

        for column, scheme in (
            ("pd_itm_no_ma", "PREF02_PD_ITM_NO_MA"),
            ("pd_isin_cd", "ISIN"),
            ("pd_lipper_id", "LIPPER"),
        ):
            value = _normalized_optional_identifier(row.get(column))
            if value is None:
                continue
            if value in duplicate_identifier_values.get(column, frozenset()):
                _append_issue(
                    issues,
                    row_number=row_number,
                    column=column,
                    code="DUPLICATE_IDENTIFIER_NOT_PROMOTED",
                )
                continue
            if scheme in {"ISIN", "LIPPER"}:
                external_resolution = identity_index.resolve(scheme, value)
                if (
                    external_resolution.status != "MATCHED"
                    or external_resolution.canonical_identity is None
                    or external_resolution.canonical_identity.entity_id != product_id
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
                scheme=scheme,
                value=value,
                primary=False,
            )

        ticker_status, ticker, _ = _text_result(
            "pd_abrv_nm", row.get("pd_abrv_nm")
        )
        if ticker_status == "present" and isinstance(ticker, str):
            records_by_table["catalog.alias"].append(
                _with_record_hash(
                    {
                        "alias_id": stable_id(
                            "alias", _SOURCE_CODE, f"{record_key}:{ticker.upper()}"
                        ),
                        "entity_id": product_id,
                        "alias_text": ticker,
                        "normalized_alias_text": ticker.upper(),
                        "valid_from": None,
                        "valid_to": None,
                    }
                )
            )

        relation_consumed: set[str] = set()
        index_status, index_name, index_reason = _text_result(
            "cu_base_index", row.get("cu_base_index")
        )
        if index_status == "present" and isinstance(index_name, str):
            _append_relation(
                records_by_table,
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                column="cu_base_index",
                raw=row.get("cu_base_index"),
                predicate_id="tracksIndex",
                object_type="index",
                object_name=index_name,
                applicable_date=date_values["cu_upt_dt"],
            )
            relation_consumed.add("cu_base_index")
        manager_status, manager_name, manager_reason = _text_result(
            "cu_fund_mgmt_co", row.get("cu_fund_mgmt_co")
        )
        if (
            group_value == "ETF"
            and manager_status == "present"
            and isinstance(manager_name, str)
        ):
            _append_relation(
                records_by_table,
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                column="cu_fund_mgmt_co",
                raw=row.get("cu_fund_mgmt_co"),
                predicate_id="managedBy",
                object_type="institution",
                object_name=manager_name,
                applicable_date=date_values["cu_upt_dt"],
                institution_kind="asset_manager",
            )
            relation_consumed.add("cu_fund_mgmt_co")

        for column, result in (
            ("cu_base_index", (index_status, index_name, index_reason)),
            ("cu_fund_mgmt_co", (manager_status, manager_name, manager_reason)),
        ):
            if column in relation_consumed:
                continue
            _append_relation_fallback(
                records_by_table,
                issues,
                row_number=row_number,
                record_key=record_key,
                product_id=product_id,
                column=column,
                row=row,
                status=result[0],
                normalized=result[1],
                reason=result[2],
                applicable_date=date_values["cu_upt_dt"],
            )

        match_status, match_value, _ = _boolean_result(
            "du_base_dt_match_yn", row.get("du_base_dt_match_yn")
        )
        close_date = date_values["du_clpr_base_dt"]
        nav_date = date_values["du_nav_base_dt"]
        price_nav_mismatch = (
            match_status == "present" and match_value is False
        ) or (
            close_date is not None and nav_date is not None and close_date != nav_date
        )
        type_flag_status, type_flag, _ = _boolean_result(
            "cu_etn_yn", row.get("cu_etn_yn")
        )
        if type_flag_status == "present" and (
            (group_value == "ETN") != bool(type_flag)
        ):
            _append_issue(
                issues,
                row_number=row_number,
                column="cu_etn_yn",
                code="PRODUCT_TYPE_FLAG_CONFLICT",
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
            if column == "du_diff_rt" and status in {"present", "zero"} and price_nav_mismatch:
                _append_issue(
                    issues,
                    row_number=row_number,
                    column=column,
                    code="PRICE_NAV_DATE_MISMATCH",
                )
            applicable_date = _applicable_date(
                column,
                date_values,
                price_nav_mismatch=price_nav_mismatch,
            )
            period_end = applicable_date if column in _PERIOD_END_FIELDS else None
            if column in _TRADING_CURRENCY_FIELDS:
                currency = trading_currency
            elif column in _PRODUCT_CURRENCY_FIELDS:
                currency = product_currency
            else:
                currency = None
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
