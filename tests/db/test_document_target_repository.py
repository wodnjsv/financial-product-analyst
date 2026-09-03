from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
import hashlib
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.db.repositories.document_targets import DocumentTargetRepository
from financial_agent.documents import DocumentRole
from financial_agent.embeddings.contracts import APPROVED_MODEL
from tests.fixtures.db.synthetic_dataset import (
    CREATED_AT,
    VALID_RECORD_HASH,
    insert_building_dataset,
    insert_entity,
    insert_identifier,
    insert_institution,
    insert_product,
    insert_relation,
    insert_source,
)


CUTOFF = date(2026, 8, 24)
RECOVERY_TEST_MODEL = replace(
    APPROVED_MODEL,
    model_id="test-dart-recovery-model",
    model_version="1",
    approval_record_id="test-dart-recovery-approval",
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_compiled_queries_join_each_dataset_scoped_table_by_dataset_version() -> None:
    repository = DocumentTargetRepository(None)  # type: ignore[arg-type]
    statements = repository.compiled_statements("facts-v1")

    compiled_sql = "\n".join(
        str(statement.compile(compile_kwargs={"literal_binds": True}))
        for statement in statements
    )

    assert all(statement.is_select for statement in statements)
    assert not hasattr(repository, "append")
    assert not hasattr(repository, "update")
    assert "catalog.product.dataset_version = catalog.entity.dataset_version" in compiled_sql
    assert "catalog.identifier.dataset_version = catalog.entity.dataset_version" in compiled_sql
    assert "relation.relation_record.dataset_version = catalog.product.dataset_version" in compiled_sql
    assert "relation.relation_record.dataset_version = index_entity.dataset_version" in compiled_sql
    assert "index_identifier.dataset_version = index_entity.dataset_version" in compiled_sql


def test_organizer_dart_query_is_product_gated_and_relation_exact() -> None:
    statement = DocumentTargetRepository.organizer_dart_statement("facts-v1")
    compiled_sql = str(statement.compile(compile_kwargs={"literal_binds": True}))

    assert statement.is_select
    assert "domestic_etf" in compiled_sql
    assert "public_fund" in compiled_sql
    assert "PRFD_ITM_NO" in compiled_sql
    assert "PREF01_PD_ITM_NO" in compiled_sql
    assert "managedBy" in compiled_sql
    assert "DART_CORP_CODE" in compiled_sql
    assert "hasShareClass" in compiled_sql
    assert "rptt_ksd_itm_no" in compiled_sql
    assert "WTREWRWE" in compiled_sql
    assert "domestic_bond" not in compiled_sql
    assert "overseas_etf" not in compiled_sql


def test_manager_identifier_query_is_dataset_scoped_and_exact() -> None:
    statement = DocumentTargetRepository.manager_identifiers_statement(
        "facts-v1",
        ("manager-one", "manager-two"),
    )
    compiled_sql = str(statement.compile(compile_kwargs={"literal_binds": True}))

    assert statement.is_select
    assert "catalog.identifier.dataset_version = 'facts-v1'" in compiled_sql
    assert (
        "catalog.identifier.entity_id IN ('manager-one', 'manager-two')"
        in compiled_sql
    )


@pytest.mark.asyncio
async def test_blank_dataset_version_is_rejected_before_query() -> None:
    repository = DocumentTargetRepository(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="dataset_version"):
        await repository.list_targets(" ", cutoff_date=CUTOFF)


class _MappingsResult:
    def __init__(self, rows: list[dict[str, str | None]]) -> None:
        self._rows = rows

    def mappings(self) -> _MappingsResult:
        return self

    def all(self) -> list[dict[str, str | None]]:
        return self._rows


class _DuplicateIdentifierConnection:
    def __init__(self) -> None:
        self._results = [
            _MappingsResult(
                [
                    {
                        "entity_id": "product-1",
                        "entity_type": "product",
                        "canonical_name": "Product One",
                        "product_family": "domestic_etf",
                        "scheme": "ISIN",
                        "identifier_value": "KR0000000001",
                    },
                    {
                        "entity_id": "product-1",
                        "entity_type": "product",
                        "canonical_name": "Product One",
                        "product_family": "domestic_etf",
                        "scheme": "ISIN",
                        "identifier_value": "KR0000000001",
                    },
                ]
            ),
            _MappingsResult([]),
        ]

    async def execute(self, _statement: object) -> _MappingsResult:
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_duplicate_identifier_rows_yield_one_exact_identifier() -> None:
    repository = DocumentTargetRepository(_DuplicateIdentifierConnection())  # type: ignore[arg-type]

    targets = await repository.list_targets("facts-v1", cutoff_date=CUTOFF)

    assert targets[0].identifiers == (("ISIN", "KR0000000001"),)


@pytest.mark.asyncio
async def test_lists_exact_manager_identifiers_without_guessing() -> None:
    connection = _DuplicateIdentifierConnection()
    connection._results = [
        _MappingsResult(
            [
                {
                    "entity_id": "manager-one",
                    "scheme": "DART_CORP_CODE",
                    "identifier_value": "00123456",
                },
                {
                    "entity_id": "manager-one",
                    "scheme": "DART_CORP_CODE",
                    "identifier_value": "00123456",
                },
                {
                    "entity_id": "manager-one",
                    "scheme": "ORGANIZER_CODE",
                    "identifier_value": "source-local",
                },
            ]
        )
    ]

    identifiers = await DocumentTargetRepository(connection).list_identifiers(
        "facts-v1",
        ("manager-one",),
    )

    assert identifiers == {
        "manager-one": (
            ("DART_CORP_CODE", "00123456"),
            ("ORGANIZER_CODE", "source-local"),
        )
    }


def _token() -> str:
    return uuid4().hex


def _prepare_target_scope(database_url: str) -> str:
    dataset_version = f"facts-{_token()}"
    foreign_dataset_version = f"foreign-{_token()}"
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        insert_building_dataset(connection, dataset_version)
        insert_building_dataset(connection, foreign_dataset_version)
        for entity_id, product_family in (
            ("bond-1", "domestic_bond"),
            ("domestic-etf-1", "domestic_etf"),
            ("domestic-etf-2", "domestic_etf"),
            ("overseas-etf-1", "overseas_etf"),
            ("public-fund-1", "public_fund"),
        ):
            insert_product(
                connection,
                dataset_version=dataset_version,
                entity_id=entity_id,
                product_family=product_family,
            )
            insert_identifier(
                connection,
                dataset_version=dataset_version,
                identifier_id=f"id-{entity_id}",
                entity_id=entity_id,
                scheme="ISIN",
                identifier_value=f"KR-{entity_id}",
            )
        insert_entity(
            connection,
            dataset_version=dataset_version,
            entity_id="index-space",
            entity_type="index",
        )
        insert_identifier(
            connection,
            dataset_version=dataset_version,
            identifier_id="id-index-space",
            entity_id="index-space",
            scheme="INDEX_CODE",
            identifier_value="SPACE",
        )
        insert_entity(
            connection,
            dataset_version=dataset_version,
            entity_id="not-an-index",
            entity_type="theme",
        )
        insert_relation(
            connection,
            dataset_version=dataset_version,
            relation_id="tracks-1",
            subject_id="domestic-etf-1",
            predicate_id="tracksIndex",
            object_id="index-space",
        )
        insert_relation(
            connection,
            dataset_version=dataset_version,
            relation_id="tracks-2",
            subject_id="domestic-etf-2",
            predicate_id="tracksIndex",
            object_id="index-space",
        )
        insert_relation(
            connection,
            dataset_version=dataset_version,
            relation_id="tracks-not-index",
            subject_id="public-fund-1",
            predicate_id="tracksIndex",
            object_id="not-an-index",
        )
        insert_entity(
            connection,
            dataset_version=foreign_dataset_version,
            entity_id="domestic-etf-1",
        )
        insert_identifier(
            connection,
            dataset_version=foreign_dataset_version,
            identifier_id="foreign-id-domestic-etf-1",
            entity_id="domestic-etf-1",
            scheme="ISIN",
            identifier_value="FOREIGN-ONLY",
        )
    return dataset_version


@pytest_asyncio.fixture
async def repository_engine(migrated_database_url: str) -> AsyncEngine:
    engine = create_async_engine(migrated_database_url, pool_size=5, max_overflow=0)
    yield engine
    await engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_lists_all_product_and_unique_index_targets(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version = _prepare_target_scope(migrated_database_url)
    async with repository_engine.connect() as connection:
        targets = await DocumentTargetRepository(connection).list_targets(
            dataset_version,
            cutoff_date=CUTOFF,
        )

    assert [
        (item.entity_id, item.required_role)
        for item in targets
    ] == [
        ("bond-1", DocumentRole.PRODUCT_SUMMARY),
        ("domestic-etf-1", DocumentRole.PRODUCT_SUMMARY),
        ("domestic-etf-2", DocumentRole.PRODUCT_SUMMARY),
        ("index-space", DocumentRole.INDEX_METHODOLOGY),
        ("overseas-etf-1", DocumentRole.PRODUCT_SUMMARY),
        ("public-fund-1", DocumentRole.PRODUCT_SUMMARY),
    ]
    assert sum(item.entity_id == "index-space" for item in targets) == 1
    assert targets[1].identifiers == (("ISIN", "KR-domestic-etf-1"),)
    assert all(("ISIN", "FOREIGN-ONLY") not in item.identifiers for item in targets)


def _prepare_dart_recovery_states(database_url: str) -> tuple[str, dict[str, str]]:
    dataset_version = f"dart-recovery-{_token()}"
    product_ids = {
        "embedded_etf": "embedded-etf",
        "missing_etf": "missing-etf",
        "etn": "etn",
        "public_fund": "public-fund",
        "private_fund": "private-fund",
    }
    current_text = "current missing ETF chunk"
    current_hash = _sha256(current_text)
    embedded_text = "embedded ETF chunk"
    embedded_hash = _sha256(embedded_text)
    vector_literal = "[" + ",".join("0" for _ in range(APPROVED_MODEL.dimension)) + "]"
    wrong_model_id = f"wrong-model-{_token()}"

    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        insert_building_dataset(connection, dataset_version)
        insert_institution(
            connection,
            dataset_version=dataset_version,
            entity_id="recovery-publisher",
        )
        insert_source(
            connection,
            dataset_version=dataset_version,
            source_id="recovery-source",
            publisher="recovery-publisher",
        )
        for key, entity_id in product_ids.items():
            product_family = "domestic_etf" if key in {"embedded_etf", "missing_etf", "etn"} else "public_fund"
            marker = "PREF01_PD_ITM_NO" if product_family == "domestic_etf" else "PRFD_ITM_NO"
            insert_product(
                connection,
                dataset_version=dataset_version,
                entity_id=entity_id,
                product_family=product_family,
            )
            insert_identifier(
                connection,
                dataset_version=dataset_version,
                identifier_id=f"marker-{entity_id}",
                entity_id=entity_id,
                scheme=marker,
                identifier_value=f"organizer-{entity_id}",
            )
        connection.execute(
            """
            INSERT INTO observation.metric_definition (
                metric_id, definition_version, semantic_family, value_kind,
                definition_hash, approved_at
            ) VALUES
                ('organizer.pref01n001.product_type', '1', 'product_type', 'text', %s, %s),
                ('organizer.prfd01n001.public_private_class', '1', 'public_private_class', 'text', %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (VALID_RECORD_HASH, CREATED_AT, VALID_RECORD_HASH, CREATED_AT),
        )
        connection.execute(
            """
            INSERT INTO observation.observation_record (
                dataset_version, observation_id, entity_id, metric_id,
                metric_definition_version, value_status, text_value,
                record_hash, created_at
            ) VALUES
                (%s, 'etn-product-type', %s, 'organizer.pref01n001.product_type', '1', 'present', 'ETN', %s, %s),
                (%s, 'private-fund-class', %s, 'organizer.prfd01n001.public_private_class', '1', 'present', '사모', %s, %s)
            """,
            (
                dataset_version,
                product_ids["etn"],
                VALID_RECORD_HASH,
                CREATED_AT,
                dataset_version,
                product_ids["private_fund"],
                VALID_RECORD_HASH,
                CREATED_AT,
            ),
        )
        for document_id, entity_id, exact_text, content_hash in (
            ("embedded-etf-document", product_ids["embedded_etf"], embedded_text, embedded_hash),
            ("missing-etf-document", product_ids["missing_etf"], current_text, current_hash),
        ):
            connection.execute(
                """
                INSERT INTO document.document_record (
                    dataset_version, document_id, source_id, document_title,
                    document_type, object_key, content_checksum, published_at,
                    available_at, record_hash, created_at
                ) VALUES (%s, %s, 'recovery-source', %s, 'full_prospectus',
                          %s, %s, %s, %s, %s, %s)
                """,
                (
                    dataset_version,
                    document_id,
                    document_id,
                    f"discarded/{document_id}.pdf",
                    "c" * 64,
                    datetime(2026, 8, 20, tzinfo=UTC),
                    datetime(2026, 8, 21, tzinfo=UTC),
                    VALID_RECORD_HASH,
                    CREATED_AT,
                ),
            )
            connection.execute(
                """
                INSERT INTO document.document_profile (
                    dataset_version, document_id, document_version, publisher_role,
                    jurisdiction, original_language, effective_from,
                    extraction_method, cutoff_eligible, record_hash, created_at
                ) VALUES (%s, %s, '2026-08-20', 'regulator_disclosure', 'KR', 'ko',
                          DATE '2026-08-20', 'pdfplumber-layout-v1', TRUE, %s, %s)
                """,
                (dataset_version, document_id, VALID_RECORD_HASH, CREATED_AT),
            )
            connection.execute(
                """
                INSERT INTO document.document_entity_binding (
                    dataset_version, binding_id, document_id, entity_id, binding_role,
                    record_hash, created_at
                ) VALUES (%s, %s, %s, %s, 'subject_product', %s, %s)
                """,
                (
                    dataset_version,
                    f"binding-{document_id}",
                    document_id,
                    entity_id,
                    VALID_RECORD_HASH,
                    CREATED_AT,
                ),
            )
            connection.execute(
                """
                INSERT INTO document.document_chunk (
                    dataset_version, chunk_id, document_id, ordinal, page_start,
                    page_end, section_type, section_path, character_start,
                    character_end, exact_text, normalized_search_text, content_hash,
                    record_hash, created_at
                ) VALUES (%s, %s, %s, 0, 1, 1, 'investment_strategy',
                          'investment strategy', 0, %s, %s, %s, %s, %s, %s)
                """,
                (
                    dataset_version,
                    f"chunk-{document_id}",
                    document_id,
                    len(exact_text),
                    exact_text,
                    exact_text.casefold(),
                    content_hash,
                    VALID_RECORD_HASH,
                    CREATED_AT,
                ),
            )
        connection.execute(
            """
            INSERT INTO search.embedding_model (
                model_id, model_version, dimension, distance_metric,
                approval_record_id, approved_at, model_hash
            ) VALUES
                (%s, %s, %s, 'cosine', 'test-approved-model', %s, %s),
                (%s, '1', %s, 'cosine', 'test-wrong-model', %s, %s)
            ON CONFLICT (model_id, model_version) DO NOTHING
            """,
            (
                RECOVERY_TEST_MODEL.model_id,
                RECOVERY_TEST_MODEL.model_version,
                RECOVERY_TEST_MODEL.dimension,
                CREATED_AT,
                RECOVERY_TEST_MODEL.model_hash,
                wrong_model_id,
                RECOVERY_TEST_MODEL.dimension,
                CREATED_AT,
                "e" * 64,
            ),
        )
        connection.execute(
            """
            INSERT INTO search.document_embedding (
                dataset_version, embedding_id, document_id, chunk_id,
                chunk_content_hash, model_id, model_version, dimension,
                embedding, created_at
            ) VALUES
                (%s, 'embedded-etf-vector', 'embedded-etf-document',
                 'chunk-embedded-etf-document', %s, %s, %s, %s,
                 %s::cdb_admin.vector, %s),
                (%s, 'missing-etf-wrong-model-vector', 'missing-etf-document',
                 'chunk-missing-etf-document', %s, %s, '1', %s,
                 %s::cdb_admin.vector, %s)
            """,
            (
                dataset_version,
                embedded_hash,
                RECOVERY_TEST_MODEL.model_id,
                RECOVERY_TEST_MODEL.model_version,
                RECOVERY_TEST_MODEL.dimension,
                vector_literal,
                CREATED_AT,
                dataset_version,
                current_hash,
                wrong_model_id,
                RECOVERY_TEST_MODEL.dimension,
                vector_literal,
                CREATED_AT,
            ),
        )
        connection.execute("SET session_replication_role = replica")
        try:
            connection.execute(
                """
                INSERT INTO search.document_embedding (
                    dataset_version, embedding_id, document_id, chunk_id,
                    chunk_content_hash, model_id, model_version, dimension,
                    embedding, created_at
                ) VALUES (%s, 'missing-etf-stale-hash-vector', 'missing-etf-document',
                         'chunk-missing-etf-document', %s, %s, %s, %s,
                         %s::cdb_admin.vector, %s)
                """,
                (
                    dataset_version,
                    "f" * 64,
                    RECOVERY_TEST_MODEL.model_id,
                    RECOVERY_TEST_MODEL.model_version,
                    RECOVERY_TEST_MODEL.dimension,
                    vector_literal,
                    CREATED_AT,
                ),
            )
        finally:
            connection.execute("SET session_replication_role = origin")
    return dataset_version, product_ids


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_lists_dart_recovery_states_with_only_current_approved_embeddings(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version, product_ids = _prepare_dart_recovery_states(
        migrated_database_url
    )
    async with repository_engine.connect() as connection:
        states = await DocumentTargetRepository(connection).list_dart_recovery_states(
            dataset_version,
            RECOVERY_TEST_MODEL,
        )

    by_id = {state.entity_id: state for state in states}

    assert by_id[product_ids["embedded_etf"]].has_exact_embedding is True
    assert by_id[product_ids["missing_etf"]].has_exact_embedding is False
    assert by_id[product_ids["etn"]].product_scope == "etn_not_applicable"
    assert by_id[product_ids["public_fund"]].product_scope == "fund_prospectus"
    assert (
        by_id[product_ids["private_fund"]].product_scope
        == "private_fund_not_applicable"
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_organizer_dart_rows_exclude_nonorganizer_and_out_of_scope_products(
    repository_engine: AsyncEngine,
    migrated_database_url: str,
) -> None:
    dataset_version = f"dart-targets-{_token()}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_building_dataset(connection, dataset_version)
        insert_institution(
            connection,
            dataset_version=dataset_version,
            entity_id="manager-one",
        )
        insert_source(
            connection,
            dataset_version=dataset_version,
            source_id="organizer-public-fund-source",
            publisher="manager-one",
        )
        insert_identifier(
            connection,
            dataset_version=dataset_version,
            identifier_id="id-manager-one-dart",
            entity_id="manager-one",
            scheme="DART_CORP_CODE",
            identifier_value="00123456",
        )
        insert_institution(
            connection,
            dataset_version=dataset_version,
            entity_id="source-local-manager",
        )
        for entity_id, family, scheme in (
            ("etf-one", "domestic_etf", "PREF01_PD_ITM_NO"),
            ("fund-one", "public_fund", "PRFD_ITM_NO"),
            ("overseas-one", "overseas_etf", "ISIN"),
            ("bond-one", "domestic_bond", "ISIN"),
            ("dart-only", "domestic_etf", "DART_PRODUCT"),
        ):
            insert_product(
                connection,
                dataset_version=dataset_version,
                entity_id=entity_id,
                product_family=family,
            )
            insert_identifier(
                connection,
                dataset_version=dataset_version,
                identifier_id=f"id-{entity_id}",
                entity_id=entity_id,
                scheme=scheme,
                identifier_value=f"value-{entity_id}",
            )
        insert_product(
            connection,
            dataset_version=dataset_version,
            entity_id="fund-representative",
            product_family="public_fund",
        )
        for entity_id in ("etf-one", "fund-one"):
            insert_relation(
                connection,
                dataset_version=dataset_version,
                relation_id=f"manager-{entity_id}",
                subject_id=entity_id,
                predicate_id="managedBy",
                object_id="manager-one",
            )
        insert_relation(
            connection,
            dataset_version=dataset_version,
            relation_id="manager-etf-source-local",
            subject_id="etf-one",
            predicate_id="managedBy",
            object_id="source-local-manager",
        )
        insert_relation(
            connection,
            dataset_version=dataset_version,
            relation_id="fund-group",
            subject_id="fund-representative",
            predicate_id="hasShareClass",
            object_id="fund-one",
        )
        insert_identifier(
            connection,
            dataset_version=dataset_version,
            identifier_id="id-fund-representative-marker",
            entity_id="fund-representative",
            scheme="PRFD_ITM_NO",
            identifier_value="value-fund-representative",
        )
        insert_identifier(
            connection,
            dataset_version=dataset_version,
            identifier_id="id-fund-one-fss",
            entity_id="fund-one",
            scheme="FSS_FUND",
            identifier_value="fss-fund-one",
        )
        tagged_value = {"type": "string", "value": "WTREWRWE"}
        connection.execute(
            """
            INSERT INTO evidence.evidence_record (
                dataset_version, evidence_id, evidence_kind, source_id,
                subject_id, predicate_id, value_or_object_id,
                normalized_value, locator_type, locator_uri_or_object_key,
                locator_sheet, locator_row, locator_column, raw_value_repr,
                parser_version, mapping_version, cutoff_status, record_hash,
                scope_completeness, created_at
            ) VALUES (
                %s, 'representative-placeholder', 'query_scope',
                'organizer-public-fund-source', 'fund-one',
                'rptt_ksd_itm_no', %s, %s, 'tabular',
                'prfd01n001_data.xlsx', 'data', 2, 'rptt_ksd_itm_no',
                'WTREWRWE', '1', '4', 'eligible', %s,
                'bounded_unknown', TIMESTAMPTZ '2026-08-24 00:00:00+00'
            )
            """,
            (
                dataset_version,
                psycopg.types.json.Jsonb(tagged_value),
                psycopg.types.json.Jsonb(tagged_value),
                "b" * 64,
            ),
        )
        connection.execute(
            """
            INSERT INTO evidence.evidence_record (
                dataset_version, evidence_id, evidence_kind, source_id,
                subject_id, predicate_id, value_or_object_id,
                normalized_value, locator_type, locator_uri_or_object_key,
                locator_sheet, locator_row, locator_column, raw_value_repr,
                parser_version, mapping_version, cutoff_status, record_hash,
                scope_completeness, created_at
            ) VALUES (
                %s, 'overlap-representative-placeholder', 'query_scope',
                'organizer-public-fund-source', 'etf-one',
                'rptt_ksd_itm_no', %s, %s, 'tabular',
                'prfd01n001_data.xlsx', 'data', 3, 'rptt_ksd_itm_no',
                'WTREWRWE', '1', '4', 'eligible', %s,
                'bounded_unknown', TIMESTAMPTZ '2026-08-24 00:00:00+00'
            )
            """,
            (
                dataset_version,
                psycopg.types.json.Jsonb(tagged_value),
                psycopg.types.json.Jsonb(tagged_value),
                "b" * 64,
            ),
        )

    async with repository_engine.connect() as connection:
        rows = await DocumentTargetRepository(connection).list_organizer_dart_rows(
            dataset_version, CUTOFF
        )

    assert {row.entity_id for row in rows} == {
        "etf-one",
        "fund-one",
        "fund-representative",
    }
    fund = next(row for row in rows if row.entity_id == "fund-one")
    assert fund.representative_entity_id == "fund-representative"
    assert fund.manager_entity_id == "manager-one"
    assert fund.document_collection_block_reason == (
        "representative_identifier_unavailable"
    )
    assert {
        row.manager_entity_id for row in rows if row.entity_id == "etf-one"
    } == {"manager-one"}
    assert all(
        row.document_collection_block_reason is None
        for row in rows
        if row.entity_id == "etf-one"
    )
    assert all(row.identifier_scheme != "FSS_FUND" for row in rows)
    representative = next(
        row for row in rows if row.entity_id == "fund-representative"
    )
    assert representative.representative_entity_id == "fund-representative"
