from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.contracts import EvidenceRecord
from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.documents import SectionType
from financial_agent.retrieval.documents import (
    DocumentCandidateRepository,
    DocumentSearchRequest,
    reciprocal_rank_fusion,
)
from tests.fixtures.document_corpus import (
    CUTOFF_DATE,
    DATASET_VERSION,
    MODEL_ID,
    MODEL_VERSION,
    insert_document_search_corpus,
    keyword_hits,
    tied_keyword_hits,
    vector_hits,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def postgres_database_url() -> str:
    database_url = os.getenv("FINANCIAL_AGENT_TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail(
            "FINANCIAL_AGENT_TEST_DATABASE_URL is required for @pytest.mark.postgres "
            "tests. Start docker/postgres.compose.yml or provide a dedicated "
            "non-production PostgreSQL 15 database URL."
        )
    return database_url


@pytest.fixture(scope="session")
def migrated_database_url(postgres_database_url: str) -> str:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_database_url)
    command.upgrade(config, "head")
    return postgres_database_url


@pytest.fixture
def corpus_dataset_version() -> str:
    return f"{DATASET_VERSION}-{uuid4().hex}"


@pytest.fixture
def risk_request(corpus_dataset_version: str) -> DocumentSearchRequest:
    return DocumentSearchRequest(
        dataset_version=corpus_dataset_version,
        entity_ids=("selected-etf",),
        claim_type="product_risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=CUTOFF_DATE,
        top_k=5,
        query_embedding=(1.0, 0.0, 0.0),
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
    )


@pytest_asyncio.fixture
async def candidate_repository(
    migrated_database_url: str,
    corpus_dataset_version: str,
) -> DocumentCandidateRepository:
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_document_search_corpus(
            connection, dataset_version=corpus_dataset_version
        )
    engine = create_async_engine(migrated_database_url, pool_size=5, max_overflow=0)
    yield DocumentCandidateRepository(engine)
    await engine.dispose()


def test_request_is_immutable_and_rejects_ambiguous_scope() -> None:
    valid = DocumentSearchRequest(
        dataset_version="dataset-v1",
        entity_ids=("entity-a",),
        claim_type="risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=date(2026, 8, 24),
    )

    with pytest.raises((AttributeError, TypeError)):
        valid.top_k = 2  # type: ignore[misc]
    for changes in (
        {"dataset_version": " "},
        {"entity_ids": ()},
        {"entity_ids": ("entity-a", "entity-a")},
        {"entity_ids": (" ",)},
        {"claim_type": ""},
        {"section_types": ()},
        {"section_types": (SectionType.RISK_FACTOR, SectionType.RISK_FACTOR)},
        {"top_k": 0},
        {"top_k": 51},
    ):
        with pytest.raises(ValueError):
            replace(valid, **changes)

    with pytest.raises(ValueError, match="unsupported claim_type"):
        replace(valid, claim_type="unknown_document_claim")

    with pytest.raises(ValueError, match="tuple"):
        DocumentSearchRequest(
            dataset_version="dataset-v1",
            entity_ids=["entity-a"],  # type: ignore[arg-type]
            claim_type="risk_factor",
            section_types=(SectionType.RISK_FACTOR,),
            cutoff_date=CUTOFF_DATE,
        )


@pytest.mark.parametrize(
    "claim_type",
    (
        "product_investment_strategy",
        "product_risk_factor",
        "concentration_risk",
        "index_methodology",
        "theme_definition",
        "selection_rules",
        "weighting_and_rebalancing",
        "relation_history",
        "structure",
        "official_update",
        "official_trend_or_update",
        "product_official_update",
        "index_official_update",
        "policy_official_update",
    ),
)
def test_request_accepts_each_supported_claim_family(claim_type: str) -> None:
    request = DocumentSearchRequest(
        dataset_version="dataset-v1",
        entity_ids=("entity-a",),
        claim_type=claim_type,
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=CUTOFF_DATE,
    )

    assert request.claim_type == claim_type


@pytest.mark.parametrize(
    "changes",
    (
        {"query_embedding": (1.0, 0.0, 0.0)},
        {"model_id": "model", "model_version": "1"},
        {
            "query_embedding": (1.0, float("nan")),
            "model_id": "model",
            "model_version": "1",
        },
        {
            "query_embedding": (),
            "model_id": "model",
            "model_version": "1",
        },
    ),
)
def test_request_requires_complete_finite_vector_identity(changes: dict[str, object]) -> None:
    base = DocumentSearchRequest(
        dataset_version="dataset-v1",
        entity_ids=("entity-a",),
        claim_type="risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=CUTOFF_DATE,
    )
    with pytest.raises(ValueError):
        replace(base, **changes)


def test_request_does_not_normalize_a_mutable_query_vector() -> None:
    base = DocumentSearchRequest(
        dataset_version="dataset-v1",
        entity_ids=("entity-a",),
        claim_type="risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=CUTOFF_DATE,
    )

    with pytest.raises(ValueError, match="tuple"):
        replace(
            base,
            query_embedding=[1.0, 0.0],  # type: ignore[arg-type]
            model_id="model",
            model_version="1",
        )


@pytest.mark.asyncio
async def test_vector_search_requires_a_vector_request() -> None:
    request = DocumentSearchRequest(
        dataset_version="dataset-v1",
        entity_ids=("entity-a",),
        claim_type="risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=CUTOFF_DATE,
    )
    engine = create_async_engine("postgresql+psycopg://unused:unused@127.0.0.1/unused")
    try:
        with pytest.raises(ValueError, match="VECTOR_SEARCH_REQUIRES_MODEL"):
            await DocumentCandidateRepository(engine).search_vector(request)
    finally:
        await engine.dispose()


def test_rrf_is_stable_and_does_not_create_claims() -> None:
    fused = reciprocal_rank_fusion(keyword_hits(), vector_hits(), top_k=5)

    assert [hit.chunk_id for hit in fused] == [
        "risk-specific",
        "risk-index",
        "risk-currency",
    ]
    assert all(hit.evidence_id is None for hit in fused)
    assert fused[0].keyword_rank == 1
    assert fused[0].vector_rank == 2


def test_rrf_breaks_identical_scores_by_document_then_chunk() -> None:
    fused = reciprocal_rank_fusion(tied_keyword_hits(), (), top_k=5)

    assert [(hit.document_id, hit.chunk_id) for hit in fused] == [
        ("document-a", "chunk-a"),
        ("document-b", "chunk-b"),
    ]


def test_rrf_validates_bounds_and_keeps_input_hits_unchanged() -> None:
    original = keyword_hits()

    with pytest.raises(ValueError):
        reciprocal_rank_fusion(original, (), rrf_k=0)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion(original, (), top_k=0)
    fused = reciprocal_rank_fusion(original, (), top_k=1)

    assert len(fused) == 1
    assert original == keyword_hits()
    assert original[0].fused_score is None


@pytest.mark.parametrize("rank", (1.5, float("nan"), float("inf"), True))
def test_candidate_rank_must_be_a_positive_integer(rank: object) -> None:
    with pytest.raises(ValueError, match="positive integers"):
        replace(keyword_hits()[0], keyword_rank=rank)  # type: ignore[arg-type]


def test_rrf_with_explicit_ranks_is_input_order_invariant() -> None:
    keyword = (
        replace(keyword_hits()[0], keyword_rank=2),
        replace(keyword_hits()[1], keyword_rank=1),
    )
    vector = vector_hits()

    direct = reciprocal_rank_fusion(keyword, vector, top_k=5)
    permuted = reciprocal_rank_fusion(
        tuple(reversed(keyword)), tuple(reversed(vector)), top_k=5
    )

    assert direct == permuted


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_vector_search_filters_before_distance_ranking(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    hits = await candidate_repository.search_vector(risk_request)

    assert hits
    assert [hit.chunk_id for hit in hits] == [
        "risk-specific",
        "risk-index",
        "risk-currency",
    ]
    assert {hit.entity_id for hit in hits} == {"selected-etf"}
    assert all(hit.section_type is SectionType.RISK_FACTOR for hit in hits)
    assert all(hit.cutoff_eligible for hit in hits)
    assert all(hit.publisher_approved for hit in hits)
    assert all(hit.vector_rank is not None and hit.keyword_rank is None for hit in hits)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_claim_authority_selects_product_index_and_policy_documents(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    product_hits = await candidate_repository.search_vector(risk_request)
    index_hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            entity_ids=("selected-index",),
            claim_type="theme_relation_evidence_span",
            section_types=(SectionType.INDEX_METHODOLOGY,),
            query_embedding=(0.0, 1.0, 0.0),
        )
    )
    policy_hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            entity_ids=("selected-policy",),
            claim_type="structure",
            section_types=(SectionType.LEGAL_STRUCTURE,),
            query_embedding=(0.0, 0.0, 1.0),
        )
    )

    assert [hit.chunk_id for hit in product_hits] == [
        "risk-specific",
        "risk-index",
        "risk-currency",
    ]
    assert [hit.chunk_id for hit in index_hits] == ["index-method"]
    assert [hit.chunk_id for hit in policy_hits] == ["policy-structure"]


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_type", "entity_ids", "query_embedding", "expected_chunk"),
    (
        (
            "product_official_update",
            ("product-update", "product-update-wrong"),
            (1.0, 0.0, 0.0),
            "product-update-chunk",
        ),
        (
            "index_official_update",
            ("index-update", "index-update-wrong"),
            (0.0, 1.0, 0.0),
            "index-update-chunk",
        ),
        (
            "policy_official_update",
            ("policy-update", "policy-update-wrong"),
            (0.0, 0.0, 1.0),
            "policy-update-chunk",
        ),
    ),
)
async def test_official_update_authority_is_binding_context_specific(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
    claim_type: str,
    entity_ids: tuple[str, ...],
    query_embedding: tuple[float, ...],
    expected_chunk: str,
) -> None:
    hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            claim_type=claim_type,
            entity_ids=entity_ids,
            section_types=(SectionType.OFFICIAL_UPDATE,),
            query_embedding=query_embedding,
        )
    )

    assert [hit.chunk_id for hit in hits] == [expected_chunk]


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_generic_official_update_uses_each_binding_publisher_matrix(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            claim_type="official_update",
            entity_ids=(
                "product-update",
                "product-update-wrong",
                "index-update",
                "index-update-wrong",
                "policy-update",
                "policy-update-wrong",
            ),
            section_types=(SectionType.OFFICIAL_UPDATE,),
            top_k=10,
        )
    )

    assert {hit.chunk_id for hit in hits} == {
        "product-update-chunk",
        "index-update-chunk",
        "policy-update-chunk",
    }


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_shared_entities_and_duplicate_authority_rows_do_not_multiply_hits(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            entity_ids=("selected-etf", "shared-etf"),
            top_k=10,
        )
    )
    identities = [
        (hit.entity_id, hit.document_id, hit.chunk_id) for hit in hits
    ]

    assert len(identities) == len(set(identities)) == 6
    assert {identity[0] for identity in identities} == {
        "selected-etf",
        "shared-etf",
    }


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_duplicate_same_model_embedding_fails_closed_without_using_top_k(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    hits = await candidate_repository.search_vector(
        replace(risk_request, top_k=10)
    )

    assert "ambiguous-vector" not in {hit.chunk_id for hit in hits}
    assert len({(hit.entity_id, hit.document_id, hit.chunk_id) for hit in hits}) == len(
        hits
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_keyword_search_uses_the_same_authority_and_scope_filters(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    hits = await candidate_repository.search_keyword(risk_request, "risk")

    assert hits
    assert {hit.chunk_id for hit in hits} <= {
        "risk-specific",
        "risk-index",
        "risk-currency",
        "ambiguous-vector",
    }
    assert all(hit.entity_id == "selected-etf" for hit in hits)
    assert all(hit.section_type is SectionType.RISK_FACTOR for hit in hits)
    assert all(hit.keyword_rank is not None and hit.vector_rank is None for hit in hits)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_candidates_have_round_trippable_source_locators_but_are_not_evidence(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    hit = (await candidate_repository.search_vector(risk_request))[0]

    assert hit.exact_text
    assert hit.source_id == "source-approved"
    assert "document-risk" in hit.source_locator
    assert "risk-specific" in hit.source_locator
    assert hit.evidence_id is None
    assert not isinstance(hit, EvidenceRecord)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_query_vector_dimension_mismatch_remains_a_database_error(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    with pytest.raises(DBAPIError):
        await candidate_repository.search_vector(
            replace(risk_request, query_embedding=(1.0, 0.0))
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_failed_dataset_is_not_searchable(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
    migrated_database_url: str,
) -> None:
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        connection.execute(
            """
            UPDATE operations.dataset_version SET status = 'failed'
            WHERE dataset_version = %s
            """,
            (risk_request.dataset_version,),
        )

    assert await candidate_repository.search_vector(risk_request) == ()
