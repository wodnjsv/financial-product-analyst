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
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.contracts import EvidenceRecord
from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.documents import SectionType
from financial_agent.retrieval.documents import (
    DocumentCandidateRepository,
    DocumentSearchRequest,
    _metadata_candidates,
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
        entity_ids=(
            "selected-etf",
            "late-etf",
            "wrong-publisher-etf",
            "unofficial-etf",
            "expired-etf",
            "ineligible-etf",
        ),
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


@pytest_asyncio.fixture
async def evaluation_candidate_repository(
    migrated_database_url: str,
) -> tuple[DocumentCandidateRepository, str]:
    dataset_version = f"{DATASET_VERSION}-negatives-{uuid4().hex}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_document_search_corpus(
            connection,
            dataset_version=dataset_version,
            include_evaluation_fixtures=True,
        )
    engine = create_async_engine(migrated_database_url, pool_size=5, max_overflow=0)
    yield DocumentCandidateRepository(engine), dataset_version
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
        {"section_types": (SectionType.LEGACY_UNCLASSIFIED,)},
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
        "publisher_provenance",
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


def test_metadata_sql_enforces_nonblank_version_and_searchable_sections() -> None:
    request = DocumentSearchRequest(
        dataset_version="dataset-v1",
        entity_ids=("entity-a",),
        claim_type="risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=CUTOFF_DATE,
    )
    compiled = _metadata_candidates(request).select().compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)
    values = {
        item
        for value in compiled.params.values()
        for item in (value if isinstance(value, list) else [value])
        if isinstance(item, str)
    }

    assert "document.document_profile.document_version ~" in sql
    assert "[^[:space:]]" in values
    assert sql.count("document.document_chunk.section_type IN") == 2
    assert SectionType.LEGACY_UNCLASSIFIED.value not in values


@pytest.mark.parametrize(
    (
        "claim_type",
        "expected_roles",
        "expected_document_types",
        "expected_bindings",
        "expected_publishers",
        "excluded_values",
    ),
    (
        (
            "structure",
            {"product_summary", "product_full", "policy_base"},
            {"summary_prospectus", "full_prospectus", "policy_base"},
            {"subject_product", "subject_policy"},
            {
                "regulator_disclosure",
                "asset_manager",
                "policy_authority",
                "policy_operator",
            },
            {"issuer", "subject_index", "index_provider"},
        ),
        (
            "official_trend_or_update",
            {"official_update"},
            {"official_update"},
            {"subject_product", "subject_policy"},
            {
                "regulator_disclosure",
                "exchange",
                "industry_association",
                "policy_authority",
                "policy_operator",
            },
            {"asset_manager", "issuer", "subject_index", "index_provider"},
        ),
        (
            "publisher_provenance",
            {"product_summary", "product_full", "policy_base"},
            {"summary_prospectus", "full_prospectus", "policy_base"},
            {"subject_product", "subject_policy"},
            {
                "regulator_disclosure",
                "asset_manager",
                "policy_authority",
                "policy_operator",
            },
            {"issuer", "subject_index", "index_provider"},
        ),
    ),
)
def test_canonical_fund_claims_compile_product_and_policy_authority(
    claim_type: str,
    expected_roles: set[str],
    expected_document_types: set[str],
    expected_bindings: set[str],
    expected_publishers: set[str],
    excluded_values: set[str],
) -> None:
    request = DocumentSearchRequest(
        dataset_version="dataset-v1",
        entity_ids=("public-fund", "policy-fund"),
        claim_type=claim_type,
        section_types=(SectionType.LEGAL_STRUCTURE,),
        cutoff_date=CUTOFF_DATE,
    )
    compiled = _metadata_candidates(request).select().compile(
        dialect=postgresql.dialect()
    )
    values = {
        item
        for value in compiled.params.values()
        for item in (value if isinstance(value, list) else [value])
        if isinstance(item, str)
    }

    assert "SELECT DISTINCT" in str(compiled)
    assert str(compiled).count("EXISTS") >= len(expected_bindings) * 2
    assert expected_roles <= values
    assert expected_document_types <= values
    assert expected_bindings <= values
    assert expected_publishers <= values
    assert not excluded_values & values


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
async def test_vector_search_casts_boundary_list_to_postgresql_vector(
    risk_request: DocumentSearchRequest,
) -> None:
    captured: dict[str, object] = {}

    class EmptyResult:
        def mappings(self) -> EmptyResult:
            return self

        def all(self) -> list[object]:
            return []

    class CapturingConnection:
        async def execute(
            self, statement: object, parameters: dict[str, object]
        ) -> EmptyResult:
            captured["statement"] = statement
            captured["parameters"] = parameters
            return EmptyResult()

    class ConnectionContext:
        async def __aenter__(self) -> CapturingConnection:
            return CapturingConnection()

        async def __aexit__(self, *args: object) -> None:
            return None

    class CapturingEngine:
        def connect(self) -> ConnectionContext:
            return ConnectionContext()

    original_vector = risk_request.query_embedding
    repository = DocumentCandidateRepository(CapturingEngine())  # type: ignore[arg-type]

    assert await repository.search_vector(risk_request) == ()

    compiled = captured["statement"].compile(dialect=postgresql.dialect())  # type: ignore[union-attr]
    assert (
        str(compiled).count("CAST(%(query_embedding)s AS cdb_admin.vector)")
        == 3
    )
    for operator in ("<=>", "<#>", "<->"):
        assert f"OPERATOR(cdb_admin.{operator})" in str(compiled)
    assert captured["parameters"] == {"query_embedding": [1.0, 0.0, 0.0]}
    assert risk_request.query_embedding is original_vector


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
async def test_product_search_accepts_asset_manager_profile_only_for_official_dart_filing(
    migrated_database_url: str,
    corpus_dataset_version: str,
) -> None:
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_document_search_corpus(
            connection, dataset_version=corpus_dataset_version
        )
        connection.execute(
            """
            INSERT INTO evidence.source_record (
                dataset_version, source_id, publisher, publisher_type,
                source_title, source_type, authority_tier, source_locator_root,
                content_checksum, eligible_for_claim, record_hash, created_at
            )
            SELECT dataset_version, 'source-official-dart', publisher, 'regulator',
                   'Official DART filing', 'filing', 'official_primary',
                   'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260801000001',
                   content_checksum, eligible_for_claim, record_hash, created_at
            FROM evidence.source_record
            WHERE dataset_version = %s AND source_id = 'source-approved'
            """,
            (corpus_dataset_version,),
        )
        connection.execute(
            """
            UPDATE document.document_record
            SET source_id = 'source-official-dart'
            WHERE dataset_version = %s AND document_id = 'document-risk'
            """,
            (corpus_dataset_version,),
        )
        connection.execute(
            """
            UPDATE document.document_profile
            SET publisher_role = 'asset_manager'
            WHERE dataset_version = %s
              AND document_id IN (
                  'document-risk', 'document-product-wrong-publisher'
              )
            """,
            (corpus_dataset_version,),
        )

    request = DocumentSearchRequest(
        dataset_version=corpus_dataset_version,
        entity_ids=("selected-etf", "wrong-publisher-etf"),
        claim_type="product_risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=CUTOFF_DATE,
        top_k=5,
        query_embedding=(1.0, 0.0, 0.0),
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
    )
    engine = create_async_engine(migrated_database_url, pool_size=5, max_overflow=0)
    try:
        hits = await DocumentCandidateRepository(engine).search_vector(request)
    finally:
        await engine.dispose()

    assert hits
    assert {hit.entity_id for hit in hits} == {"selected-etf"}
    assert {hit.source_id for hit in hits} == {"source-official-dart"}


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
            entity_ids=("selected-index", "selected-index-wrong-publisher"),
            claim_type="theme_relation_evidence_span",
            section_types=(SectionType.INDEX_METHODOLOGY,),
            query_embedding=(0.0, 1.0, 0.0),
        )
    )
    policy_hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            entity_ids=("selected-policy", "selected-policy-wrong-publisher"),
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
async def test_canonical_structure_covers_public_fund_and_policy_entities(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    public_fund_hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            entity_ids=(
                "public-fund",
                "public-fund-wrong-publisher",
                "public-fund-wrong-binding",
            ),
            claim_type="structure",
            section_types=(SectionType.LEGAL_STRUCTURE,),
            query_embedding=(0.0, 0.0, 1.0),
        )
    )
    policy_hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            entity_ids=("selected-policy", "selected-policy-wrong-publisher"),
            claim_type="structure",
            section_types=(SectionType.LEGAL_STRUCTURE,),
            query_embedding=(0.0, 0.0, 1.0),
        )
    )

    assert [hit.chunk_id for hit in public_fund_hits] == ["public-fund-structure"]
    assert [hit.chunk_id for hit in policy_hits] == ["policy-structure"]


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_canonical_official_trend_covers_product_and_policy_not_index(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            claim_type="official_trend_or_update",
            entity_ids=(
                "product-update",
                "product-update-wrong",
                "policy-update",
                "policy-update-wrong",
                "index-update",
            ),
            section_types=(SectionType.OFFICIAL_UPDATE,),
            top_k=10,
        )
    )

    assert {hit.chunk_id for hit in hits} == {
        "product-update-chunk",
        "policy-update-chunk",
    }


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_canonical_publisher_provenance_obeys_section_and_fund_authority(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
) -> None:
    public_fund_hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            entity_ids=(
                "public-fund",
                "public-fund-wrong-publisher",
                "public-fund-wrong-binding",
            ),
            claim_type="publisher_provenance",
            section_types=(SectionType.LEGAL_STRUCTURE,),
            query_embedding=(0.0, 0.0, 1.0),
        )
    )
    policy_hits = await candidate_repository.search_vector(
        replace(
            risk_request,
            entity_ids=("selected-policy", "selected-policy-wrong-publisher"),
            claim_type="publisher_provenance",
            section_types=(SectionType.LEGAL_STRUCTURE,),
            query_embedding=(0.0, 0.0, 1.0),
        )
    )

    assert [hit.chunk_id for hit in public_fund_hits] == ["public-fund-structure"]
    assert [hit.chunk_id for hit in policy_hits] == ["policy-structure"]
    assert all(
        hit.source_id == "source-approved"
        for hit in (*public_fund_hits, *policy_hits)
    )
    assert all(hit.publisher_approved for hit in (*public_fund_hits, *policy_hits))


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
@pytest.mark.parametrize(
    ("entity_ids", "claim_type", "section_types", "query_text", "query_embedding"),
    (
        (
            ("policy-fund-one",),
            "structure",
            (SectionType.LEGAL_STRUCTURE,),
            "policy fund structure",
            (0.0, 0.0, 1.0),
        ),
        (
            ("aerospace-index-one",),
            "theme_relation_evidence_span",
            (SectionType.THEME_DEFINITION, SectionType.CHANGE_HISTORY),
            "aerospace theme",
            (0.0, 1.0, 0.0),
        ),
        (
            ("selected-etf",),
            "product_risk_factor",
            (SectionType.RISK_FACTOR,),
            "generated summary risk",
            (1.0, 0.0, 0.0),
        ),
    ),
)
async def test_generated_summary_is_absent_from_keyword_and_vector_candidates(
    evaluation_candidate_repository: tuple[DocumentCandidateRepository, str],
    entity_ids: tuple[str, ...],
    claim_type: str,
    section_types: tuple[SectionType, ...],
    query_text: str,
    query_embedding: tuple[float, ...],
) -> None:
    candidate_repository, dataset_version = evaluation_candidate_repository
    request = DocumentSearchRequest(
        dataset_version=dataset_version,
        entity_ids=entity_ids,
        claim_type=claim_type,
        section_types=section_types,
        cutoff_date=CUTOFF_DATE,
        query_embedding=query_embedding,
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        top_k=10,
    )

    keyword_hits = await candidate_repository.search_keyword(request, query_text)
    vector_hits = await candidate_repository.search_vector(request)

    assert "generated-summary" not in {hit.chunk_id for hit in keyword_hits}
    assert "generated-summary" not in {hit.chunk_id for hit in vector_hits}


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_whitespace_only_version_is_absent_from_keyword_and_vector_candidates(
    candidate_repository: DocumentCandidateRepository,
    risk_request: DocumentSearchRequest,
    migrated_database_url: str,
) -> None:
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        connection.execute(
            """
            ALTER TABLE document.document_profile
            DROP CONSTRAINT ck_document_profile_document_version
            """
        )
        connection.execute(
            """
            UPDATE document.document_profile
            SET document_version = %s
            WHERE dataset_version = %s
              AND document_id = 'document-risk'
            """,
            (" \t\n\r\f\v ", risk_request.dataset_version),
        )
        connection.execute(
            """
            ALTER TABLE document.document_profile
            ADD CONSTRAINT ck_document_profile_document_version
            CHECK (document_version ~ '[^[:space:]]') NOT VALID
            """
        )

    try:
        assert await candidate_repository.search_keyword(risk_request, "risk") == ()
        assert await candidate_repository.search_vector(risk_request) == ()
    finally:
        with psycopg.connect(
            normalize_psycopg_url(migrated_database_url)
        ) as connection:
            connection.execute(
                """
                UPDATE document.document_profile
                SET document_version = '2026-08-01'
                WHERE dataset_version = %s
                  AND document_id = 'document-risk'
                """,
                (risk_request.dataset_version,),
            )
            connection.execute(
                """
                ALTER TABLE document.document_profile
                VALIDATE CONSTRAINT ck_document_profile_document_version
                """
            )


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
