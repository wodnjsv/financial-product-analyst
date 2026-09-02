"""Strict immutable contracts at the semantic-plan to SQL boundary."""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.validation import require_unique_ids
from financial_agent.contracts.values import ContractValue
from financial_agent.planning.physical_bindings import EvidenceLocator, ObservationValueColumn
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
_SQL_TOKEN = re.compile(
    r'\s+|:[A-Za-z][A-Za-z0-9_]*|"(?:[^"]|"")+"|'
    r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|<=|>=|<>|!=|[-+*/=<>(),.]"
)
_SQL_KEYWORDS = frozenset(
    "SELECT WITH AS FROM JOIN ON WHERE AND OR NOT IS DISTINCT NULL IN BETWEEN "
    "LIKE ESCAPE ORDER BY ASC DESC NULLS FIRST LAST LIMIT GROUP HAVING UNION ALL"
    .split()
)
_SQL_FUNCTIONS = frozenset({"sum", "avg", "min", "max", "count", "array_agg"})
_SQL_IDENTIFIERS = frozenset(
    {
        "catalog", "observation", "evidence", "relation",
        "product", "entity", "observation_record", "evidence_record",
        "source_record", "evidence_observation_origin", "evidence_relation_origin",
        "relation_record", "representative_product", "distribution_values",
        "distribution_stats", "dataset_version", "entity_id", "product_family",
        "canonical_name", "numeric_value", "text_value", "boolean_value",
        "date_value", "value_status", "observation_id", "metric_id",
        "metric_definition_version", "unit", "currency", "applicable_date",
        "evidence_id", "source_id", "evidence_kind", "relation_id", "subject_id",
        "predicate_id", "object_id", "evidence_ids", "source_ids", "product_id",
        "product_name", "aggregate_value", "product_ids", "observation_ids", "metric_ids",
        "metric_definition_versions", "units", "currencies", "applicable_dates",
    }
)
_GENERATED_IDENTIFIER = re.compile(
    r"^(?:observation|evidence|evidence_origin|evidence_source|evidence_lineage|"
    r"field|observation_id|metric_id|metric_definition_version|unit|currency|"
    r"applicable_date|evidence_id|source_id|group)_[0-9]+$"
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


class CompiledSqlRequest(_StrictModel):
    compiled_request_id: Identifier
    logical_plan_id: Identifier
    task_id: Identifier
    statement: str = Field(min_length=1)
    parameters: tuple[SqlParameter, ...]
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
    _validate_closed_sql_tokens(stripped)


def _validate_closed_sql_tokens(statement: str) -> None:
    """Accept only the deliberately small SQLAlchemy-emitted SQL vocabulary."""

    cursor = 0
    tokens: list[str] = []
    for match in _SQL_TOKEN.finditer(statement):
        if match.start() != cursor:
            raise ValueError("SQL_IDENTIFIER_NOT_REGISTERED")
        cursor = match.end()
        token = match.group(0)
        if not token.isspace():
            tokens.append(token)
    if cursor != len(statement):
        raise ValueError("SQL_IDENTIFIER_NOT_REGISTERED")

    for index, token in enumerate(tokens):
        if token[0].isdigit():
            raise ValueError("SQL_IDENTIFIER_NOT_REGISTERED")
        if token.startswith(":") or token in {
            "-", "+", "*", "/", "=", "<", ">", "<=", ">=", "<>", "!=",
            "(", ")", ",", ".",
        }:
            continue
        identifier = token[1:-1].replace('""', '"') if token.startswith('"') else token
        upper = identifier.upper()
        if upper in _SQL_KEYWORDS:
            continue
        follows_call = index + 1 < len(tokens) and tokens[index + 1] == "("
        if follows_call and identifier.lower() in _SQL_FUNCTIONS:
            continue
        if identifier in _SQL_IDENTIFIERS or _GENERATED_IDENTIFIER.fullmatch(identifier):
            continue
        raise ValueError("SQL_IDENTIFIER_NOT_REGISTERED")
