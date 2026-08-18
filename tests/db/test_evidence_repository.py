from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from importlib import import_module
from typing import Any
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.contracts import (
    AtomicClaim,
    CalculationParameter,
    CalculationRecord,
    CalculationType,
    ClaimQualifier,
    ClaimSupport,
    ClaimType,
    CutoffStatus,
    EvidenceKind,
    EvidenceRecord,
    PopulationDefinition,
    SourceLocator,
    SourceRecord,
    SupportKind,
    encode_contract_value,
)
from financial_agent.db.preflight import normalize_psycopg_url
from tests.fixtures.db.synthetic_dataset import (
    insert_building_dataset,
    insert_entity,
    insert_institution,
    insert_request_run,
)


REQUEST_KEY = "d" * 64


@dataclass(frozen=True, slots=True)
class RepositoryContext:
    dataset_version: str
    run_id: str
    subtask_id: str
    source_id: str = "source-one"
    subject_id: str = "subject-one"
    object_id: str = "object-one"


def repository_api() -> Any:
    return import_module("financial_agent.db.repositories.evidence")


def prepare_repository_context(database_url: str) -> RepositoryContext:
    token = uuid4().hex
    context = RepositoryContext(
        dataset_version=f"repository-{token}",
        run_id=f"run-{token}",
        subtask_id=f"subtask-{token}",
    )
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        insert_building_dataset(connection, context.dataset_version)
        insert_institution(connection, dataset_version=context.dataset_version)
        insert_entity(
            connection,
            dataset_version=context.dataset_version,
            entity_id=context.subject_id,
        )
        insert_entity(
            connection,
            dataset_version=context.dataset_version,
            entity_id=context.object_id,
        )
        insert_request_run(
            connection,
            dataset_version=context.dataset_version,
            run_id=context.run_id,
            subtask_id=context.subtask_id,
        )
    return context


def source_record(context: RepositoryContext) -> SourceRecord:
    return SourceRecord(
        source_id=context.source_id,
        publisher="publisher-one",
        publisher_type="organizer",
        source_title="Synthetic official source",
        source_type="dataset",
        authority_tier="organizer",
        source_locator_root="synthetic/source",
        content_checksum="2" * 64,
        license_or_usage_note="synthetic test use",
        eligible_for_claim=True,
    )


def evidence_record(
    context: RepositoryContext,
    evidence_id: str,
    *,
    evidence_kind: EvidenceKind = EvidenceKind.POLICY,
    value: object = Decimal("125000000.000100000000"),
    applicable_date: date = date(2026, 7, 11),
    cutoff_status: CutoffStatus = CutoffStatus.ELIGIBLE,
    scope_completeness: str | None = None,
    record_hash: str = "3" * 64,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        evidence_kind=evidence_kind,
        source_id=context.source_id,
        dataset_version=context.dataset_version,
        subject_id=context.subject_id,
        predicate_id="aum",
        value_or_object_id=encode_contract_value(value),  # type: ignore[arg-type]
        normalized_value=encode_contract_value(value),  # type: ignore[arg-type]
        unit="won",
        currency="KRW",
        applicable_date=applicable_date,
        source_locator=SourceLocator(
            locator_type="tabular",
            uri_or_object_key="synthetic://products",
            record_key=context.subject_id,
            sheet="products",
            row=7,
            column="aum",
        ),
        raw_value_repr=str(value),
        parser_version="parser.v1",
        mapping_version="mapping.v1",
        cutoff_status=cutoff_status,
        record_hash=record_hash,
        scope_completeness=scope_completeness,
    )


def request_scope(context: RepositoryContext) -> Any:
    api = repository_api()
    return api.RequestScope(
        request_key=REQUEST_KEY,
        run_id=context.run_id,
        dataset_version=context.dataset_version,
    )


async def persist_ranking_prerequisites(
    repository: Any,
    context: RepositoryContext,
) -> tuple[EvidenceRecord, EvidenceRecord, EvidenceRecord, CalculationRecord]:
    direct = evidence_record(context, "evidence-direct")
    scope = evidence_record(
        context,
        "evidence-scope",
        evidence_kind=EvidenceKind.QUERY_SCOPE,
        value="all synthetic products",
        scope_completeness="closed_world",
        record_hash="4" * 64,
    )
    exclusion = evidence_record(
        context,
        "evidence-exclusion",
        evidence_kind=EvidenceKind.EXCLUSION,
        value="missing fee",
        record_hash="5" * 64,
    )
    for evidence in (direct, scope, exclusion):
        await repository.append_evidence(evidence)

    calculation = CalculationRecord(
        calculation_id="calculation-rank",
        calculation_type=CalculationType.RANKING,
        formula_id="rank-descending",
        formula_version="1",
        input_evidence_ids=(direct.evidence_id, scope.evidence_id),
        parameters=(
            CalculationParameter(
                parameter_id="rank-order",
                value=encode_contract_value("descending"),
            ),
            CalculationParameter(
                parameter_id="comparison-key",
                value=encode_contract_value(("aum", "KRW")),
            ),
        ),
        population_definition=PopulationDefinition(
            population_id="population-one",
            scope_evidence_id=scope.evidence_id,
            filter_ids=("domestic-only", "available-only"),
            member_count=2,
            population_hash="6" * 64,
        ),
        exclusion_evidence_ids=(exclusion.evidence_id,),
        tie_break_rule="entity-id-ascending",
        result_value=encode_contract_value(Decimal("1.00")),
        unit="rank",
        rounding_rule="none",
        calculation_hash="7" * 64,
    )
    await repository.append_calculation(request_scope(context), calculation)
    return direct, scope, exclusion, calculation


async def persist_claim_prerequisites(
    repository: Any,
    context: RepositoryContext,
) -> tuple[AtomicClaim, ClaimSupport, ClaimSupport]:
    await repository.append_source(
        context.dataset_version,
        source_record(context),
    )
    direct, _, _, calculation = await persist_ranking_prerequisites(
        repository, context
    )
    claim = AtomicClaim(
        claim_id="claim-one",
        claim_type=ClaimType.RANK,
        subtask_id=context.subtask_id,
        subject_id=context.subject_id,
        predicate_id="rank",
        value=encode_contract_value(1),
        unit="rank",
        qualifiers=(
            ClaimQualifier(
                qualifier_id="population",
                value=encode_contract_value("population-one"),
            ),
            ClaimQualifier(
                qualifier_id="tie-break",
                value=encode_contract_value("entity-id-ascending"),
            ),
        ),
        display_policy_id="rank.v1",
        claim_hash="a" * 64,
    )
    initial_support = ClaimSupport(
        claim_id=claim.claim_id,
        support_kind=SupportKind.DIRECT,
        evidence_id=direct.evidence_id,
        support_role="ranked-value",
        ordinal=0,
    )
    later_support = ClaimSupport(
        claim_id=claim.claim_id,
        support_kind=SupportKind.CALCULATION,
        calculation_id=calculation.calculation_id,
        support_role="ranking-calculation",
        ordinal=1,
    )
    return claim, initial_support, later_support


@pytest_asyncio.fixture
async def repository_engine(migrated_database_url: str) -> AsyncEngine:
    engine = create_async_engine(migrated_database_url, pool_size=5, max_overflow=0)
    yield engine
    await engine.dispose()


@pytest.fixture
def repository_context(migrated_database_url: str) -> RepositoryContext:
    return prepare_repository_context(migrated_database_url)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_source_and_cutoff_evidence_round_trip_losslessly(
    repository_engine: AsyncEngine,
    repository_context: RepositoryContext,
) -> None:
    api = repository_api()
    repository = api.EvidenceLedgerRepository(repository_engine)
    source = source_record(repository_context)
    eligible = evidence_record(repository_context, "evidence-eligible")
    after_cutoff = evidence_record(
        repository_context,
        "evidence-after-cutoff",
        value="2026-07-12",
        applicable_date=date(2026, 7, 12),
        cutoff_status=CutoffStatus.AFTER_CUTOFF,
        record_hash="8" * 64,
    )

    await repository.append_source(repository_context.dataset_version, source)
    await repository.append_evidence(eligible)
    await repository.append_evidence(after_cutoff)

    assert await repository.get_evidence(
        repository_context.dataset_version, eligible.evidence_id
    ) == eligible
    assert await repository.get_evidence(
        repository_context.dataset_version, after_cutoff.evidence_id
    ) == after_cutoff
    await repository.append_evidence(eligible)
    same_hash_different_payload = eligible.model_copy(
        update={"raw_value_repr": "different raw representation"}
    )
    with pytest.raises(api.EvidenceLedgerConflict):
        await repository.append_evidence(same_hash_different_payload)
    async with repository_engine.connect() as connection:
        source_row = (
            await connection.execute(
                text(
                    """
                    SELECT source_id, source_title, eligible_for_claim
                    FROM evidence.source_record
                    WHERE dataset_version = :dataset_version
                    """
                ),
                {"dataset_version": repository_context.dataset_version},
            )
        ).one()
    assert source_row == (
        source.source_id,
        source.source_title,
        source.eligible_for_claim,
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_evidence_origin_is_persisted_and_compared_on_retry(
    repository_engine: AsyncEngine,
    repository_context: RepositoryContext,
) -> None:
    api = repository_api()
    repository = api.EvidenceLedgerRepository(repository_engine)
    await repository.append_source(
        repository_context.dataset_version,
        source_record(repository_context),
    )
    async with repository_engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO relation.relation_record (
                    dataset_version, relation_id, subject_id, predicate_id,
                    object_id, record_hash, created_at
                ) VALUES (
                    :dataset_version, 'relation-one', :subject_id,
                    'related-to', :object_id, :record_hash, clock_timestamp()
                )
                """
            ),
            {
                "dataset_version": repository_context.dataset_version,
                "subject_id": repository_context.subject_id,
                "object_id": repository_context.object_id,
                "record_hash": "0" * 64,
            },
        )
    evidence = evidence_record(
        repository_context,
        "evidence-relation",
        evidence_kind=EvidenceKind.RELATION,
        value=repository_context.object_id,
        record_hash="1" * 64,
    )
    origin = api.OriginReference(
        origin_kind="relation",
        dataset_version=repository_context.dataset_version,
        record_id="relation-one",
    )

    await repository.append_evidence(evidence, origin=origin)
    await repository.append_evidence(evidence, origin=origin)

    assert await repository.get_evidence(
        repository_context.dataset_version, evidence.evidence_id
    ) == evidence
    conflicting_origin = api.OriginReference(
        origin_kind="relation",
        dataset_version=repository_context.dataset_version,
        record_id="different-relation",
    )
    with pytest.raises(api.EvidenceLedgerConflict):
        await repository.append_evidence(evidence, origin=conflicting_origin)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_calculation_round_trip_preserves_every_ordered_association(
    repository_engine: AsyncEngine,
    repository_context: RepositoryContext,
) -> None:
    api = repository_api()
    repository = api.EvidenceLedgerRepository(repository_engine)
    await repository.append_source(
        repository_context.dataset_version,
        source_record(repository_context),
    )
    _, _, _, calculation = await persist_ranking_prerequisites(
        repository, repository_context
    )

    assert await repository.get_calculation(
        repository_context.run_id, calculation.calculation_id
    ) == calculation
    await repository.append_calculation(request_scope(repository_context), calculation)

    conflicting = calculation.model_copy(
        update={"parameters": tuple(reversed(calculation.parameters))}
    )
    with pytest.raises(api.EvidenceLedgerConflict):
        await repository.append_calculation(
            request_scope(repository_context), conflicting
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_unrelated_unique_violation_is_not_treated_as_an_identity_retry(
    repository_engine: AsyncEngine,
    repository_context: RepositoryContext,
) -> None:
    api = repository_api()
    repository = api.EvidenceLedgerRepository(repository_engine)
    await repository.append_source(
        repository_context.dataset_version,
        source_record(repository_context),
    )
    _, _, _, calculation = await persist_ranking_prerequisites(
        repository, repository_context
    )
    second = calculation.model_copy(
        update={
            "calculation_id": "calculation-two",
            "calculation_hash": "8" * 64,
        }
    )

    with pytest.raises(IntegrityError) as error:
        await repository.append_calculation(request_scope(repository_context), second)

    assert error.value.orig.diag.constraint_name == "uq_calculation_population_id"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_claim_and_initial_support_are_atomic_then_accept_later_support(
    repository_engine: AsyncEngine,
    repository_context: RepositoryContext,
) -> None:
    api = repository_api()
    repository = api.EvidenceLedgerRepository(repository_engine)
    claim, initial_support, later_support = await persist_claim_prerequisites(
        repository, repository_context
    )

    await repository.append_claim(
        request_scope(repository_context),
        claim,
        supports=(initial_support,),
    )
    await repository.append_claim(
        request_scope(repository_context),
        claim,
        supports=(initial_support,),
    )
    await repository.append_support(request_scope(repository_context), later_support)
    await repository.append_claim(
        request_scope(repository_context),
        claim,
        supports=(initial_support, later_support),
    )
    await repository.append_support(request_scope(repository_context), later_support)

    assert await repository.get_claim(
        repository_context.run_id, claim.claim_id
    ) == claim
    async with repository_engine.connect() as connection:
        support_rows = (
            await connection.execute(
                text(
                    """
                    SELECT support_kind, evidence_id, calculation_id,
                           support_role, ordinal
                    FROM evidence.claim_support
                    WHERE run_id = :run_id AND claim_id = :claim_id
                    ORDER BY ordinal
                    """
                ),
                {"run_id": repository_context.run_id, "claim_id": claim.claim_id},
            )
        ).all()
    assert support_rows == [
        (
            initial_support.support_kind.value,
            initial_support.evidence_id,
            None,
            initial_support.support_role,
            initial_support.ordinal,
        ),
        (
            later_support.support_kind.value,
            None,
            later_support.calculation_id,
            later_support.support_role,
            later_support.ordinal,
        ),
    ]
    conflicting_claim = claim.model_copy(
        update={"qualifiers": tuple(reversed(claim.qualifiers))}
    )
    with pytest.raises(api.EvidenceLedgerConflict):
        await repository.append_claim(
            request_scope(repository_context),
            conflicting_claim,
            supports=(initial_support, later_support),
        )
    conflicting_support = later_support.model_copy(
        update={"support_role": "different-role"}
    )
    with pytest.raises(api.EvidenceLedgerConflict):
        await repository.append_support(
            request_scope(repository_context), conflicting_support
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_append_claim_retry_rejects_a_shorter_support_graph(
    repository_engine: AsyncEngine,
    repository_context: RepositoryContext,
) -> None:
    api = repository_api()
    repository = api.EvidenceLedgerRepository(repository_engine)
    claim, initial_support, later_support = await persist_claim_prerequisites(
        repository, repository_context
    )
    await repository.append_claim(
        request_scope(repository_context),
        claim,
        supports=(initial_support,),
    )
    await repository.append_claim(
        request_scope(repository_context),
        claim,
        supports=(initial_support,),
    )
    await repository.append_support(request_scope(repository_context), later_support)

    with pytest.raises(api.EvidenceLedgerConflict):
        await repository.append_claim(
            request_scope(repository_context),
            claim,
            supports=(initial_support,),
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_append_claim_retry_rejects_a_longer_new_ordinal_support_graph(
    repository_engine: AsyncEngine,
    repository_context: RepositoryContext,
) -> None:
    api = repository_api()
    repository = api.EvidenceLedgerRepository(repository_engine)
    claim, initial_support, later_support = await persist_claim_prerequisites(
        repository, repository_context
    )
    await repository.append_claim(
        request_scope(repository_context),
        claim,
        supports=(initial_support,),
    )

    with pytest.raises(api.EvidenceLedgerConflict):
        await repository.append_claim(
            request_scope(repository_context),
            claim,
            supports=(initial_support, later_support),
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_append_claim_retry_rejects_a_changed_support_graph(
    repository_engine: AsyncEngine,
    repository_context: RepositoryContext,
) -> None:
    api = repository_api()
    repository = api.EvidenceLedgerRepository(repository_engine)
    claim, initial_support, later_support = await persist_claim_prerequisites(
        repository, repository_context
    )
    await repository.append_claim(
        request_scope(repository_context),
        claim,
        supports=(initial_support, later_support),
    )
    changed_support = later_support.model_copy(
        update={"support_role": "changed-ranking-calculation"}
    )

    with pytest.raises(api.EvidenceLedgerConflict):
        await repository.append_claim(
            request_scope(repository_context),
            claim,
            supports=(initial_support, changed_support),
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_claim_requires_nonempty_initial_supports(
    repository_engine: AsyncEngine,
    repository_context: RepositoryContext,
) -> None:
    api = repository_api()
    repository = api.EvidenceLedgerRepository(repository_engine)
    claim = AtomicClaim(
        claim_id="claim-without-support",
        claim_type=ClaimType.DIRECT_FACT,
        subtask_id=repository_context.subtask_id,
        subject_id=repository_context.subject_id,
        predicate_id="aum",
        value=encode_contract_value(Decimal("1")),
        display_policy_id="number.v1",
        claim_hash="b" * 64,
    )

    with pytest.raises(ValueError, match="initial support"):
        await repository.append_claim(
            request_scope(repository_context), claim, supports=()
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_request_scope_must_match_the_exact_persisted_request_tuple(
    repository_engine: AsyncEngine,
    repository_context: RepositoryContext,
) -> None:
    api = repository_api()
    repository = api.EvidenceLedgerRepository(repository_engine)
    mismatched_scope = api.RequestScope(
        request_key="e" * 64,
        run_id=repository_context.run_id,
        dataset_version=repository_context.dataset_version,
    )
    calculation = CalculationRecord(
        calculation_id="scope-mismatch",
        calculation_type=CalculationType.CONVERSION,
        formula_id="identity",
        formula_version="1",
        input_evidence_ids=("not-inserted",),
        result_value=encode_contract_value(1),
        calculation_hash="c" * 64,
    )

    with pytest.raises(api.RequestScopeMismatch):
        await repository.append_calculation(mismatched_scope, calculation)

    async with repository_engine.connect() as connection:
        count = (
            await connection.execute(
                text(
                    """
                    SELECT count(*) FROM evidence.calculation_record
                    WHERE run_id = :run_id AND calculation_id = :calculation_id
                    """
                ),
                {
                    "run_id": repository_context.run_id,
                    "calculation_id": calculation.calculation_id,
                },
            )
        ).scalar_one()
    assert count == 0
