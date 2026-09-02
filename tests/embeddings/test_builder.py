from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
import hashlib

import pytest

from financial_agent.embeddings.builder import (
    EmbeddingBuildError,
    EmbeddingBuildService,
    RetrievalValidationCase,
)
from financial_agent.embeddings.contracts import (
    APPROVED_MODEL,
    EmbeddingChunk,
    EmbeddingResult,
    embedding_id,
)
from financial_agent.embeddings.ncp import (
    PermanentEmbeddingError,
    RetryableEmbeddingError,
)
from financial_agent.embeddings.repository import (
    EmbeddingPreflight,
    EmbeddingReconciliation,
    PendingEmbedding,
    ProtectedCounts,
)
from financial_agent.documents import SectionType
from financial_agent.retrieval.documents import DocumentCandidateHit


DATASET_VERSION = "organizer-dart-2026-08-24-v2"


def _chunk(number: int, section_type: str = "risk_factor") -> EmbeddingChunk:
    exact_text = f"공식 문서 청크 {number}"
    return EmbeddingChunk(
        dataset_version=DATASET_VERSION,
        document_id=f"document-{number // 2}",
        chunk_id=f"chunk-{number}",
        content_hash=hashlib.sha256(exact_text.encode()).hexdigest(),
        document_title="공식 투자설명서",
        section_type=section_type,
        section_path="제2부 > 공식 섹션",
        exact_text=exact_text,
    )


class FakeEmbeddingRepository:
    def __init__(self, chunks: tuple[EmbeddingChunk, ...]) -> None:
        self.chunks = chunks
        self.persisted: dict[str, PendingEmbedding] = {}
        self.registered = False
        self.read_back_ids: list[str] = []
        self.protected_counts = ProtectedCounts(0, 0, 0, 0)

    async def preflight(self, dataset_version, model):
        assert dataset_version == DATASET_VERSION
        assert model == APPROVED_MODEL
        exact = len(self.persisted)
        return EmbeddingPreflight(
            dataset_status="building",
            eligible_chunk_count=len(self.chunks),
            existing_exact_embedding_count=exact,
            missing_embedding_count=len(self.chunks) - exact,
            stale_embedding_count=0,
            orphan_embedding_count=0,
        )

    async def register_model(self, model):
        assert model == APPROVED_MODEL
        self.registered = True

    async def resolve_product(self, dataset_version, canonical_product_name):
        assert dataset_version == DATASET_VERSION
        if canonical_product_name != "KODEX 200":
            raise AssertionError("unexpected product")
        return "product-kodex-200"

    async def missing_chunks(
        self,
        dataset_version,
        model,
        *,
        limit,
        entity_id=None,
        section_types=(),
    ):
        assert dataset_version == DATASET_VERSION
        assert model == APPROVED_MODEL
        if entity_id is not None:
            assert entity_id == "product-kodex-200"
        missing = tuple(
            chunk
            for chunk in self.chunks
            if embedding_id(model, chunk) not in self.persisted
            and (not section_types or chunk.section_type in section_types)
        )
        return missing if limit is None else missing[:limit]

    async def embedded_section_types(self, dataset_version, model, entity_id):
        assert dataset_version == DATASET_VERSION
        assert model == APPROVED_MODEL
        assert entity_id == "product-kodex-200"
        return frozenset(
            item.chunk.section_type for item in self.persisted.values()
        )

    async def append_embeddings(self, model, pending):
        inserted = 0
        for item in pending:
            identity = embedding_id(model, item.chunk)
            if identity not in self.persisted:
                self.persisted[identity] = item
                inserted += 1
        return inserted

    async def has_exact_embedding(self, model, chunk):
        identity = embedding_id(model, chunk)
        self.read_back_ids.append(identity)
        return identity in self.persisted

    async def reconcile(self, dataset_version, model):
        assert dataset_version == DATASET_VERSION
        exact = len(self.persisted)
        return EmbeddingReconciliation(
            eligible_count=len(self.chunks),
            exact_count=exact,
            missing_count=len(self.chunks) - exact,
            duplicate_count=0,
            stale_count=0,
            orphan_count=0,
            wrong_dimension_count=0,
            embedding_bytes=exact * 4096,
        )

    async def snapshot_protected_counts(self, dataset_version):
        assert dataset_version == DATASET_VERSION
        return self.protected_counts


class FakeProvider:
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.calls: list[str] = []
        self.fail_after = fail_after

    async def embed(self, text: str) -> EmbeddingResult:
        self.calls.append(text)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise RetryableEmbeddingError("retry_exhausted")
        return EmbeddingResult(
            vector=(0.1,) * 1024,
            input_tokens=12,
            request_id=f"request-{len(self.calls)}",
            retry_count=1 if len(self.calls) == 2 else 0,
        )


class ScriptedProvider:
    def __init__(
        self,
        outcomes: tuple[EmbeddingResult | Exception, ...],
    ) -> None:
        self.outcomes = iter(outcomes)
        self.calls: list[str] = []

    async def embed(self, text: str) -> EmbeddingResult:
        self.calls.append(text)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _embedding_result(request_id: str) -> EmbeddingResult:
    return EmbeddingResult(
        vector=(0.1,) * 1024,
        input_tokens=12,
        request_id=request_id,
    )


def _hit(section_type: SectionType, *, vector: bool) -> DocumentCandidateHit:
    return DocumentCandidateHit(
        dataset_version=DATASET_VERSION,
        entity_id="product-kodex-200",
        document_id="document-kodex-200",
        chunk_id=f"chunk-{section_type.value}",
        section_type=section_type,
        exact_text="공식 문서 근거 문장",
        source_id="source-dart",
        source_locator="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260824000001",
        published_at=datetime(2026, 8, 20, tzinfo=UTC),
        available_at=datetime(2026, 8, 21, tzinfo=UTC),
        effective_from=date(2026, 8, 20),
        effective_to=None,
        document_version="2026-08-20",
        cutoff_eligible=True,
        publisher_approved=True,
        keyword_rank=None if vector else 1,
        vector_rank=1 if vector else None,
        fused_score=None,
        evidence_id=None,
    )


class FakeCandidateRepository:
    def __init__(self, section_type: SectionType) -> None:
        self.section_type = section_type
        self.requests = []

    async def search_keyword(self, request, query_text):
        self.requests.append((request, query_text, "keyword"))
        return (_hit(self.section_type, vector=False),)

    async def search_vector(self, request):
        self.requests.append((request, None, "vector"))
        return (_hit(self.section_type, vector=True),)


@pytest.mark.asyncio
async def test_canary_embeds_and_reads_back_one_exact_chunk() -> None:
    repository = FakeEmbeddingRepository((_chunk(1),))
    provider = FakeProvider()
    service = EmbeddingBuildService(repository, provider)

    report = await service.embed_canary(
        DATASET_VERSION,
        expected_chunk_count=1,
    )

    assert report.stage == "canary"
    assert report.requested_count == 1
    assert report.inserted_count == 1
    assert report.input_token_count == 12
    assert report.retry_count == 0
    assert repository.registered is True
    assert repository.read_back_ids == [
        embedding_id(APPROVED_MODEL, _chunk(1))
    ]


@pytest.mark.asyncio
async def test_full_build_stops_before_provider_when_count_differs() -> None:
    repository = FakeEmbeddingRepository((_chunk(1), _chunk(2)))
    provider = FakeProvider()

    with pytest.raises(
        EmbeddingBuildError,
        match="eligible_chunk_count_mismatch",
    ):
        await EmbeddingBuildService(repository, provider).embed_all(
            DATASET_VERSION,
            expected_chunk_count=37_629,
        )

    assert provider.calls == []
    assert repository.registered is False


@pytest.mark.asyncio
async def test_full_build_backs_off_until_rate_limit_recovers_and_resets_after_commit(
) -> None:
    repository = FakeEmbeddingRepository((_chunk(1), _chunk(2)))
    provider = ScriptedProvider(
        (
            RetryableEmbeddingError("retry_exhausted"),
            RetryableEmbeddingError("retry_exhausted"),
            _embedding_result("request-1"),
            RetryableEmbeddingError("retry_exhausted"),
            _embedding_result("request-2"),
        )
    )
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    report = await EmbeddingBuildService(
        repository,
        provider,
        batch_size=1,
        recovery_sleep=sleep,
    ).embed_all(DATASET_VERSION, expected_chunk_count=2)

    assert delays == [60.0, 300.0, 60.0]
    assert report.inserted_count == 2
    assert len(repository.persisted) == 2


@pytest.mark.asyncio
async def test_full_build_does_not_auto_resume_permanent_provider_failure() -> None:
    repository = FakeEmbeddingRepository((_chunk(1),))
    provider = ScriptedProvider(
        (PermanentEmbeddingError("provider_http_permanent"),)
    )
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    with pytest.raises(EmbeddingBuildError, match="provider_http_permanent"):
        await EmbeddingBuildService(
            repository,
            provider,
            recovery_sleep=sleep,
        ).embed_all(DATASET_VERSION, expected_chunk_count=1)

    assert delays == []
    assert repository.persisted == {}


@pytest.mark.asyncio
async def test_full_build_caps_repeated_rate_limit_waits_at_one_hour() -> None:
    repository = FakeEmbeddingRepository((_chunk(1),))
    provider = ScriptedProvider(
        (
            *(RetryableEmbeddingError("retry_exhausted") for _ in range(5)),
            _embedding_result("request-1"),
        )
    )
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    report = await EmbeddingBuildService(
        repository,
        provider,
        recovery_sleep=sleep,
    ).embed_all(DATASET_VERSION, expected_chunk_count=1)

    assert delays == [60.0, 300.0, 1_800.0, 3_600.0, 3_600.0]
    assert report.inserted_count == 1


@pytest.mark.asyncio
async def test_sample_requires_and_embeds_strategy_and_risk_sections() -> None:
    repository = FakeEmbeddingRepository(
        (
            _chunk(1, "investment_strategy"),
            _chunk(2, "risk_factor"),
            _chunk(3, "legal_structure"),
        )
    )
    service = EmbeddingBuildService(repository, FakeProvider())

    report = await service.embed_sample(
        DATASET_VERSION,
        expected_chunk_count=3,
        canonical_product_name="KODEX 200",
        limit=20,
    )

    assert report.stage == "sample"
    assert report.inserted_count == 2
    assert {
        item.chunk.section_type for item in repository.persisted.values()
    } == {"investment_strategy", "risk_factor"}


@pytest.mark.asyncio
async def test_sample_stops_when_one_required_section_is_absent() -> None:
    repository = FakeEmbeddingRepository((_chunk(1, "risk_factor"),))
    provider = FakeProvider()

    with pytest.raises(EmbeddingBuildError, match="sample_sections_missing"):
        await EmbeddingBuildService(repository, provider).embed_sample(
            DATASET_VERSION,
            expected_chunk_count=1,
            canonical_product_name="KODEX 200",
            limit=20,
        )

    assert provider.calls == []


@pytest.mark.asyncio
async def test_sample_accepts_a_required_section_already_embedded_by_canary() -> None:
    strategy = _chunk(1, "investment_strategy")
    risk = _chunk(2, "risk_factor")
    repository = FakeEmbeddingRepository((strategy, risk))
    repository.persisted[embedding_id(APPROVED_MODEL, strategy)] = PendingEmbedding(
        strategy,
        EmbeddingResult((0.1,) * 1024, 12, "canary"),
    )

    report = await EmbeddingBuildService(
        repository,
        FakeProvider(),
    ).embed_sample(
        DATASET_VERSION,
        expected_chunk_count=2,
        canonical_product_name="KODEX 200",
        limit=20,
    )

    assert report.inserted_count == 1
    assert len(repository.persisted) == 2


@pytest.mark.asyncio
async def test_final_reconciliation_rejects_invalid_projection_state() -> None:
    repository = FakeEmbeddingRepository((_chunk(1),))

    async def invalid_reconcile(dataset_version, model):
        result = await FakeEmbeddingRepository.reconcile(
            repository,
            dataset_version,
            model,
        )
        return replace(result, duplicate_count=1)

    repository.reconcile = invalid_reconcile  # type: ignore[method-assign]

    with pytest.raises(EmbeddingBuildError, match="reconciliation_failed"):
        await EmbeddingBuildService(repository, FakeProvider()).embed_all(
            DATASET_VERSION,
            expected_chunk_count=1,
        )


def test_build_report_has_no_chunk_text_vector_or_request_identifier() -> None:
    names = set(EmbeddingBuildService.report_field_names())
    assert "chunk_text" not in names
    assert "query_text" not in names
    assert "embedding" not in names
    assert "request_id" not in names
    assert "api_key" not in names


@pytest.mark.asyncio
async def test_retrieval_validation_sends_only_fixed_generic_query() -> None:
    repository = FakeEmbeddingRepository((_chunk(1),))
    provider = FakeProvider()
    candidates = FakeCandidateRepository(SectionType.RISK_FACTOR)
    case = RetrievalValidationCase(
        case_id="risk",
        dataset_version=DATASET_VERSION,
        canonical_product_name="KODEX 200",
        query_text="주요 투자위험과 원금 손실 가능성",
        claim_type="product_risk_factor",
        section_types=(
            SectionType.INVESTMENT_STRATEGY,
            SectionType.RISK_FACTOR,
        ),
        expected_section_type=SectionType.RISK_FACTOR,
    )

    report = await EmbeddingBuildService(
        repository,
        provider,
    ).verify_retrieval((case,), candidates)

    assert report.case_count == 1
    assert report.vector_top5_pass_count == 1
    assert report.fused_top5_pass_count == 1
    assert provider.calls == ["주요 투자위험과 원금 손실 가능성"]
    assert "KODEX 200" not in provider.calls[0]


@pytest.mark.asyncio
async def test_retrieval_validation_rejects_wrong_section_or_ledger_delta() -> None:
    case = RetrievalValidationCase(
        case_id="risk",
        dataset_version=DATASET_VERSION,
        canonical_product_name="KODEX 200",
        query_text="주요 투자위험과 원금 손실 가능성",
        claim_type="product_risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        expected_section_type=SectionType.RISK_FACTOR,
    )
    wrong_candidates = FakeCandidateRepository(SectionType.INVESTMENT_STRATEGY)
    repository = FakeEmbeddingRepository((_chunk(1),))
    with pytest.raises(EmbeddingBuildError, match="retrieval_top5_failed"):
        await EmbeddingBuildService(repository, FakeProvider()).verify_retrieval(
            (case,), wrong_candidates
        )

    changing_repository = FakeEmbeddingRepository((_chunk(1),))
    snapshots = iter((ProtectedCounts(0, 0, 0, 0), ProtectedCounts(1, 0, 0, 0)))

    async def changing_counts(dataset_version):
        assert dataset_version == DATASET_VERSION
        return next(snapshots)

    changing_repository.snapshot_protected_counts = changing_counts  # type: ignore[method-assign]
    with pytest.raises(EmbeddingBuildError, match="protected_state_changed"):
        await EmbeddingBuildService(
            changing_repository,
            FakeProvider(),
        ).verify_retrieval((case,), FakeCandidateRepository(SectionType.RISK_FACTOR))
