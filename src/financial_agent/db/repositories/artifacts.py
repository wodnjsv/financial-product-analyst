from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts import (
    AnswerPlan,
    EvidenceBundle,
    ExecutionGraph,
    LogicalQueryPlanV2,
    QueryPlan,
    ResolvedQueryContractSetV2,
    ReleasedAnswer,
    RequestContext,
    RuntimeArtifact,
    ToolResult,
    VerificationReport,
    canonical_json_bytes,
)
from financial_agent.db.schema.operations import request_artifact
from financial_agent.intent.resolution import (
    ValidatedIntentResolution,
    ValidatedIntentResolutionV2,
    ValidatedIntentResolutionV3,
)

from .operations import raise_request_run_error


ArtifactType = Literal[
    "request_context",
    "intent_resolution",
    "query_plan",
    "query_contract",
    "logical_query_plan",
    "execution_graph",
    "tool_result",
    "evidence_bundle",
    "verification_report",
    "answer_plan",
    "released_answer",
]


ARTIFACT_MODELS: Mapping[ArtifactType, type[RuntimeArtifact]] = {
    "request_context": RequestContext,
    "intent_resolution": ValidatedIntentResolution,
    "query_plan": QueryPlan,
    "query_contract": ResolvedQueryContractSetV2,
    "logical_query_plan": LogicalQueryPlanV2,
    "execution_graph": ExecutionGraph,
    "tool_result": ToolResult,
    "evidence_bundle": EvidenceBundle,
    "verification_report": VerificationReport,
    "answer_plan": AnswerPlan,
    "released_answer": ReleasedAnswer,
}


class ArtifactPersistenceError(RuntimeError):
    code = "ARTIFACT_PERSISTENCE_ERROR"

    def __init__(self, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(self.code)


class ArtifactValidationError(ArtifactPersistenceError):
    code = "ARTIFACT_PAYLOAD_INVALID"


class ArtifactConflict(ArtifactPersistenceError):
    code = "ARTIFACT_CONFLICT"


class ArtifactNotFound(ArtifactPersistenceError, LookupError):
    code = "ARTIFACT_NOT_FOUND"


def _database_reason(error: DBAPIError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "message_primary", None)


def _validate_model_metadata(
    artifact_type: ArtifactType,
    model_id: str | None,
    prompt_version: str | None,
) -> None:
    if (model_id is None) != (prompt_version is None):
        raise ArtifactValidationError("MODEL_METADATA_PAIR_REQUIRED")
    if model_id is not None and prompt_version is not None:
        if not model_id.strip() or not prompt_version.strip():
            raise ArtifactValidationError("MODEL_METADATA_BLANK")
    if artifact_type == "intent_resolution":
        if model_id is None:
            raise ArtifactValidationError("MODEL_METADATA_REQUIRED")
        return
    if artifact_type == "answer_plan":
        return
    if model_id is not None:
        raise ArtifactValidationError("MODEL_METADATA_FORBIDDEN")


def _artifact_model(
    artifact_type: ArtifactType, payload: str | bytes
) -> type[RuntimeArtifact]:
    if artifact_type != "intent_resolution":
        return ARTIFACT_MODELS[artifact_type]
    parsed_payload = json.loads(payload)
    if not isinstance(parsed_payload, Mapping):
        raise ValueError("INTENT_RESOLUTION_SCHEMA_VERSION_INVALID")
    manifest = parsed_payload.get("build_manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("INTENT_RESOLUTION_SCHEMA_VERSION_INVALID")
    resolver_schema_version = manifest.get("resolver_schema_version")
    if resolver_schema_version == "1.0":
        return ValidatedIntentResolution
    if resolver_schema_version == "2.0":
        return ValidatedIntentResolutionV2
    if resolver_schema_version == "3.0":
        return ValidatedIntentResolutionV3
    raise ValueError("INTENT_RESOLUTION_SCHEMA_VERSION_INVALID")


class RequestArtifactRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def start_run(self, context: RequestContext) -> str:
        try:
            validated = RequestContext.model_validate_json(
                canonical_json_bytes(context)
            )
        except (TypeError, ValidationError) as error:
            raise ArtifactValidationError("REQUEST_CONTEXT_INVALID") from error

        statement = sa.text(
            """
            SELECT (operations.start_request_run(
                :run_id,
                :request_key,
                :question_id,
                :question,
                :schema_version,
                :dataset_version,
                :cutoff_date,
                :created_at,
                :deadline_at
            )).run_id
            """
        )
        try:
            async with self._engine.begin() as connection:
                return str(
                    (
                        await connection.execute(
                            statement,
                            {
                                "run_id": validated.run_id,
                                "request_key": validated.request_key,
                                "question_id": validated.question_id,
                                "question": validated.question,
                                "schema_version": validated.schema_version,
                                "dataset_version": validated.dataset_version,
                                "cutoff_date": validated.cutoff_date,
                                "created_at": validated.created_at,
                                "deadline_at": validated.deadline_at,
                            },
                        )
                    ).scalar_one()
                )
        except DBAPIError as error:
            raise_request_run_error(error)

    async def append(
        self,
        artifact_type: ArtifactType,
        artifact: RuntimeArtifact,
        *,
        model_id: str | None = None,
        prompt_version: str | None = None,
    ) -> UUID:
        if artifact_type not in ARTIFACT_MODELS:
            raise ArtifactValidationError("ARTIFACT_TYPE_UNKNOWN")
        _validate_model_metadata(artifact_type, model_id, prompt_version)
        try:
            artifact_payload = canonical_json_bytes(artifact)
            model = _artifact_model(artifact_type, artifact_payload)
            validated = model.model_validate_json(artifact_payload)
            validated.model_dump(mode="json")
            canonical_payload = canonical_json_bytes(validated).decode("utf-8")
        except (TypeError, UnicodeError, ValueError) as error:
            raise ArtifactValidationError() from error

        statement = sa.text(
            """
            SELECT operations.append_request_artifact(
                :artifact_type,
                :model_id,
                :prompt_version,
                :canonical_payload
            )
            """
        )
        try:
            async with self._engine.begin() as connection:
                artifact_record_id = (
                    await connection.execute(
                        statement,
                        {
                            "artifact_type": artifact_type,
                            "model_id": model_id,
                            "prompt_version": prompt_version,
                            "canonical_payload": canonical_payload,
                        },
                    )
                ).scalar_one()
        except DBAPIError as error:
            if _database_reason(error) == ArtifactConflict.code:
                raise ArtifactConflict() from error
            raise ArtifactPersistenceError() from error
        return UUID(str(artifact_record_id))

    async def get(
        self, run_id: str, artifact_record_id: UUID
    ) -> RuntimeArtifact:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.select(
                        request_artifact.c.artifact_type,
                        request_artifact.c.canonical_payload,
                    ).where(
                        request_artifact.c.run_id == run_id,
                        request_artifact.c.artifact_record_id
                        == artifact_record_id,
                    )
                )
            ).one_or_none()
        if row is None:
            raise ArtifactNotFound()
        try:
            model = _artifact_model(row.artifact_type, row.canonical_payload)
            return model.model_validate_json(row.canonical_payload)
        except (TypeError, ValueError) as error:
            raise ArtifactPersistenceError("ARTIFACT_RESTORE_INVALID") from error
