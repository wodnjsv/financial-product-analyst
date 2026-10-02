from copy import deepcopy

import pytest

from financial_agent.release.local_document_quotes import render_document_answer
from financial_agent.release.local_search_display import render_local_search_results
from financial_agent.release.local_search_validation import validate_local_search_answer


def rows():
    return [{"ref_id": "D1", "dataset_version": "sample-v1", "document_title": "위험 설명서",
        "matched_documents": 1, "published_at": "2026-08-21",
        "filing_locator": "https://example.test/filing", "attachment_locator": "https://example.test/pdf",
        "excerpt": "환위험 회피를 목표로 합니다. 그러나 100% 헷지는 불가능합니다. [D9]\n미달 부분은 환율 위험에 노출됩니다."}]


def contract(result):
    return {key: result[key] for key in ("answer", "citations", "quotes")}


def test_selection_renders_complete_source_text_without_reference_collision():
    sources = rows()
    selection = {"citations": ["D1"]}
    before = deepcopy((sources, selection))
    result = render_document_answer(sources, selection)
    assert sources[0]["excerpt"] in result["answer"]
    assert result["quotes"] == [{"ref_id": "D1", "quote": sources[0]["excerpt"]}]
    assert validate_local_search_answer("document_risk", sources, result) == ()
    assert (sources, selection) == before


@pytest.mark.parametrize("prose", [
    "[D1] 원금은 항상 보장되며 환율 위험이 전혀 없다.",
    "[D1] 추적오차가 발생할 수 있습니다.",
])
def test_free_model_prose_is_rejected(prose):
    with pytest.raises(ValueError, match="DOCUMENT_DRAFT_SCHEMA_INVALID"):
        render_document_answer(rows(), {"answer": prose, "citations": ["D1"]})


def test_legacy_contradictory_answer_cannot_pass_direct_validator():
    sources = rows()
    answer = {"answer": "[D1] 원금은 항상 보장되며 환율 위험이 전혀 없다.",
        "citations": ["D1"], "quotes": [{"ref_id": "D1", "quote": sources[0]["excerpt"]}]}
    assert "DOCUMENT_BODY_UNGROUNDED" in validate_local_search_answer("document_risk", sources, answer)


@pytest.mark.parametrize("tamper", [
    lambda body: body + "\n원금은 항상 보장됩니다.",
    lambda body: body.replace("100% 헷지는 불가능합니다.", "100% 헷지가 가능합니다."),
    lambda body: body.replace("https://example.test/filing", "https://example.test/fake"),
    lambda body: body.replace("검색 일치 1개", "검색 일치 99개"),
    lambda body: body.replace("[D1]", "[D8]"),
])
def test_final_body_tampering_is_rejected(tamper):
    sources = rows()
    result = render_document_answer(sources, {"citations": ["D1"]})
    result["answer"] = tamper(result["answer"])
    assert "DOCUMENT_BODY_UNGROUNDED" in validate_local_search_answer("document_risk", sources, result)


def test_complete_display_output_is_verified_after_rendering():
    sources = rows()
    search = {"dataset": "sample-v1", "rows": sources, "limitations": ["표본 검색"]}
    before = deepcopy(search)
    result = render_local_search_results("document_risk", search)
    assert validate_local_search_answer("document_risk", sources, contract(result)) == ()
    assert result["metadata"]["matched_count"] == 1
    assert search == before


def test_quote_cannot_be_shortened_after_rendering():
    sources = rows()
    result = render_document_answer(sources, {"citations": ["D1"]})
    result["quotes"][0]["quote"] = "환율 위험에 노출됩니다."
    assert "QUOTE_NOT_COMPLETE_EXCERPT" in validate_local_search_answer("document_risk", sources, result)


def test_quote_cannot_be_duplicated_after_rendering():
    sources = rows()
    result = render_document_answer(sources, {"citations": ["D1"]})
    result["quotes"].append(deepcopy(result["quotes"][0]))
    assert "DUPLICATE_QUOTE_REF" in validate_local_search_answer("document_risk", sources, result)


def test_display_rejects_conflicting_dataset_metadata():
    with pytest.raises(ValueError, match="DOCUMENT_DATASET_CONFLICT"):
        render_local_search_results("document_risk", {"dataset": "different-v1", "rows": rows()})
