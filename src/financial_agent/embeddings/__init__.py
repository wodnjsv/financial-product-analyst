"""Approved document embedding contracts and provider boundaries."""

from financial_agent.embeddings.contracts import (
    APPROVED_MODEL,
    EmbeddingChunk,
    EmbeddingContractError,
    EmbeddingModelContract,
    EmbeddingProvider,
    EmbeddingResult,
    document_input,
    embedding_id,
    query_input,
    validate_result,
)

__all__ = (
    "APPROVED_MODEL",
    "EmbeddingChunk",
    "EmbeddingContractError",
    "EmbeddingModelContract",
    "EmbeddingProvider",
    "EmbeddingResult",
    "document_input",
    "embedding_id",
    "query_input",
    "validate_result",
)
