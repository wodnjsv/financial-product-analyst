from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from financial_agent.contracts.enums import ProductFamily
from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.intent.query_contracts import (
    AggregationFunction,
    AggregationSpecV2,
    ComparisonSpecV2,
    OrderingDirection,
    OrderingSpecV2,
    PredicateAllOfV2,
    PredicateAtomV2,
    ProjectionSpecV2,
    QueryOperatorId,
    QueryQualifiersV2,
    QueryResultShape,
    TypedSemanticValue,
)
from financial_agent.planning.logical_query import (
    LogicalAggregateOperationV2,
    LogicalCompareOperationV2,
    LogicalLookupOperationV2,
    LogicalRankOperationV2,
    LogicalScreenOperationV2,
)
from financial_agent.sql.compiler import SemanticSqlCompiler
from financial_agent.sql.executor import ReadOnlySqlRunner
from tests.fixtures.db.synthetic_dataset import (
    insert_building_dataset,
    insert_institution,
    insert_numeric_metric_definition,
    insert_numeric_observation_with_evidence,
    insert_product,
    insert_relation_with_evidence,
    insert_source,
)
from tests.sql.helpers import (
    ACTIVE_DATASET,
    BINDINGS,
    DATASET_PIN,
    PLANNING,
    POLICIES,
    make_plan,
    verified_public_fund_facts,
)


pytestmark = pytest.mark.postgres
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_VERSION = "synthetic-dataset-v1"
COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET)


def _async_url(url: str) -> str:
    normalized = normalize_psycopg_url(url)
    if normalized.startswith("postgresql://"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    return normalized


@pytest.fixture(scope="module")
def semantic_sql_database_url() -> str:
    url = os.getenv("FINANCIAL_AGENT_TEST_DATABASE_URL")
    if url is None:
        pytest.skip(
            "unmeasured: FINANCIAL_AGENT_TEST_DATABASE_URL is not configured; "
            "SQLite is not a semantic SQL conformance substitute"
        )
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    _seed_semantic_dataset(url)
    return url


@pytest_asyncio.fixture(scope="module")
async def semantic_sql_runner(semantic_sql_database_url: str):
    engine = create_async_engine(_async_url(semantic_sql_database_url))
    yield ReadOnlySqlRunner(engine, COMPILER)
    await engine.dispose()


def _seed_semantic_dataset(url: str) -> None:
    with psycopg.connect(normalize_psycopg_url(url)) as connection:
        for statement in (
            "DELETE FROM evidence.evidence_relation_origin WHERE dataset_version = %s",
            "DELETE FROM evidence.evidence_observation_origin WHERE dataset_version = %s",
            "DELETE FROM evidence.evidence_record WHERE dataset_version = %s",
            "DELETE FROM observation.observation_record WHERE dataset_version = %s",
            "DELETE FROM relation.relation_record WHERE dataset_version = %s",
            "DELETE FROM evidence.source_record WHERE dataset_version = %s",
            "DELETE FROM catalog.product WHERE dataset_version = %s",
            "DELETE FROM catalog.institution WHERE dataset_version = %s",
            "DELETE FROM catalog.entity WHERE dataset_version = %s",
            "DELETE FROM operations.dataset_version WHERE dataset_version = %s",
        ):
            connection.execute(statement, (DATASET_VERSION,))
        insert_building_dataset(connection, DATASET_VERSION, manifest_hash=DATASET_PIN)
        insert_institution(connection, dataset_version=DATASET_VERSION)
        for source_id in (
            "source-one",
            "source-a",
            "source-b",
            "source-observation-a",
        ):
            insert_source(connection, dataset_version=DATASET_VERSION, source_id=source_id)
        for metric_id, unit in (
            ("organizer.pref01n001.aum", "source_defined_amount"),
            ("organizer.pref01n001.total_fee_rate", "percentage_point"),
            ("organizer.pref02n001.aum", "amount"),
            ("organizer.prfd01n001.net_assets", "source_defined_amount"),
        ):
            insert_numeric_metric_definition(
                connection,
                metric_id=metric_id,
                default_unit=unit,
                definition_version="semantic-sql.v1",
            )
        domestic = (
            ("etf-a", "ETF A", Decimal("100"), Decimal("0.5")),
            ("etf-b", "ETF B", Decimal("200"), Decimal("1")),
            ("etf-c", "ETF C", Decimal("200"), Decimal("1.5")),
            ("etf-zero", "ETF Zero", Decimal("0"), Decimal("0")),
            ("etf-missing", "ETF Missing", None, Decimal("0.2")),
            ("etf-injection", "ETF'); DROP TABLE catalog.product; --", Decimal("50"), Decimal("0.9")),
        )
        for entity_id, name, aum, fee in domestic:
            insert_product(
                connection,
                dataset_version=DATASET_VERSION,
                entity_id=entity_id,
                product_family="domestic_etf",
                canonical_name=name,
                primary_currency="KRW",
            )
            insert_numeric_observation_with_evidence(
                connection,
                dataset_version=DATASET_VERSION,
                entity_id=entity_id,
                observation_id=f"observation-{entity_id}-aum",
                metric_id="organizer.pref01n001.aum",
                value=aum,
                unit="source_defined_amount",
                currency="KRW",
                applicable_date=date(2026, 8, 24),
                definition_version="semantic-sql.v1",
            )
            insert_numeric_observation_with_evidence(
                connection,
                dataset_version=DATASET_VERSION,
                entity_id=entity_id,
                observation_id=f"observation-{entity_id}-fee",
                metric_id="organizer.pref01n001.total_fee_rate",
                value=fee,
                unit="percentage_point",
                currency=None,
                applicable_date=date(2026, 8, 24),
                definition_version="semantic-sql.v1",
            )
        insert_product(
            connection,
            dataset_version=DATASET_VERSION,
            entity_id="overseas-a",
            product_family="overseas_etf",
            canonical_name="Overseas A",
            primary_currency="USD",
        )
        insert_numeric_observation_with_evidence(
            connection,
            dataset_version=DATASET_VERSION,
            entity_id="overseas-a",
            observation_id="observation-overseas-a-aum",
            metric_id="organizer.pref02n001.aum",
            value=Decimal("10"),
            unit="amount",
            currency="USD",
            applicable_date=date(2026, 8, 24),
            definition_version="semantic-sql.v1",
        )
        insert_product(
            connection,
            dataset_version=DATASET_VERSION,
            entity_id="representative-a",
            product_family="public_fund",
            canonical_name="Representative Fund A",
            primary_currency="KRW",
        )
        insert_numeric_observation_with_evidence(
            connection,
            dataset_version=DATASET_VERSION,
            entity_id="representative-a",
            observation_id="observation-a",
            metric_id="organizer.prfd01n001.net_assets",
            value=Decimal("330"),
            unit="source_defined_amount",
            currency="KRW",
            applicable_date=date(2026, 8, 24),
            source_id="source-observation-a",
            definition_version="semantic-sql.v1",
        )
        for share_id, relation_id, evidence_id, source_id in (
            ("share-a", "relation-a", "evidence-a", "source-a"),
            ("share-b", "relation-b", "evidence-b", "source-b"),
        ):
            insert_product(
                connection,
                dataset_version=DATASET_VERSION,
                entity_id=share_id,
                product_family="public_fund",
                canonical_name=f"Share class {share_id}",
                primary_currency="KRW",
            )
            insert_relation_with_evidence(
                connection,
                dataset_version=DATASET_VERSION,
                relation_id=relation_id,
                subject_id="representative-a",
                predicate_id="hasShareClass",
                object_id=share_id,
                evidence_id=evidence_id,
                source_id=source_id,
            )
            insert_numeric_observation_with_evidence(
                connection,
                dataset_version=DATASET_VERSION,
                entity_id=share_id,
                observation_id=f"observation-{share_id}-aum",
                metric_id="organizer.prfd01n001.net_assets",
                value=Decimal("999"),
                unit="source_defined_amount",
                currency="KRW",
                applicable_date=date(2026, 8, 24),
                definition_version="semantic-sql.v1",
            )


async def _execute(runner, plan, *, facts=None):
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id, readiness_facts=facts)
    assert outcome.request is not None, outcome.rejection
    return await runner.execute(outcome.request, plan, readiness_facts=facts, timeout_ms=10_000)


@pytest.mark.asyncio
async def test_lookup_screen_rank_compare_and_lineage(semantic_sql_runner) -> None:
    lookup = make_plan(
        LogicalLookupOperationV2(projections=ProjectionSpecV2(field_concept_ids=("aum",)))
    )
    lookup_result = await _execute(semantic_sql_runner, lookup)
    assert {row.entity_ids[0] for row in lookup_result.result_rows} == {
        "etf-a", "etf-b", "etf-c", "etf-zero", "etf-missing", "etf-injection"
    }
    missing = next(
        row for row in lookup_result.result_rows if row.entity_ids == ("etf-missing",)
    )
    zero = next(
        row for row in lookup_result.result_rows if row.entity_ids == ("etf-zero",)
    )
    assert all(field.field_id != "aum" for field in missing.fields)
    assert any(item.subject_id == "etf-missing" for item in lookup_result.exclusions)
    assert next(
        field for field in zero.fields if field.field_id == "aum"
    ).value.value == 0
    assert lookup_result.evidence_refs

    screen = make_plan(
        LogicalScreenOperationV2(
            predicate=PredicateAllOfV2(
                children=(
                    PredicateAtomV2(
                        field_concept_id="aum",
                        operator_id=QueryOperatorId.GTE,
                        value=TypedSemanticValue(kind="decimal", decimal="100"),
                        null_policy_id="exclude_missing.v1",
                    ),
                    PredicateAtomV2(
                        field_concept_id="fee_rate",
                        operator_id=QueryOperatorId.LTE,
                        value=TypedSemanticValue(kind="decimal", decimal="1", unit_id="percent"),
                        null_policy_id="exclude_missing.v1",
                    ),
                )
            )
        ),
        binding_ids=("domestic-etf-aum.v1", "domestic-etf-fee-rate.v1"),
        policy_ids=("exclude_missing.v1", "identity-unit.v1", "semantic-percent-to-percentage-point.v1"),
        qualifiers=QueryQualifiersV2(unit_id="percent", as_of_date=date(2026, 8, 24)),
    )
    assert {row.entity_ids[0] for row in (await _execute(semantic_sql_runner, screen)).result_rows} == {"etf-a", "etf-b"}

    rank = make_plan(
        LogicalRankOperationV2(
            ordering=(OrderingSpecV2(field_concept_id="aum", direction=OrderingDirection.DESC, nulls_policy_id="exclude_missing.v1", tie_break_policy_id="stable-product-id.v1"),),
            limit=2,
        ),
        policy_ids=("exclude_missing.v1", "stable-product-id.v1", "identity-unit.v1"),
    )
    assert [row.entity_ids[0] for row in (await _execute(semantic_sql_runner, rank)).result_rows] == ["etf-b", "etf-c"]

    compare = make_plan(
        LogicalCompareOperationV2(
            comparison=ComparisonSpecV2(subject_refs=("etf-a", "etf-zero"), metric_concept_ids=("aum",), basis_policy_id="same-definition-period-unit.v1")
        ),
        policy_ids=("same-definition-period-unit.v1", "identity-unit.v1", "exclude_missing.v1"),
    )
    assert [row.entity_ids[0] for row in (await _execute(semantic_sql_runner, compare)).result_rows] == ["etf-a", "etf-zero"]


@pytest.mark.asyncio
async def test_aggregates_grouping_date_unit_and_split_families(semantic_sql_runner) -> None:
    expected = {
        AggregationFunction.SUM: Decimal("550"),
        AggregationFunction.AVG: Decimal("110"),
        AggregationFunction.MIN: Decimal("0"),
        AggregationFunction.MAX: Decimal("200"),
    }
    for function, expected_value in expected.items():
        plan = make_plan(
            LogicalAggregateOperationV2(
                aggregation=AggregationSpecV2(function_id=function, target_field_concept_id="aum", population_grain_id="source-product.v1", dedup_policy_id="no-dedup.v1")
            ),
            policy_ids=("source-product.v1", "no-dedup.v1", "identity-unit.v1", "exclude_missing.v1"),
            qualifiers=QueryQualifiersV2(unit_id="source_defined_amount", as_of_date=date(2026, 8, 24)),
        )
        assert (await _execute(semantic_sql_runner, plan)).result_rows[0].fields[0].value.value == expected_value

    count_plan = make_plan(
        LogicalAggregateOperationV2(
            aggregation=AggregationSpecV2(function_id=AggregationFunction.COUNT, count_population_id="source-product.v1", population_grain_id="source-product.v1", dedup_policy_id="no-dedup.v1")
        ),
        binding_ids=(),
        policy_ids=("source-product.v1", "no-dedup.v1"),
        qualifiers=QueryQualifiersV2(),
    )
    count_result = await _execute(semantic_sql_runner, count_plan)
    assert count_result.result_rows[0].fields[0].value.value == 6
    assert any(item.startswith("observation:") for item in count_result.evidence_refs)
    assert any(item.startswith("evidence:") for item in count_result.evidence_refs)
    assert "source:source-one" in count_result.evidence_refs

    grouped = make_plan(
        LogicalAggregateOperationV2(
            aggregation=AggregationSpecV2(function_id=AggregationFunction.SUM, target_field_concept_id="aum", group_by_field_concept_ids=("aum",), population_grain_id="source-product.v1", dedup_policy_id="no-dedup.v1")
        ),
        binding_ids=("domestic-etf-aum.v1",),
        policy_ids=("source-product.v1", "no-dedup.v1", "identity-unit.v1", "exclude_missing.v1"),
        qualifiers=QueryQualifiersV2(as_of_date=date(2026, 8, 24)),
        result_shape=QueryResultShape.GROUPED_TABLE,
    )
    grouped_result = await _execute(semantic_sql_runner, grouped)
    assert {row.fields[0].value.value for row in grouped_result.result_rows} == {
        Decimal("0"), Decimal("50"), Decimal("100"), Decimal("200")
    }

    overseas = make_plan(
        LogicalLookupOperationV2(projections=ProjectionSpecV2(field_concept_ids=("aum",))),
        family=ProductFamily.OVERSEAS_ETF,
        binding_ids=("overseas-etf-aum.v1",),
        qualifiers=QueryQualifiersV2(as_of_date=date(2026, 8, 24)),
    )
    assert (await _execute(semantic_sql_runner, overseas)).result_rows[0].entity_ids == ("overseas-a",)


@pytest.mark.asyncio
async def test_public_fund_representative_population_is_not_duplicated(
    semantic_sql_runner, semantic_sql_database_url
) -> None:
    with psycopg.connect(normalize_psycopg_url(semantic_sql_database_url)) as connection:
        edges = connection.execute(
            """
            SELECT relation.relation_record.relation_id,
                   relation.relation_record.subject_id,
                   relation.relation_record.object_id,
                   evidence.evidence_relation_origin.evidence_id,
                   evidence.evidence_record.source_id
              FROM relation.relation_record
              JOIN evidence.evidence_relation_origin
                USING (dataset_version, relation_id)
              JOIN evidence.evidence_record
                USING (dataset_version, evidence_id)
             WHERE relation.relation_record.dataset_version = %s
               AND relation.relation_record.predicate_id = 'hasShareClass'
             ORDER BY relation.relation_record.relation_id
            """,
            (DATASET_VERSION,),
        ).fetchall()
        ownership = connection.execute(
            """
            SELECT observation.observation_record.entity_id,
                   observation.observation_record.observation_id,
                   evidence.evidence_observation_origin.evidence_id,
                   evidence.evidence_record.source_id
              FROM observation.observation_record
              JOIN evidence.evidence_observation_origin
                USING (dataset_version, observation_id)
              JOIN evidence.evidence_record
                USING (dataset_version, evidence_id)
             WHERE observation.observation_record.dataset_version = %s
               AND observation.observation_record.observation_id = 'observation-a'
            """,
            (DATASET_VERSION,),
        ).fetchall()
    assert edges == [
        ("relation-a", "representative-a", "share-a", "evidence-a", "source-a"),
        ("relation-b", "representative-a", "share-b", "evidence-b", "source-b"),
    ]
    assert ownership == [
        (
            "representative-a",
            "observation-a",
            "evidence-observation-a",
            "source-observation-a",
        )
    ]
    facts = verified_public_fund_facts()
    plan = make_plan(
        LogicalAggregateOperationV2(
            aggregation=AggregationSpecV2(function_id=AggregationFunction.SUM, target_field_concept_id="aum", population_grain_id="representative-product.v1", dedup_policy_id="public-fund-representative-share.v1")
        ),
        family=ProductFamily.PUBLIC_FUND,
        binding_ids=("public-fund-aum.v1",),
        policy_ids=("representative-product.v1", "public-fund-representative-share.v1", "identity-unit.v1", "exclude_missing.v1"),
        qualifiers=QueryQualifiersV2(as_of_date=date(2026, 8, 24)),
    )
    result = await _execute(semantic_sql_runner, plan, facts=facts)
    assert result.result_rows[0].fields[0].value.value == Decimal("330")
    assert "observation:observation-a" in result.evidence_refs
