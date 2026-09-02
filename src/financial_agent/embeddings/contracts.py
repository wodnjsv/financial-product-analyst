"""Immutable identities and payload rules for approved DART embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
from typing import Protocol


class EmbeddingContractError(ValueError):
    """The approved embedding contract was violated."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class EmbeddingModelContract:
    provider: str
    api: str
    model_id: str
    model_version: str
    dimension: int
    distance_metric: str
    document_input_template: str
    query_input_template: str
    approval_record_id: str
    approved_at: datetime

    @property
    def model_hash(self) -> str:
        manifest = {
            "api": self.api,
            "dimension": self.dimension,
            "distance_metric": self.distance_metric,
            "document_input_template": self.document_input_template,
            "model": "bge-m3",
            "provider": self.provider,
            "query_input_template": self.query_input_template,
        }
        return hashlib.sha256(_canonical_json(manifest)).hexdigest()


APPROVED_MODEL = EmbeddingModelContract(
    provider="ncp_clova_studio",
    api="embedding_v2",
    model_id="ncp-clova-bge-m3",
    model_version="embedding-v2-dart-search-text-v1",
    dimension=1024,
    distance_metric="cosine",
    document_input_template="dart-search-text-v1",
    query_input_template="bge-m3-query-v1",
    approval_record_id="ADR-0031",
    approved_at=datetime(2026, 9, 2, tzinfo=UTC),
)


@dataclass(frozen=True, slots=True)
class EmbeddingChunk:
    dataset_version: str
    document_id: str
    chunk_id: str
    content_hash: str
    document_title: str
    section_path: str
    exact_text: str


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vector: tuple[float, ...]
    input_tokens: int
    request_id: str | None
    retry_count: int = 0


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> EmbeddingResult: ...


def document_input(chunk: EmbeddingChunk) -> str:
    return (
        f"문서: {' '.join(chunk.document_title.split())}\n"
        f"섹션: {' '.join(chunk.section_path.split())}\n"
        f"본문:\n{chunk.exact_text}"
    )


def query_input(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        raise EmbeddingContractError("query_text_blank")
    return normalized


def embedding_id(
    model: EmbeddingModelContract,
    chunk: EmbeddingChunk,
) -> str:
    identity = {
        "chunk_content_hash": chunk.content_hash,
        "chunk_id": chunk.chunk_id,
        "dataset_version": chunk.dataset_version,
        "document_id": chunk.document_id,
        "model_id": model.model_id,
        "model_version": model.model_version,
    }
    return "embedding:" + hashlib.sha256(_canonical_json(identity)).hexdigest()


def validate_result(result: EmbeddingResult) -> EmbeddingResult:
    if len(result.vector) != APPROVED_MODEL.dimension or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in result.vector
    ):
        raise EmbeddingContractError("result_vector_invalid")
    if (
        isinstance(result.input_tokens, bool)
        or not isinstance(result.input_tokens, int)
        or result.input_tokens <= 0
    ):
        raise EmbeddingContractError("input_tokens_invalid")
    if (
        isinstance(result.retry_count, bool)
        or not isinstance(result.retry_count, int)
        or result.retry_count < 0
    ):
        raise EmbeddingContractError("retry_count_invalid")
    return result
