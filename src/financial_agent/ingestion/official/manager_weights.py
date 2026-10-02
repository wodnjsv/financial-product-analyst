"""Strict parser for the approved local Samsung manager-weight supplement."""

from datetime import date
from decimal import Decimal, InvalidOperation

METRIC = "manager_pdf_weight_excluding_cash_deposits_pct"
BASIS = "국내외 현금성 자산과 예금 제외; 운용사 PDF 비중"
REQUESTED_DATE = date(2026, 8, 22)
ACTUAL_DATE = date(2026, 8, 21)
PRODUCT_CODES = ("325010", "364690", "494890")


def product_identity(lookup: object, code: str) -> dict:
    if code not in PRODUCT_CODES or not isinstance(lookup, list):
        raise ValueError("MANAGER_IDENTITY_INVALID")
    exact = [row for row in lookup if isinstance(row, dict) and row.get("stkTicker") == code]
    if len(exact) != 1 or not exact[0].get("fId") or not exact[0].get("fNm"):
        raise ValueError("MANAGER_IDENTITY_INVALID")
    return exact[0]


def parse_samsung_weight(body: object) -> dict:
    if not isinstance(body, dict) or not isinstance(body.get("pdf"), dict):
        raise ValueError("MANAGER_RESPONSE_INVALID")
    pdf = body["pdf"]
    if pdf.get("gijunYMD") != ACTUAL_DATE.strftime("%Y%m%d"):
        raise ValueError("MANAGER_DATE_MISMATCH")
    rows = pdf.get("list")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("MANAGER_ROWS_INVALID")
    if type(pdf.get("totalCnt")) is not int or pdf["totalCnt"] != len(rows):
        raise ValueError("MANAGER_RESPONSE_INCOMPLETE")
    hits = [(i, row) for i, row in enumerate(rows) if row.get("itmNo") == "005930"]
    if len(hits) != 1 or hits[0][1].get("secNm") != "삼성전자":
        raise ValueError("MANAGER_SECURITY_MISMATCH")
    index, row = hits[0]
    raw = row.get("ratio")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("MANAGER_WEIGHT_MISSING")
    try:
        weight = Decimal(raw)
    except InvalidOperation:
        raise ValueError("MANAGER_WEIGHT_INVALID") from None
    if not weight.is_finite() or not 0 <= weight <= 100:
        raise ValueError("MANAGER_WEIGHT_INVALID")
    return {"security_code": "005930", "security_name": "삼성전자보통주",
            "weight_pct": weight, "applicable_date": ACTUAL_DATE,
            "requested_date": REQUESTED_DATE, "metric_id": METRIC,
            "basis": BASIS, "source_pointer": f"$.pdf.list[{index}].ratio"}

# Publisher-reported weights have a separate metric: no assumption that their
# denominator equals Samsung's cash-excluding weights or the original KRX field.
TIGER_PRODUCTS = {"147970": "KR7147970008", "376410": "KR7376410007", "396500": "KR7396500001"}
TIGER_BASIS = "TIGER 공식 PDF 표시 비중; 분모의 현금 포함 여부 미확인"


def parse_tiger_weight(body: object, isin: str, expected_count: int) -> dict:
    if isin not in TIGER_PRODUCTS.values() or not isinstance(body, dict):
        raise ValueError("MANAGER_IDENTITY_INVALID")
    rows = body.get("rtnData")
    if not isinstance(rows, list) or not rows or len(rows) != expected_count:
        raise ValueError("MANAGER_RESPONSE_INCOMPLETE")
    if any(not isinstance(row, dict) or row.get("ksdFund") != isin or row.get("wkdate") != "20260821" for row in rows):
        raise ValueError("MANAGER_DATE_OR_IDENTITY_MISMATCH")
    hits = [(i, row) for i, row in enumerate(rows) if str(row.get("memItemcode", "")).strip() == "005930"]
    if len(hits) != 1 or hits[0][1].get("code") != "KR7005930003":
        raise ValueError("MANAGER_SECURITY_MISMATCH")
    index, row = hits[0]
    try:
        value = Decimal(str(row.get("stockRate")))
    except InvalidOperation:
        raise ValueError("MANAGER_WEIGHT_INVALID") from None
    if not value.is_finite() or not 0 <= value <= 100:
        raise ValueError("MANAGER_WEIGHT_INVALID")
    return {"security_code": "005930", "security_name": "삼성전자보통주", "weight_pct": value,
            "applicable_date": ACTUAL_DATE, "requested_date": REQUESTED_DATE,
            "metric_id": "tiger_pdf_publisher_reported_weight_pct", "basis": TIGER_BASIS,
            "source_pointer": f"$.rtnData[{index}].stockRate"}


def parse_plus_weight(body: object) -> dict:
    if not isinstance(body, dict) or body.get("last") is not True:
        raise ValueError("MANAGER_RESPONSE_INCOMPLETE")
    rows = body.get("content")
    if not isinstance(rows, list) or not rows or len(rows) != body.get("totalElements"):
        raise ValueError("MANAGER_RESPONSE_INCOMPLETE")
    if any(not isinstance(row, dict) or row.get("wkdate") != "20260821" for row in rows):
        raise ValueError("MANAGER_DATE_MISMATCH")
    hits = [(i, row) for i, row in enumerate(rows) if row.get("jmCd") == "005930"]
    if len(hits) != 1 or hits[0][1].get("krJmCd") != "KR7005930003":
        raise ValueError("MANAGER_SECURITY_MISMATCH")
    index, row = hits[0]
    try:
        value = Decimal(str(row.get("ratio")))
    except InvalidOperation:
        raise ValueError("MANAGER_WEIGHT_INVALID") from None
    if not value.is_finite() or not 0 <= value <= 100:
        raise ValueError("MANAGER_WEIGHT_INVALID")
    return {"security_code": "005930", "security_name": "삼성전자보통주", "weight_pct": value,
            "applicable_date": ACTUAL_DATE, "requested_date": REQUESTED_DATE,
            "metric_id": "plus_pdf_publisher_reported_weight_pct",
            "basis": "PLUS 공식 PDF 표시 비중; 분모의 현금 포함 여부 미확인",
            "source_pointer": f"$.content[{index}].ratio"}


def parse_hanaro_weight(html: str, workbook: bytes, disposition: str) -> dict:
    """Cross-check displayed ratio against the officially dated Excel export."""
    from html.parser import HTMLParser
    from io import BytesIO
    import openpyxl

    if "2026.08.21.xlsx" not in disposition or "HANARO" not in disposition:
        raise ValueError("MANAGER_DATE_MISMATCH")

    class Rows(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows, self.row, self.cell = [], None, None

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self.row = []
            elif tag in ("td", "th") and self.row is not None:
                self.cell = []

        def handle_data(self, data):
            if self.cell is not None:
                self.cell.append(data)

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.cell is not None:
                self.row.append("".join(self.cell).strip())
                self.cell = None
            elif tag == "tr" and self.row is not None:
                self.rows.append(self.row)
                self.row = None

    parser = Rows()
    parser.feed(html)
    hits = [(i, row) for i, row in enumerate(parser.rows) if len(row) == 6 and row[1] == "KR7005930003" and row[2] == "삼성전자"]
    if len(hits) != 1:
        raise ValueError("MANAGER_SECURITY_MISMATCH")
    index, row = hits[0]
    try:
        value = Decimal(row[5])
    except InvalidOperation:
        raise ValueError("MANAGER_WEIGHT_INVALID") from None
    if not value.is_finite() or not 0 <= value <= 100:
        raise ValueError("MANAGER_WEIGHT_INVALID")
    book = openpyxl.load_workbook(BytesIO(workbook), read_only=True, data_only=True)
    try:
        cells = list(book.active.iter_rows(values_only=True))
    finally:
        book.close()
    if len(cells) < 3 or tuple(cells[1][:6]) != ("번호", "종목코드", "종목명", "수량(주)", "평가금액(원)", "비중(%)"):
        raise ValueError("MANAGER_WORKBOOK_SCHEMA_INVALID")
    matches = [r for r in cells[2:] if len(r) >= 6 and r[1] == "KR7005930003"]
    if len(matches) != 1 or matches[0][2] != "삼성전자" or Decimal(str(matches[0][5])).quantize(Decimal("0.01")) != value:
        raise ValueError("MANAGER_WORKBOOK_VALUE_MISMATCH")
    return {"security_code": "005930", "security_name": "삼성전자보통주", "weight_pct": value,
            "applicable_date": ACTUAL_DATE, "requested_date": REQUESTED_DATE,
            "metric_id": "hanaro_pdf_publisher_reported_weight_pct",
            "basis": "HANARO 공식 PDF 표시 비중; 현금 포함 기준 별도 미확인; 날짜는 공식 엑셀 파일명으로 대조",
            "source_pointer": f"tr[{index + 1}]/td[5]"}


def parse_won_weight(body: object) -> dict:
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise ValueError("MANAGER_RESPONSE_INVALID")
    rows = body["data"].get("PDFList")
    if not isinstance(rows, list) or not rows:
        raise ValueError("MANAGER_RESPONSE_INCOMPLETE")
    if any(not isinstance(row, dict) or row.get("LAST_DATE") != "2026.08.21" or row.get("FUND_CODE") != "ETFG" for row in rows):
        raise ValueError("MANAGER_DATE_OR_IDENTITY_MISMATCH")
    hits = [(i, row) for i, row in enumerate(rows) if row.get("GUSEONG_CODE") == "005930"]
    if len(hits) != 1 or hits[0][1].get("GUSEONG_NAME") != "삼성전자":
        raise ValueError("MANAGER_SECURITY_MISMATCH")
    index, row = hits[0]
    try:
        value = Decimal(str(row.get("BIJUNG")))
    except InvalidOperation:
        raise ValueError("MANAGER_WEIGHT_INVALID") from None
    if not value.is_finite() or not 0 <= value <= 100:
        raise ValueError("MANAGER_WEIGHT_INVALID")
    return {"security_code": "005930", "security_name": "삼성전자보통주", "weight_pct": value,
            "applicable_date": ACTUAL_DATE, "requested_date": REQUESTED_DATE,
            "metric_id": "won_pdf_publisher_reported_weight_pct",
            "basis": "WON 공식 PDF 표시 비중; 분모의 현금 포함 여부 미확인",
            "source_pointer": f"$.data.PDFList[{index}].BIJUNG"}
