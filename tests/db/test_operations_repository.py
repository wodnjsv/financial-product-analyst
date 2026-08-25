from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from financial_agent.contracts import (
    AnswerDisposition,
    ExecutionGraph,
    ExecutionOutcome,
    RequestContext,
    VerificationReport,
    VerificationStatus,
    build_request_key,
)
from financial_agent.db.preflight import normalize_psycopg_url
from tests.db.test_foundation_migration import (
    finish_and_ready_dataset,
    insert_dataset_validation,
)


CREATED_AT = datetime(2026, 8, 17, tzinfo=UTC)


def _activate_dataset(database_url: str, dataset_version: str) -> None:
    validation_run_id = f"validation-{dataset_version}"
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        insert_dataset_validation(
            connection,
            dataset_version=dataset_version,
            validation_run_id=validation_run_id,
        )
        finish_and_ready_dataset(
            connection,
            dataset_version=dataset_version,
            validation_run_id=validation_run_id,
        )
        connection.execute(
            "SELECT operations.activate_dataset(%s)", (dataset_version,)
        )


def _active_dataset(database_url: str) -> str:
    dataset_version = f"run-{uuid4().hex}"
    _activate_dataset(database_url, dataset_version)
    return dataset_version


def _request_context(
    dataset_version: str,
    *,
    run_id: str | None = None,
    question_id: str | None = None,
    question: str = "Synthetic request lifecycle question",
) -> RequestContext:
    run_id = run_id or f"run-{uuid4().hex}"
    question_id = question_id or f"Q-{uuid4().hex}"
    return RequestContext.model_validate_json(
        json.dumps(
            {
                "schema_version": "1.0",
                "request_key": build_request_key(
                    question_id, question, dataset_version, "1.0"
                ),
                "run_id": run_id,
                "dataset_version": dataset_version,
                "cutoff_date": "2026-08-24",
                "producer": "request-normalizer",
                "created_at": CREATED_AT.isoformat().replace("+00:00", "Z"),
                "question_id": question_id,
                "question": question,
                "segments": [
                    {
                        "segment_id": "s1",
                        "ordinal": 0,
                        "text": question,
                    }
                ],
                "deadline_at": (CREATED_AT + timedelta(seconds=55))
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    )


def _verification_report(
    context: RequestContext,
    *,
    report_id: str | None = None,
    disposition: AnswerDisposition = AnswerDisposition.ANSWER,
) -> VerificationReport:
    return VerificationReport(
        request_key=context.request_key,
        run_id=context.run_id,
        dataset_version=context.dataset_version,
        producer="verifier",
        created_at=context.created_at + timedelta(seconds=10),
        verification_report_id=report_id or f"verification-{uuid4().hex}",
        verification_status=VerificationStatus.PASS,
        recommended_answer_disposition=disposition,
        claim_checks=(),
        calculation_checks=(),
        subtask_coverage=(),
        releaseable_claim_ids=(),
    )


def _execution_graph(context: RequestContext) -> ExecutionGraph:
    return ExecutionGraph(
        request_key=context.request_key,
        run_id=context.run_id,
        dataset_version=context.dataset_version,
        producer="orchestrator",
        created_at=context.created_at + timedelta(seconds=1),
        graph_id=f"graph-{uuid4().hex}",
        tasks=(),
        critical_path=(),
        total_budget_ms=0,
    )


@pytest_asyncio.fixture
async def operations_engine(migrated_database_url: str) -> AsyncEngine:
    engine = create_async_engine(migrated_database_url, pool_size=5, max_overflow=0)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_start_run_accepts_exact_55_seconds_and_keeps_captured_dataset(
    migrated_database_url: str,
    operations_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import RequestArtifactRepository

    first_dataset = _active_dataset(migrated_database_url)
    context = _request_context(first_dataset)
    repository = RequestArtifactRepository(operations_engine)
    assert await repository.start_run(context) == context.run_id

    second_dataset = f"run-switch-{uuid4().hex}"
    _activate_dataset(migrated_database_url, second_dataset)
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        stored = connection.execute(
            """
            SELECT dataset_version, cutoff_date, deadline_at - created_at
            FROM operations.request_run WHERE run_id = %s
            """,
            (context.run_id,),
        ).fetchone()
    assert stored == (first_dataset, context.cutoff_date, timedelta(seconds=55))


@pytest.mark.postgres
@pytest.mark.parametrize("deadline_offset", (56, 0, -1))
def test_start_run_rejects_deadlines_outside_the_strict_ordered_window(
    migrated_database_url: str,
    deadline_offset: int,
) -> None:
    dataset_version = _active_dataset(migrated_database_url)
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """
                SELECT operations.start_request_run(
                    %s, %s, 'Q-deadline', 'question', '1.0', %s,
                    DATE '2026-08-24', %s, %s
                )
                """,
                (
                    f"run-deadline-{uuid4().hex}",
                    "a" * 64,
                    dataset_version,
                    CREATED_AT,
                    CREATED_AT + timedelta(seconds=deadline_offset),
                ),
            )


@pytest.mark.postgres
def test_start_run_requires_the_current_dataset_and_matching_cutoff(
    migrated_database_url: str,
) -> None:
    active_dataset = _active_dataset(migrated_database_url)
    stale_dataset = f"stale-{uuid4().hex}"
    validation_run_id = f"validation-{stale_dataset}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_dataset_validation(
            connection,
            dataset_version=stale_dataset,
            validation_run_id=validation_run_id,
        )
        finish_and_ready_dataset(
            connection,
            dataset_version=stale_dataset,
            validation_run_id=validation_run_id,
        )
        statement = """
            SELECT operations.start_request_run(
                %s, %s, 'Q-dataset', 'question', '1.0', %s, %s, %s, %s
            )
        """
        for supplied_dataset, cutoff_date in (
            (stale_dataset, date(2026, 8, 24)),
            (active_dataset, date(2026, 8, 23)),
        ):
            with pytest.raises(
                psycopg.errors.ObjectNotInPrerequisiteState,
                match="ACTIVE_DATASET_MISMATCH",
            ):
                with connection.transaction():
                    connection.execute(
                        statement,
                        (
                            f"run-dataset-{uuid4().hex}",
                            "b" * 64,
                            supplied_dataset,
                            cutoff_date,
                            CREATED_AT,
                            CREATED_AT + timedelta(seconds=55),
                        ),
                    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_two_connections_converge_and_conflicting_run_reuse_is_stable(
    migrated_database_url: str,
) -> None:
    from financial_agent.db.repositories.artifacts import RequestArtifactRepository
    from financial_agent.db.repositories.operations import RequestRunConflict

    dataset_version = _active_dataset(migrated_database_url)
    context = _request_context(dataset_version)
    first_engine = create_async_engine(migrated_database_url, pool_size=1)
    second_engine = create_async_engine(migrated_database_url, pool_size=1)
    try:
        first_repo = RequestArtifactRepository(first_engine)
        second_repo = RequestArtifactRepository(second_engine)
        results = await asyncio.gather(
            first_repo.start_run(context), second_repo.start_run(context)
        )
        assert results == [context.run_id, context.run_id]

        conflict = _request_context(
            dataset_version,
            run_id=context.run_id,
            question_id=context.question_id,
            question="Different question",
        )
        with pytest.raises(RequestRunConflict, match="REQUEST_RUN_CONFLICT"):
            await first_repo.start_run(conflict)

        separate = context.model_copy(update={"run_id": f"run-{uuid4().hex}"})
        assert await first_repo.start_run(separate) == separate.run_id
        with psycopg.connect(
            normalize_psycopg_url(migrated_database_url)
        ) as connection:
            count = connection.execute(
                "SELECT count(*) FROM operations.request_run WHERE request_key = %s",
                (context.request_key,),
            ).fetchone()[0]
        assert count == 2
    finally:
        await first_engine.dispose()
        await second_engine.dispose()


@pytest.mark.postgres
def test_request_run_keeps_three_terminal_axes_and_no_raw_reasoning(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        columns = {
            str(name): str(nullable)
            for name, nullable in connection.execute(
                """
                SELECT column_name, is_nullable FROM information_schema.columns
                WHERE table_schema = 'operations' AND table_name = 'request_run'
                """
            ).fetchall()
        }
    assert columns["execution_outcome"] == "YES"
    assert columns["verification_status"] == "YES"
    assert columns["answer_disposition"] == "YES"
    assert columns["final_verification_artifact_id"] == "YES"
    assert "chain_of_thought" not in columns
    assert "raw_reasoning" not in columns


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_failure_events_append_every_attempt_without_overwrite(
    migrated_database_url: str,
    operations_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import RequestArtifactRepository
    from financial_agent.db.repositories.operations import (
        FailureEventRecord,
        RequestRunRepository,
    )

    dataset_version = _active_dataset(migrated_database_url)
    context = _request_context(dataset_version)
    await RequestArtifactRepository(operations_engine).start_run(context)
    repository = RequestRunRepository(operations_engine)
    for attempt, remaining_budget in ((1, 40_000), (2, 35_000)):
        await repository.append_failure_event(
            FailureEventRecord(
                event_id=f"event-{uuid4().hex}",
                run_id=context.run_id,
                task_id="task-one",
                stage="retrieval",
                code="UPSTREAM_TIMEOUT",
                category="transient",
                retryable=True,
                attempt=attempt,
                remaining_budget_ms=remaining_budget,
                duration_ms=1_000,
                dependency="official-api",
                occurred_at=context.created_at + timedelta(seconds=attempt),
            )
        )

    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        rows = connection.execute(
            """
            SELECT attempt, remaining_budget_ms FROM operations.failure_event
            WHERE run_id = %s ORDER BY attempt
            """,
            (context.run_id,),
        ).fetchall()
    assert rows == [(1, 40_000), (2, 35_000)]


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_semantic_finish_requires_matching_pass_report_and_is_one_way(
    migrated_database_url: str,
    operations_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import RequestArtifactRepository
    from financial_agent.db.repositories.operations import (
        RequestRunConflict,
        RequestRunRepository,
    )

    dataset_version = _active_dataset(migrated_database_url)
    context = _request_context(dataset_version)
    artifacts = RequestArtifactRepository(operations_engine)
    runs = RequestRunRepository(operations_engine)
    await artifacts.start_run(context)
    report = _verification_report(context)
    report_record_id = await artifacts.append("verification_report", report)

    finish_kwargs = {
        "execution_outcome": ExecutionOutcome.COMPLETED,
        "verification_status": VerificationStatus.PASS,
        "answer_disposition": AnswerDisposition.ANSWER,
        "http_status": 200,
        "final_verification_report_id": report.verification_report_id,
        "terminal_failure_code": None,
        "finished_at": context.created_at + timedelta(seconds=20),
    }
    await runs.finish_run(context.run_id, **finish_kwargs)
    await runs.finish_run(context.run_id, **finish_kwargs)
    with pytest.raises(RequestRunConflict, match="REQUEST_RUN_CONFLICT"):
        await runs.finish_run(
            context.run_id,
            **{**finish_kwargs, "answer_disposition": AnswerDisposition.PARTIAL},
        )

    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        row = connection.execute(
            """
            SELECT execution_outcome, verification_status, answer_disposition,
                   http_status, final_verification_artifact_id,
                   terminal_failure_code
            FROM operations.request_run WHERE run_id = %s
            """,
            (context.run_id,),
        ).fetchone()
    assert row == ("completed", "pass", "answer", 200, report_record_id, None)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_finish_rejects_wrong_artifact_type_or_report_semantics(
    migrated_database_url: str,
    operations_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import RequestArtifactRepository
    from financial_agent.db.repositories.operations import RequestRunInvalidState

    dataset_version = _active_dataset(migrated_database_url)
    artifacts = RequestArtifactRepository(operations_engine)

    wrong_type_context = _request_context(dataset_version)
    await artifacts.start_run(wrong_type_context)
    graph = _execution_graph(wrong_type_context)
    await artifacts.append("execution_graph", graph)
    from financial_agent.db.repositories.operations import RequestRunRepository

    runs = RequestRunRepository(operations_engine)
    with pytest.raises(
        RequestRunInvalidState, match="FINAL_VERIFICATION_ARTIFACT_INVALID"
    ):
        await runs.finish_run(
            wrong_type_context.run_id,
            execution_outcome=ExecutionOutcome.COMPLETED,
            verification_status=VerificationStatus.PASS,
            answer_disposition=AnswerDisposition.ANSWER,
            http_status=200,
            final_verification_report_id=graph.graph_id,
            terminal_failure_code=None,
            finished_at=wrong_type_context.created_at + timedelta(seconds=20),
        )

    other_run_context = _request_context(dataset_version)
    await artifacts.start_run(other_run_context)
    other_run_report = _verification_report(other_run_context)
    await artifacts.append("verification_report", other_run_report)
    with pytest.raises(
        RequestRunInvalidState, match="FINAL_VERIFICATION_ARTIFACT_INVALID"
    ):
        await runs.finish_run(
            wrong_type_context.run_id,
            execution_outcome=ExecutionOutcome.COMPLETED,
            verification_status=VerificationStatus.PASS,
            answer_disposition=AnswerDisposition.ANSWER,
            http_status=200,
            final_verification_report_id=(
                other_run_report.verification_report_id
            ),
            terminal_failure_code=None,
            finished_at=wrong_type_context.created_at + timedelta(seconds=20),
        )

    semantic_context = _request_context(dataset_version)
    await artifacts.start_run(semantic_context)
    report = _verification_report(
        semantic_context, disposition=AnswerDisposition.LIMITATION
    )
    await artifacts.append("verification_report", report)
    with pytest.raises(
        RequestRunInvalidState, match="FINAL_VERIFICATION_ARTIFACT_INVALID"
    ):
        await runs.finish_run(
            semantic_context.run_id,
            execution_outcome=ExecutionOutcome.COMPLETED,
            verification_status=VerificationStatus.PASS,
            answer_disposition=AnswerDisposition.ANSWER,
            http_status=200,
            final_verification_report_id=report.verification_report_id,
            terminal_failure_code=None,
            finished_at=semantic_context.created_at + timedelta(seconds=20),
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_5xx_finish_requires_failed_execution_and_no_semantic_result(
    migrated_database_url: str,
    operations_engine: AsyncEngine,
) -> None:
    from financial_agent.db.repositories.artifacts import RequestArtifactRepository
    from financial_agent.db.repositories.operations import (
        RequestRunInvalidState,
        RequestRunRepository,
    )

    dataset_version = _active_dataset(migrated_database_url)
    artifacts = RequestArtifactRepository(operations_engine)
    runs = RequestRunRepository(operations_engine)
    failed_context = _request_context(dataset_version)
    await artifacts.start_run(failed_context)
    await runs.finish_run(
        failed_context.run_id,
        execution_outcome=ExecutionOutcome.FAILED,
        verification_status=None,
        answer_disposition=None,
        http_status=503,
        final_verification_report_id=None,
        terminal_failure_code="UPSTREAM_UNAVAILABLE",
        finished_at=failed_context.created_at + timedelta(seconds=20),
    )

    invalid_context = _request_context(dataset_version)
    await artifacts.start_run(invalid_context)
    with pytest.raises(RequestRunInvalidState, match="INVALID_TERMINAL_STATE"):
        await runs.finish_run(
            invalid_context.run_id,
            execution_outcome=ExecutionOutcome.COMPLETED,
            verification_status=VerificationStatus.PASS,
            answer_disposition=AnswerDisposition.ANSWER,
            http_status=503,
            final_verification_report_id=None,
            terminal_failure_code="UPSTREAM_UNAVAILABLE",
            finished_at=invalid_context.created_at + timedelta(seconds=20),
        )
