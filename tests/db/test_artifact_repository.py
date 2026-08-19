from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg.types.json import Jsonb
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.contracts import (
    AnswerPlan,
    ClaimBinding,
    EvidenceBundle,
    ExecutionGraph,
    QueryPlan,
    ReleasedAnswer,
    RequestContext,
    RuntimeArtifact,
    ToolResult,
    VerificationReport,
    build_request_key,
    canonical_json_bytes,
)
from financial_agent.db.preflight import normalize_psycopg_url
from tests.fixtures.db.synthetic_dataset import (
    CREATED_AT,
    VALID_RECORD_HASH,
    insert_building_dataset,
    insert_entity,
    insert_institution,
    insert_source,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "contracts" / "v1"
MODEL_BY_TYPE: dict[str, type[RuntimeArtifact]] = {
    "request_context": RequestContext,
    "query_plan": QueryPlan,
    "execution_graph": ExecutionGraph,
    "tool_result": ToolResult,
    "evidence_bundle": EvidenceBundle,
    "verification_report": VerificationReport,
    "answer_plan": AnswerPlan,
    "released_answer": ReleasedAnswer,
}
FIXTURE_BY_TYPE = {
    "request_context": "request_context.json",
    "query_plan": "query_plan.json",
    "execution_graph": "execution_graph.json",
    "tool_result": "tool_result.json",
    "evidence_bundle": "evidence_bundle.json",
    "verification_report": "verification_report.json",
    "answer_plan": "answer_plan.json",
}


@dataclass(frozen=True, slots=True)
class ArtifactContext:
    dataset_version: str
    run_id: str
    request_key: str
    question_id: str
    question: str
    created_at: datetime


def _fixture_payload(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _artifact_context(database_url: str) -> ArtifactContext:
    token = uuid4().hex
    dataset_version = f"artifact-{token}"
    run_id = f"run-{token}"
    question_id = f"Q-{token}"
    question = "Synthetic artifact persistence question"
    request_key = build_request_key(question_id, question, dataset_version, "1.0")
    created_at = datetime(2026, 8, 17, tzinfo=UTC)
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        insert_building_dataset(connection, dataset_version)
        insert_institution(connection, dataset_version=dataset_version)
        insert_source(connection, dataset_version=dataset_version)
        insert_entity(
            connection,
            dataset_version=dataset_version,
            entity_id="subject-one",
        )
        connection.execute(
            """
            INSERT INTO operations.request_run (
                run_id, request_key, question_id, question, schema_version,
                dataset_version, cutoff_date, created_at, deadline_at
            ) VALUES (%s, %s, %s, %s, '1.0', %s, DATE '2026-07-11', %s, %s)
            """,
            (
                run_id,
                request_key,
                question_id,
                question,
                dataset_version,
                created_at,
                created_at + timedelta(seconds=55),
            ),
        )
    return ArtifactContext(
        dataset_version=dataset_version,
        run_id=run_id,
        request_key=request_key,
        question_id=question_id,
        question=question,
        created_at=created_at,
    )


def _artifact(
    artifact_type: str,
    context: ArtifactContext,
    *,
    empty_references: bool = True,
) -> RuntimeArtifact:
    if artifact_type == "released_answer":
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "request_key": context.request_key,
            "run_id": context.run_id,
            "dataset_version": context.dataset_version,
            "cutoff_date": "2026-07-11",
            "producer": "deterministic-renderer",
            "created_at": context.created_at.isoformat().replace("+00:00", "Z"),
            "answer_disposition": "answer",
            "answer_text": "Synthetic answer",
            "retrieved_context_text": "Synthetic context",
            "think_trace_text": "Synthetic execution trace",
            "claim_bindings": [],
            "response_hash": "1" * 64,
        }
    else:
        payload = _fixture_payload(FIXTURE_BY_TYPE[artifact_type])
        payload.update(
            {
                "request_key": context.request_key,
                "run_id": context.run_id,
                "dataset_version": context.dataset_version,
                "created_at": context.created_at.isoformat().replace(
                    "+00:00", "Z"
                ),
            }
        )
        if artifact_type == "request_context":
            payload.update(
                {
                    "question_id": context.question_id,
                    "question": context.question,
                    "segments": [
                        {
                            "segment_id": "s1",
                            "ordinal": 0,
                            "text": context.question,
                        }
                    ],
                    "named_entities": [],
                    "reference_mentions": [],
                    "deadline_at": (
                        context.created_at + timedelta(seconds=55)
                    ).isoformat().replace("+00:00", "Z"),
                }
            )
        if empty_references:
            if artifact_type == "tool_result":
                payload["evidence_refs"] = []
            elif artifact_type == "evidence_bundle":
                payload.update(
                    {
                        "evidence_ids": [],
                        "calculation_ids": [],
                        "candidate_claim_ids": [],
                        "exclusion_evidence_ids": [],
                        "limitations": [],
                    }
                )
            elif artifact_type == "verification_report":
                payload.update(
                    {
                        "claim_checks": [],
                        "calculation_checks": [],
                        "releaseable_claim_ids": [],
                        "rejected_claims": [],
                    }
                )
            elif artifact_type == "answer_plan":
                payload["blocks"] = []
    return MODEL_BY_TYPE[artifact_type].model_validate_json(
        json.dumps(payload, ensure_ascii=False)
    )


def _seed_references(connection: psycopg.Connection, context: ArtifactContext) -> None:
    tagged_value = Jsonb({"type": "string", "value": "synthetic"})
    connection.execute(
        """
        INSERT INTO evidence.evidence_record (
            dataset_version, evidence_id, evidence_kind, source_id,
            subject_id, predicate_id, value_or_object_id, normalized_value,
            unit, currency, applicable_date, locator_type,
            locator_uri_or_object_key, parser_version, mapping_version,
            cutoff_status, record_hash, created_at
        ) VALUES (
            %s, 'evidence-aum-1', 'policy', 'source-one', 'subject-one',
            'synthetic-predicate', %s, %s, 'won', 'KRW', DATE '2026-07-11',
            'tabular', 'synthetic://artifact', 'parser.v1', 'mapping.v1',
            'eligible', %s, %s
        )
        """,
        (
            context.dataset_version,
            tagged_value,
            tagged_value,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO evidence.evidence_record (
            dataset_version, evidence_id, evidence_kind, source_id,
            subject_id, predicate_id, value_or_object_id, normalized_value,
            unit, currency, applicable_date, locator_type,
            locator_uri_or_object_key, parser_version, mapping_version,
            cutoff_status, record_hash, created_at
        ) VALUES (
            %s, 'evidence-syn-etf-a', 'policy', 'source-one', 'subject-one',
            'synthetic-predicate', %s, %s, 'won', 'KRW', DATE '2026-07-11',
            'tabular', 'synthetic://artifact', 'parser.v1', 'mapping.v1',
            'eligible', %s, %s
        )
        """,
        (
            context.dataset_version,
            tagged_value,
            tagged_value,
            VALID_RECORD_HASH,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO evidence.calculation_record (
            run_id, dataset_version, calculation_id, calculation_type,
            formula_id, formula_version, result_value, calculation_hash,
            created_at
        ) VALUES (
            %s, %s, 'calculation-rank-1', 'comparison', 'synthetic-formula',
            '1', %s, %s, %s
        )
        """,
        (
            context.run_id,
            context.dataset_version,
            tagged_value,
            "2" * 64,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO evidence.calculation_evidence_input (
            run_id, dataset_version, calculation_id, evidence_id, ordinal
        ) VALUES (%s, %s, 'calculation-rank-1', 'evidence-aum-1', 0)
        """,
        (context.run_id, context.dataset_version),
    )
    connection.execute(
        """
        INSERT INTO evidence.atomic_claim (
            run_id, dataset_version, claim_id, claim_type, subtask_id,
            subject_id, subject_kind, subject_entity_id, predicate_id, value,
            display_policy_id, claim_hash, created_at
        ) VALUES (
            %s, %s, 'claim-rank-1', 'direct_fact', 'q1', 'subject-one',
            'entity', 'subject-one', 'synthetic-predicate', %s,
            'display.synthetic', %s, %s
        )
        """,
        (
            context.run_id,
            context.dataset_version,
            tagged_value,
            "3" * 64,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO evidence.claim_support (
            run_id, dataset_version, claim_id, support_kind, evidence_id,
            support_role, ordinal
        ) VALUES (%s, %s, 'claim-rank-1', 'direct', 'evidence-aum-1', 'value', 0)
        """,
        (context.run_id, context.dataset_version),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest_asyncio.fixture
async def artifact_engine(migrated_database_url: str) -> AsyncEngine:
    engine = create_async_engine(migrated_database_url, pool_size=5, max_overflow=0)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.postgres
def test_database_derives_artifact_metadata_projection_and_sha256(
    migrated_database_url: str,
) -> None:
    context = _artifact_context(migrated_database_url)
    artifact = _artifact("request_context", context)
    canonical_payload = canonical_json_bytes(artifact).decode("utf-8")
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        row = connection.execute(
            """
            INSERT INTO operations.request_artifact (
                artifact_type, canonical_payload, payload_jsonb, payload_hash
            ) VALUES ('request_context', %s, '{"caller":"wrong"}', repeat('0', 64))
            RETURNING schema_version, request_key, run_id, dataset_version,
                      cutoff_date, producer, created_at, payload_jsonb, payload_hash
            """,
            (canonical_payload,),
        ).fetchone()
        changed_payload = canonical_json_bytes(
            artifact.model_copy(update={"producer": "changed-producer"})
        ).decode("utf-8")
        changed_hash = connection.execute(
            """
            INSERT INTO operations.request_artifact (
                artifact_type, canonical_payload, payload_jsonb, payload_hash
            ) VALUES ('request_context', %s, '{}', repeat('0', 64))
            RETURNING payload_hash
            """,
            (changed_payload,),
        ).fetchone()[0]

    assert row[:7] == (
        artifact.schema_version,
        artifact.request_key,
        artifact.run_id,
        artifact.dataset_version,
        artifact.cutoff_date,
        artifact.producer,
        artifact.created_at,
    )
    assert row[7] == artifact.model_dump(mode="json")
    assert row[8] == hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    assert changed_hash == hashlib.sha256(changed_payload.encode("utf-8")).hexdigest()
    assert changed_hash != row[8]


@pytest.mark.postgres
def test_artifact_type_constraint_matches_the_eight_runtime_models(
    migrated_database_url: str,
) -> None:
    expected = set(MODEL_BY_TYPE)
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        definition = connection.execute(
            """
            SELECT pg_catalog.pg_get_constraintdef(constraint_record.oid)
            FROM pg_catalog.pg_constraint AS constraint_record
            JOIN pg_catalog.pg_class AS table_record
              ON table_record.oid = constraint_record.conrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = table_record.relnamespace
            WHERE namespace.nspname = 'operations'
              AND table_record.relname = 'request_artifact'
              AND constraint_record.conname = 'ck_request_artifact_artifact_type'
            """
        ).fetchone()[0]

    assert set(re.findall(r"'([a-z_]+)'", definition)) == expected


@pytest.mark.postgres
def test_artifact_and_reference_rows_reject_updates_and_deletes(
    migrated_database_url: str,
) -> None:
    context = _artifact_context(migrated_database_url)
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        query_plan_payload = canonical_json_bytes(
            _artifact("query_plan", context, empty_references=False)
        ).decode("utf-8")
        connection.execute(
            "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
            ("query_plan", "hcx-model", "prompt-v1", query_plan_payload),
        )
        _seed_references(connection, context)
        canonical_payload = canonical_json_bytes(
            _artifact("evidence_bundle", context, empty_references=False)
        ).decode("utf-8")
        artifact_record_id = connection.execute(
            "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
            ("evidence_bundle", None, None, canonical_payload),
        ).fetchone()[0]
        for statement in (
            "UPDATE operations.request_artifact SET producer='changed' "
            "WHERE artifact_record_id=%s",
            "DELETE FROM operations.request_artifact WHERE artifact_record_id=%s",
            "UPDATE operations.artifact_evidence_ref "
            "SET reference_role='changed' WHERE artifact_record_id=%s",
            "DELETE FROM operations.artifact_evidence_ref "
            "WHERE artifact_record_id=%s",
        ):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                with connection.transaction():
                    connection.execute(statement, (artifact_record_id,))


@pytest.mark.postgres
def test_stage02_creates_no_release_authority_or_raw_chain_of_thought_column(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        release_relations = connection.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'operations'
              AND (table_name ILIKE '%release%' OR table_name ILIKE '%cache%')
            """
        ).fetchall()
        release_functions = connection.execute(
            """
            SELECT routine_name FROM information_schema.routines
            WHERE routine_schema = 'operations'
              AND routine_name IN ('cache_verified_release', 'get_cached_release')
            """
        ).fetchall()
        forbidden_columns = connection.execute(
            """
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema = 'operations'
              AND (
                  column_name ILIKE '%release_author%'
                  OR column_name ILIKE '%release_status%'
                  OR column_name ILIKE '%release_timestamp%'
                  OR column_name ILIKE '%chain_of_thought%'
                  OR column_name ILIKE '%raw_reasoning%'
              )
            """
        ).fetchall()

    assert release_relations == []
    assert release_functions == []
    assert forbidden_columns == []


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_repository_round_trips_all_eight_selected_stage01_models(
    migrated_database_url: str,
    artifact_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import (
        ARTIFACT_MODELS,
        RequestArtifactRepository,
    )

    context = _artifact_context(migrated_database_url)
    repository = RequestArtifactRepository(artifact_engine)
    assert set(ARTIFACT_MODELS) == set(MODEL_BY_TYPE)

    expected_contract_ids = {
        "request_context": None,
        "query_plan": None,
        "execution_graph": "graph-syn-001",
        "tool_result": "t3",
        "evidence_bundle": "bundle-syn-001",
        "verification_report": "verification-syn-001",
        "answer_plan": None,
        "released_answer": None,
    }
    stored: dict[str, UUID] = {}
    for artifact_type in MODEL_BY_TYPE:
        artifact = _artifact(artifact_type, context)
        kwargs = (
            {"model_id": "hcx-model", "prompt_version": "prompt-v1"}
            if artifact_type == "query_plan"
            else {}
        )
        artifact_record_id = await repository.append(
            artifact_type, artifact, **kwargs  # type: ignore[arg-type]
        )
        assert await repository.get(context.run_id, artifact_record_id) == artifact
        stored[artifact_type] = artifact_record_id

    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        rows = connection.execute(
            """
            SELECT artifact_type, contract_object_id
            FROM operations.request_artifact
            WHERE run_id = %s
            """,
            (context.run_id,),
        ).fetchall()
    assert dict(rows) == expected_contract_ids
    assert len(set(stored.values())) == 8


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_model_metadata_rules_are_checked_before_insert(
    migrated_database_url: str,
    artifact_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import (
        ArtifactValidationError,
        RequestArtifactRepository,
    )

    context = _artifact_context(migrated_database_url)
    repository = RequestArtifactRepository(artifact_engine)
    query_plan = _artifact("query_plan", context)
    answer_plan = _artifact("answer_plan", context)
    tool_result = _artifact("tool_result", context)

    with pytest.raises(ArtifactValidationError, match="MODEL_METADATA_REQUIRED"):
        await repository.append("query_plan", query_plan)
    with pytest.raises(ArtifactValidationError, match="MODEL_METADATA_PAIR_REQUIRED"):
        await repository.append(
            "answer_plan", answer_plan, model_id="hcx-model"
        )
    with pytest.raises(ArtifactValidationError, match="MODEL_METADATA_FORBIDDEN"):
        await repository.append(
            "tool_result",
            tool_result,
            model_id="hcx-model",
            prompt_version="prompt-v1",
        )

    deterministic_id = await repository.append("answer_plan", answer_plan)
    model_id = await repository.append(
        "answer_plan",
        answer_plan.model_copy(update={"producer": "answer-composer-retry"}),
        model_id="hcx-model",
        prompt_version="prompt-v1",
    )
    assert deterministic_id != model_id


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_selected_model_rejects_unknown_cross_type_and_extra_payloads(
    migrated_database_url: str,
    artifact_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import (
        ArtifactValidationError,
        RequestArtifactRepository,
    )

    class ExtendedArtifact(RuntimeArtifact):
        unexpected: str

    context = _artifact_context(migrated_database_url)
    repository = RequestArtifactRepository(artifact_engine)
    query_plan = _artifact("query_plan", context)
    with pytest.raises(ArtifactValidationError, match="ARTIFACT_TYPE_UNKNOWN"):
        await repository.append("unknown", query_plan)  # type: ignore[arg-type]
    with pytest.raises(ArtifactValidationError, match="ARTIFACT_PAYLOAD_INVALID"):
        await repository.append("tool_result", query_plan)

    extra = ExtendedArtifact(
        request_key=context.request_key,
        run_id=context.run_id,
        dataset_version=context.dataset_version,
        producer="test",
        created_at=context.created_at,
        unexpected="forbidden",
    )
    with pytest.raises(ArtifactValidationError, match="ARTIFACT_PAYLOAD_INVALID"):
        await repository.append("tool_result", extra)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_identical_retry_returns_original_uuid_and_canonical_text(
    migrated_database_url: str,
    artifact_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import RequestArtifactRepository

    context = _artifact_context(migrated_database_url)
    repository = RequestArtifactRepository(artifact_engine)
    artifact = _artifact("execution_graph", context)
    first = await repository.append("execution_graph", artifact)
    second = await repository.append("execution_graph", artifact)
    restored = await repository.get(context.run_id, first)

    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        canonical_payload, jsonb_text, payload_hash = connection.execute(
            """
            SELECT canonical_payload, payload_jsonb::text, payload_hash
            FROM operations.request_artifact WHERE artifact_record_id = %s
            """,
            (first,),
        ).fetchone()

    assert first == second
    assert canonical_payload != jsonb_text
    assert canonical_json_bytes(restored).decode("utf-8") == canonical_payload
    assert payload_hash == hashlib.sha256(canonical_payload.encode()).hexdigest()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_two_connections_converge_or_raise_stable_contract_conflict(
    migrated_database_url: str,
) -> None:
    from financial_agent.db.repositories.artifacts import (
        ArtifactConflict,
        RequestArtifactRepository,
    )

    context = _artifact_context(migrated_database_url)
    first_engine = create_async_engine(migrated_database_url, pool_size=1)
    second_engine = create_async_engine(migrated_database_url, pool_size=1)
    try:
        first_repo = RequestArtifactRepository(first_engine)
        second_repo = RequestArtifactRepository(second_engine)
        artifact = _artifact("execution_graph", context)
        identical = await asyncio.gather(
            first_repo.append("execution_graph", artifact),
            second_repo.append("execution_graph", artifact),
        )
        assert identical[0] == identical[1]

        conflict_context = _artifact_context(migrated_database_url)
        original = _artifact("execution_graph", conflict_context)
        changed = original.model_copy(update={"producer": "other-orchestrator"})
        results = await asyncio.gather(
            first_repo.append("execution_graph", original),
            second_repo.append("execution_graph", changed),
            return_exceptions=True,
        )
        assert sum(isinstance(result, UUID) for result in results) == 1
        conflicts = [
            result for result in results if isinstance(result, ArtifactConflict)
        ]
        assert len(conflicts) == 1
        assert conflicts[0].code == "ARTIFACT_CONFLICT"
    finally:
        await first_engine.dispose()
        await second_engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_repository_populates_subtasks_and_normalized_references(
    migrated_database_url: str,
    artifact_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import RequestArtifactRepository

    context = _artifact_context(migrated_database_url)
    repository = RequestArtifactRepository(artifact_engine)
    await repository.append(
        "query_plan",
        _artifact("query_plan", context, empty_references=False),
        model_id="hcx-model",
        prompt_version="prompt-v1",
    )
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        _seed_references(connection, context)

    for artifact_type in (
        "tool_result",
        "evidence_bundle",
        "verification_report",
        "answer_plan",
    ):
        await repository.append(
            artifact_type,
            _artifact(artifact_type, context, empty_references=False),
            **(
                {"model_id": "hcx-model", "prompt_version": "prompt-v1"}
                if artifact_type == "answer_plan"
                else {}
            ),
        )
    released = _artifact("released_answer", context).model_copy(
        update={
            "claim_bindings": (
                ClaimBinding(
                    output_locator="answer.summary",
                    claim_ids=("claim-rank-1",),
                    evidence_ids=("evidence-aum-1",),
                ),
            )
        }
    )
    released = ReleasedAnswer.model_validate_json(
        json.dumps(released.model_dump(mode="json"))
    )
    await repository.append("released_answer", released)

    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        subtasks = connection.execute(
            """
            SELECT subtask_id, importance FROM operations.request_subtask
            WHERE run_id = %s ORDER BY subtask_id
            """,
            (context.run_id,),
        ).fetchall()
        evidence_roles = {
            row[0]
            for row in connection.execute(
                """
                SELECT reference_role FROM operations.artifact_evidence_ref
                WHERE run_id = %s
                """,
                (context.run_id,),
            ).fetchall()
        }
        calculation_roles = {
            row[0]
            for row in connection.execute(
                """
                SELECT reference_role FROM operations.artifact_calculation_ref
                WHERE run_id = %s
                """,
                (context.run_id,),
            ).fetchall()
        }
        claim_roles = {
            row[0]
            for row in connection.execute(
                """
                SELECT reference_role FROM operations.artifact_claim_ref
                WHERE run_id = %s
                """,
                (context.run_id,),
            ).fetchall()
        }

    assert subtasks == [("q1", "critical"), ("q2", "critical")]
    assert {"result", "included", "claim_check", "calculation_check", "bound"} <= evidence_roles
    assert {"included", "checked"} <= calculation_roles
    assert {"candidate", "releaseable", "selected", "bound"} <= claim_roles
