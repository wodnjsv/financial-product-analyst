from financial_agent.contracts.canonical import (
    build_request_key,
    canonical_sha256,
    normalize_question,
)


def test_normalize_question_is_unicode_and_whitespace_stable() -> None:
    assert normalize_question("  삼성전자\u3000ETF\n질문 ") == "삼성전자 ETF 질문"


def test_request_key_changes_with_dataset_version() -> None:
    first = build_request_key("Q-001", "삼성전자 ETF", "2026-07-11-v1", "1.0")
    second = build_request_key("Q-001", "삼성전자 ETF", "2026-07-11-v2", "1.0")
    assert first != second
    assert len(first) == 64


def test_canonical_hash_ignores_mapping_order() -> None:
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})
