"""Persistence boundary for Claim-Gate-authorized released-answer cache rows."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts import (
    ReleasedAnswer,
    canonical_json_bytes,
    canonical_sha256,
)


class VerifiedReleaseCacheError(RuntimeError):
    pass


class VerifiedReleaseCacheConflict(VerifiedReleaseCacheError):
    pass


class VerifiedReleaseCacheRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def cache(
        self,
        *,
        run_id: str,
        verification_artifact_id: UUID,
        answer_plan_artifact_id: UUID,
        released_answer_artifact_id: UUID,
        released_answer: ReleasedAnswer,
    ) -> UUID:
        validated = ReleasedAnswer.model_validate_json(
            canonical_json_bytes(released_answer)
        )
        if validated.run_id != run_id or validated.response_hash != canonical_sha256(
            validated, exclude_fields=("response_hash",)
        ):
            raise VerifiedReleaseCacheError("RELEASED_ANSWER_INVALID")
        try:
            async with self._engine.begin() as connection:
                stored_payload = (
                    await connection.execute(
                        sa.text(
                            """
                            SELECT canonical_payload
                            FROM operations.request_artifact
                            WHERE run_id = :run_id
                              AND artifact_record_id = :released_answer_artifact_id
                              AND artifact_type = 'released_answer'
                            """
                        ),
                        {
                            "run_id": run_id,
                            "released_answer_artifact_id": (
                                released_answer_artifact_id
                            ),
                        },
                    )
                ).scalar_one_or_none()
                if stored_payload != canonical_json_bytes(validated).decode("utf-8"):
                    raise VerifiedReleaseCacheError(
                        "RELEASED_ANSWER_ARTIFACT_MISMATCH"
                    )
                stored = (
                    await connection.execute(
                        sa.text(
                            """
                            SELECT operations.cache_verified_release(
                                :run_id,
                                :verification_artifact_id,
                                :answer_plan_artifact_id,
                                :released_answer_artifact_id
                            )
                            """
                        ),
                        {
                            "run_id": run_id,
                            "verification_artifact_id": verification_artifact_id,
                            "answer_plan_artifact_id": answer_plan_artifact_id,
                            "released_answer_artifact_id": released_answer_artifact_id,
                        },
                    )
                ).scalar_one()
        except DBAPIError as error:
            reason = getattr(getattr(error.orig, "diag", None), "message_primary", "")
            if reason == "VERIFIED_RELEASE_CACHE_CONFLICT":
                raise VerifiedReleaseCacheConflict(reason) from error
            raise VerifiedReleaseCacheError(
                reason or "VERIFIED_RELEASE_CACHE_ERROR"
            ) from error
        return UUID(str(stored))

    async def get(
        self,
        *,
        request_key: str,
        dataset_version: str,
        schema_version: str,
    ) -> ReleasedAnswer | None:
        try:
            async with self._engine.connect() as connection:
                payload = (
                    await connection.execute(
                        sa.text(
                            """
                            SELECT operations.get_cached_release(
                                :request_key, :dataset_version, :schema_version
                            )
                            """
                        ),
                        {
                            "request_key": request_key,
                            "dataset_version": dataset_version,
                            "schema_version": schema_version,
                        },
                    )
                ).scalar_one_or_none()
        except DBAPIError as error:
            raise VerifiedReleaseCacheError("VERIFIED_RELEASE_CACHE_ERROR") from error
        if payload is None:
            return None
        try:
            released = ReleasedAnswer.model_validate_json(payload)
        except ValueError as error:
            raise VerifiedReleaseCacheError("CACHED_RELEASE_INVALID") from error
        if released.response_hash != canonical_sha256(
            released, exclude_fields=("response_hash",)
        ):
            raise VerifiedReleaseCacheError("CACHED_RELEASE_INVALID")
        return released


__all__ = [
    "VerifiedReleaseCacheConflict",
    "VerifiedReleaseCacheError",
    "VerifiedReleaseCacheRepository",
]
