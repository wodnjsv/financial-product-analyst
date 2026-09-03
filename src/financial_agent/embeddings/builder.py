"""Staged, resumable build service for approved DART embeddings."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields
from datetime import date
from typing import Protocol

from financial_agent.embeddings.contracts import (
    APPROVED_MODEL,
    EmbeddingChunk,
    EmbeddingProvider,
    document_input,
    query_input,
)
from financial_agent.embeddings.ncp import EmbeddingProviderError
from financial_agent.embeddings.repository import (
    EmbeddingPreflight,
    EmbeddingReconciliation,
    PendingEmbedding,
    ProtectedCounts,
)
from financial_agent.documents import SectionType
from financial_agent.retrieval.documents import (
    DocumentCandidateHit,
    DocumentSearchRequest,
    reciprocal_rank_fusion,
)


class EmbeddingBuildError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_FULL_BUILD_RECOVERY_DELAYS = (60.0, 300.0, 1_800.0, 3_600.0)


@dataclass(frozen=True, slots=True)
class BuildReport:
    stage: str
    eligible_count: int
    requested_count: int
    inserted_count: int
    skipped_existing_count: int
    input_token_count: int
    retry_count: int
    failure_codes: tuple[str, ...]
    model_hash: str
    embedding_bytes: int


@dataclass(frozen=True, slots=True)
class RetrievalValidationCase:
    case_id: str
    dataset_version: str
    canonical_product_name: str
    query_text: str
    claim_type: str
    section_types: tuple[SectionType, ...]
    expected_section_type: SectionType


@dataclass(frozen=True, slots=True)
class RetrievalValidationReport:
    case_count: int
    vector_top5_pass_count: int
    fused_top5_pass_count: int
    input_token_count: int
    retry_count: int


class BuildRepository(Protocol):
    async def preflight(self, dataset_version: str, model: object) -> EmbeddingPreflight: ...
    async def register_model(self, model: object) -> None: ...
    async def resolve_product(self, dataset_version: str, canonical_product_name: str) -> str: ...
    async def missing_chunks(
        self,
        dataset_version: str,
        model: object,
        *,
        limit: int | None,
        entity_id: str | None = None,
        section_types: tuple[str, ...] = (),
    ) -> tuple[EmbeddingChunk, ...]: ...
    async def append_embeddings(self, model: object, pending: tuple[PendingEmbedding, ...]) -> int: ...
    async def has_exact_embedding(self, model: object, chunk: EmbeddingChunk) -> bool: ...
    async def embedded_section_types(
        self,
        dataset_version: str,
        model: object,
        *,
        entity_id: str,
    ) -> frozenset[str]: ...
    async def reconcile(self, dataset_version: str, model: object) -> EmbeddingReconciliation: ...
    async def snapshot_protected_counts(self, dataset_version: str) -> ProtectedCounts: ...


class CandidateRepository(Protocol):
    async def search_keyword(
        self,
        request: DocumentSearchRequest,
        query_text: str,
    ) -> tuple[DocumentCandidateHit, ...]: ...
    async def search_vector(
        self,
        request: DocumentSearchRequest,
    ) -> tuple[DocumentCandidateHit, ...]: ...


class EmbeddingBuildService:
    def __init__(
        self,
        repository: BuildRepository,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 25,
        recovery_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or not 1 <= batch_size <= 100
        ):
            raise EmbeddingBuildError("batch_size_invalid")
        self._repository = repository
        self._provider = provider
        self._batch_size = batch_size
        self._recovery_sleep = recovery_sleep

    @staticmethod
    def report_field_names() -> tuple[str, ...]:
        return tuple(field.name for field in fields(BuildReport))

    async def _checked_preflight(
        self,
        dataset_version: str,
        expected_chunk_count: int,
    ) -> EmbeddingPreflight:
        preflight = await self._repository.preflight(
            dataset_version,
            APPROVED_MODEL,
        )
        if preflight.dataset_status != "building":
            raise EmbeddingBuildError("dataset_not_building")
        if preflight.eligible_chunk_count != expected_chunk_count:
            raise EmbeddingBuildError("eligible_chunk_count_mismatch")
        if preflight.stale_embedding_count or preflight.orphan_embedding_count:
            raise EmbeddingBuildError("preflight_projection_invalid")
        return preflight

    async def embed_canary(
        self,
        dataset_version: str,
        *,
        expected_chunk_count: int,
    ) -> BuildReport:
        preflight = await self._checked_preflight(
            dataset_version,
            expected_chunk_count,
        )
        await self._repository.register_model(APPROVED_MODEL)
        chunks = await self._repository.missing_chunks(
            dataset_version,
            APPROVED_MODEL,
            limit=1,
        )
        if not chunks:
            raise EmbeddingBuildError("canary_chunk_missing")
        inserted, tokens, retries = await self._embed_batch(chunks)
        if inserted != 1 or not await self._repository.has_exact_embedding(
            APPROVED_MODEL,
            chunks[0],
        ):
            raise EmbeddingBuildError("canary_readback_failed")
        reconciliation = await self._repository.reconcile(
            dataset_version,
            APPROVED_MODEL,
        )
        return self._report(
            "canary",
            preflight,
            reconciliation,
            requested=1,
            inserted=inserted,
            input_tokens=tokens,
            retries=retries,
        )

    async def embed_sample(
        self,
        dataset_version: str,
        *,
        expected_chunk_count: int,
        canonical_product_name: str,
        limit: int,
    ) -> BuildReport:
        preflight = await self._checked_preflight(
            dataset_version,
            expected_chunk_count,
        )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise EmbeddingBuildError("sample_limit_invalid")
        entity_id = await self._repository.resolve_product(
            dataset_version,
            canonical_product_name,
        )
        chunks = await self._repository.missing_chunks(
            dataset_version,
            APPROVED_MODEL,
            limit=limit,
            entity_id=entity_id,
            section_types=("investment_strategy", "risk_factor"),
        )
        already_embedded = await self._repository.embedded_section_types(
            dataset_version,
            APPROVED_MODEL,
            entity_id=entity_id,
        )
        if ({chunk.section_type for chunk in chunks} | set(already_embedded)) != {
            "investment_strategy",
            "risk_factor",
        }:
            raise EmbeddingBuildError("sample_sections_missing")
        await self._repository.register_model(APPROVED_MODEL)
        inserted, tokens, retries = await self._embed_batch(chunks)
        reconciliation = await self._repository.reconcile(
            dataset_version,
            APPROVED_MODEL,
        )
        return self._report(
            "sample",
            preflight,
            reconciliation,
            requested=len(chunks),
            inserted=inserted,
            input_tokens=tokens,
            retries=retries,
        )

    async def embed_all(
        self,
        dataset_version: str,
        *,
        expected_chunk_count: int,
    ) -> BuildReport:
        preflight = await self._checked_preflight(
            dataset_version,
            expected_chunk_count,
        )
        await self._repository.register_model(APPROVED_MODEL)
        requested = 0
        inserted = 0
        input_tokens = 0
        retries = 0
        recovery_index = 0
        while True:
            chunks = await self._repository.missing_chunks(
                dataset_version,
                APPROVED_MODEL,
                limit=self._batch_size,
            )
            if not chunks:
                break
            try:
                batch_inserted, batch_tokens, batch_retries = (
                    await self._embed_batch(chunks)
                )
            except EmbeddingBuildError as error:
                if error.code != "retry_exhausted":
                    raise
                delay = _FULL_BUILD_RECOVERY_DELAYS[
                    min(recovery_index, len(_FULL_BUILD_RECOVERY_DELAYS) - 1)
                ]
                recovery_index += 1
                await self._recovery_sleep(delay)
                continue
            if batch_inserted == 0:
                raise EmbeddingBuildError("build_made_no_progress")
            recovery_index = 0
            requested += len(chunks)
            inserted += batch_inserted
            input_tokens += batch_tokens
            retries += batch_retries
        reconciliation = await self._repository.reconcile(
            dataset_version,
            APPROVED_MODEL,
        )
        if (
            reconciliation.eligible_count != expected_chunk_count
            or reconciliation.exact_count != expected_chunk_count
            or reconciliation.missing_count
            or reconciliation.duplicate_count
            or reconciliation.stale_count
            or reconciliation.orphan_count
            or reconciliation.wrong_dimension_count
        ):
            raise EmbeddingBuildError("reconciliation_failed")
        return self._report(
            "full",
            preflight,
            reconciliation,
            requested=requested,
            inserted=inserted,
            input_tokens=input_tokens,
            retries=retries,
        )

    async def verify_retrieval(
        self,
        cases: tuple[RetrievalValidationCase, ...],
        candidates: CandidateRepository,
    ) -> RetrievalValidationReport:
        if not cases or len({case.dataset_version for case in cases}) != 1:
            raise EmbeddingBuildError("validation_cases_invalid")
        dataset_version = cases[0].dataset_version
        before = await self._repository.snapshot_protected_counts(dataset_version)
        vector_passes = 0
        fused_passes = 0
        input_tokens = 0
        retries = 0
        for case in cases:
            entity_id = await self._repository.resolve_product(
                dataset_version,
                case.canonical_product_name,
            )
            try:
                result = await self._provider.embed(query_input(case.query_text))
            except EmbeddingProviderError as error:
                raise EmbeddingBuildError(error.code) from None
            input_tokens += result.input_tokens
            retries += result.retry_count
            request = DocumentSearchRequest(
                dataset_version=dataset_version,
                entity_ids=(entity_id,),
                claim_type=case.claim_type,
                section_types=case.section_types,
                cutoff_date=date(2026, 8, 24),
                top_k=5,
                query_embedding=result.vector,
                model_id=APPROVED_MODEL.model_id,
                model_version=APPROVED_MODEL.model_version,
            )
            vector_hits = await candidates.search_vector(request)
            keyword_hits = await candidates.search_keyword(
                request,
                case.query_text,
            )
            fused_hits = reciprocal_rank_fusion(
                keyword_hits,
                vector_hits,
                top_k=5,
            )
            vector_pass = any(
                hit.section_type is case.expected_section_type
                for hit in vector_hits
            )
            fused_pass = any(
                hit.section_type is case.expected_section_type
                for hit in fused_hits
            )
            if not vector_pass or not fused_pass:
                raise EmbeddingBuildError("retrieval_top5_failed")
            vector_passes += 1
            fused_passes += 1
        after = await self._repository.snapshot_protected_counts(dataset_version)
        if after != before:
            raise EmbeddingBuildError("protected_state_changed")
        return RetrievalValidationReport(
            case_count=len(cases),
            vector_top5_pass_count=vector_passes,
            fused_top5_pass_count=fused_passes,
            input_token_count=input_tokens,
            retry_count=retries,
        )

    async def _embed_batch(
        self,
        chunks: tuple[EmbeddingChunk, ...],
    ) -> tuple[int, int, int]:
        pending: list[PendingEmbedding] = []
        input_tokens = 0
        retries = 0
        try:
            for chunk in chunks:
                result = await self._provider.embed(document_input(chunk))
                pending.append(PendingEmbedding(chunk, result))
                input_tokens += result.input_tokens
                retries += result.retry_count
        except EmbeddingProviderError as error:
            raise EmbeddingBuildError(error.code) from None
        inserted = await self._repository.append_embeddings(
            APPROVED_MODEL,
            tuple(pending),
        )
        return inserted, input_tokens, retries

    @staticmethod
    def _report(
        stage: str,
        preflight: EmbeddingPreflight,
        reconciliation: EmbeddingReconciliation,
        *,
        requested: int,
        inserted: int,
        input_tokens: int,
        retries: int,
    ) -> BuildReport:
        return BuildReport(
            stage=stage,
            eligible_count=preflight.eligible_chunk_count,
            requested_count=requested,
            inserted_count=inserted,
            skipped_existing_count=preflight.existing_exact_embedding_count,
            input_token_count=input_tokens,
            retry_count=retries,
            failure_codes=(),
            model_hash=APPROVED_MODEL.model_hash,
            embedding_bytes=reconciliation.embedding_bytes,
        )
