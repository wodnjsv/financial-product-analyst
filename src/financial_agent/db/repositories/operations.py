from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal, NoReturn

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts import (
    AnswerDisposition,
    ExecutionOutcome,
    VerificationStatus,
)
from financial_agent.db.schema.operations import failure_event


FailureCategory = Literal[
    "transient",
    "deadline",
    "internal_invariant",
    "planner_contract",
    "answer_contract",
]


@dataclass(frozen=True, slots=True)
class FailureEventRecord:
    event_id: str
    run_id: str
    task_id: str | None
    stage: str
    code: str
    category: FailureCategory
    retryable: bool
    attempt: int
    remaining_budget_ms: int
    duration_ms: int
    dependency: str | None
    occurred_at: datetime


class RequestRunPersistenceError(RuntimeError):
    code = "REQUEST_RUN_PERSISTENCE_ERROR"

    def __init__(self, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(self.code)


class RequestRunConflict(RequestRunPersistenceError):
    code = "REQUEST_RUN_CONFLICT"


class RequestRunNotFound(RequestRunPersistenceError):
    code = "REQUEST_RUN_NOT_FOUND"


class RequestRunInvalidState(RequestRunPersistenceError):
    code = "INVALID_TERMINAL_STATE"


class FailureEventConflict(RequestRunPersistenceError):
    code = "FAILURE_EVENT_CONFLICT"


def _database_reason(error: DBAPIError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "message_primary", None)


def raise_request_run_error(error: DBAPIError) -> NoReturn:
    reason = _database_reason(error)
    if reason == RequestRunConflict.code:
        raise RequestRunConflict() from error
    if reason == RequestRunNotFound.code:
        raise RequestRunNotFound() from error
    if reason in {
        "ACTIVE_DATASET_MISMATCH",
        "INVALID_TERMINAL_STATE",
        "FINAL_VERIFICATION_ARTIFACT_INVALID",
    }:
        raise RequestRunInvalidState(reason) from error
    raise RequestRunPersistenceError() from error


class RequestRunRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append_failure_event(self, event: FailureEventRecord) -> None:
        try:
            async with self._engine.begin() as connection:
                await connection.execute(
                    sa.insert(failure_event).values(**asdict(event))
                )
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise FailureEventConflict() from error
            raise RequestRunPersistenceError() from error
        except DBAPIError as error:
            raise RequestRunPersistenceError() from error

    async def finish_run(
        self,
        run_id: str,
        *,
        execution_outcome: ExecutionOutcome,
        verification_status: VerificationStatus | None,
        answer_disposition: AnswerDisposition | None,
        http_status: int,
        final_verification_report_id: str | None,
        terminal_failure_code: str | None,
        finished_at: datetime,
    ) -> None:
        statement = sa.text(
            """
            SELECT operations.finish_request_run(
                :run_id,
                :execution_outcome,
                :verification_status,
                :answer_disposition,
                CAST(:http_status AS smallint),
                :final_verification_report_id,
                :terminal_failure_code,
                :finished_at
            )
            """
        )
        try:
            async with self._engine.begin() as connection:
                await connection.execute(
                    statement,
                    {
                        "run_id": run_id,
                        "execution_outcome": execution_outcome.value,
                        "verification_status": (
                            verification_status.value
                            if verification_status is not None
                            else None
                        ),
                        "answer_disposition": (
                            answer_disposition.value
                            if answer_disposition is not None
                            else None
                        ),
                        "http_status": http_status,
                        "final_verification_report_id": (
                            final_verification_report_id
                        ),
                        "terminal_failure_code": terminal_failure_code,
                        "finished_at": finished_at,
                    },
                )
        except DBAPIError as error:
            raise_request_run_error(error)
