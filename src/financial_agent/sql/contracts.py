"""Strict immutable contracts at the semantic-plan to SQL boundary."""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Literal, TypeAlias

from pydantic import ConfigDict, Field, ValidationError, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.enums import ProductFamily
from financial_agent.contracts.canonical import canonical_json_bytes, canonical_sha256
from financial_agent.contracts.validation import require_unique_ids
from financial_agent.contracts.values import ContractValue
from financial_agent.intent.query_contracts import AggregationFunction
from financial_agent.planning.logical_query import (
    LogicalAggregateOperationV2,
    LogicalQueryPlanV2,
    LogicalQueryTaskV2,
    logical_task_semantic_hash,
)
from financial_agent.planning.physical_bindings import (
    EvidenceLocator,
    ObservationValueColumn,
    PhysicalBindingDefinition,
    PhysicalReadinessFacts,
)
from financial_agent.planning.physical_bindings import (
    EXPECTED_BINDING_DEFINITION_HASHES,
    EXPECTED_POLICY_IDS,
)


COMPILER_VERSION = "semantic-sql-compiler.v1"
_PLACEHOLDER = re.compile(r"(?<!:):([A-Za-z][A-Za-z0-9_]*)")
_MUTATION = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|UPSERT|CREATE|ALTER|DROP|TRUNCATE|INTO|"
    r"GRANT|REVOKE|COPY|CALL|DO|VACUUM|ANALYZE|REFRESH|LOCK)\b",
    re.IGNORECASE,
)
_LOCKING = re.compile(
    r"\bFOR\s+(?:UPDATE|SHARE|NO\s+KEY\s+UPDATE|KEY\s+SHARE)\b",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"--|/\*|\*/")
_SERVER_BINDING_IDS = frozenset(EXPECTED_BINDING_DEFINITION_HASHES) | {
    "catalog-product-family.v1",
    *(f"evidence-{item.value}.v1" for item in EvidenceLocator),
}
_SEMANTIC_PATH = re.compile(
    r"^(?:scope\.product_family_ids|operation\.(?:projections|predicate|ordering|"
    r"aggregation(?:\.target|\.population|\.group_by)?)(?:\.[0-9]+)?|"
    r"qualifiers\.(?:period|currency|unit|as_of)|evidence\.[0-9]+)$"
)
_IDENTIFIER_TOKEN = re.compile(r'(?<!:)(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*')
_NON_IDENTIFIER_WORDS = frozenset(
    "SELECT WITH AS FROM JOIN LATERAL ON WHERE AND OR NOT IS DISTINCT NULL IN "
    "BETWEEN LIKE ESCAPE ORDER BY ASC DESC NULLS FIRST LAST LIMIT GROUP HAVING "
    "TRUE SUM AVG MIN MAX COUNT ARRAY_AGG UNNEST".split()
)


class SqlValueKind(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    TUPLE = "tuple"


class PhysicalLoweringKind(str, Enum):
    SCOPE = "scope"
    PROJECTION = "projection"
    PREDICATE = "predicate"
    QUALIFIER = "qualifier"
    ORDERING = "ordering"
    AGGREGATION = "aggregation"
    GROUPING = "grouping"
    DEDUPLICATION = "deduplication"
    EVIDENCE = "evidence"


class SqlRenderTemplateId(str, Enum):
    LOOKUP = "lookup.observation.v1"
    SCREEN = "screen.observation.v1"
    RANK = "rank.observation.v1"
    COMPARE = "compare.observation.v1"
    AGGREGATE = "aggregate.observation.v1"
    REPRESENTATIVE_AGGREGATE = "aggregate.representative.v1"


class _StrictModel(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SqlParameter(_StrictModel):
    name: Identifier
    value: ContractValue
    value_kind: SqlValueKind = Field(strict=False)

    @model_validator(mode="after")
    def validate_tag_matches_kind(self):
        if self.value.type != self.value_kind.value:
            raise ValueError("SQL_PARAMETER_VALUE_KIND_MISMATCH")
        return self


class DeferredSqlParameter(_StrictModel):
    """Compiler-owned slot that can only be resolved by the runtime binder."""

    name: Identifier
    binding_id: Identifier
    value_kind: Literal[SqlValueKind.TUPLE] = SqlValueKind.TUPLE


SqlParameterInput: TypeAlias = SqlParameter | DeferredSqlParameter


class PhysicalLoweringRecord(_StrictModel):
    lowering_id: Identifier
    semantic_path: Identifier
    binding_id: Identifier
    lowering_kind: PhysicalLoweringKind = Field(strict=False)
    value_column: ObservationValueColumn | None = Field(default=None, strict=False)
    policy_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_record(self):
        require_unique_ids(self.policy_ids, label="physical lowering policy IDs")
        if not set(self.policy_ids) <= EXPECTED_POLICY_IDS:
            raise ValueError("PHYSICAL_LOWERING_POLICY_NOT_REGISTERED")
        if self.binding_id not in _SERVER_BINDING_IDS:
            raise ValueError("PHYSICAL_LOWERING_BINDING_NOT_REGISTERED")
        if _SEMANTIC_PATH.fullmatch(self.semantic_path) is None:
            raise ValueError("PHYSICAL_LOWERING_PATH_NOT_REGISTERED")
        if self.lowering_id != physical_lowering_record_id(self):
            raise ValueError("PHYSICAL_LOWERING_ID_MISMATCH")
        return self


class PhysicalSqlRenderManifest(_StrictModel):
    """Closed, self-rendering physical IR for one validated logical task.

    The manifest is sufficient to reproduce compiler output, but it is not an
    authorization token. Execution must additionally pair it with the original
    validated ``LogicalQueryPlanV2`` through
    :func:`validate_compiled_request_ownership`.
    """

    manifest_id: Identifier
    template_id: SqlRenderTemplateId = Field(strict=False)
    logical_plan_id: Identifier
    logical_task: LogicalQueryTaskV2
    logical_task_semantic_hash: Sha256Hex
    dataset_version: Identifier
    dataset_pin: Sha256Hex
    binding_definitions: tuple[PhysicalBindingDefinition, ...]
    effective_product_family_ids: tuple[ProductFamily, ...] = Field(
        min_length=1, strict=False
    )
    readiness_facts: PhysicalReadinessFacts | None = None
    binding_registry_version: Identifier
    binding_registry_hash: Sha256Hex
    policy_registry_version: Identifier
    policy_registry_hash: Sha256Hex
    contract_registry_version: Identifier
    contract_registry_hash: Sha256Hex
    operator_registry_version: Identifier
    operator_registry_hash: Sha256Hex
    semantic_policy_registry_version: Identifier
    semantic_policy_registry_hash: Sha256Hex
    planning_registry_version: Identifier
    planning_registry_hash: Sha256Hex
    statement_sha256: Sha256Hex
    ordered_placeholder_names: tuple[Identifier, ...]
    identifier_occurrences: tuple[Identifier, ...]
    lowering_record_ids: tuple[Identifier, ...]
    evidence_projection_ids: tuple[EvidenceLocator, ...] = Field(strict=False)
    count_lineage_metric_definition_refs: tuple[Identifier, ...] = ()
    prior_result_entity_ids: tuple[Identifier, ...] | None = None

    @model_validator(mode="after")
    def validate_manifest(self):
        if self.logical_plan_id == self.logical_task.task_id:
            raise ValueError("SQL_MANIFEST_PLAN_TASK_OWNERSHIP_MISMATCH")
        if self.logical_task_semantic_hash != logical_task_semantic_hash(
            self.logical_task
        ):
            raise ValueError("SQL_MANIFEST_LOGICAL_SEMANTIC_HASH_MISMATCH")
        if self.template_id is not sql_render_template_id(self.logical_task):
            raise ValueError("SQL_MANIFEST_TEMPLATE_MISMATCH")
        binding_ids = tuple(item.id for item in self.binding_definitions)
        require_unique_ids(binding_ids, label="manifest physical bindings")
        require_unique_ids(
            tuple(item.value for item in self.effective_product_family_ids),
            label="manifest effective product families",
        )
        prior_only_scope = (
            self.logical_task.scope.prior_result_binding is not None
            and not self.logical_task.scope.product_family_ids
            and not self.logical_task.binding_ids
        )
        if not prior_only_scope and binding_ids != self.logical_task.binding_ids:
            raise ValueError("SQL_MANIFEST_BINDING_OWNERSHIP_MISMATCH")
        prior_only_count_lineage = (
            prior_only_scope
            and isinstance(self.logical_task.operation, LogicalAggregateOperationV2)
            and self.logical_task.operation.aggregation.function_id
            is AggregationFunction.COUNT
            and bool(self.count_lineage_metric_definition_refs)
        )
        if prior_only_scope and not binding_ids and not prior_only_count_lineage:
            raise ValueError("SQL_MANIFEST_BINDING_OWNERSHIP_MISMATCH")
        local_families = self.logical_task.scope.product_family_ids
        if local_families:
            if self.effective_product_family_ids != local_families:
                raise ValueError("SQL_MANIFEST_SCOPE_FAMILY_MISMATCH")
        elif self.logical_task.scope.prior_result_binding is None:
            raise ValueError("SQL_MANIFEST_SCOPE_FAMILY_MISMATCH")
        if any(
            EXPECTED_BINDING_DEFINITION_HASHES.get(item.id)
            != canonical_sha256(item)
            for item in self.binding_definitions
        ):
            raise ValueError("SQL_MANIFEST_BINDING_DEFINITION_MISMATCH")
        if (
            self.template_id is SqlRenderTemplateId.REPRESENTATIVE_AGGREGATE
        ) != (self.readiness_facts is not None):
            raise ValueError("SQL_MANIFEST_READINESS_PROOF_MISMATCH")
        require_unique_ids(self.lowering_record_ids, label="manifest lowering records")
        require_unique_ids(
            self.evidence_projection_ids, label="manifest evidence projections"
        )
        require_unique_ids(
            self.count_lineage_metric_definition_refs,
            label="COUNT lineage metric definitions",
        )
        has_prior_result = self.logical_task.scope.prior_result_binding is not None
        if not has_prior_result and self.prior_result_entity_ids is not None:
            raise ValueError("SQL_MANIFEST_PRIOR_RESULT_MISMATCH")
        if self.prior_result_entity_ids is not None and (
            not self.prior_result_entity_ids
            or self.prior_result_entity_ids
            != tuple(sorted(set(self.prior_result_entity_ids)))
        ):
            raise ValueError("SQL_MANIFEST_PRIOR_RESULT_MISMATCH")
        if self.manifest_id != physical_sql_render_manifest_id(self):
            raise ValueError("SQL_RENDER_MANIFEST_ID_MISMATCH")
        return self


class CompiledSqlRequest(_StrictModel):
    compiled_request_id: Identifier
    logical_plan_id: Identifier
    task_id: Identifier
    logical_task_semantic_hash: Sha256Hex
    render_manifest: PhysicalSqlRenderManifest
    execution_ownership_required: Literal[True] = True
    statement: str = Field(min_length=1)
    parameters: tuple[SqlParameterInput, ...]
    lowering_records: tuple[PhysicalLoweringRecord, ...] = Field(min_length=1)
    applied_policy_ids: tuple[Identifier, ...]
    evidence_projection_ids: tuple[EvidenceLocator, ...] = Field(strict=False)
    compiler_version: Literal["semantic-sql-compiler.v1"] = COMPILER_VERSION
    binding_registry_version: Identifier
    binding_registry_hash: Sha256Hex
    policy_registry_version: Identifier
    policy_registry_hash: Sha256Hex
    contract_registry_version: Identifier
    contract_registry_hash: Sha256Hex
    operator_registry_version: Identifier
    operator_registry_hash: Sha256Hex
    semantic_policy_registry_version: Identifier
    semantic_policy_registry_hash: Sha256Hex
    planning_registry_version: Identifier
    planning_registry_hash: Sha256Hex
    dataset_version: Identifier
    dataset_pin: Sha256Hex
    population_manifest_id: Identifier | None = None
    population_manifest_hash: Sha256Hex | None = None

    @model_validator(mode="after")
    def validate_request(self):
        _validate_read_only_statement(self.statement)
        manifest = self.render_manifest
        if (
            self.logical_plan_id != manifest.logical_plan_id
            or self.task_id != manifest.logical_task.task_id
            or self.logical_task_semantic_hash != manifest.logical_task_semantic_hash
        ):
            raise ValueError("SQL_MANIFEST_LOGICAL_OWNERSHIP_MISMATCH")
        request_pins = _request_registry_pins(self)
        manifest_pins = _manifest_registry_pins(manifest)
        if request_pins != manifest_pins:
            raise ValueError("SQL_MANIFEST_REGISTRY_PIN_MISMATCH")
        if (
            self.dataset_version != manifest.dataset_version
            or self.dataset_pin != manifest.dataset_pin
        ):
            raise ValueError("SQL_MANIFEST_DATASET_PIN_MISMATCH")

        # Import lazily so the contracts remain importable by the renderer.
        from .compiler import render_physical_sql_manifest

        rendered = render_physical_sql_manifest(manifest)
        if self.statement != rendered.statement:
            raise ValueError("SQL_MANIFEST_STATEMENT_MISMATCH")
        if self.parameters != rendered.parameters:
            raise ValueError("SQL_MANIFEST_PARAMETER_MISMATCH")
        if self.lowering_records != rendered.lowering_records:
            raise ValueError("SQL_MANIFEST_LOWERING_MISMATCH")
        if self.evidence_projection_ids != rendered.evidence_projection_ids:
            raise ValueError("SQL_MANIFEST_EVIDENCE_MISMATCH")
        effective_policy_ids = tuple(
            dict.fromkeys(
                (
                    *manifest.logical_task.policy_ids,
                    *(
                        item
                        for binding in manifest.binding_definitions
                        for item in (
                            binding.unit_conversion_policy_id,
                            binding.missingness_policy_id,
                        )
                        if item is not None
                    ),
                )
            )
        )
        if self.applied_policy_ids != effective_policy_ids:
            raise ValueError("SQL_MANIFEST_POLICY_OWNERSHIP_MISMATCH")
        if self.population_manifest_id != rendered.population_manifest_id or (
            self.population_manifest_hash != rendered.population_manifest_hash
        ):
            raise ValueError("SQL_MANIFEST_POPULATION_PROOF_MISMATCH")
        if manifest.statement_sha256 != statement_sha256(rendered.statement):
            raise ValueError("SQL_MANIFEST_STATEMENT_HASH_MISMATCH")
        if manifest.ordered_placeholder_names != placeholder_occurrences(
            rendered.statement
        ):
            raise ValueError("SQL_MANIFEST_PLACEHOLDER_ORDER_MISMATCH")
        if manifest.identifier_occurrences != identifier_occurrences(
            rendered.statement
        ):
            raise ValueError("SQL_MANIFEST_IDENTIFIER_MISMATCH")
        if manifest.lowering_record_ids != tuple(
            item.lowering_id for item in rendered.lowering_records
        ):
            raise ValueError("SQL_MANIFEST_LOWERING_ID_MISMATCH")
        if manifest.evidence_projection_ids != rendered.evidence_projection_ids:
            raise ValueError("SQL_MANIFEST_EVIDENCE_MISMATCH")

        parameter_names = tuple(item.name for item in self.parameters)
        require_unique_ids(parameter_names, label="SQL parameters")
        if set(_PLACEHOLDER.findall(self.statement)) != set(parameter_names):
            raise ValueError("SQL_PARAMETER_MISMATCH")
        require_unique_ids(
            (item.lowering_id for item in self.lowering_records),
            label="physical lowering records",
        )
        require_unique_ids(self.applied_policy_ids, label="compiled SQL policies")
        if not set(self.applied_policy_ids) <= EXPECTED_POLICY_IDS:
            raise ValueError("SQL_POLICY_NOT_REGISTERED")
        require_unique_ids(self.evidence_projection_ids, label="evidence projections")
        if bool(self.population_manifest_id) != bool(self.population_manifest_hash):
            raise ValueError("POPULATION_MANIFEST_PROVENANCE_MISMATCH")
        if self.compiled_request_id != compiled_sql_request_id(self):
            raise ValueError("COMPILED_REQUEST_ID_MISMATCH")
        return self


def physical_lowering_record_id(record: PhysicalLoweringRecord) -> str:
    return "physical-lowering-" + canonical_sha256(
        record,
        exclude_fields={"lowering_id"},
    )


def compiled_sql_request_id(request: CompiledSqlRequest) -> str:
    return "compiled-sql-" + canonical_sha256(
        request,
        exclude_fields={"compiled_request_id"},
    )


def physical_sql_render_manifest_id(manifest: PhysicalSqlRenderManifest) -> str:
    return "physical-sql-manifest-" + canonical_sha256(
        manifest,
        exclude_fields={"manifest_id"},
    )


def statement_sha256(statement: str) -> str:
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def placeholder_occurrences(statement: str) -> tuple[str, ...]:
    return tuple(_PLACEHOLDER.findall(statement))


def identifier_occurrences(statement: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _IDENTIFIER_TOKEN.findall(statement)
        if token.upper() not in _NON_IDENTIFIER_WORDS
    )


def validate_compiled_request_ownership(
    request: CompiledSqlRequest,
    logical_plan: LogicalQueryPlanV2,
) -> None:
    """Bind a restored request to its authoritative validated logical plan.

    Content-addressed IDs detect drift; they do not authorize caller-provided
    content. Task 9's runner must call this before opening a transaction.
    """

    try:
        plan = LogicalQueryPlanV2.model_validate_json(canonical_json_bytes(logical_plan))
    except ValidationError as error:
        raise ValueError("COMPILED_SQL_LOGICAL_PLAN_REVALIDATION_FAILED") from error
    if request.logical_plan_id != plan.logical_plan_id:
        raise ValueError("COMPILED_SQL_LOGICAL_PLAN_OWNERSHIP_MISMATCH")
    task = next((item for item in plan.tasks if item.task_id == request.task_id), None)
    if task is None:
        raise ValueError("COMPILED_SQL_LOGICAL_TASK_OWNERSHIP_MISMATCH")
    if (
        request.render_manifest.logical_task != task
        or request.logical_task_semantic_hash != logical_task_semantic_hash(task)
    ):
        raise ValueError("COMPILED_SQL_LOGICAL_TASK_OWNERSHIP_MISMATCH")
    if _request_registry_pins(request) != {
        "binding_registry_version": plan.binding_registry_version,
        "binding_registry_hash": plan.binding_registry_hash,
        "policy_registry_version": plan.physical_policy_registry_version,
        "policy_registry_hash": plan.physical_policy_registry_hash,
        "contract_registry_version": plan.contract_registry_version,
        "contract_registry_hash": plan.contract_registry_hash,
        "operator_registry_version": plan.operator_registry_version,
        "operator_registry_hash": plan.operator_registry_hash,
        "semantic_policy_registry_version": plan.semantic_policy_registry_version,
        "semantic_policy_registry_hash": plan.semantic_policy_registry_hash,
        "planning_registry_version": plan.planning_registry_version,
        "planning_registry_hash": plan.planning_registry_hash,
    }:
        raise ValueError("COMPILED_SQL_LOGICAL_PLAN_PIN_MISMATCH")
    if (
        request.dataset_version != plan.dataset_version
        or request.dataset_pin != plan.dataset_pin
    ):
        raise ValueError("COMPILED_SQL_LOGICAL_PLAN_PIN_MISMATCH")


def _validate_read_only_statement(statement: str) -> None:
    stripped = statement.strip()
    if ";" in stripped:
        raise ValueError("SQL_MULTIPLE_STATEMENTS_FORBIDDEN")
    if _COMMENT.search(stripped):
        raise ValueError("SQL_COMMENTS_FORBIDDEN")
    if not re.match(r"^(?:SELECT|WITH)\b", stripped, flags=re.IGNORECASE):
        raise ValueError("SQL_READ_ONLY_STATEMENT_REQUIRED")
    if _MUTATION.search(stripped) or _LOCKING.search(stripped):
        raise ValueError("SQL_MUTATION_FORBIDDEN")


def sql_render_template_id(task: LogicalQueryTaskV2) -> SqlRenderTemplateId:
    if task.operation.operation_type == "lookup":
        return SqlRenderTemplateId.LOOKUP
    if task.operation.operation_type == "screen":
        return SqlRenderTemplateId.SCREEN
    if task.operation.operation_type == "rank":
        return SqlRenderTemplateId.RANK
    if task.operation.operation_type == "compare":
        return SqlRenderTemplateId.COMPARE
    if task.operation.operation_type == "aggregate":
        if task.operation.aggregation.population_grain_id == "representative-product.v1":
            return SqlRenderTemplateId.REPRESENTATIVE_AGGREGATE
        return SqlRenderTemplateId.AGGREGATE
    raise ValueError("SQL_RENDER_TEMPLATE_NOT_REGISTERED")


def _request_registry_pins(request: CompiledSqlRequest) -> dict[str, str]:
    return {
        "binding_registry_version": request.binding_registry_version,
        "binding_registry_hash": request.binding_registry_hash,
        "policy_registry_version": request.policy_registry_version,
        "policy_registry_hash": request.policy_registry_hash,
        "contract_registry_version": request.contract_registry_version,
        "contract_registry_hash": request.contract_registry_hash,
        "operator_registry_version": request.operator_registry_version,
        "operator_registry_hash": request.operator_registry_hash,
        "semantic_policy_registry_version": request.semantic_policy_registry_version,
        "semantic_policy_registry_hash": request.semantic_policy_registry_hash,
        "planning_registry_version": request.planning_registry_version,
        "planning_registry_hash": request.planning_registry_hash,
    }


def _manifest_registry_pins(manifest: PhysicalSqlRenderManifest) -> dict[str, str]:
    return {
        "binding_registry_version": manifest.binding_registry_version,
        "binding_registry_hash": manifest.binding_registry_hash,
        "policy_registry_version": manifest.policy_registry_version,
        "policy_registry_hash": manifest.policy_registry_hash,
        "contract_registry_version": manifest.contract_registry_version,
        "contract_registry_hash": manifest.contract_registry_hash,
        "operator_registry_version": manifest.operator_registry_version,
        "operator_registry_hash": manifest.operator_registry_hash,
        "semantic_policy_registry_version": manifest.semantic_policy_registry_version,
        "semantic_policy_registry_hash": manifest.semantic_policy_registry_hash,
        "planning_registry_version": manifest.planning_registry_version,
        "planning_registry_hash": manifest.planning_registry_hash,
    }
