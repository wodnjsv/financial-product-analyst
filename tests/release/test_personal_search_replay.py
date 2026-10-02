import json

import pytest

from financial_agent.release.local_document_quotes import render_document_answer
from financial_agent.release.local_search_validation import validate_local_search_answer
from scripts.revalidate_personal_search import main


def replay(tmp_path, monkeypatch, capsys, records, *, derive=False):
    paths = []
    originals = []
    for index, record in enumerate(records):
        path = tmp_path / f"Q{index + 1}.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        paths.append(path)
        originals.append(path.read_bytes())
    args = ["revalidate_personal_search.py", *map(str, paths)]
    if derive:
        args.append("--render-document-quotes")
    monkeypatch.setattr("sys.argv", args)
    status = main()
    result = json.loads(capsys.readouterr().out)
    assert [path.read_bytes() for path in paths] == originals
    return status, result


def legacy_document():
    rows = [{"ref_id": "D1", "excerpt": "환헷지를 하더라도 환율변동위험에 노출됩니다. [D9]"}]
    return {
        "question_id": "Q3",
        "plan": {"plan_id": "document_risk"},
        "search": {"rows": rows},
        "answer": {
            "answer": "환위험이 완전히 없어 안전합니다. [D1]",
            "citations": ["D1"],
            "quotes": [{"ref_id": "D1", "quote": rows[0]["excerpt"]}],
        },
    }


def test_legacy_derivative_cannot_override_original_failure(tmp_path, monkeypatch, capsys):
    record = legacy_document()
    original_errors = validate_local_search_answer("document_risk", record["search"]["rows"], record["answer"])
    status, results = replay(tmp_path, monkeypatch, capsys, [record], derive=True)
    result = results[0]
    assert status == 1
    assert not result["contract_passed"]
    assert result["errors"] == list(original_errors)
    assert "DOCUMENT_BODY_UNGROUNDED" in result["errors"]
    assert result["server_render_contract_passed"]
    derivative = result["server_rendered_answer"]
    assert "환위험이 완전히 없어 안전합니다." not in derivative["answer"]
    assert record["search"]["rows"][0]["excerpt"] in derivative["answer"]
    assert derivative["quotes"] == record["answer"]["quotes"]
    assert "prose removed; distinct source-only derivative" in result["replay_note"]


def test_replay_does_not_derive_without_explicit_option(tmp_path, monkeypatch, capsys):
    status, results = replay(tmp_path, monkeypatch, capsys, [legacy_document()])
    assert status == 1
    assert "server_rendered_answer" not in results[0]
    assert "replay_note" not in results[0]


def test_current_source_owned_answer_remains_valid(tmp_path, monkeypatch, capsys):
    record = legacy_document()
    record["answer"] = render_document_answer(record["search"]["rows"], {"citations": ["D1"]})
    status, results = replay(tmp_path, monkeypatch, capsys, [record], derive=True)
    assert status == 0
    assert results[0]["contract_passed"]
    assert results[0]["errors"] == []
    assert results[0]["server_render_contract_passed"]
    assert "source-owned document body" in results[0]["scope"]
    assert "production truth" in results[0]["scope"]


@pytest.mark.parametrize("citations", [["D9"], ["D1", "D1"], [], [1], None])
def test_derivative_rejects_invalid_original_selection(tmp_path, monkeypatch, capsys, citations):
    record = legacy_document()
    record["answer"]["citations"] = citations
    status, results = replay(tmp_path, monkeypatch, capsys, [record], derive=True)
    assert status == 1
    assert not results[0]["contract_passed"]
    assert not results[0]["server_render_contract_passed"]
    assert results[0]["server_render_errors"]
    assert "server_rendered_answer" not in results[0]


def test_valid_derivative_does_not_hide_another_record_failure(tmp_path, monkeypatch, capsys):
    invalid_sql = {
        "question_id": "Q1",
        "plan": {"plan_id": "rank_return"},
        "search": {"rows": [{"ref_id": "R1"}]},
        "answer": {"answer": "조회 결과 [R1]", "citations": ["R1"], "quotes": [{"ref_id": "R1", "quote": "모델 인용"}]},
    }
    document = legacy_document()
    document["answer"] = render_document_answer(document["search"]["rows"], {"citations": ["D1"]})
    status, results = replay(tmp_path, monkeypatch, capsys, [invalid_sql, document], derive=True)
    assert status == 1
    assert results[0]["errors"] == ["SQL_QUOTES_MUST_BE_EMPTY"]
    assert "server_rendered_answer" not in results[0]
    assert results[1]["contract_passed"]
    assert results[1]["server_render_contract_passed"]
