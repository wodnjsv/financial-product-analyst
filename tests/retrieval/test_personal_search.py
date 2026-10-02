from contextlib import nullcontext
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from financial_agent.retrieval import personal_search as module


@pytest.mark.parametrize("plan,word,limit", [
    ("bad", "환율", 1), ("rank_return", "", 1), ("rank_return", "%", 1),
    ("holding_weight", "a_b", 1), ("rank_return", "x", True),
    ("rank_return", "x", 6), ("document_risk", "환율", 4),
])
def test_invalid_plan_does_not_connect(monkeypatch, plan, word, limit):
    monkeypatch.setattr(module.psycopg, "connect", lambda *a, **k: pytest.fail("Must not connect"))
    with pytest.raises(ValueError):
        module.search_personal_dataset(plan, word, limit)


def test_sql_is_parameterized(monkeypatch):
    calls = []
    def execute(sql, params):
        calls.append((sql, params))
        return SimpleNamespace(fetchall=lambda: [])
    def connect(*args, **kwargs):
        assert "default_transaction_read_only=on" in kwargs["options"]
        assert "role=fa_runtime" in kwargs["options"]
        return nullcontext(SimpleNamespace(execute=execute))
    monkeypatch.setattr(module.psycopg, "connect", connect)
    result = module.search_personal_dataset("rank_return", "x'; SELECT 1;--", 1)
    assert calls[0][1] == (module.DATASET, "%x'; SELECT 1;--%", 1)
    assert "SELECT 1;--" not in calls[0][0]
    assert result["metadata"]["matched_count"] == 0


def test_document_excerpt_hash_and_literal_text():
    text = " 앞부분 환율 위험\n원문 유지 "
    row = {"exact_text": text, "content_hash": hashlib.sha256(text.encode()).hexdigest()}
    module.document_excerpt(row, "환율")
    assert row["excerpt"] == text
    with pytest.raises(ValueError, match="HASH"):
        module.document_excerpt({"exact_text": text, "content_hash": "bad"}, "환율")


def test_live_path_wires_evidence_to_renderer(monkeypatch):
    row = {"canonical_name": "예시", "observation_id": "o", "relation_id": "r",
        "weight_pct": None, "unit": "percentage_point", "value_status": "unknown",
        "reason_code": "SOURCE_VALUE_MISSING", "matched_products": 1,
        "products_with_known_weight": 0, "holdings_date": "2026-08-22"}
    def execute(sql, params=None):
        if "to_regclass" in sql:
            return SimpleNamespace(fetchone=lambda: {"table_name": None})
        if sql == module.SQLS["holding_weight"]:
            data = [deepcopy(row)]
        else:
            assert params in [(module.DATASET, "o"), (module.DATASET, "r")]
            data = [{"locator": "sample.csv", "row": 2, "column": "비중"}]
        return SimpleNamespace(fetchall=lambda: data)
    monkeypatch.setattr(module.psycopg, "connect", lambda *a, **k: nullcontext(SimpleNamespace(execute=execute)))
    result = module.search_personal_dataset("holding_weight", "삼성전자보통주", 1)
    assert "행 2" in result["answer"]
    assert result["metadata"]["ranking_available"] is False
    assert result["items"][0]["sources_complete"] is True


@pytest.mark.parametrize("limit,returned", [(1, 1), (3, 1), (3, 3)])
def test_document_guidance_matches_bounded_return_count(monkeypatch, limit, returned):
    text = "환율 변동 위험이 있습니다."
    rows = [{"document_title": f"문서 {index}", "exact_text": text,
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "matched_documents": 8, "published_at": "2026-08-21",
        "filing_locator": "https://example.org/filing",
        "attachment_locator": "https://example.org/attachment"}
        for index in range(returned)]
    def execute(sql, params):
        assert sql == module.SQLS["document_risk"]
        assert params == (module.DATASET, "환율", limit)
        return SimpleNamespace(fetchall=lambda: deepcopy(rows))
    monkeypatch.setattr(module.psycopg, "connect", lambda *a, **k: nullcontext(SimpleNamespace(execute=execute)))
    result = module.search_personal_dataset("document_risk", "환율", limit)
    assert f"검색 일치 8개 / 표시 {returned}개" in result["answer"]
    assert "요청한 개수 이내" in result["answer"]
    assert "문서 3개를 반환" not in result["answer"]


@pytest.mark.parametrize("limit,keyword", [(1, "삼성전자보통주"), (5, "삼성전자우")])
def test_holding_guidance_matches_exact_name_search(monkeypatch, limit, keyword):
    row = {"canonical_name": "예시", "observation_id": "o", "relation_id": "r",
        "weight_pct": None, "unit": "percentage_point", "value_status": "unknown",
        "reason_code": "SOURCE_VALUE_MISSING", "matched_products": 9,
        "products_with_known_weight": 0, "holdings_date": "2026-08-22"}
    def execute(sql, params=None):
        if "to_regclass" in sql:
            return SimpleNamespace(fetchone=lambda: {"table_name": None})
        if sql == module.SQLS["holding_weight"]:
            assert params == (module.DATASET, keyword, limit)
            data = [deepcopy(row)]
        else:
            data = [{"locator": "sample.csv", "row": 2, "column": "비중"}]
        return SimpleNamespace(fetchall=lambda: data)
    monkeypatch.setattr(module.psycopg, "connect", lambda *a, **k: nullcontext(SimpleNamespace(execute=execute)))
    result = module.search_personal_dataset("holding_weight", keyword, limit)
    assert "검색 일치 9개 / 표시 1개" in result["answer"]
    assert "공백을 제외하고 이름이 정확히 일치" in result["answer"]
    assert "보통주만 검색" not in result["answer"]
    assert "우선주는 제외" not in result["answer"]
    assert "표시된 5개" not in result["answer"]
