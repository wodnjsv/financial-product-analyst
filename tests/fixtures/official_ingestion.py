from __future__ import annotations

import hashlib
import csv
import io
import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

from financial_agent.ingestion.official.models import (
    OfficialObjectManifest,
    OfficialSnapshotManifest,
)


def official_manifest(
    *,
    source_code: str,
    object_name: str,
    payload: bytes,
    applicable_date: date,
    published_at: datetime | None = None,
    available_at: datetime | None = None,
    media_type: str = "application/json",
) -> OfficialSnapshotManifest:
    return OfficialSnapshotManifest(
        source_code=source_code,
        snapshot_id=f"{source_code.lower()}-{applicable_date:%Y%m%d}",
        publisher_code=(
            "KRX"
            if source_code.startswith("KRX_")
            else "BOK"
            if source_code.startswith("ECOS_")
            else "SEC"
        ),
        cutoff_date=date(2026, 7, 11),
        applicable_date=applicable_date,
        published_at=published_at,
        available_at=available_at
        or datetime(2026, 7, 10, 23, 59, 59, tzinfo=timezone.utc),
        vintage_date=applicable_date,
        parser_version="1",
        mapping_version="1",
        objects=(
            OfficialObjectManifest(
                object_name=object_name,
                object_key=(
                    f"external/2026-07-11/{source_code}/synthetic/{object_name}"
                ),
                media_type=media_type,
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            ),
        ),
    )


def krx_security_basic_payload(
    rows: tuple[dict[str, str], ...] | None = None,
) -> bytes:
    values = rows if rows is not None else (
        {
            "ISU_CD": "KR7000000001",
            "ISU_SRT_CD": "000001",
            "ISU_NM": "합성 보통주",
            "ISU_ABBRV": "합성주",
            "ISU_ENG_NM": "Synthetic Common Stock",
            "LIST_DD": "20200102",
        },
    )
    return json.dumps(
        {"OutBlock_1": values}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def krx_etf_pdf_payload(
    rows: tuple[dict[str, str], ...] | None = None,
) -> bytes:
    values = rows if rows is not None else (
        {
            "종목코드": "005930",
            "구성종목명": "삼성전자",
            "주식수(계약수)": "10.00",
            "평가금액": "1000",
            "시가총액": "1000",
            "시가총액 구성비중": "25.00",
        },
        {
            "종목코드": "TYU6",
            "구성종목명": "US 10YR NOTE FUT (CBOT) SEPT 2026",
            "주식수(계약수)": "2.00",
            "평가금액": "500",
            "시가총액": "-",
            "시가총액 구성비중": "-",
        },
        {
            "종목코드": "KRD010010001",
            "구성종목명": "원화현금",
            "주식수(계약수)": "-",
            "평가금액": "-",
            "시가총액": "-100",
            "시가총액 구성비중": "-1.00",
        },
        {
            "종목코드": "CASH00000001",
            "구성종목명": "설정현금액",
            "주식수(계약수)": "-",
            "평가금액": "-",
            "시가총액": "1400",
            "시가총액 구성비중": "-",
        },
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "종목코드",
            "구성종목명",
            "주식수(계약수)",
            "평가금액",
            "시가총액",
            "시가총액 구성비중",
        ),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(values)
    return output.getvalue().encode("cp949")


def krx_etf_daily_payload(
    rows: tuple[dict[str, str], ...] | None = None,
) -> bytes:
    values = rows if rows is not None else (
        {
            "BAS_DD": "20260710",
            "ISU_CD": "305080",
            "ISU_NM": "TIGER 미국채10년선물",
            "TDD_CLSPRC": "12345.50",
            "NAV": "12340.25",
        },
    )
    return json.dumps(
        {"OutBlock_1": values},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def sec_series_class_payload(
    rows: tuple[dict[str, str], ...] | None = None,
) -> bytes:
    values = rows if rows is not None else (
        {
            "CIK": "0000123456",
            "Series ID": "S000000001",
            "Series Name": "Synthetic ETF Series",
            "Class ID": "C000000001",
            "Class Name": "Synthetic ETF Class",
            "Class Ticker": "SYNX",
        },
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "CIK",
            "Series ID",
            "Series Name",
            "Class ID",
            "Class Name",
            "Class Ticker",
        ),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(values)
    return output.getvalue().encode("utf-8")


def ecos_731y001_payload(
    rows: tuple[dict[str, str], ...] | None = None,
) -> bytes:
    values = rows if rows is not None else (
        {
            "STAT_CODE": "731Y001",
            "ITEM_CODE1": "0000001",
            "ITEM_NAME1": "원/미국달러(매매기준율)",
            "UNIT_NAME": "원",
            "TIME": "20260710",
            "DATA_VALUE": "1301.25",
        },
        {
            "STAT_CODE": "731Y001",
            "ITEM_CODE1": "0000002",
            "ITEM_NAME1": "원/일본엔(100엔)",
            "UNIT_NAME": "원",
            "TIME": "20260710",
            "DATA_VALUE": "891.25",
        },
        {
            "STAT_CODE": "731Y001",
            "ITEM_CODE1": "0000003",
            "ITEM_NAME1": "원/유로",
            "UNIT_NAME": "원",
            "TIME": "20260710",
            "DATA_VALUE": "1502.75",
        },
        {
            "STAT_CODE": "731Y001",
            "ITEM_CODE1": "0000053",
            "ITEM_NAME1": "원/위안(매매기준율)",
            "UNIT_NAME": "원",
            "TIME": "20260710",
            "DATA_VALUE": "181.05",
        },
    )
    return json.dumps(
        {"StatisticSearch": {"row": values}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _tsv_payload(
    fieldnames: tuple[str, ...], rows: tuple[dict[str, str], ...]
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def sec_nport_tsv_files() -> dict[str, bytes]:
    accession = "0000000000-26-000001"
    return {
        "SUBMISSION.tsv": _tsv_payload(
            (
                "ACCESSION_NUMBER",
                "FILING_DATE",
                "FILE_NUM",
                "SUB_TYPE",
                "REPORT_ENDING_PERIOD",
                "REPORT_DATE",
                "IS_LAST_FILING",
            ),
            (
                {
                    "ACCESSION_NUMBER": accession,
                    "FILING_DATE": "2026-06-20",
                    "FILE_NUM": "811-SYNTHETIC",
                    "SUB_TYPE": "NPORT-P/A",
                    "REPORT_ENDING_PERIOD": "2026-12-31",
                    "REPORT_DATE": "2026-03-31",
                    "IS_LAST_FILING": "N",
                },
            ),
        ),
        "REGISTRANT.tsv": _tsv_payload(
            (
                "ACCESSION_NUMBER",
                "CIK",
                "REGISTRANT_NAME",
                "FILE_NUM",
                "LEI",
                "ADDRESS1",
                "ADDRESS2",
                "CITY",
                "STATE",
                "COUNTRY",
                "ZIP",
                "PHONE",
            ),
            (
                {
                    "ACCESSION_NUMBER": accession,
                    "CIK": "0000123456",
                    "REGISTRANT_NAME": "Synthetic Registrant",
                    "FILE_NUM": "811-SYNTHETIC",
                    "LEI": "",
                    "ADDRESS1": "",
                    "ADDRESS2": "",
                    "CITY": "",
                    "STATE": "",
                    "COUNTRY": "",
                    "ZIP": "",
                    "PHONE": "",
                },
            ),
        ),
        "FUND_REPORTED_INFO.tsv": _tsv_payload(
            ("ACCESSION_NUMBER", "SERIES_NAME", "SERIES_ID", "SERIES_LEI"),
            (
                {
                    "ACCESSION_NUMBER": accession,
                    "SERIES_NAME": "Synthetic ETF Series",
                    "SERIES_ID": "S000000001",
                    "SERIES_LEI": "",
                },
            ),
        ),
        "FUND_REPORTED_HOLDING.tsv": _tsv_payload(
            (
                "ACCESSION_NUMBER",
                "HOLDING_ID",
                "ISSUER_NAME",
                "ISSUER_LEI",
                "ISSUER_TITLE",
                "ISSUER_CUSIP",
                "BALANCE",
                "UNIT",
                "OTHER_UNIT_DESC",
                "CURRENCY_CODE",
                "CURRENCY_VALUE",
                "EXCHANGE_RATE",
                "PERCENTAGE",
                "PAYOFF_PROFILE",
                "ASSET_CAT",
                "OTHER_ASSET",
                "ISSUER_TYPE",
                "OTHER_ISSUER",
                "INVESTMENT_COUNTRY",
                "IS_RESTRICTED_SECURITY",
                "FAIR_VALUE_LEVEL",
                "DERIVATIVE_CAT",
            ),
            (
                {
                    "ACCESSION_NUMBER": accession,
                    "HOLDING_ID": "1001",
                    "ISSUER_NAME": "Synthetic Issuer",
                    "ISSUER_LEI": "",
                    "ISSUER_TITLE": "Synthetic Common Stock",
                    "ISSUER_CUSIP": "000000000",
                    "BALANCE": "100",
                    "UNIT": "SH",
                    "OTHER_UNIT_DESC": "",
                    "CURRENCY_CODE": "USD",
                    "CURRENCY_VALUE": "1000.25",
                    "EXCHANGE_RATE": "1",
                    "PERCENTAGE": "4.25",
                    "PAYOFF_PROFILE": "Long",
                    "ASSET_CAT": "EC",
                    "OTHER_ASSET": "",
                    "ISSUER_TYPE": "CORP",
                    "OTHER_ISSUER": "",
                    "INVESTMENT_COUNTRY": "US",
                    "IS_RESTRICTED_SECURITY": "N",
                    "FAIR_VALUE_LEVEL": "1",
                    "DERIVATIVE_CAT": "",
                },
            ),
        ),
        "IDENTIFIERS.tsv": _tsv_payload(
            (
                "HOLDING_ID",
                "IDENTIFIERS_ID",
                "IDENTIFIER_ISIN",
                "IDENTIFIER_TICKER",
                "OTHER_IDENTIFIER",
                "OTHER_IDENTIFIER_DESC",
            ),
            (
                {
                    "HOLDING_ID": "1001",
                    "IDENTIFIERS_ID": "1",
                    "IDENTIFIER_ISIN": "US0000000002",
                    "IDENTIFIER_TICKER": "SYNH",
                    "OTHER_IDENTIFIER": "",
                    "OTHER_IDENTIFIER_DESC": "",
                },
            ),
        ),
    }


def write_sec_nport_archive(
    path: Path, files: dict[str, bytes] | None = None
) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in (files or sec_nport_tsv_files()).items():
            archive.writestr(name, payload)
    return path
