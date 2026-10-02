from copy import deepcopy

import pytest

from financial_agent.release.local_search_display import render_local_search_results


def holding(value=None, status="unknown", total=9, known=0):
    return {
        "ref_id": "H1", "canonical_name": "예시 ETF", "holding_name": "삼성전자보통주",
        "holdings_date": "2026-08-22", "weight_pct": value, "unit": "percentage_point",
        "value_status": status, "reason_code": "SOURCE_VALUE_MISSING" if value is None else None,
        "matched_products": total, "products_with_known_weight": known,
        "evidence": [{"locator": "sample.csv", "row": 2, "column": "비중"}],
        "holding_evidence": [{"locator": "sample.csv", "record_key": "005930", "column": "종목코드"}],
    }


def search(*rows):
    return {"dataset": "sample-v1", "rows": list(rows), "limitations": ["표본 검색"]}


def test_missing_weights_disable_ranking_and_show_sources():
    data = search(holding())
    before = deepcopy(data)
    result = render_local_search_results("holding_weight", data)
    assert result["metadata"]["missing_weights"] == 9
    assert result["metadata"]["ranking_available"] is False
    assert "검색 일치 9개" in result["answer"]
    assert "비중 확인 0개 / 누락 9개" in result["answer"]
    assert "순위 산출 불가" in result["answer"]
    assert "비중: 미확인" in result["answer"]
    assert "sample.csv | 행 2 | 열 비중" in result["answer"]
    assert "종목코드" in result["answer"]
    assert data == before


def test_zero_is_known_and_rankable():
    result = render_local_search_results("holding_weight", search(holding("0", "zero", 1, 1)))
    assert result["metadata"]["ranking_available"] is True
    assert "비중: 0%" in result["answer"]


def test_known_sample_does_not_make_incomplete_population_rankable():
    result = render_local_search_results("holding_weight", search(holding("12.5", "present", 9, 1)))
    assert result["metadata"]["missing_weights"] == 8
    assert result["metadata"]["ranking_available"] is False


def test_missing_count_is_not_assumed_zero():
    row = holding()
    del row["products_with_known_weight"]
    result = render_local_search_results("holding_weight", search(row))
    assert result["metadata"]["missing_weights"] is None
    assert result["metadata"]["ranking_available"] is False
    assert "비중 확인 미확인개" not in result["answer"]


def test_missing_evidence_is_visible():
    row = holding()
    row["evidence"] = []
    row["holding_evidence"] = []
    result = render_local_search_results("holding_weight", search(row))
    assert result["items"][0]["sources_complete"] is False
    assert "출처 미확인" in result["answer"]


def test_workbook_source_and_date():
    row = holding("3", "present", 1, 1) | {
        "ref_id": "R1", "return_1y_pct": "3.00", "applicable_date": "2026-08-21",
        "evidence": [{"locator": "master.xlsx", "sheet": "data", "row": 7, "column": "return"}],
    }
    result = render_local_search_results("rank_return", search(row))
    assert "시트 data | 행 7 | 열 return" in result["answer"]
    assert "2026-08-21" in result["answer"]


def test_document_count_sources_and_exact_quotes():
    row = {"ref_id": "D1", "document_title": "설명서", "matched_documents": 58,
        "published_at": "2026-08-07", "page_start": 20, "page_end": 38,
        "filing_locator": "https://example.test/filing", "attachment_locator": "https://example.test/doc.pdf",
        "excerpt": " 원문\n환율 위험\t", "section_path": "투자 위험"}
    result = render_local_search_results("document_risk", search(row))
    assert "검색 일치 58개" in result["answer"]
    assert "순위" not in result["answer"]
    assert "https://example.test/filing" in result["answer"]
    assert "https://example.test/doc.pdf" in result["answer"]
    assert "20~38" in result["answer"] and "정확한 인용 페이지 미검증" in result["answer"]
    assert result["quotes"] == [{"ref_id": "D1", "quote": row["excerpt"]}]


@pytest.mark.parametrize("known", [-1, 10, True, "0"])
def test_invalid_counts_rejected(known):
    with pytest.raises(ValueError):
        render_local_search_results("holding_weight", search(holding(known=known)))


def test_conflicting_counts_rejected():
    other = holding(total=10) | {"ref_id": "H2"}
    with pytest.raises(ValueError, match="COUNT"):
        render_local_search_results("holding_weight", search(holding(), other))


def test_claimed_full_coverage_with_null_rejected():
    with pytest.raises(ValueError, match="COUNT"):
        render_local_search_results("holding_weight", search(holding(total=1, known=1)))


@pytest.mark.parametrize("date", [None, ""])
def test_missing_date_disables_rank(date):
    row = holding("0", "zero", 1, 1) | {"holdings_date": date}
    assert render_local_search_results("holding_weight", search(row))["metadata"]["ranking_available"] is False


def test_zero_status_cannot_hide_nonzero_value():
    with pytest.raises(ValueError, match="VALUE_STATUS_CONFLICT"):
        render_local_search_results("holding_weight", search(holding("5", "zero", 1, 1)))


def test_wrong_percentage_unit_rejected():
    row = holding("1", "present", 1, 1) | {"unit": "fraction"}
    with pytest.raises(ValueError, match="PERCENTAGE_UNIT_INVALID"):
        render_local_search_results("holding_weight", search(row))


def test_supplement_does_not_fill_primary_or_enable_rank():
    row = holding()
    row["supplementary_weights"] = [{"weight_pct": "25.11", "applicable_date": "2026-08-21",
        "requested_date": "2026-08-22", "basis": "현금성 자산 제외", "publisher": "운용사",
        "source_url": "https://example.test/source", "source_pointer": "$.pdf.list[1].ratio",
        "source_path": "source.json", "source_sha256": "example-hash"}]
    data = search(row) | {"supplement_known_products": 3}
    result = render_local_search_results("holding_weight", data)
    assert result["metadata"]["ranking_available"] is False
    assert result["metadata"]["known_weights"] == 0
    assert result["metadata"]["missing_weights"] == 9
    assert "3/9개" in result["answer"]
    assert "보조 비중: 25.11%" in result["answer"]
    assert "보조 기준일: 2026-08-21 / 요청일: 2026-08-22" in result["answer"]
    assert row["weight_pct"] is None
