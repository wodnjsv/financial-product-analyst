from copy import deepcopy

import pytest

from financial_agent.release.local_document_quotes import render_document_answer
from financial_agent.release.local_search_validation import validate_local_search_answer


def test_server_copies_exact_excerpts_and_preserves_inputs():
    rows = [
        {"ref_id": "D1", "excerpt": " 환율\n원금 손실\t위험\f "},
        {"ref_id": "D2", "excerpt": "헷지 ± 범위"},
    ]
    draft = {"citations": ["D2", "D1"]}
    before = deepcopy((rows, draft))
    result = render_document_answer(rows, draft)
    assert result["quotes"] == [
        {"ref_id": "D2", "quote": rows[1]["excerpt"]},
        {"ref_id": "D1", "quote": rows[0]["excerpt"]},
    ]
    assert rows[0]["excerpt"] in result["answer"]
    assert rows[1]["excerpt"] in result["answer"]
    assert validate_local_search_answer("document_risk", rows, result) == ()
    assert (rows, draft) == before


@pytest.mark.parametrize("draft,code", [
    (None, "DOCUMENT_DRAFT_SCHEMA_INVALID"),
    ({}, "DOCUMENT_DRAFT_SCHEMA_INVALID"),
    ({"citations": ["D1"], "quotes": []}, "DOCUMENT_DRAFT_SCHEMA_INVALID"),
    ({"citations": [1]}, "DOCUMENT_DRAFT_SCHEMA_INVALID"),
    ({"answer": " ", "citations": ["D1"]}, "DOCUMENT_DRAFT_SCHEMA_INVALID"),
    ({"citations": ["D9"]}, "CITATION_REFS_MISMATCH"),
    ({"citations": ["D1", "D1"]}, "DUPLICATE_CITATION"),
    ({"citations": []}, "CITATION_REFS_MISMATCH"),
    ({"answer": "설명", "citations": ["D1"]}, "DOCUMENT_DRAFT_SCHEMA_INVALID"),
])
def test_bad_draft_fails_before_rendering(draft, code):
    with pytest.raises(ValueError, match=code):
        render_document_answer([{"ref_id": "D1", "excerpt": "원문"}], draft)


@pytest.mark.parametrize("rows", [None, [], [None], [{}],
    [{"ref_id": "D1"}], [{"ref_id": "D1", "excerpt": " "}],
    [{"ref_id": "D1", "excerpt": "원문"}] * 2])
def test_invalid_sources_fail_explicitly(rows):
    with pytest.raises(ValueError):
        render_document_answer(rows, {"citations": ["D1"]})


def test_missing_document_is_not_silently_omitted():
    rows = [{"ref_id": "D1", "excerpt": "첫 원문"}, {"ref_id": "D2", "excerpt": "둘째 원문"}]
    with pytest.raises(ValueError, match="CITATION_REFS_MISMATCH"):
        render_document_answer(rows, {"citations": ["D1"]})
