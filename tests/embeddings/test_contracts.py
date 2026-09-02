from __future__ import annotations

from dataclasses import replace
import math

import pytest

from financial_agent.embeddings.contracts import (
    APPROVED_MODEL,
    EmbeddingChunk,
    EmbeddingContractError,
    EmbeddingResult,
    document_input,
    embedding_id,
    query_input,
    validate_result,
)


def _chunk() -> EmbeddingChunk:
    return EmbeddingChunk(
        dataset_version="organizer-dart-2026-08-24-v2",
        document_id="document-001",
        chunk_id="chunk-001",
        content_hash="a" * 64,
        document_title="공식   투자설명서",
        section_path="제2부  >  주요 투자위험",
        exact_text="투자원금 손실이 발생할 수 있습니다.",
    )


def test_document_input_preserves_exact_text_and_normalizes_search_context() -> None:
    assert document_input(_chunk()) == (
        "문서: 공식 투자설명서\n"
        "섹션: 제2부 > 주요 투자위험\n"
        "본문:\n투자원금 손실이 발생할 수 있습니다."
    )


def test_query_input_preserves_fixed_query_without_instruction_prefix() -> None:
    assert query_input("  주요 투자위험   원금 손실  ") == "주요 투자위험 원금 손실"


def test_query_input_rejects_blank_text() -> None:
    with pytest.raises(EmbeddingContractError, match="query_text_blank"):
        query_input(" \n\t ")


def test_model_manifest_hash_matches_the_approved_canonical_contract() -> None:
    assert (
        APPROVED_MODEL.model_hash
        == "6c896c9beaabef74d6d174c9133338c270be06ff33fff02ff5935bd83448fbdd"
    )


def test_embedding_id_changes_when_the_exact_content_hash_changes() -> None:
    assert embedding_id(APPROVED_MODEL, _chunk()) == (
        "embedding:3da0e1f8005b70c97dbae8d1c94564eb022e051e895fa0cec56e3c8fb28b87d0"
    )
    assert embedding_id(APPROVED_MODEL, _chunk()) != embedding_id(
        APPROVED_MODEL,
        replace(_chunk(), content_hash="b" * 64),
    )


@pytest.mark.parametrize(
    "vector",
    (
        (),
        (0.0,) * 1023,
        (math.nan,) + (0.0,) * 1023,
        (False,) + (0.0,) * 1023,
    ),
)
def test_result_rejects_wrong_or_nonfinite_vectors(
    vector: tuple[float, ...],
) -> None:
    with pytest.raises(EmbeddingContractError, match="result_vector_invalid"):
        validate_result(
            EmbeddingResult(vector=vector, input_tokens=1, request_id=None)
        )


@pytest.mark.parametrize("input_tokens", (0, -1, True, 1.5))
def test_result_requires_a_positive_integer_token_count(
    input_tokens: object,
) -> None:
    result = EmbeddingResult(
        vector=(0.0,) * 1024,
        input_tokens=input_tokens,  # type: ignore[arg-type]
        request_id=None,
    )
    with pytest.raises(EmbeddingContractError, match="input_tokens_invalid"):
        validate_result(result)


def test_result_returns_the_same_immutable_valid_value() -> None:
    result = EmbeddingResult(
        vector=(0.0,) * 1024,
        input_tokens=17,
        request_id="request-001",
    )
    assert validate_result(result) is result


@pytest.mark.parametrize("retry_count", (-1, True, 1.5))
def test_result_requires_a_nonnegative_integer_retry_count(
    retry_count: object,
) -> None:
    result = EmbeddingResult(
        vector=(0.0,) * 1024,
        input_tokens=17,
        request_id=None,
        retry_count=retry_count,  # type: ignore[arg-type]
    )
    with pytest.raises(EmbeddingContractError, match="retry_count_invalid"):
        validate_result(result)
