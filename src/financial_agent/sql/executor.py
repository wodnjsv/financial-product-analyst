"""Read-only execution boundary for compiler-owned semantic SQL."""

from __future__ import annotations

import re
from typing import Protocol

import sqlalchemy as sa

from financial_agent.contracts.canonical import canonical_json_bytes
from financial_agent.contracts.values import decode_contract_value
from financial_agent.planning.logical_query import LogicalQueryPlanV2
from financial_agent.planning.physical_bindings import PhysicalReadinessFacts

from .compiler import SemanticSqlCompiler
from .contracts import CompiledSqlRequest
from .result_mapping import MAX_RETURNED_ROWS, MappedSqlResult, map_sql_rows


_READ_ONLY = re.compile(r"^(?:SELECT|WITH)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|UPSERT|CREATE|ALTER|DROP|TRUNCATE|INTO|"
    r"GRANT|REVOKE|COPY|CALL|DO|VACUUM|ANALYZE|REFRESH|LOCK)\b|"
    r"\bFOR\s+(?:UPDATE|SHARE|NO\s+KEY\s+UPDATE|KEY\s+SHARE)\b",
    re.IGNORECASE,
)
_MAX_TIMEOUT_MS = 55_000


class SqlExecutionError(RuntimeError):
    """Stable, non-provider-specific failure at the SQL execution boundary."""


class _AsyncEngine(Protocol):
    def connect(self): ...


class ReadOnlySqlRunner:
    def __init__(
        self,
        engine: _AsyncEngine,
        compiler: SemanticSqlCompiler,
        *,
        default_timeout_ms: int = _MAX_TIMEOUT_MS,
        max_rows: int = MAX_RETURNED_ROWS,
    ) -> None:
        self._engine = engine
        self._compiler = compiler
        self._default_timeout_ms = _validate_timeout(default_timeout_ms)
        if (
            isinstance(max_rows, bool)
            or not isinstance(max_rows, int)
            or not 1 <= max_rows <= MAX_RETURNED_ROWS
        ):
            raise SqlExecutionError("SQL_RESULT_ROW_LIMIT_OUT_OF_RANGE")
        self._max_rows = max_rows

    async def execute(
        self,
        request: CompiledSqlRequest,
        logical_plan: LogicalQueryPlanV2,
        *,
        readiness_facts: PhysicalReadinessFacts | None = None,
        timeout_ms: int | None = None,
    ) -> MappedSqlResult:
        effective_timeout = _validate_timeout(
            self._default_timeout_ms if timeout_ms is None else timeout_ms
        )
        _assert_read_only(request.statement)
        request_before = canonical_json_bytes(request)
        try:
            self._compiler.validate_request_for_execution(
                request,
                logical_plan,
                readiness_facts=readiness_facts,
            )
        except (ValueError, TypeError) as error:
            raise SqlExecutionError("EXECUTION_REQUEST_REJECTED") from error

        parameters = {
            item.name: decode_contract_value(item.value) for item in request.parameters
        }
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                    await connection.execute(
                        sa.text(
                            "SELECT set_config('statement_timeout', "
                            ":statement_timeout, true)"
                        ),
                        {"statement_timeout": f"{effective_timeout}ms"},
                    )
                    raw_result = await connection.execute(
                        sa.text(request.statement), parameters
                    )
                    rows = raw_result.mappings().fetchmany(self._max_rows + 1)
        except Exception as error:
            raise SqlExecutionError("SQL_EXECUTION_FAILED") from error

        if len(rows) > self._max_rows:
            raise SqlExecutionError("SQL_RESULT_ROW_LIMIT_EXCEEDED")
        if canonical_json_bytes(request) != request_before:
            raise SqlExecutionError("COMPILED_REQUEST_MUTATED")
        return map_sql_rows(request, rows)


def _assert_read_only(statement: str) -> None:
    stripped = statement.strip()
    if (
        not _READ_ONLY.match(stripped)
        or ";" in stripped
        or "--" in stripped
        or "/*" in stripped
        or "*/" in stripped
    ):
        raise SqlExecutionError("SQL_READ_ONLY_STATEMENT_REQUIRED")
    if _FORBIDDEN.search(stripped):
        raise SqlExecutionError("SQL_READ_ONLY_STATEMENT_REQUIRED")


def _validate_timeout(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= _MAX_TIMEOUT_MS
    ):
        raise SqlExecutionError("SQL_TIMEOUT_OUT_OF_RANGE")
    return value
