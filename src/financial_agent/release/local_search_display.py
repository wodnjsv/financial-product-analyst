"""Deterministic missingness and provenance display for local result logs."""

from decimal import Decimal, InvalidOperation

from .local_document_quotes import render_document_answer
from .local_document_text import document_source_lines
from .local_search_validation import validate_local_search_answer


def _count(rows: list[dict], field: str) -> int | None:
    values = [row.get(field) for row in rows]
    if any(value is not None and (type(value) is not int or value < 0) for value in values):
        raise ValueError("COUNT_INVALID")
    known = {value for value in values if value is not None}
    if len(known) > 1:
        raise ValueError("COUNT_CONFLICT")
    return values[0] if values and all(value is not None for value in values) else None


def _number(row: dict, field: str) -> Decimal | None:
    raw = row.get(field)
    if raw is None or row.get("value_status") not in ("present", "zero"):
        return None
    if row.get("unit") != "percentage_point":
        raise ValueError("PERCENTAGE_UNIT_INVALID")
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        raise ValueError("NUMERIC_VALUE_INVALID") from None
    if not value.is_finite():
        raise ValueError("NUMERIC_VALUE_INVALID")
    if row["value_status"] == "zero" and value != 0:
        raise ValueError("VALUE_STATUS_CONFLICT")
    return value


def _source_lines(row: dict, holding: bool) -> tuple[list[str], bool]:
    lines = []
    complete = True
    groups = [("값 근거", row.get("evidence"))]
    if holding:
        groups.append(("보유관계 근거", row.get("holding_evidence")))
    for label, records in groups:
        if not isinstance(records, list) or not records:
            lines.append(f"{label}: 출처 미확인")
            complete = False
            continue
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("SOURCE_RECORD_INVALID")
            locator = record.get("locator")
            column = record.get("column")
            position = record.get("row") or record.get("record_key")
            valid = bool(locator and column and position)
            complete = complete and valid
            parts = [str(locator or "출처 미확인")]
            for key, name in (("sheet", "시트"), ("row", "행"), ("record_key", "레코드"), ("column", "열")):
                if record.get(key) is not None:
                    parts.append(f"{name} {record[key]}")
            if not valid:
                parts.append("출처 정보 불완전")
            lines.append(f"{label}: " + " | ".join(parts))
    return lines, complete


def render_local_search_results(plan_id: str, search: dict) -> dict:
    """Render trusted query results; no model-authored facts or source strings."""
    if plan_id not in ("rank_return", "holding_weight", "document_risk"):
        raise ValueError("UNKNOWN_PLAN")
    rows = search.get("rows")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("SEARCH_ROWS_INVALID")
    ids = [row.get("ref_id") for row in rows]
    if any(not isinstance(ref, str) for ref in ids) or len(set(ids)) != len(ids):
        raise ValueError("SOURCE_REFS_INVALID")
    document = plan_id == "document_risk"
    holding = plan_id == "holding_weight"
    matched = _count(rows, "matched_documents" if document else "matched_products")
    if matched is not None and matched < len(rows):
        raise ValueError("COUNT_CONFLICT")
    metadata = {"dataset": search.get("dataset"), "matched_count": matched, "returned_count": len(rows)}
    if document:
        if any(row.get("dataset_version") and row["dataset_version"] != search.get("dataset") for row in rows):
            raise ValueError("DOCUMENT_DATASET_CONFLICT")
        result = render_document_answer(rows, {"citations": ids})
        items = [{"ref_id": row["ref_id"],
                  "sources_complete": bool(row.get("filing_locator") and row.get("attachment_locator")),
                  "source_lines": document_source_lines(row)} for row in rows]
        return result | {"metadata": metadata, "items": items}
    lines = [f"데이터셋: {search.get('dataset') or '미확인'}",
             f"검색 일치 {matched}개 / 표시 {len(rows)}개" if matched is not None
             else f"검색 일치 건수 미확인 / 표시 {len(rows)}개"]
    values = [_number(row, "weight_pct" if holding else "return_1y_pct") for row in rows]
    if holding:
        known = _count(rows, "products_with_known_weight")
        if known is not None and matched is not None:
            if known > matched or known < sum(v is not None for v in values) or matched - known < sum(v is None for v in values):
                raise ValueError("COUNT_CONFLICT")
        missing = matched - known if matched is not None and known is not None else None
        dates = {row.get("holdings_date") for row in rows}
        rankable = matched is not None and known == matched and all(v is not None for v in values) and len(dates) == 1 and all(dates)
        if rankable and values != sorted(values, reverse=True):
            raise ValueError("RESULT_ORDER_INVALID")
        metadata.update(known_weights=known, missing_weights=missing, ranking_available=rankable)
        lines.append(f"비중 확인 {known}개 / 누락 {missing}개" if missing is not None else "전체 대상의 비중 확인·누락 건수 미확인")
        lines.append("비중 내림차순" if rankable else "순위 산출 불가: 비중 또는 조회 범위·기준일 정보 불완전. 아래는 조회 예시이며 비중 순위가 아닙니다.")
    if holding and "supplement_known_products" in search:
        count = search["supplement_known_products"]
        if type(count) is not int or matched is None or not 0 <= count <= matched:
            raise ValueError("SUPPLEMENT_COUNT_INVALID")
        metadata["supplement_known_products"] = count
        metadata["supplement_ranking_available"] = False
        lines.append(f"별도 운용사 보조 비중 확보: {count}/{matched}개. KRX 비중과 기준일·계산 기준이 달라 대체하거나 혼합 순위를 만들지 않습니다.")
    items = []
    for index, row in enumerate(rows):
        ref = row["ref_id"]
        lines.extend(["", f"[{ref}] {row.get('canonical_name') or '이름 미확인'}"])
        value = values[index]
        text = "미확인" if value is None else f"{format(value.normalize(), 'f')}%"
        lines.append(f"{'비중' if holding else '1년 수익률'}: {text}")
        lines.append(f"기준일: {row.get('holdings_date' if holding else 'applicable_date') or '미확인'}")
        lines.append(f"값 상태: {row.get('value_status') or '미확인'} / 누락 사유: {row.get('reason_code') or ('미확인' if value is None else '해당 없음')}")
        source_lines, complete = _source_lines(row, holding)
        lines.extend(source_lines)
        if holding:
            for supplement in row.get("supplementary_weights", []):
                value = Decimal(str(supplement["weight_pct"]))
                if not value.is_finite() or not 0 <= value <= 100:
                    raise ValueError("SUPPLEMENT_VALUE_INVALID")
                lines.extend([
                    f"별도 보조 비중: {format(value.normalize(), 'f')}% (KRX 값 아님)",
                    f"보조 기준일: {supplement['applicable_date']} / 요청일: {supplement['requested_date']}",
                    f"보조 계산 기준: {supplement['basis']}",
                    f"보조 제공기관: {supplement['publisher']}",
                    f"보조 출처: {supplement['source_url']} | {supplement['source_pointer']}",
                    f"보관 원본: {supplement['source_path']} | SHA256 {supplement['source_sha256']}",
                ])
        items.append({"ref_id": ref, "sources_complete": complete, "source_lines": source_lines})
    limitations = search.get("limitations", [])
    if not isinstance(limitations, list) or any(not isinstance(value, str) for value in limitations):
        raise ValueError("LIMITATIONS_INVALID")
    lines.extend(["", "조회 한계:", *limitations])
    draft = {"answer": "\n".join(lines), "citations": ids}
    result = draft | {"quotes": []}
    errors = validate_local_search_answer(plan_id, rows, result)
    if errors:
        raise ValueError(",".join(errors))
    return result | {"metadata": metadata, "items": items}
