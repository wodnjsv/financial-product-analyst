from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.db.test_evidence_repository import (
    evidence_record,
    prepare_repository_context,
    repository_api,
    source_record,
)


async def _dispose_engines(*engines: AsyncEngine) -> None:
    await asyncio.gather(*(engine.dispose() for engine in engines))


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_concurrent_identical_source_appends_converge_across_connections(
    migrated_database_url: str,
) -> None:
    api = repository_api()
    context = prepare_repository_context(migrated_database_url)
    first_engine = create_async_engine(
        migrated_database_url, pool_size=1, max_overflow=0
    )
    second_engine = create_async_engine(
        migrated_database_url, pool_size=1, max_overflow=0
    )
    first = api.EvidenceLedgerRepository(first_engine)
    second = api.EvidenceLedgerRepository(second_engine)
    source = source_record(context)
    try:
        results = await asyncio.gather(
            first.append_source(context.dataset_version, source),
            second.append_source(context.dataset_version, source),
            return_exceptions=True,
        )

        assert results == [None, None]
        async with first_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*), min(source_title)
                        FROM evidence.source_record
                        WHERE dataset_version = :dataset_version
                          AND source_id = :source_id
                        """
                    ),
                    {
                        "dataset_version": context.dataset_version,
                        "source_id": source.source_id,
                    },
                )
            ).one()
        assert row == (1, source.source_title)
    finally:
        await _dispose_engines(first_engine, second_engine)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_concurrent_conflicting_source_appends_keep_one_payload(
    migrated_database_url: str,
) -> None:
    api = repository_api()
    context = prepare_repository_context(migrated_database_url)
    first_engine = create_async_engine(
        migrated_database_url, pool_size=1, max_overflow=0
    )
    second_engine = create_async_engine(
        migrated_database_url, pool_size=1, max_overflow=0
    )
    first = api.EvidenceLedgerRepository(first_engine)
    second = api.EvidenceLedgerRepository(second_engine)
    original = source_record(context)
    changed = original.model_copy(update={"source_title": "Changed synthetic source"})
    try:
        results = await asyncio.gather(
            first.append_source(context.dataset_version, original),
            second.append_source(context.dataset_version, changed),
            return_exceptions=True,
        )

        assert sum(result is None for result in results) == 1
        conflicts = [
            result
            for result in results
            if isinstance(result, api.EvidenceLedgerConflict)
        ]
        assert len(conflicts) == 1
        assert conflicts[0].code == "EVIDENCE_LEDGER_CONFLICT"
        async with first_engine.connect() as connection:
            titles = (
                await connection.execute(
                    text(
                        """
                        SELECT source_title FROM evidence.source_record
                        WHERE dataset_version = :dataset_version
                          AND source_id = :source_id
                        """
                    ),
                    {
                        "dataset_version": context.dataset_version,
                        "source_id": original.source_id,
                    },
                )
            ).scalars().all()
        assert titles in ([original.source_title], [changed.source_title])
    finally:
        await _dispose_engines(first_engine, second_engine)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_concurrent_evidence_retries_use_independent_committed_transactions(
    migrated_database_url: str,
) -> None:
    api = repository_api()
    context = prepare_repository_context(migrated_database_url)
    first_engine = create_async_engine(
        migrated_database_url, pool_size=1, max_overflow=0
    )
    second_engine = create_async_engine(
        migrated_database_url, pool_size=1, max_overflow=0
    )
    first = api.EvidenceLedgerRepository(first_engine)
    second = api.EvidenceLedgerRepository(second_engine)
    source = source_record(context)
    identical = evidence_record(context, "evidence-concurrent")
    conflict_original = evidence_record(
        context, "evidence-conflict", record_hash="e" * 64
    )
    conflict_changed = conflict_original.model_copy(
        update={"record_hash": "f" * 64}
    )
    try:
        await first.append_source(context.dataset_version, source)
        identical_results = await asyncio.gather(
            first.append_evidence(identical),
            second.append_evidence(identical),
            return_exceptions=True,
        )
        assert identical_results == [None, None]
        assert await asyncio.gather(
            first.get_evidence(context.dataset_version, identical.evidence_id),
            second.get_evidence(context.dataset_version, identical.evidence_id),
        ) == [identical, identical]

        conflict_results = await asyncio.gather(
            first.append_evidence(conflict_original),
            second.append_evidence(conflict_changed),
            return_exceptions=True,
        )
        assert sum(result is None for result in conflict_results) == 1
        conflicts = [
            result
            for result in conflict_results
            if isinstance(result, api.EvidenceLedgerConflict)
        ]
        assert len(conflicts) == 1
        assert conflicts[0].code == "EVIDENCE_LEDGER_CONFLICT"
        async with first_engine.connect() as connection:
            hashes = (
                await connection.execute(
                    text(
                        """
                        SELECT record_hash FROM evidence.evidence_record
                        WHERE dataset_version = :dataset_version
                          AND evidence_id = :evidence_id
                        """
                    ),
                    {
                        "dataset_version": context.dataset_version,
                        "evidence_id": conflict_original.evidence_id,
                    },
                )
            ).scalars().all()
        assert hashes in (
            [conflict_original.record_hash],
            [conflict_changed.record_hash],
        )
    finally:
        await _dispose_engines(first_engine, second_engine)
