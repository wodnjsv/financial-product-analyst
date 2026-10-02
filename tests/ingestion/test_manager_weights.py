from copy import deepcopy
from decimal import Decimal

import pytest

from financial_agent.ingestion.official.manager_weights import parse_samsung_weight, product_identity


def response(ratio="25.11"):
    return {"pdf": {"gijunYMD": "20260821", "totalCnt": 1,
                    "list": [{"itmNo": "005930", "secNm": "삼성전자", "ratio": ratio}]}}


def test_date_basis_and_literal_ratio():
    raw = response()
    original = deepcopy(raw)
    parsed = parse_samsung_weight(raw)
    assert parsed["weight_pct"] == Decimal("25.11")
    assert str(parsed["applicable_date"]) == "2026-08-21"
    assert str(parsed["requested_date"]) == "2026-08-22"
    assert "현금성" in parsed["basis"]
    assert parsed["source_pointer"] == "$.pdf.list[0].ratio"
    assert raw == original


@pytest.mark.parametrize("ratio", [None, "", "-", "NaN", "Infinity", "-1", "101", True])
def test_invalid_weight_rejected(ratio):
    with pytest.raises(ValueError):
        parse_samsung_weight(response(ratio))


def test_zero_is_valid():
    assert parse_samsung_weight(response("0"))["weight_pct"] == 0


@pytest.mark.parametrize("patch", [{"gijunYMD": "20260922"}, {"totalCnt": 2},
    {"list": []}, {"list": [{"itmNo": "005935", "secNm": "삼성전자우", "ratio": "25.11"}]}])
def test_date_coverage_security_fail_closed(patch):
    raw = response()
    raw["pdf"].update(patch)
    with pytest.raises(ValueError):
        parse_samsung_weight(raw)


def test_lookup_matches_exact_ticker():
    row = {"stkTicker": "325010", "fId": "example", "fNm": "예시"}
    assert product_identity([row], "325010") == row
    with pytest.raises(ValueError):
        product_identity([row, row], "325010")
    with pytest.raises(ValueError):
        product_identity([row], "364690")


def test_tiger_keeps_publisher_basis_separate():
    from financial_agent.ingestion.official.manager_weights import parse_tiger_weight
    body = {"rtnData": [{"ksdFund": "KR7147970008", "wkdate": "20260821",
        "memItemcode": "005930  ", "code": "KR7005930003", "stockRate": 3.48}]}
    parsed = parse_tiger_weight(body, "KR7147970008", 1)
    assert parsed["weight_pct"] == Decimal("3.48")
    assert parsed["metric_id"] == "tiger_pdf_publisher_reported_weight_pct"
    assert "미확인" in parsed["basis"]
    with pytest.raises(ValueError, match="INCOMPLETE"):
        parse_tiger_weight(body, "KR7147970008", 31)
    body["rtnData"][0]["wkdate"] = "20260922"
    with pytest.raises(ValueError, match="DATE"):
        parse_tiger_weight(body, "KR7147970008", 1)


def test_plus_pagination_and_date_are_required():
    from financial_agent.ingestion.official.manager_weights import parse_plus_weight
    body = {"last": True, "totalElements": 1, "content": [{"wkdate": "20260821",
        "jmCd": "005930", "krJmCd": "KR7005930003", "ratio": 31.3334}]}
    assert parse_plus_weight(body)["weight_pct"] == Decimal("31.3334")
    body["last"] = False
    with pytest.raises(ValueError, match="INCOMPLETE"):
        parse_plus_weight(body)


def test_hanaro_crosschecks_dated_workbook_and_displayed_precision():
    from io import BytesIO
    from openpyxl import Workbook
    from financial_agent.ingestion.official.manager_weights import parse_hanaro_weight
    book = Workbook()
    sheet = book.active
    sheet.append(["title"])
    sheet.append(["번호", "종목코드", "종목명", "수량(주)", "평가금액(원)", "비중(%)"])
    sheet.append([1, "KR7005930003", "삼성전자", 10, 100, 36.15999984741211])
    buffer = BytesIO()
    book.save(buffer)
    html = '<tr><td>1</td><td>KR7005930003</td><th>삼성전자</th><td>10</td><td>100</td><td>36.16</td></tr>'
    disposition = 'attachment;filename=HANARO_PDF_2026.08.21.xlsx'
    result = parse_hanaro_weight(html, buffer.getvalue(), disposition)
    assert result["weight_pct"] == Decimal("36.16")
    with pytest.raises(ValueError, match="DATE"):
        parse_hanaro_weight(html, buffer.getvalue(), disposition.replace('08.21', '09.22'))
    with pytest.raises(ValueError, match="VALUE_MISMATCH"):
        parse_hanaro_weight(html.replace('36.16', '40.00'), buffer.getvalue(), disposition)


def test_won_checks_actual_date_and_fund_identity():
    from financial_agent.ingestion.official.manager_weights import parse_won_weight
    body = {"data": {"PDFList": [{"LAST_DATE": "2026.08.21", "FUND_CODE": "ETFG",
        "GUSEONG_CODE": "005930", "GUSEONG_NAME": "삼성전자", "BIJUNG": 1.95}]}}
    assert parse_won_weight(body)["weight_pct"] == Decimal("1.95")
    body["data"]["PDFList"][0]["FUND_CODE"] = "OTHER"
    with pytest.raises(ValueError, match="IDENTITY"):
        parse_won_weight(body)
