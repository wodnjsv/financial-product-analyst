"""Deterministic semantic SQL with optional dependencies loaded lazily."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "CompiledSqlRequest": (".contracts", "CompiledSqlRequest"),
    "DeferredSqlParameter": (".contracts", "DeferredSqlParameter"),
    "PhysicalSqlRenderManifest": (".contracts", "PhysicalSqlRenderManifest"),
    "PhysicalLoweringKind": (".contracts", "PhysicalLoweringKind"),
    "PhysicalLoweringRecord": (".contracts", "PhysicalLoweringRecord"),
    "SqlRenderTemplateId": (".contracts", "SqlRenderTemplateId"),
    "SqlParameter": (".contracts", "SqlParameter"),
    "SqlValueKind": (".contracts", "SqlValueKind"),
    "compiled_sql_request_id": (".contracts", "compiled_sql_request_id"),
    "physical_lowering_record_id": (".contracts", "physical_lowering_record_id"),
    "physical_sql_render_manifest_id": (
        ".contracts",
        "physical_sql_render_manifest_id",
    ),
    "validate_compiled_request_ownership": (
        ".contracts",
        "validate_compiled_request_ownership",
    ),
    "SemanticSqlCompiler": (".compiler", "SemanticSqlCompiler"),
    "SemanticSqlRuntimeBinder": (".compiler", "SemanticSqlRuntimeBinder"),
    "SqlCompilationOutcome": (".compiler", "SqlCompilationOutcome"),
    "SqlCompileRejectionRecord": (".compiler", "SqlCompileRejectionRecord"),
    "ReadOnlySqlRunner": (".executor", "ReadOnlySqlRunner"),
    "SqlExecutionError": (".executor", "SqlExecutionError"),
    "MappedSqlResult": (".result_mapping", "MappedSqlResult"),
    "SqlResultMappingError": (".result_mapping", "SqlResultMappingError"),
    "map_sql_rows": (".result_mapping", "map_sql_rows"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value
