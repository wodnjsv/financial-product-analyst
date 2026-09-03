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
import sqlalchemy as sa
from psycopg.types.json import Jsonb
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.contracts import (
    AnswerPlan,
    ClaimBinding,
    CheckResult,
    CheckStatus,
    CheckTargetType,
    EvidenceBundle,
    ExecutionGraph,
    QueryPlan,
    ReleasedAnswer,
    Repairability,
    RequestContext,
    RuntimeArtifact,
    ToolResult,
    VerificationReport,
    build_request_key,
    canonical_json_bytes,
    canonical_sha256,
)
from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.intent.resolution import (
    ValidatedIntentResolution,
    ValidatedIntentResolutionV2,
)
from financial_agent.intent.query_contracts import (
    ResolvedQueryContractSetV2,
    query_contract_candidate_id,
)
from financial_agent.planning.logical_query import LogicalQueryPlanV2
from tests.fixtures.db.synthetic_dataset import (
    CREATED_AT,
    VALID_RECORD_HASH,
    insert_building_dataset,
    insert_entity,
    insert_institution,
    insert_source,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "contracts" / "v1"
V2_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "contracts" / "v2"
MODEL_BY_TYPE: dict[str, type[RuntimeArtifact]] = {
    "request_context": RequestContext,
    "intent_resolution": ValidatedIntentResolution,
    "query_contract": ResolvedQueryContractSetV2,
    "logical_query_plan": LogicalQueryPlanV2,
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

V2_FIXTURE_BY_TYPE = {
    "query_contract": "query_contract.json",
    "logical_query_plan": "logical_query_plan.json",
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


def _v2_fixture_payload(name: str) -> dict[str, Any]:
    return json.loads((V2_FIXTURE_ROOT / name).read_text(encoding="utf-8"))


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
            ) VALUES (%s, %s, %s, %s, '1.0', %s, DATE '2026-08-24', %s, %s)
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
    if artifact_type == "intent_resolution":
        payload: dict[str, Any] = {
            "request_key": context.request_key,
            "run_id": context.run_id,
            "dataset_version": context.dataset_version,
            "producer": "intent-resolver",
            "created_at": context.created_at.isoformat().replace("+00:00", "Z"),
            "resolution_id": "resolution-syn-001",
            "draft_hash": "8" * 64,
            "canonical_frames": [],
            "context_links": [],
            "final_tags": [],
            "resolution_status": "resolved",
            "issues": [],
            "validation_events": [],
            "build_manifest": {
                "catalog_version": "catalog-v1",
                "catalog_hash": "9" * 64,
                "ontology_hashes": [
                    {
                        "relative_path": "ontology/financial-product.ttl",
                        "sha256": "a" * 64,
                    }
                ],
                "overlay_version": "overlay-v1",
                "overlay_hash": "b" * 64,
                "normalizer_version": "intent-normalizer-v1",
                "candidate_policy_version": "intent-candidate-v1",
                "resolver_schema_version": "1.0",
                "prompt_version": "intent-resolver-ko-v1",
                "adapter_version": "clova-chat-v3-structured-v1",
            },
            "active_dataset_manifest_hash": "c" * 64,
            "repair_used": False,
            "invalid_attempt_hashes": [],
        }
    elif artifact_type in V2_FIXTURE_BY_TYPE:
        payload = _v2_fixture_payload(V2_FIXTURE_BY_TYPE[artifact_type])
        payload.update(
            {
                "request_key": context.request_key,
                "run_id": context.run_id,
                "dataset_version": context.dataset_version,
                "created_at": context.created_at.isoformat().replace("+00:00", "Z"),
            }
        )
        if artifact_type == "logical_query_plan":
            payload["logical_plan_id"] = "logical-query-plan-" + canonical_sha256(
                {
                    key: value
                    for key, value in payload.items()
                    if key != "logical_plan_id"
                }
            )
    elif artifact_type == "released_answer":
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "request_key": context.request_key,
            "run_id": context.run_id,
            "dataset_version": context.dataset_version,
            "cutoff_date": "2026-08-24",
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


def _v2_intent_resolution(context: ArtifactContext) -> ValidatedIntentResolutionV2:
    payload = json.loads(canonical_json_bytes(_artifact("intent_resolution", context)))
    payload["build_manifest"]["resolver_schema_version"] = "2.0"
    payload["canonical_frames"] = [
        {
            "frame_id": "frame-syn-001",
            "ordinal": 0,
            "frame_status": "resolved",
            "segment_ids": ["segment-syn-001"],
            "evidence_span_ids": [],
            "action_choice": {
                "state": "selected",
                "selected_ids": ["lookup"],
                "evidence_span_ids": [],
                "reason_code": "explicit",
            },
            "product_family_choice": {
                "state": "selected",
                "selected_ids": ["domestic_etf"],
                "evidence_span_ids": [],
                "reason_code": "explicit",
            },
            "entity_type_ids": [],
            "entity_hint_ids": [],
            "slot_assignments": [],
            "produced_result_roles": [],
            "slot_mutations": [],
            "semantic_coverage": [
                {"state": "covered", "reason": "none", "evidence_ids": []}
            ],
        }
    ]
    return ValidatedIntentResolutionV2.model_validate(payload)


def test_intent_resolution_and_query_plan_model_metadata_policy() -> None:
    from financial_agent.db.repositories.artifacts import (
        ArtifactValidationError,
        _validate_model_metadata,
    )

    with pytest.raises(ArtifactValidationError, match="MODEL_METADATA_REQUIRED"):
        _validate_model_metadata("intent_resolution", None, None)
    _validate_model_metadata(
        "intent_resolution", "synthetic-model", "intent-resolver-ko-v1"
    )

    with pytest.raises(ArtifactValidationError, match="MODEL_METADATA_FORBIDDEN"):
        _validate_model_metadata(
            "query_plan", "synthetic-model", "intent-resolver-ko-v1"
        )
    _validate_model_metadata("query_plan", None, None)
    for deterministic_type in ("query_contract", "logical_query_plan"):
        with pytest.raises(ArtifactValidationError, match="MODEL_METADATA_FORBIDDEN"):
            _validate_model_metadata(
                deterministic_type,  # type: ignore[arg-type]
                "synthetic-model",
                "semantic-query-v2",
            )
        _validate_model_metadata(  # type: ignore[arg-type]
            deterministic_type, None, None
        )


@pytest.mark.parametrize(
    ("resolver_schema_version", "expected_model"),
    (
        ("1.0", ValidatedIntentResolution),
        ("2.0", ValidatedIntentResolutionV2),
    ),
)
def test_intent_resolution_dispatch_accepts_only_known_schema_versions(
    resolver_schema_version: str,
    expected_model: type[ValidatedIntentResolution],
) -> None:
    from financial_agent.db.repositories.artifacts import _artifact_model

    payload = json.dumps(
        {"build_manifest": {"resolver_schema_version": resolver_schema_version}}
    )

    assert _artifact_model("intent_resolution", payload) is expected_model


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"build_manifest": None},
        {"build_manifest": []},
        {"build_manifest": {}},
        {"build_manifest": {"resolver_schema_version": None}},
        {"build_manifest": {"resolver_schema_version": 2}},
        {"build_manifest": {"resolver_schema_version": "3.0"}},
    ),
)
def test_intent_resolution_dispatch_rejects_missing_or_unknown_schema_versions(
    payload: object,
) -> None:
    from financial_agent.db.repositories.artifacts import _artifact_model

    with pytest.raises(ValueError, match="INTENT_RESOLUTION_SCHEMA_VERSION_INVALID"):
        _artifact_model("intent_resolution", json.dumps(payload))


@pytest.mark.asyncio
async def test_repository_append_rejects_unknown_intent_resolution_schema_version() -> None:
    from financial_agent.db.repositories.artifacts import (
        ArtifactValidationError,
        RequestArtifactRepository,
    )

    context = ArtifactContext(
        dataset_version="artifact-invalid-version",
        run_id="run-invalid-version",
        request_key="a" * 64,
        question_id="Q-invalid-version",
        question="Synthetic invalid schema version",
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
    )
    resolution = _artifact("intent_resolution", context)
    invalid_resolution = resolution.model_copy(
        update={
            "build_manifest": resolution.build_manifest.model_copy(
                update={"resolver_schema_version": "3.0"}
            )
        }
    )
    repository = RequestArtifactRepository(None)  # type: ignore[arg-type]

    with pytest.raises(ArtifactValidationError, match="ARTIFACT_PAYLOAD_INVALID"):
        await repository.append(
            "intent_resolution",
            invalid_resolution,
            model_id="hcx-model",
            prompt_version="prompt-v3",
        )


@pytest.mark.parametrize(
    ("artifact_type", "model_id", "prompt_version"),
    (
        ("intent_resolution", " ", "intent-resolver-ko-v1"),
        ("intent_resolution", "synthetic-model", "\t"),
        ("answer_plan", " ", "prompt-v1"),
        ("answer_plan", "synthetic-model", "\n"),
    ),
)
def test_model_metadata_rejects_blank_values_for_every_optional_or_required_pair(
    artifact_type: str,
    model_id: str,
    prompt_version: str,
) -> None:
    from financial_agent.db.repositories.artifacts import (
        ArtifactValidationError,
        _validate_model_metadata,
    )

    with pytest.raises(ArtifactValidationError, match="MODEL_METADATA_BLANK"):
        _validate_model_metadata(  # type: ignore[arg-type]
            artifact_type,
            model_id,
            prompt_version,
        )


def test_intent_resolution_contract_model_is_registered() -> None:
    from financial_agent.db.repositories.artifacts import ARTIFACT_MODELS
    from financial_agent.intent.resolution import ValidatedIntentResolution

    assert ARTIFACT_MODELS["intent_resolution"] is ValidatedIntentResolution


def test_semantic_query_artifact_models_are_registered_without_changing_v1_dispatch(
) -> None:
    from financial_agent.db.repositories.artifacts import (
        ARTIFACT_MODELS,
        _artifact_model,
    )

    assert ARTIFACT_MODELS["query_contract"] is ResolvedQueryContractSetV2
    assert ARTIFACT_MODELS["logical_query_plan"] is LogicalQueryPlanV2
    assert _artifact_model("query_contract", b"{}") is ResolvedQueryContractSetV2
    assert _artifact_model("logical_query_plan", b"{}") is LogicalQueryPlanV2
    assert _artifact_model(
        "intent_resolution",
        json.dumps({"build_manifest": {"resolver_schema_version": "1.0"}}),
    ) is ValidatedIntentResolution


@pytest.mark.parametrize("artifact_type", ("query_contract", "logical_query_plan"))
def test_semantic_query_fixtures_are_strict_and_content_addressed(
    artifact_type: str,
) -> None:
    context = ArtifactContext(
        dataset_version="dataset-v1",
        run_id="run-1",
        request_key="e" * 64,
        question_id="Q-v2",
        question="Synthetic V2 persistence fixture",
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    artifact = _artifact(artifact_type, context)
    object_id_field = (
        "query_contract_id"
        if artifact_type == "query_contract"
        else "logical_plan_id"
    )
    payload = artifact.model_dump(mode="json")
    payload[object_id_field] = "forged-object-id"

    with pytest.raises(ValueError):
        MODEL_BY_TYPE[artifact_type].model_validate(payload)
    with pytest.raises(ValueError):
        MODEL_BY_TYPE[artifact_type].model_validate(
            {**artifact.model_dump(mode="json"), "unexpected": True}
        )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        (("registry_pins", "contract_registry_hash"), "f" * 64,
         "CONTRACT_REGISTRY_PIN_MISMATCH"),
        (("readiness", 0, "frame_id"), "foreign-frame",
         "CONTRACT_READINESS_OWNERSHIP_MISMATCH"),
        (("judge_provenance", 0, "frame_id"), "foreign-frame",
         "CONTRACT_SELECTION_OWNERSHIP_MISMATCH"),
    ),
)
def test_query_contract_fixture_rejects_divergent_pins_and_ownership(
    path: tuple[str | int, ...],
    value: object,
    message: str,
) -> None:
    payload = _v2_fixture_payload("query_contract.json")
    target: Any = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ValueError, match=message):
        ResolvedQueryContractSetV2.model_validate_json(json.dumps(payload))


def test_query_contract_fixture_candidate_id_is_deterministic_and_round_trips(
) -> None:
    artifact = ResolvedQueryContractSetV2.model_validate_json(
        (V2_FIXTURE_ROOT / "query_contract.json").read_bytes()
    )
    contract = artifact.contracts[0]

    assert artifact.judge_provenance[0].selected_candidate_id == (
        query_contract_candidate_id(contract)
    )
    assert ResolvedQueryContractSetV2.model_validate_json(
        canonical_json_bytes(artifact)
    ) == artifact
    assert query_contract_candidate_id(
        contract.model_copy(
            update={
                "provenance": contract.provenance[:1],
                "axis_readiness": contract.axis_readiness.model_copy(
                    update={"reason_codes": ("different-audit-reason",)}
                ),
            }
        )
    ) == query_contract_candidate_id(contract)


@pytest.mark.parametrize(
    "selected_candidate_id",
    ("arbitrary-candidate", "query-contract-" + "0" * 64),
)
def test_query_contract_fixture_rejects_arbitrary_candidate_id(
    selected_candidate_id: str,
) -> None:
    payload = _v2_fixture_payload("query_contract.json")
    payload["judge_provenance"][0]["selected_candidate_id"] = selected_candidate_id

    with pytest.raises(ValueError, match="CONTRACT_SELECTION_CANDIDATE_MISMATCH"):
        ResolvedQueryContractSetV2.model_validate_json(json.dumps(payload))


def test_query_contract_fixture_rejects_candidate_id_for_different_contract(
) -> None:
    artifact = ResolvedQueryContractSetV2.model_validate_json(
        (V2_FIXTURE_ROOT / "query_contract.json").read_bytes()
    )
    other_contract = artifact.contracts[0].model_copy(update={"limit": 6})
    payload = artifact.model_dump(mode="json")
    payload["judge_provenance"][0]["selected_candidate_id"] = (
        query_contract_candidate_id(other_contract)
    )

    with pytest.raises(ValueError, match="CONTRACT_SELECTION_CANDIDATE_MISMATCH"):
        ResolvedQueryContractSetV2.model_validate_json(json.dumps(payload))


def test_failure_event_accepts_only_bounded_payload_audit_metadata() -> None:
    from financial_agent.db.repositories.operations import FailureEventRecord

    event = FailureEventRecord(
        event_id="event-1",
        run_id="run-1",
        task_id=None,
        stage="intent_resolution",
        code="MODEL_SCHEMA_INVALID",
        category="planner_contract",
        retryable=False,
        attempt=1,
        remaining_budget_ms=1_000,
        duration_ms=10,
        dependency="hcx",
        occurred_at=datetime(2026, 8, 31, tzinfo=UTC),
        payload_hash="a" * 64,
        payload_size_bytes=128,
    )

    assert event.payload_hash == "a" * 64
    assert event.payload_size_bytes == 128
    assert not hasattr(event, "raw_payload")
    assert not hasattr(event, "raw_question")
    assert not hasattr(event, "raw_model_output")


@pytest.mark.parametrize(
    ("payload_hash", "payload_size_bytes", "message"),
    (
        ("not-sha256", 1, "PAYLOAD_HASH_INVALID"),
        (123, 1, "PAYLOAD_HASH_INVALID"),
        ("a" * 64, -1, "PAYLOAD_SIZE_BYTES_INVALID"),
        ("a" * 64, True, "PAYLOAD_SIZE_BYTES_INVALID"),
        ("a" * 64, "128", "PAYLOAD_SIZE_BYTES_INVALID"),
        ("a" * 64, 1.5, "PAYLOAD_SIZE_BYTES_INVALID"),
        (None, 1, "PAYLOAD_AUDIT_PAIR_REQUIRED"),
        ("a" * 64, None, "PAYLOAD_AUDIT_PAIR_REQUIRED"),
    ),
)
def test_failure_event_rejects_invalid_payload_audit_metadata(
    payload_hash: object | None,
    payload_size_bytes: object | None,
    message: str,
) -> None:
    from financial_agent.db.repositories.operations import FailureEventRecord

    with pytest.raises(ValueError, match=message):
        FailureEventRecord(
            event_id="event-1",
            run_id="run-1",
            task_id=None,
            stage="intent_resolution",
            code="MODEL_SCHEMA_INVALID",
            category="planner_contract",
            retryable=False,
            attempt=1,
            remaining_budget_ms=1_000,
            duration_ms=10,
            dependency="hcx",
            occurred_at=datetime(2026, 8, 31, tzinfo=UTC),
            payload_hash=payload_hash,  # type: ignore[arg-type]
            payload_size_bytes=payload_size_bytes,  # type: ignore[arg-type]
        )


def test_failure_event_schema_exposes_hash_and_size_without_raw_content() -> None:
    from financial_agent.db.schema.operations import failure_event

    column_names = set(failure_event.c.keys())
    assert {"payload_hash", "payload_size_bytes"} <= column_names
    assert {
        "raw_payload",
        "raw_question",
        "raw_model_output",
    }.isdisjoint(column_names)

    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in failure_event.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert "^[0-9a-f]{64}$" in checks["ck_failure_event_payload_hash"]
    assert ">= 0" in checks["ck_failure_event_payload_size_bytes"]
    assert checks["ck_failure_event_payload_audit_pair"] == (
        "(payload_hash IS NULL) = (payload_size_bytes IS NULL)"
    )


def test_request_artifact_schema_rejects_blank_provenance_and_resolution_id() -> None:
    from financial_agent.db.schema.operations import request_artifact

    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in request_artifact.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }

    model_metadata = checks["ck_request_artifact_model_metadata"]
    assert "model_id ~ '[^[:space:]]'" in model_metadata
    assert "prompt_version ~ '[^[:space:]]'" in model_metadata
    resolution_id = checks[
        "ck_request_artifact_intent_resolution_contract_object_id"
    ]
    assert "artifact_type <> 'intent_resolution'" in resolution_id
    assert "contract_object_id IS NOT NULL" in resolution_id
    assert "contract_object_id ~ '[^[:space:]]'" in resolution_id


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


def _seed_colliding_calculations(
    connection: psycopg.Connection, context: ArtifactContext
) -> None:
    tagged_value = Jsonb({"type": "string", "value": "synthetic"})
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        """
        INSERT INTO evidence.calculation_record (
            run_id, dataset_version, calculation_id, calculation_type,
            formula_id, formula_version, result_value, calculation_hash,
            created_at
        ) VALUES
            (%s, %s, 'evidence-syn-etf-a', 'comparison',
             'collision-evidence', '1', %s, repeat('4', 64), %s),
            (%s, %s, 'claim-rank-1', 'comparison',
             'collision-claim', '1', %s, repeat('5', 64), %s),
            (%s, %s, 'q2', 'comparison',
             'collision-subtask', '1', %s, repeat('6', 64), %s)
        """,
        (
            context.run_id,
            context.dataset_version,
            tagged_value,
            CREATED_AT,
            context.run_id,
            context.dataset_version,
            tagged_value,
            CREATED_AT,
            context.run_id,
            context.dataset_version,
            tagged_value,
            CREATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO evidence.calculation_evidence_input (
            run_id, dataset_version, calculation_id, evidence_id, ordinal
        ) VALUES
            (%s, %s, 'evidence-syn-etf-a', 'evidence-aum-1', 0),
            (%s, %s, 'claim-rank-1', 'evidence-aum-1', 0),
            (%s, %s, 'q2', 'evidence-aum-1', 0)
        """,
        (
            context.run_id,
            context.dataset_version,
            context.run_id,
            context.dataset_version,
            context.run_id,
            context.dataset_version,
        ),
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
def test_artifact_type_constraint_matches_the_runtime_models(
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
@pytest.mark.parametrize(
    "resolution_id",
    (None, " \t"),
    ids=("missing", "blank"),
)
def test_runtime_append_rejects_missing_or_blank_intent_resolution_id(
    migrated_database_url: str,
    resolution_id: str | None,
) -> None:
    context = _artifact_context(migrated_database_url)
    payload = json.loads(
        canonical_json_bytes(_artifact("intent_resolution", context))
    )
    if resolution_id is None:
        payload.pop("resolution_id")
    else:
        payload["resolution_id"] = resolution_id
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        with pytest.raises(
            psycopg.errors.InvalidParameterValue,
            match="INTENT_RESOLUTION_ID_REQUIRED",
        ):
            connection.execute(
                "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
                (
                    "intent_resolution",
                    "synthetic-model",
                    "intent-resolver-ko-v1",
                    canonical_payload,
                ),
            )


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("artifact_type", "model_id", "prompt_version"),
    (
        ("intent_resolution", " ", "intent-resolver-ko-v1"),
        ("intent_resolution", "synthetic-model", "\t"),
        ("answer_plan", " ", "prompt-v1"),
        ("answer_plan", "synthetic-model", "\n"),
    ),
)
def test_runtime_append_rejects_blank_model_metadata(
    migrated_database_url: str,
    artifact_type: str,
    model_id: str,
    prompt_version: str,
) -> None:
    context = _artifact_context(migrated_database_url)
    canonical_payload = canonical_json_bytes(
        _artifact(artifact_type, context)
    ).decode("utf-8")

    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        with pytest.raises(psycopg.errors.CheckViolation) as captured:
            connection.execute(
                "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
                (
                    artifact_type,
                    model_id,
                    prompt_version,
                    canonical_payload,
                ),
            )

    assert captured.value.diag.constraint_name == (
        "ck_request_artifact_model_metadata"
    )


@pytest.mark.postgres
def test_runtime_append_intent_resolution_is_idempotent_and_conflict_safe(
    migrated_database_url: str,
) -> None:
    context = _artifact_context(migrated_database_url)
    canonical_payload = canonical_json_bytes(
        _artifact("intent_resolution", context)
    ).decode("utf-8")
    conflicting_payload = json.loads(canonical_payload)
    conflicting_payload["producer"] = "different-intent-resolver"
    conflicting_canonical_payload = json.dumps(
        conflicting_payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    statement = "SELECT operations.append_request_artifact(%s, %s, %s, %s)"
    provenance = (
        "intent_resolution",
        "synthetic-model",
        "intent-resolver-ko-v1",
    )

    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        first_id = connection.execute(
            statement,
            (*provenance, canonical_payload),
        ).fetchone()[0]
        second_id = connection.execute(
            statement,
            (*provenance, canonical_payload),
        ).fetchone()[0]

        with pytest.raises(psycopg.errors.RaiseException) as payload_conflict:
            with connection.transaction():
                connection.execute(
                    statement,
                    (*provenance, conflicting_canonical_payload),
                )
        with pytest.raises(psycopg.errors.RaiseException) as provenance_conflict:
            with connection.transaction():
                connection.execute(
                    statement,
                    (
                        "intent_resolution",
                        "different-model",
                        "intent-resolver-ko-v1",
                        canonical_payload,
                    ),
                )

    assert first_id == second_id
    assert payload_conflict.value.diag.message_primary == "ARTIFACT_CONFLICT"
    assert provenance_conflict.value.diag.message_primary == "ARTIFACT_CONFLICT"


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
            ("query_plan", None, None, query_plan_payload),
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
async def test_repository_round_trips_all_registered_models(
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
        "intent_resolution": "resolution-syn-001",
        "query_plan": None,
        "query_contract": _artifact("query_contract", context).query_contract_id,
        "logical_query_plan": _artifact(
            "logical_query_plan", context
        ).logical_plan_id,
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
            if artifact_type == "intent_resolution"
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
    assert len(set(stored.values())) == len(MODEL_BY_TYPE)


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("artifact_type", ("query_contract", "logical_query_plan"))
async def test_semantic_query_object_id_is_idempotent_only_for_identical_payload(
    migrated_database_url: str,
    artifact_engine: AsyncEngine,
    artifact_type: str,
) -> None:
    from financial_agent.db.repositories.artifacts import (
        ArtifactConflict,
        RequestArtifactRepository,
    )

    context = _artifact_context(migrated_database_url)
    repository = RequestArtifactRepository(artifact_engine)
    artifact = _artifact(artifact_type, context)
    first = await repository.append(
        artifact_type, artifact  # type: ignore[arg-type]
    )
    assert (
        await repository.append(
            artifact_type, artifact  # type: ignore[arg-type]
        )
        == first
    )
    divergent = artifact.model_copy(update={"producer": "divergent-producer"})
    with pytest.raises(ArtifactConflict, match="ARTIFACT_CONFLICT"):
        await repository.append(artifact_type, divergent)  # type: ignore[arg-type]

    assert await repository.get(context.run_id, first) == artifact


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_repository_round_trips_v2_intent_resolution(
    migrated_database_url: str,
    artifact_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import RequestArtifactRepository

    context = _artifact_context(migrated_database_url)
    resolution = _v2_intent_resolution(context)
    repository = RequestArtifactRepository(artifact_engine)

    artifact_record_id = await repository.append(
        "intent_resolution",
        resolution,
        model_id="hcx-model",
        prompt_version="prompt-v2",
    )

    assert await repository.get(context.run_id, artifact_record_id) == resolution


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_repository_restore_rejects_unknown_intent_resolution_schema_version(
    migrated_database_url: str,
    artifact_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import (
        ArtifactPersistenceError,
        RequestArtifactRepository,
    )

    context = _artifact_context(migrated_database_url)
    resolution = _artifact("intent_resolution", context)
    invalid_resolution = resolution.model_copy(
        update={
            "build_manifest": resolution.build_manifest.model_copy(
                update={"resolver_schema_version": "3.0"}
            )
        }
    )
    canonical_payload = canonical_json_bytes(invalid_resolution).decode("utf-8")
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        artifact_record_id = connection.execute(
            "SELECT operations.append_request_artifact(%s, %s, %s, %s)",
            (
                "intent_resolution",
                "hcx-model",
                "prompt-v3",
                canonical_payload,
            ),
        ).fetchone()[0]

    repository = RequestArtifactRepository(artifact_engine)

    with pytest.raises(ArtifactPersistenceError, match="ARTIFACT_RESTORE_INVALID"):
        await repository.get(context.run_id, artifact_record_id)


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
    intent_resolution = _artifact("intent_resolution", context)
    query_plan = _artifact("query_plan", context)
    answer_plan = _artifact("answer_plan", context)
    tool_result = _artifact("tool_result", context)

    with pytest.raises(ArtifactValidationError, match="MODEL_METADATA_REQUIRED"):
        await repository.append("intent_resolution", intent_resolution)
    await repository.append(
        "intent_resolution",
        intent_resolution,
        model_id="hcx-model",
        prompt_version="intent-resolver-ko-v1",
    )
    with pytest.raises(ArtifactValidationError, match="MODEL_METADATA_FORBIDDEN"):
        await repository.append(
            "query_plan",
            query_plan,
            model_id="hcx-model",
            prompt_version="prompt-v1",
        )
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
    with pytest.raises(ArtifactValidationError, match="ARTIFACT_PAYLOAD_INVALID"):
        await repository.append(
            "intent_resolution",
            query_plan,
            model_id="hcx-model",
            prompt_version="intent-resolver-ko-v1",
        )

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
async def test_identical_intent_payload_with_different_provenance_conflicts(
    migrated_database_url: str,
    artifact_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import (
        ArtifactConflict,
        RequestArtifactRepository,
    )

    context = _artifact_context(migrated_database_url)
    repository = RequestArtifactRepository(artifact_engine)
    resolution = _artifact("intent_resolution", context)
    await repository.append(
        "intent_resolution",
        resolution,
        model_id="synthetic-model-a",
        prompt_version="intent-resolver-ko-v1",
    )

    with pytest.raises(ArtifactConflict, match="ARTIFACT_CONFLICT"):
        await repository.append(
            "intent_resolution",
            resolution,
            model_id="synthetic-model-b",
            prompt_version="intent-resolver-ko-v1",
        )


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


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "with_colliding_calculations",
    (False, True),
    ids=("no-collision", "same-id-collision"),
)
async def test_verification_report_normalizes_only_calculation_typed_targets(
    migrated_database_url: str,
    artifact_engine: AsyncEngine,
    with_colliding_calculations: bool,
) -> None:
    from financial_agent.db.repositories.artifacts import RequestArtifactRepository

    context = _artifact_context(migrated_database_url)
    repository = RequestArtifactRepository(artifact_engine)
    await repository.append(
        "query_plan",
        _artifact("query_plan", context, empty_references=False),
    )
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        _seed_references(connection, context)
        if with_colliding_calculations:
            _seed_colliding_calculations(connection, context)

    checks = (
        CheckResult(
            check_id="check-calculation-target",
            target_type=CheckTargetType.CALCULATION,
            target_id="calculation-rank-1",
            rule_id="rule-target-type",
            rule_version="v1",
            status=CheckStatus.PASS,
            reason_code="calculation-checked",
            related_evidence_ids=("evidence-aum-1",),
            repairability=Repairability.NONE,
        ),
        CheckResult(
            check_id="check-evidence-target",
            target_type=CheckTargetType.EVIDENCE,
            target_id="evidence-syn-etf-a",
            rule_id="rule-target-type",
            rule_version="v1",
            status=CheckStatus.PASS,
            reason_code="evidence-checked",
            repairability=Repairability.NONE,
        ),
        CheckResult(
            check_id="check-claim-target",
            target_type=CheckTargetType.CLAIM,
            target_id="claim-rank-1",
            rule_id="rule-target-type",
            rule_version="v1",
            status=CheckStatus.PASS,
            reason_code="claim-checked",
            repairability=Repairability.NONE,
        ),
        CheckResult(
            check_id="check-subtask-target",
            target_type=CheckTargetType.SUBTASK,
            target_id="q2",
            rule_id="rule-target-type",
            rule_version="v1",
            status=CheckStatus.PASS,
            reason_code="subtask-checked",
            repairability=Repairability.NONE,
        ),
    )
    report = _artifact(
        "verification_report", context, empty_references=False
    ).model_copy(update={"calculation_checks": checks})
    artifact_record_id = await repository.append("verification_report", report)

    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        calculation_rows = connection.execute(
            """
            SELECT calculation_id, reference_role, ordinal
            FROM operations.artifact_calculation_ref
            WHERE artifact_record_id = %s
            ORDER BY ordinal
            """,
            (artifact_record_id,),
        ).fetchall()
        evidence_rows = connection.execute(
            """
            SELECT evidence_id, reference_role, ordinal
            FROM operations.artifact_evidence_ref
            WHERE artifact_record_id = %s
            ORDER BY reference_role, ordinal
            """,
            (artifact_record_id,),
        ).fetchall()
        claim_rows = connection.execute(
            """
            SELECT claim_id, reference_role, ordinal
            FROM operations.artifact_claim_ref
            WHERE artifact_record_id = %s
            ORDER BY reference_role, ordinal
            """,
            (artifact_record_id,),
        ).fetchall()

    assert calculation_rows == [("calculation-rank-1", "checked", 0)]
    assert evidence_rows == [
        ("evidence-aum-1", "calculation_check", 0),
        ("evidence-aum-1", "claim_check", 0),
    ]
    assert claim_rows == [("claim-rank-1", "releaseable", 0)]
