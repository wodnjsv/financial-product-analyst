"""Bounded read-only PostgreSQL queries for the personal local profile."""

import hashlib

import psycopg
from psycopg.rows import dict_row

from financial_agent.release.local_search_display import render_local_search_results

DATASET = "personal-2026-08-24-v1"

SQLS = {
    'rank_return': """SELECT p.entity_id,e.canonical_name,o.observation_id,
 o.numeric_value AS return_1y_pct,o.unit,o.value_status,o.applicable_date,
 count(*) OVER() AS matched_products
 FROM catalog.product p JOIN catalog.entity e USING(dataset_version,entity_id)
 JOIN observation.observation_record o USING(dataset_version,entity_id)
 WHERE p.dataset_version=%s AND p.product_family='domestic_etf'
 AND e.canonical_name ILIKE %s
 AND o.metric_id='organizer.pref01n001.cumulative_return_1y'
 AND o.value_status IN ('present','zero') AND o.applicable_date='2026-08-21'
 ORDER BY o.numeric_value DESC,p.entity_id LIMIT %s""",
    'holding_weight': """SELECT p.entity_id,e.canonical_name,held.canonical_name AS holding_name,
 r.relation_id,r.valid_from AS holdings_date,o.observation_id,
 o.numeric_value AS weight_pct,o.unit,o.value_status,o.reason_code,
 count(*) OVER() AS matched_products,count(o.numeric_value) OVER() AS products_with_known_weight
 FROM relation.relation_record r
 JOIN catalog.product p ON p.dataset_version=r.dataset_version AND p.entity_id=r.subject_id
 JOIN catalog.entity e ON e.dataset_version=r.dataset_version AND e.entity_id=r.subject_id
 JOIN catalog.entity held ON held.dataset_version=r.dataset_version AND held.entity_id=r.object_id
 JOIN observation.observation_record o ON o.dataset_version=r.dataset_version AND o.relation_id=r.relation_id
 WHERE r.dataset_version=%s AND r.predicate_id='holdsSecurity' AND p.product_family='domestic_etf'
 AND replace(held.canonical_name,' ','')=replace(%s,' ','')
 AND o.metric_id='krx_etf_holding_weight_pct'
 ORDER BY o.numeric_value DESC NULLS LAST,e.canonical_name,p.entity_id LIMIT %s""",
    'document_risk': """WITH hits AS (
 SELECT d.dataset_version,d.document_id,d.document_title,d.published_at,c.chunk_id,c.section_type,c.section_path,
 c.page_start,c.page_end,c.exact_text,c.content_hash,a.filing_locator,a.attachment_locator,
 row_number() OVER(PARTITION BY d.document_id ORDER BY c.ordinal,c.chunk_id) AS doc_rank
 FROM document.document_chunk c JOIN document.document_record d USING(dataset_version,document_id)
 JOIN document.document_source_artifact a USING(dataset_version,document_id)
 JOIN document.document_profile dp USING(dataset_version,document_id)
 WHERE c.dataset_version=%s AND c.section_type='risk_factor' AND dp.cutoff_eligible
 AND d.published_at::date<='2026-08-24' AND position(%s in c.exact_text)>0)
 SELECT *,count(*) OVER() AS matched_documents FROM hits WHERE doc_rank=1
 ORDER BY published_at DESC,document_id LIMIT %s""",
}

LIMITATIONS = {
    'rank_return': [
        '국내 ETF 마스터에서 이름에 검색어가 포함되고 1년 수익률이 present/zero이며 기준일이 2026-08-21인 상품만 순위에 포함.',
        '원본 저장값의 내림차순이며 현재 시세나 미래 수익 예측이 아님. 레버리지 상품도 포함되며 별도 위험 조정은 하지 않음.',
    ],
    'holding_weight': [
        '구성종목이 적재된 국내 ETF 50개 표본 내 검색. 나머지 국내 ETF 전체로 일반화 불가.',
        '검색어와 공백을 제외하고 이름이 정확히 일치하는 보유종목을 검색. KRX 표본의 전체 식별 커버리지는 PARTIALLY_COVERED 상태.',
        'products_with_known_weight가 matched_products보다 작으면 전체 대상의 비중 순위를 확정할 수 없음. 특히 알려진 비중이 0개이면 비중 순위 산출 불가이며 표시된 상품은 이름순 조회 예시다. 누락을 0%로 치환하거나 수량·평가금액으로 임의 비중을 계산하지 말 것.',
    ],
    'document_risk': [
        '복원한 100개 문서의 risk_factor 청크에서 키워드 포함 여부로 검색. 벡터 검색은 실행하지 않음.',
        '문서별 첫 일치 청크를 선택하고 공시일 내림차순으로 요청한 개수 이내 반환. 최신 공시 전체를 포괄하지 않음.',
        '문서 청크 참조이며 운영 Evidence 승격이나 전체 Answer Verifier 실행 결과가 아님.',
    ],
}

EVIDENCE_SQL = """
SELECT er.locator_uri_or_object_key AS locator, er.locator_sheet AS sheet,
       er.locator_row AS row, er.locator_column AS column,
       er.raw_value_repr AS raw_value, er.evidence_id
FROM evidence.evidence_observation_origin eo
JOIN evidence.evidence_record er USING (dataset_version, evidence_id)
WHERE eo.dataset_version=%s AND eo.observation_id=%s
ORDER BY er.evidence_id
"""
HOLDING_EVIDENCE_SQL = """
SELECT er.locator_uri_or_object_key AS locator, er.locator_row AS row,
       er.locator_column AS column, er.locator_record_key AS record_key
FROM evidence.evidence_relation_origin eo
JOIN evidence.evidence_record er USING (dataset_version, evidence_id)
WHERE eo.dataset_version=%s AND eo.relation_id=%s
ORDER BY er.evidence_id
"""


def validate_plan(plan_id: str, keyword: str, limit: int) -> None:
    if plan_id not in SQLS:
        raise ValueError("UNKNOWN_PLAN")
    if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 40:
        raise ValueError("KEYWORD_INVALID")
    if any(char in keyword for char in ("%", "_", "\\")):
        raise ValueError("LITERAL_KEYWORD_REQUIRED")
    if type(limit) is not int or not 1 <= limit <= (3 if plan_id == "document_risk" else 5):
        raise ValueError("LIMIT_INVALID")


def document_excerpt(row: dict, keyword: str) -> None:
    text = row.pop("exact_text")
    if hashlib.sha256(text.encode()).hexdigest() != row["content_hash"]:
        raise ValueError("DOCUMENT_HASH_MISMATCH")
    position = text.find(keyword)
    if position < 0:
        raise ValueError("DOCUMENT_KEYWORD_MISSING")
    start = max(0, position - 180)
    row["excerpt"] = text[start:position + 1100]
    row["excerpt_start_in_chunk"] = start


def search_personal_dataset(plan_id: str, keyword: str, limit: int = 3) -> dict:
    validate_plan(plan_id, keyword, limit)
    word = f"%{keyword}%" if plan_id == "rank_return" else keyword
    supplements = []
    with psycopg.connect(
        "postgresql://localhost/financial_agent_local", row_factory=dict_row,
        options="-c role=fa_runtime -c default_transaction_read_only=on -c statement_timeout=30000",
    ) as connection:
        rows = connection.execute(SQLS[plan_id], (DATASET, word, limit)).fetchall()
        prefix = {"rank_return": "R", "holding_weight": "H", "document_risk": "D"}[plan_id]
        for index, row in enumerate(rows, 1):
            row["ref_id"] = f"{prefix}{index}"
            if plan_id == "document_risk":
                document_excerpt(row, keyword)
            else:
                row["evidence"] = connection.execute(EVIDENCE_SQL, (DATASET, row["observation_id"])).fetchall()
                if plan_id == "holding_weight":
                    row["holding_evidence"] = connection.execute(HOLDING_EVIDENCE_SQL, (DATASET, row["relation_id"])).fetchall()
        if plan_id == "holding_weight" and rows:
            table = connection.execute(
                "SELECT to_regclass('personal_local.holding_weight_supplement') AS table_name"
            ).fetchone()
            if table["table_name"] is not None:
                supplements = connection.execute("""
                    SELECT DISTINCT s.* FROM personal_local.holding_weight_supplement s
                    JOIN relation.relation_record r ON r.dataset_version=s.dataset_version AND r.subject_id=s.entity_id
                    JOIN catalog.entity held ON held.dataset_version=r.dataset_version AND held.entity_id=r.object_id
                    WHERE s.dataset_version=%s AND r.predicate_id='holdsSecurity'
                      AND replace(held.canonical_name,' ','')=replace(%s,' ','')
                      AND held.canonical_name=s.security_name
                      AND s.requested_date='2026-08-22'
                      AND s.applicable_date='2026-08-21'
                      AND s.metric_id IN ('manager_pdf_weight_excluding_cash_deposits_pct', 'tiger_pdf_publisher_reported_weight_pct', 'plus_pdf_publisher_reported_weight_pct', 'hanaro_pdf_publisher_reported_weight_pct', 'won_pdf_publisher_reported_weight_pct')
                    ORDER BY s.product_code
                """, (DATASET, keyword)).fetchall()
                for row in rows:
                    row["supplementary_weights"] = [s for s in supplements if s["entity_id"] == row["entity_id"]]
    search = {"dataset": DATASET, "rows": rows, "limitations": LIMITATIONS[plan_id]}
    if supplements:
        search["supplement_known_products"] = len({s["entity_id"] for s in supplements})
    if not rows:
        return {"answer": f"데이터셋: {DATASET}\n검색 일치 0개 / 표시 0개\n현재 조회 범위 내 결과 없음. 전체 시장의 부재를 의미하지 않습니다.",
                "citations": [], "quotes": [], "metadata": {"dataset": DATASET, "matched_count": 0, "returned_count": 0}, "items": []}
    return render_local_search_results(plan_id, search)
