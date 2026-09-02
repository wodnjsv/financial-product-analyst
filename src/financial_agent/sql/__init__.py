"""Deterministic semantic SQL compilation."""

from .contracts import (
    CompiledSqlRequest,
    PhysicalSqlRenderManifest,
    PhysicalLoweringKind,
    PhysicalLoweringRecord,
    SqlRenderTemplateId,
    SqlParameter,
    SqlValueKind,
    compiled_sql_request_id,
    physical_lowering_record_id,
    physical_sql_render_manifest_id,
    validate_compiled_request_ownership,
)
from .compiler import (
    SemanticSqlCompiler,
    SqlCompilationOutcome,
    SqlCompileRejectionRecord,
)
from .executor import ReadOnlySqlRunner, SqlExecutionError
from .result_mapping import MappedSqlResult, SqlResultMappingError, map_sql_rows

__all__ = [
    "CompiledSqlRequest",
    "MappedSqlResult",
    "PhysicalSqlRenderManifest",
    "ReadOnlySqlRunner",
    "PhysicalLoweringKind",
    "PhysicalLoweringRecord",
    "SqlRenderTemplateId",
    "SqlParameter",
    "SqlValueKind",
    "SemanticSqlCompiler",
    "SqlCompilationOutcome",
    "SqlCompileRejectionRecord",
    "SqlExecutionError",
    "SqlResultMappingError",
    "compiled_sql_request_id",
    "physical_lowering_record_id",
    "physical_sql_render_manifest_id",
    "map_sql_rows",
    "validate_compiled_request_ownership",
]
