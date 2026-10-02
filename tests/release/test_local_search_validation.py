from copy import deepcopy

import pytest

from financial_agent.release.local_search_validation import validate_local_search_answer
from financial_agent.release.local_document_text import document_answer_text


def sql_answer():
    return {"answer": "조회 결과 [R1]", "citations": ["R1"], "quotes": []}


def document_answer():
    return {
        "answer": document_answer_text([{"ref_id": "D1", "excerpt": "환율에 따라 원금 손실 발생"}]),
        "citations": ["D1"],
        "quotes": [{"ref_id": "D1", "quote": "환율에 따라 원금 손실 발생"}],
    }


@pytest.mark.parametrize("plan", ["rank_return", "holding_weight"])
def test_sql_needs_no_excerpt(plan):
    assert validate_local_search_answer(plan, [{"ref_id": "R1"}], sql_answer()) == ()


@pytest.mark.parametrize("quotes", [[{"ref_id": "R1", "quote": "상품", "note": ""}], [None]])
def test_sql_quotes_rejected_without_document_access(quotes):
    answer = sql_answer()
    answer["quotes"] = quotes
    assert validate_local_search_answer("rank_return", [{"ref_id": "R1"}], answer) == (
        "SQL_QUOTES_MUST_BE_EMPTY",
    )


@pytest.mark.parametrize("answer", [None, [], "text", {}, {"answer": 3},
    {"answer": "x", "citations": [None], "quotes": []},
    {"answer": "x", "citations": ["R1"], "quotes": None}])
def test_malformed_answer_fails_closed(answer):
    assert validate_local_search_answer("rank_return", [{"ref_id": "R1"}], answer) == (
        "ANSWER_SCHEMA_INVALID",
    )


@pytest.mark.parametrize("patch,code", [
    ({"answer": " "}, "ANSWER_EMPTY"),
    ({"answer": "결과 [R2]"}, "INLINE_REFS_MISMATCH"),
    ({"citations": ["R2"]}, "CITATION_REFS_MISMATCH"),
    ({"citations": ["R1", "R1"]}, "DUPLICATE_CITATION"),
    ({"extra": True}, "ANSWER_SCHEMA_INVALID"),
])
def test_answer_contract(patch, code):
    answer = sql_answer() | patch
    assert code in validate_local_search_answer("rank_return", [{"ref_id": "R1"}], answer)


def test_document_quote_is_literal_and_inputs_unchanged():
    rows = [{"ref_id": "D1", "excerpt": "환율에 따라 원금 손실 발생"}]
    answer = document_answer()
    original = deepcopy((rows, answer))
    assert validate_local_search_answer("document_risk", rows, answer) == ()
    assert (rows, answer) == original


@pytest.mark.parametrize("quotes,code", [
    ([{"ref_id": "D1", "quote": "원금 손실 원금 손실"}], "QUOTE_NOT_VERBATIM"),
    ([{"ref_id": "D1", "quote": ""}], "QUOTE_NOT_VERBATIM"),
    ([{"ref_id": "D1", "quote": " "}], "QUOTE_NOT_VERBATIM"),
    ([{"ref_id": "D9", "quote": "원금 손실"}], "QUOTE_REF_UNKNOWN"),
    ([], "DOCUMENT_QUOTES_INCOMPLETE"),
    ([None], "QUOTE_SCHEMA_INVALID"),
    ([{"ref_id": "D1"}], "QUOTE_SCHEMA_INVALID"),
])
def test_document_rejections(quotes, code):
    answer = document_answer() | {"quotes": quotes}
    assert code in validate_local_search_answer(
        "document_risk", [{"ref_id": "D1", "excerpt": "원금 손실 위험"}], answer
    )


@pytest.mark.parametrize("rows,code", [
    (None, "SEARCH_ROWS_INVALID"), ([], "SEARCH_ROWS_INVALID"),
    ([None], "SEARCH_ROWS_INVALID"), ([{}], "SEARCH_ROWS_INVALID"),
    ([{"ref_id": []}], "SEARCH_ROWS_INVALID"),
    ([{"ref_id": "D1"}], "DOCUMENT_EXCERPT_INVALID"),
    ([{"ref_id": "D1", "excerpt": 3}], "DOCUMENT_EXCERPT_INVALID"),
    ([{"ref_id": "D1", "excerpt": "x"}] * 2, "DUPLICATE_SOURCE_REF"),
])
def test_invalid_sources(rows, code):
    assert validate_local_search_answer("document_risk", rows, document_answer()) == (code,)


def test_every_document_requires_a_quote():
    rows = [{"ref_id": "D1", "excerpt": "원금 손실"}, {"ref_id": "D2", "excerpt": "위험"}]
    answer = document_answer() | {"answer": "[D1] [D2]", "citations": ["D1", "D2"]}
    assert "DOCUMENT_QUOTES_INCOMPLETE" in validate_local_search_answer("document_risk", rows, answer)


def test_unknown_plan():
    assert validate_local_search_answer("unexpected", [], {}) == ("UNKNOWN_PLAN",)
