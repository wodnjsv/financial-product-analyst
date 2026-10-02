"""Capture/import the three approved manager observations into a local adjunct."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path

import httpx
import psycopg
from psycopg.rows import dict_row

from financial_agent.ingestion.official.manager_weights import (
    PRODUCT_CODES, REQUESTED_DATE, TIGER_PRODUCTS, parse_samsung_weight, parse_tiger_weight, parse_plus_weight, parse_hanaro_weight, parse_won_weight, product_identity,
)

DATASET = "personal-2026-08-24-v1"
HOST = "https://www.samsungfund.com"
DDL = """
CREATE SCHEMA IF NOT EXISTS personal_local;
CREATE TABLE IF NOT EXISTS personal_local.holding_weight_supplement (
 dataset_version text NOT NULL,
 entity_id text NOT NULL,
 product_code text NOT NULL,
 security_code text NOT NULL,
 security_name text NOT NULL,
 metric_id text NOT NULL,
 weight_pct numeric NOT NULL CHECK (weight_pct >= 0 AND weight_pct <= 100),
 applicable_date date NOT NULL,
 requested_date date NOT NULL,
 publisher text NOT NULL,
 basis text NOT NULL,
 source_url text NOT NULL,
 source_sha256 text NOT NULL,
 source_path text NOT NULL,
 source_pointer text NOT NULL,
 identity_url text NOT NULL,
 identity_sha256 text NOT NULL,
 identity_path text NOT NULL,
 captured_at timestamptz NOT NULL,
 PRIMARY KEY (dataset_version,entity_id,security_code,metric_id,applicable_date),
 FOREIGN KEY (dataset_version,entity_id) REFERENCES catalog.entity(dataset_version,entity_id)
);
GRANT USAGE ON SCHEMA personal_local TO fa_runtime;
GRANT SELECT ON personal_local.holding_weight_supplement TO fa_runtime;
"""


def capture(root: Path) -> list[dict]:
    directory = root / "data/personal-manager-weights" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    records = []
    with httpx.Client(timeout=25) as client:
        for code in PRODUCT_CODES:
            identity = client.get(HOST + "/api/v1/kodex/product.do", params={
                "ordrColm": "NAV", "ordrSort": "DESC", "pageNo": 1, "srchTerm": "w", "srchVal": code})
            identity.raise_for_status()
            product = product_identity(identity.json(), code)
            response = client.get(HOST + f"/api/v1/kodex/product-pdf/{product['fId']}.do", params={"gijunYMD": REQUESTED_DATE.strftime("%Y.%m.%d")})
            response.raise_for_status()
            parsed = parse_samsung_weight(response.json())
            raw_path = directory / f"{code}-pdf.json"
            identity_path = directory / f"{code}-identity.json"
            raw_path.write_bytes(response.content)
            identity_path.write_bytes(identity.content)
            records.append(parsed | {
                "product_code": code, "publisher": "삼성자산운용",
                "source_url": str(response.url), "source_sha256": hashlib.sha256(response.content).hexdigest(),
                "source_path": str(raw_path.relative_to(root)),
                "identity_url": str(identity.url), "identity_sha256": hashlib.sha256(identity.content).hexdigest(),
                "identity_path": str(identity_path.relative_to(root)),
                "captured_at": datetime.now(timezone.utc).isoformat(),
            })
    (directory / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str))
    return records


def import_records(records: list[dict]) -> list[dict]:
    codes = {r["product_code"] for r in records}
    if len(records) != len(codes) or codes not in (set(PRODUCT_CODES), set(TIGER_PRODUCTS), {"122090"}, {"332940"}, {"0177A0"}):
        raise ValueError("SUPPLEMENT_BATCH_INCOMPLETE")
    with psycopg.connect("postgresql://localhost/financial_agent_local", row_factory=dict_row) as conn:
        conn.execute("SET LOCAL statement_timeout='30s'")
        for record in records:
            matches = conn.execute("""
                SELECT DISTINCT i.entity_id FROM catalog.identifier i
                JOIN catalog.product p USING(dataset_version,entity_id)
                WHERE i.dataset_version=%s AND i.scheme='PREF01_PD_ITM_NO_MA'
                  AND i.identifier_value=%s AND p.product_family='domestic_etf'
            """, (DATASET, "A" + record["product_code"])).fetchall()
            if len(matches) != 1:
                raise ValueError("LOCAL_PRODUCT_IDENTITY_INVALID")
            record["entity_id"] = matches[0]["entity_id"]
            record["dataset_version"] = DATASET
        conn.execute(DDL)
        columns = ("dataset_version", "entity_id", "product_code", "security_code", "security_name", "metric_id", "weight_pct", "applicable_date", "requested_date", "publisher", "basis", "source_url", "source_sha256", "source_path", "source_pointer", "identity_url", "identity_sha256", "identity_path", "captured_at")
        # Column names are a fixed application constant; values are always bound.
        sql = "INSERT INTO personal_local.holding_weight_supplement (" + ",".join(columns) + ") VALUES (" + ",".join(["%s"] * len(columns)) + ") ON CONFLICT DO NOTHING"
        for record in records:
            conn.execute(sql, tuple(record[name] for name in columns))
            stored = conn.execute("""SELECT weight_pct,basis FROM personal_local.holding_weight_supplement
                WHERE dataset_version=%s AND entity_id=%s AND security_code=%s AND metric_id=%s AND applicable_date=%s""",
                tuple(record[name] for name in ("dataset_version", "entity_id", "security_code", "metric_id", "applicable_date"))).fetchone()
            if stored["weight_pct"] != record["weight_pct"] or stored["basis"] != record["basis"]:
                raise ValueError("IMMUTABLE_SUPPLEMENT_CONFLICT")
    return records


def capture_tiger(root: Path) -> list[dict]:
    directory = root / "data/personal-manager-weights" / datetime.now(timezone.utc).strftime("tiger-%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    base = "https://investments.miraeasset.com/tigeretf/ko/product/"
    records = []
    with httpx.Client(timeout=25) as client:
        for code, isin in TIGER_PRODUCTS.items():
            identity = client.get(base + "search/detail/index.do", params={"ksdFund": isin})
            identity.raise_for_status()
            headings = re.findall(r"<h1[^>]*>(.*?)</h1>", identity.text, flags=re.S)
            if not any("TIGER" in heading and f"({code})" in heading for heading in headings):
                raise ValueError("MANAGER_IDENTITY_INVALID")
            listing = client.get(base + "search/detail/pdfListAjax.ajax", params={"ksdFund": isin, "fixDate": "2026.08.21", "prfPrd": "Week01", "order": "SRD"})
            listing.raise_for_status()
            totals = set(re.findall(r'data-tot-cnt="([0-9]+)"', listing.text))
            if len(totals) != 1:
                raise ValueError("MANAGER_RESPONSE_INCOMPLETE")
            expected = int(next(iter(totals)))
            if not 1 <= expected <= 1000:
                raise ValueError("MANAGER_RESPONSE_INCOMPLETE")
            response = client.get(base + "chart/prdct-item-list.ajax", params={"ksdFund": isin, "fixDate": "20260821", "prfPrd": "Week01", "listCnt": expected})
            response.raise_for_status()
            parsed = parse_tiger_weight(response.json(), isin, expected)
            raw_path = directory / f"{code}-pdf.json"
            identity_path = directory / f"{code}-identity.html"
            raw_path.write_bytes(response.content)
            identity_path.write_bytes(identity.content)
            (directory / f"{code}-count.html").write_bytes(listing.content)
            records.append(parsed | {"product_code": code, "publisher": "미래에셋자산운용 TIGER",
                "source_url": str(response.url), "source_sha256": hashlib.sha256(response.content).hexdigest(),
                "source_path": str(raw_path.relative_to(root)),
                "identity_url": str(identity.url), "identity_sha256": hashlib.sha256(identity.content).hexdigest(),
                "identity_path": str(identity_path.relative_to(root)), "captured_at": datetime.now(timezone.utc).isoformat()})
    (directory / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str))
    return records


def capture_plus(root: Path) -> list[dict]:
    directory = root / "data/personal-manager-weights" / datetime.now(timezone.utc).strftime("plus-%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    with httpx.Client(timeout=25) as client:
        identity = client.get("https://www.plusetf.co.kr/product/detail", params={"n": "006181"})
        identity.raise_for_status()
        if "<title>PLUS 코스피50 | PLUS ETF</title>" not in identity.text or "122090" not in identity.text:
            raise ValueError("MANAGER_IDENTITY_INVALID")
        response = client.get("https://www.plusetf.co.kr/api/v1/product/pdf/list", params={"n": "006181", "page": 0, "d": "20260821", "pageSize": 1000})
        response.raise_for_status()
        parsed = parse_plus_weight(response.json())
    raw_path = directory / "122090-pdf.json"
    identity_path = directory / "122090-identity.html"
    raw_path.write_bytes(response.content)
    identity_path.write_bytes(identity.content)
    records = [parsed | {"product_code": "122090", "publisher": "한화자산운용 PLUS",
        "source_url": str(response.url), "source_sha256": hashlib.sha256(response.content).hexdigest(),
        "source_path": str(raw_path.relative_to(root)),
        "identity_url": str(identity.url), "identity_sha256": hashlib.sha256(identity.content).hexdigest(),
        "identity_path": str(identity_path.relative_to(root)), "captured_at": datetime.now(timezone.utc).isoformat()}]
    (directory / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str))
    return records


def capture_hanaro(root: Path) -> list[dict]:
    directory = root / "data/personal-manager-weights" / datetime.now(timezone.utc).strftime("hanaro-%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    base = "https://www.hanaroetf.com"
    uid = "CEBA1E927AC1478B"
    with httpx.Client(timeout=25) as client:
        identity = client.get(base + f"/fund/{uid}")
        identity.raise_for_status()
        if "332940" not in identity.text or "HANARO MSCI KOREA TR" not in identity.text:
            raise ValueError("MANAGER_IDENTITY_INVALID")
        response = client.get(base + f"/api/v1/fund/{uid}/get-fund-holdings-list", params={"baseDate": "2026.08.21"})
        response.raise_for_status()
        excel = client.get(base + f"/fund/pdfExcelDownload/{uid}/2026.08.21")
        excel.raise_for_status()
        parsed = parse_hanaro_weight(response.text, excel.content, excel.headers.get("content-disposition", ""))
    raw_path = directory / "332940-pdf.html"
    identity_path = directory / "332940-identity.html"
    date_path = directory / "332940-20260821.xlsx"
    raw_path.write_bytes(response.content)
    identity_path.write_bytes(identity.content)
    date_path.write_bytes(excel.content)
    records = [parsed | {"product_code": "332940", "publisher": "NH-Amundi HANARO",
        "source_url": str(response.url), "source_sha256": hashlib.sha256(response.content).hexdigest(),
        "source_path": str(raw_path.relative_to(root)),
        "identity_url": str(identity.url), "identity_sha256": hashlib.sha256(identity.content).hexdigest(),
        "identity_path": str(identity_path.relative_to(root)), "captured_at": datetime.now(timezone.utc).isoformat(),
        "date_evidence_url": str(excel.url), "date_evidence_path": str(date_path.relative_to(root)),
        "date_evidence_sha256": hashlib.sha256(excel.content).hexdigest(),
        "date_evidence_disposition": excel.headers.get("content-disposition") }]
    (directory / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str))
    return records


def capture_won(root: Path) -> list[dict]:
    directory = root / "data/personal-manager-weights" / datetime.now(timezone.utc).strftime("won-%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    with httpx.Client(timeout=25) as client:
        identity = client.get("https://www.wooriam.kr/investment/etf-view/EyxRV5tq8bcirxah")
        identity.raise_for_status()
        if "0177A0" not in identity.text or "두산그룹포커스" not in identity.text:
            raise ValueError("MANAGER_IDENTITY_INVALID")
        token = re.search(r'<meta name="csrf-token" content="([^"]+)"', identity.text)
        if not token:
            raise ValueError("PUBLIC_FORM_TOKEN_MISSING")
        response = client.post("https://www.wooriam.kr/investment/GetPDFListAJX",
            files={"fundCode": (None, "ETFG"), "pdfSearchDate": (None, "2026.08.21")},
            headers={"X-CSRF-TOKEN": token.group(1), "Referer": str(identity.url)})
        response.raise_for_status()
        parsed = parse_won_weight(response.json())
    # Preserve non-secret identity evidence, never the transient public form token.
    sanitized = identity.text.replace(token.group(1), "[REDACTED]").encode()
    raw_path = directory / "0177A0-pdf.json"
    identity_path = directory / "0177A0-identity-redacted.html"
    raw_path.write_bytes(response.content)
    identity_path.write_bytes(sanitized)
    records = [parsed | {"product_code": "0177A0", "publisher": "우리자산운용 WON",
        "source_url": str(response.url), "source_sha256": hashlib.sha256(response.content).hexdigest(),
        "source_path": str(raw_path.relative_to(root)),
        "identity_url": str(identity.url), "identity_sha256": hashlib.sha256(sanitized).hexdigest(),
        "identity_path": str(identity_path.relative_to(root)), "identity_sanitized": True,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "request_method": "POST", "request_parameters": {"fundCode": "ETFG", "pdfSearchDate": "2026.08.21"}}]
    (directory / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str))
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--publisher", choices=("samsung", "tiger", "plus", "hanaro", "won"), default="samsung")
    args = parser.parse_args()
    root = args.workspace_root.resolve()
    records = import_records({"samsung": capture, "tiger": capture_tiger, "plus": capture_plus, "hanaro": capture_hanaro, "won": capture_won}[args.publisher](root))
    print(json.dumps([{"product_code": r["product_code"], "weight_pct": str(r["weight_pct"]), "applicable_date": str(r["applicable_date"]), "basis": r["basis"]} for r in records], ensure_ascii=False, indent=2))
