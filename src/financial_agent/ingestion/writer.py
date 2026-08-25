from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from financial_agent.db.schema.catalog import (
    alias,
    entity,
    identifier,
    institution,
    product,
    security,
)
from financial_agent.db.schema.evidence import (
    evidence_observation_origin,
    evidence_record,
    evidence_relation_origin,
    source_record,
)
from financial_agent.db.schema.observation import (
    metric_definition,
    observation_record,
)
from financial_agent.db.schema.operations import dataset_version
from financial_agent.db.schema.relation import relation_record
from financial_agent.ingestion.models import MappedRow


_CUTOFF_DATE = date(2026, 8, 24)
_SQL_CHUNK_SIZE = 500
_WRITE_TABLES = (
    entity,
    product,
    security,
    institution,
    source_record,
    metric_definition,
    identifier,
    alias,
    relation_record,
    observation_record,
    evidence_record,
    evidence_observation_origin,
    evidence_relation_origin,
)
_TABLES_BY_NAME = {table.fullname: table for table in _WRITE_TABLES}


class DatasetBuildConflict(RuntimeError):
    code = "BUILD_PAYLOAD_CONFLICT"

    def __init__(self, table_name: str) -> None:
        super().__init__(f"{self.code}: {table_name}")


class DatasetBuildRoleError(PermissionError):
    code = "BUILD_ROLE_MISMATCH"

    def __init__(self) -> None:
        super().__init__(self.code)


class DatasetBuildStateError(RuntimeError):
    code = "BUILD_DATASET_NOT_BUILDING"

    def __init__(self) -> None:
        super().__init__(self.code)


class DatasetBuildPayloadError(ValueError):
    code = "BUILD_PAYLOAD_INVALID"

    def __init__(self, table_name: str) -> None:
        super().__init__(f"{self.code}: {table_name}")


class DatasetBuildWriteError(RuntimeError):
    code = "BUILD_WRITE_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


def _chunks[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _primary_key(table: sa.Table, record: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(record[column.name] for column in table.primary_key.columns)


def _persisted_payload(
    table: sa.Table,
    record: Mapping[str, object],
) -> dict[str, object]:
    return {
        column.name: record[column.name]
        for column in table.columns
        if column.name != "created_at"
    }


def _identity_filter(
    table: sa.Table,
    identities: Sequence[tuple[object, ...]],
) -> sa.ColumnElement[bool]:
    primary_columns = tuple(table.primary_key.columns)
    if len(primary_columns) == 1:
        return primary_columns[0].in_([identity[0] for identity in identities])
    return sa.tuple_(*primary_columns).in_(identities)


class DatasetBuildWriter:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create_building_dataset(
        self,
        dataset_version_value: str,
        manifest_hash: str,
        cutoff_date: date,
    ) -> None:
        if (
            not dataset_version_value.strip()
            or cutoff_date != _CUTOFF_DATE
            or len(manifest_hash) != 64
            or any(character not in "0123456789abcdef" for character in manifest_hash)
        ):
            raise DatasetBuildPayloadError("operations.dataset_version")

        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await self._require_build_role(connection)
                    await self._lock_dataset_key(connection, dataset_version_value)
                    await connection.execute(
                        postgresql.insert(dataset_version)
                        .values(
                            dataset_version=dataset_version_value,
                            cutoff_date=cutoff_date,
                            manifest_hash=manifest_hash,
                            previous_dataset_version=None,
                            created_at=datetime.now(UTC),
                        )
                        .on_conflict_do_nothing()
                    )
                    existing = (
                        await connection.execute(
                            sa.select(dataset_version)
                            .where(
                                dataset_version.c.dataset_version
                                == dataset_version_value
                            )
                        )
                    ).mappings().one_or_none()
                    if existing is None:
                        raise DatasetBuildConflict("operations.dataset_version")
                    if existing["status"] != "building":
                        raise DatasetBuildStateError()
                    if (
                        existing["cutoff_date"] != cutoff_date
                        or existing["manifest_hash"] != manifest_hash
                        or existing["previous_dataset_version"] is not None
                    ):
                        raise DatasetBuildConflict("operations.dataset_version")
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise DatasetBuildConflict("operations.dataset_version") from None
            raise DatasetBuildWriteError() from None

    async def write_rows(
        self,
        dataset_version_value: str,
        rows: Sequence[MappedRow],
    ) -> None:
        prepared = self._prepare_records(dataset_version_value, rows)
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await self._require_build_role(connection)
                    await self._lock_building_dataset(
                        connection, dataset_version_value
                    )
                    for table in _WRITE_TABLES:
                        records = prepared[table.fullname]
                        for record_chunk in _chunks(records, _SQL_CHUNK_SIZE):
                            await self._write_exact_records(
                                connection,
                                table,
                                record_chunk,
                            )
                    await connection.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise DatasetBuildConflict("database_unique_constraint") from None
            raise DatasetBuildWriteError() from None

    async def table_counts(
        self,
        dataset_version_value: str,
    ) -> Mapping[str, int]:
        async with self._engine.connect() as connection:
            async with connection.begin():
                await self._require_build_role(connection)
                await self._lock_building_dataset(
                    connection, dataset_version_value, for_update=False
                )
                counts: dict[str, int] = {}
                for table in _WRITE_TABLES:
                    if table is metric_definition:
                        referenced_metrics = (
                            sa.select(
                                observation_record.c.metric_id,
                                observation_record.c.metric_definition_version,
                            )
                            .where(
                                observation_record.c.dataset_version
                                == dataset_version_value
                            )
                            .distinct()
                            .subquery()
                        )
                        statement = sa.select(sa.func.count()).select_from(
                            referenced_metrics
                        )
                    else:
                        statement = sa.select(sa.func.count()).select_from(table).where(
                            table.c.dataset_version == dataset_version_value
                        )
                    counts[table.fullname] = int(
                        (await connection.scalar(statement)) or 0
                    )
        return counts

    def _prepare_records(
        self,
        dataset_version_value: str,
        rows: Sequence[MappedRow],
    ) -> dict[str, tuple[dict[str, object], ...]]:
        collected: dict[str, dict[tuple[object, ...], dict[str, object]]] = {
            table.fullname: {} for table in _WRITE_TABLES
        }
        created_at = datetime.now(UTC)
        for row in rows:
            for table_name, records in row.records_by_table.items():
                table = _TABLES_BY_NAME.get(table_name)
                if table is None:
                    raise DatasetBuildPayloadError(table_name)
                expected_columns = {
                    column.name
                    for column in table.columns
                    if column.name not in {"dataset_version", "created_at"}
                }
                for raw_record in records:
                    if set(raw_record) != expected_columns:
                        raise DatasetBuildPayloadError(table_name)
                    record = dict(raw_record)
                    if "dataset_version" in table.c:
                        record["dataset_version"] = dataset_version_value
                    if "created_at" in table.c:
                        record["created_at"] = created_at
                    identity = _primary_key(table, record)
                    existing = collected[table_name].get(identity)
                    if existing is not None and _persisted_payload(
                        table, existing
                    ) != _persisted_payload(table, record):
                        raise DatasetBuildConflict(table_name)
                    collected[table_name][identity] = record
        return {
            table_name: tuple(records.values())
            for table_name, records in collected.items()
        }

    async def _write_exact_records(
        self,
        connection: AsyncConnection,
        table: sa.Table,
        records: Sequence[dict[str, object]],
    ) -> None:
        if not records:
            return
        await connection.execute(
            postgresql.insert(table).values(list(records)).on_conflict_do_nothing()
        )
        identities = [_primary_key(table, record) for record in records]
        stored_rows = (
            await connection.execute(
                sa.select(table).where(_identity_filter(table, identities))
            )
        ).mappings()
        stored_by_identity = {
            _primary_key(table, stored): stored for stored in stored_rows
        }
        for record in records:
            identity = _primary_key(table, record)
            stored = stored_by_identity.get(identity)
            if stored is None or _persisted_payload(
                table, stored
            ) != _persisted_payload(table, record):
                raise DatasetBuildConflict(table.fullname)

    async def _require_build_role(self, connection: AsyncConnection) -> None:
        current_user = await connection.scalar(sa.text("SELECT current_user"))
        if current_user != "fa_build":
            raise DatasetBuildRoleError()

    async def _lock_building_dataset(
        self,
        connection: AsyncConnection,
        dataset_version_value: str,
        *,
        for_update: bool = True,
    ) -> None:
        if for_update:
            await self._lock_dataset_key(connection, dataset_version_value)
        statement = sa.select(dataset_version.c.status).where(
            dataset_version.c.dataset_version == dataset_version_value
        )
        status = await connection.scalar(statement)
        if status != "building":
            raise DatasetBuildStateError()

    async def _lock_dataset_key(
        self,
        connection: AsyncConnection,
        dataset_version_value: str,
    ) -> None:
        await connection.execute(
            sa.text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(CAST(:dataset_version AS text), 0))"
            ),
            {"dataset_version": dataset_version_value},
        )
