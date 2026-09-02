"""Fail-closed mapping from one compiled SQL result into public result contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
import re

from pydantic import ConfigDict

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.execution import Exclusion, ResultField, ResultRow, ResultWarning
from financial_agent.contracts.values import encode_contract_value
from financial_agent.intent.query_contracts import AggregationFunction, SemanticValueKind
from financial_agent.planning.logical_query import (
    LogicalAggregateOperationV2,
    LogicalCompareOperationV2,
    LogicalLookupOperationV2,
    LogicalRankOperationV2,
    LogicalScreenOperationV2,
)
from financial_agent.planning.physical_bindings import (
    EvidenceLocator,
    population_metric_ownership_lineage_ref,
    representative_share_edge_lineage_ref,
)

from .contracts import CompiledSqlRequest


_SENTINEL_TEXT = frozenset({"", "-", "—", "N/A", "NA", "n/a", "미제공", "없음"})
MAX_RETURNED_ROWS = 10_000
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class SqlResultMappingError(ValueError):
    """The database returned a shape not authorized by the compiled request."""


class MappedSqlResult(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    result_rows: tuple[ResultRow, ...]
    evidence_refs: tuple[Identifier, ...]
    exclusions: tuple[Exclusion, ...]
    warnings: tuple[ResultWarning, ...]


def map_sql_rows(
    request: CompiledSqlRequest,
    rows: Sequence[Mapping[str, object]],
) -> MappedSqlResult:
    """Map only the exact compiler-owned projection shape.

    Observation, evidence and source identifiers are namespaced in the flat
    evidence reference array because the existing V1 ``ResultField`` has no
    physical-lineage members. Task 10 can therefore wrap this result without
    weakening the existing execution contracts.
    """

    if len(rows) > MAX_RETURNED_ROWS:
        raise SqlResultMappingError("RETURNED_CARDINALITY_EXCEEDED")
    task = request.render_manifest.logical_task
    operation = task.operation
    descriptors = _field_descriptors(request)
    expected_columns = _expected_columns(request, descriptors)

    result_rows: list[ResultRow] = []
    exclusions: list[Exclusion] = []
    warnings: list[ResultWarning] = []
    lineage: set[str] = set()
    seen_rows: set[tuple[object, ...]] = set()

    for raw in rows:
        row = dict(raw)
        if set(row) != expected_columns:
            raise SqlResultMappingError("RETURNED_COLUMN_SET_MISMATCH")
        _validate_physical_metadata(request, row, descriptors)
        row_key = _row_key(operation, row, descriptors)
        if row_key in seen_rows:
            raise SqlResultMappingError("RETURNED_DUPLICATE_ROW")
        seen_rows.add(row_key)

        entity_ids: tuple[str, ...] = ()
        fields: list[ResultField] = []
        subject_id = task.task_id
        if not isinstance(operation, LogicalAggregateOperationV2):
            product_id = _identifier(row["product_id"])
            product_name = _string(row["product_name"])
            subject_id = product_id
            entity_ids = (product_id,)
            fields.append(
                ResultField(
                    field_id="product_name",
                    value=encode_contract_value(product_name),
                )
            )
        elif "product_ids" in row:
            count_value = row.get("aggregate_value")
            if row["product_ids"] is None and count_value == 0:
                entity_ids = ()
            else:
                entity_ids = tuple(
                    sorted(
                        _identifier_array(
                            row["product_ids"], "RETURNED_PRODUCT_IDS_MALFORMED"
                        )
                    )
                )
            if row.get("aggregate_value") != len(entity_ids):
                raise SqlResultMappingError("RETURNED_COUNT_CARDINALITY_MISMATCH")
            _validate_count_lineage(request, row, entity_ids)

        for index, (concept_id, value_kind, prefix) in enumerate(descriptors):
            value_column = (
                f"{prefix}_{index}" if prefix in {"field", "group"} else prefix
            )
            value = row[value_column]
            _collect_field_lineage(
                request, row, prefix=prefix, index=index, target=lineage
            )
            missing_reason = _missing_reason(row, prefix=prefix, index=index, value=value)
            if missing_reason is not None:
                exclusions.append(
                    Exclusion(
                        subject_id=subject_id,
                        rule_id="exclude_missing.v1",
                        reason_code=missing_reason,
                    )
                )
                warnings.append(
                    ResultWarning(
                        warning_code="MISSING_VALUE_EXCLUDED",
                        related_ids=(subject_id, concept_id),
                    )
                )
                continue
            typed = _typed_value(value, value_kind)
            unit, currency, applicable_date = _field_metadata(
                request, row, prefix=prefix, index=index
            )
            fields.append(
                ResultField(
                    field_id=(
                        f"group:{concept_id}" if prefix == "group" else concept_id
                    ),
                    value=encode_contract_value(typed),
                    unit_id=unit,
                    currency=currency,
                    applicable_date=applicable_date,
                )
            )

        _collect_aggregate_lineage(
            request,
            row,
            lineage,
            empty_count=(
                isinstance(operation, LogicalAggregateOperationV2)
                and operation.aggregation.function_id is AggregationFunction.COUNT
                and row.get("aggregate_value") == 0
            ),
        )
        row_payload = {
            "request_id": request.compiled_request_id,
            "entity_ids": list(entity_ids),
            "fields": [field.model_dump(mode="json") for field in fields],
        }
        result_rows.append(
            ResultRow(
                row_id="sql-row-" + canonical_sha256(row_payload),
                entity_ids=entity_ids,
                fields=tuple(fields),
            )
        )

    _collect_manifest_relation_lineage(request, lineage)
    _validate_evidence_categories(request, rows, lineage)
    _validate_cardinality(request, result_rows)
    if not isinstance(operation, LogicalRankOperationV2):
        result_rows.sort(key=lambda item: (item.entity_ids, item.row_id))
        exclusions.sort(key=lambda item: (item.subject_id, item.rule_id, item.reason_code))
        warnings.sort(key=lambda item: (item.warning_code, item.related_ids))
    return MappedSqlResult(
        result_rows=tuple(result_rows),
        evidence_refs=tuple(sorted(lineage)),
        exclusions=tuple(exclusions),
        warnings=tuple(warnings),
    )


def _field_descriptors(
    request: CompiledSqlRequest,
) -> tuple[tuple[str, SemanticValueKind, str], ...]:
    task = request.render_manifest.logical_task
    operation = task.operation
    concepts: tuple[tuple[str, str], ...]
    if isinstance(operation, LogicalLookupOperationV2):
        concepts = tuple((item, "field") for item in operation.projections.field_concept_ids)
    elif isinstance(operation, LogicalScreenOperationV2):
        concepts = tuple((item, "field") for item in _predicate_concepts(operation.predicate))
    elif isinstance(operation, LogicalRankOperationV2):
        ordered = tuple(dict.fromkeys(item.field_concept_id for item in operation.ordering))
        predicate = _predicate_concepts(operation.predicate) if operation.predicate is not None else ()
        concepts = tuple((item, "field") for item in (*ordered, *(item for item in predicate if item not in ordered)))
    elif isinstance(operation, LogicalCompareOperationV2):
        concepts = tuple((item, "field") for item in operation.comparison.metric_concept_ids)
    elif isinstance(operation, LogicalAggregateOperationV2):
        grouped = tuple((item, "group") for item in operation.aggregation.group_by_field_concept_ids)
        target = (
            ((operation.aggregation.target_field_concept_id, "aggregate_value"),)
            if operation.aggregation.target_field_concept_id is not None
            and operation.aggregation.function_id is not AggregationFunction.DISTRIBUTION
            else ()
        )
        if operation.aggregation.function_id is AggregationFunction.COUNT:
            target = (("product_count", "aggregate_value"),)
        concepts = (*grouped, *target)
    else:  # Compiler currently authorizes only these SQL operation variants.
        raise SqlResultMappingError("RETURNED_OPERATION_NOT_SUPPORTED")

    by_concept = {
        binding.semantic_concept_id: binding.semantic_value_kind
        for binding in request.render_manifest.binding_definitions
    }
    descriptors = []
    for concept_id, prefix in concepts:
        if concept_id == "product_count":
            kind = SemanticValueKind.INTEGER
        else:
            try:
                kind = by_concept[concept_id]
            except KeyError as error:
                raise SqlResultMappingError("RETURNED_FIELD_BINDING_MISSING") from error
        descriptors.append((concept_id, kind, prefix))
    return tuple(descriptors)


def _expected_columns(
    request: CompiledSqlRequest,
    descriptors: tuple[tuple[str, SemanticValueKind, str], ...],
) -> set[str]:
    operation = request.render_manifest.logical_task.operation
    if not isinstance(operation, LogicalAggregateOperationV2):
        columns = {"product_id", "product_name"}
        for index in range(len(descriptors)):
            columns.update(
                {
                    f"field_{index}",
                    f"observation_id_{index}",
                    f"metric_id_{index}",
                    f"metric_definition_version_{index}",
                    f"unit_{index}",
                    f"currency_{index}",
                    f"applicable_date_{index}",
                    f"evidence_id_{index}",
                    f"source_id_{index}",
                }
            )
            if isinstance(operation, LogicalLookupOperationV2):
                columns.update({f"value_status_{index}", f"reason_code_{index}"})
        return columns

    group_count = len(operation.aggregation.group_by_field_concept_ids)
    columns = {f"group_{index}" for index in range(group_count)}
    if operation.aggregation.function_id is AggregationFunction.COUNT:
        columns.update({"aggregate_value", "product_ids"})
        requested = set(request.evidence_projection_ids)
        if EvidenceLocator.METRIC_DEFINITION in requested:
            columns.add("metric_definition_refs")
        if EvidenceLocator.OBSERVATION_RECORD in requested:
            columns.add("observation_ids")
        if EvidenceLocator.RELATION_RECORD in requested:
            columns.add("relation_ids")
        if EvidenceLocator.EVIDENCE_RECORD in requested:
            columns.add("evidence_ids")
        if EvidenceLocator.SOURCE_RECORD in requested:
            columns.add("source_ids")
        facts = request.render_manifest.readiness_facts
        if (
            facts is not None
            and facts.public_fund_manifest is not None
            and requested
        ):
            columns.update(
                {"observation_lineage_refs", "relation_lineage_refs"}
            )
    else:
        if operation.aggregation.function_id is not AggregationFunction.DISTRIBUTION:
            columns.add("aggregate_value")
        columns.update(
            {
                "observation_ids",
                "metric_ids",
                "metric_definition_versions",
                "units",
                "currencies",
                "applicable_dates",
            }
        )
    if group_count or operation.aggregation.function_id is not AggregationFunction.COUNT:
        columns.update({"evidence_ids", "source_ids"})
    return columns


def _field_metadata(request, row, *, prefix: str, index: int):
    operation = request.render_manifest.logical_task.operation
    if prefix == "field":
        return (
            _optional_string(row[f"unit_{index}"]),
            _optional_string(row[f"currency_{index}"]),
            _optional_date(row[f"applicable_date_{index}"]),
        )
    if prefix == "group" and isinstance(operation, LogicalAggregateOperationV2):
        concept_id = operation.aggregation.group_by_field_concept_ids[index]
        binding = next(
            item
            for item in request.render_manifest.binding_definitions
            if item.semantic_concept_id == concept_id
        )
        return (
            binding.storage_unit_id,
            request.render_manifest.logical_task.qualifiers.currency_id,
            request.render_manifest.logical_task.qualifiers.as_of_date,
        )
    if prefix == "aggregate_value" and isinstance(operation, LogicalAggregateOperationV2):
        units = _optional_scalar_array(row.get("units"), "RETURNED_AGGREGATE_UNIT_MISMATCH")
        currencies = _optional_scalar_array(row.get("currencies"), "RETURNED_AGGREGATE_CURRENCY_MISMATCH")
        dates = _optional_scalar_array(row.get("applicable_dates"), "RETURNED_AGGREGATE_DATE_MISMATCH", date_only=True)
        return (
            units[0] if units else None,
            currencies[0] if currencies else None,
            dates[0] if dates else None,
        )
    return None, None, None


def _validate_physical_metadata(request, row, descriptors) -> None:
    operation = request.render_manifest.logical_task.operation
    bindings = {
        binding.semantic_concept_id: binding
        for binding in request.render_manifest.binding_definitions
    }
    if not isinstance(operation, LogicalAggregateOperationV2):
        for index, (concept_id, _, prefix) in enumerate(descriptors):
            if prefix != "field":
                continue
            binding = bindings[concept_id]
            if row[f"metric_id_{index}"] not in binding.approved_metric_ids:
                raise SqlResultMappingError("RETURNED_METRIC_OWNERSHIP_MISMATCH")
            _identifier(row[f"metric_definition_version_{index}"])
            value = row[f"field_{index}"]
            if value is not None and row[f"unit_{index}"] != binding.storage_unit_id:
                raise SqlResultMappingError("RETURNED_UNIT_OWNERSHIP_MISMATCH")
            qualifiers = request.render_manifest.logical_task.qualifiers
            if (
                value is not None
                and qualifiers.currency_id is not None
                and row[f"currency_{index}"] != qualifiers.currency_id
            ):
                raise SqlResultMappingError("RETURNED_CURRENCY_OWNERSHIP_MISMATCH")
            if (
                value is not None
                and qualifiers.as_of_date is not None
                and row[f"applicable_date_{index}"] != qualifiers.as_of_date
            ):
                raise SqlResultMappingError("RETURNED_DATE_OWNERSHIP_MISMATCH")
            if not _identifier_array(
                row[f"evidence_id_{index}"], "RETURNED_EVIDENCE_IDS_MALFORMED"
            ):
                raise SqlResultMappingError("RETURNED_EVIDENCE_IDS_MALFORMED")
            if not _identifier_array(
                row[f"source_id_{index}"], "RETURNED_SOURCE_IDS_MALFORMED"
            ):
                raise SqlResultMappingError("RETURNED_SOURCE_IDS_MALFORMED")
        return
    spec = operation.aggregation
    if spec.function_id is AggregationFunction.COUNT:
        return
    target = spec.target_field_concept_id
    if target is None:
        return
    binding = bindings[target]
    metrics = _identifier_array(
        row["metric_ids"], "RETURNED_METRIC_IDS_MALFORMED"
    )
    if not metrics or not set(metrics) <= set(binding.approved_metric_ids):
        raise SqlResultMappingError("RETURNED_METRIC_OWNERSHIP_MISMATCH")
    definitions = _identifier_array(
        row["metric_definition_versions"],
        "RETURNED_METRIC_DEFINITION_VERSIONS_MALFORMED",
    )
    if len(definitions) != 1:
        raise SqlResultMappingError("RETURNED_METRIC_DEFINITION_VERSIONS_MALFORMED")
    units = _optional_scalar_array(
        row["units"], "RETURNED_AGGREGATE_UNIT_MISMATCH"
    )
    if units != (binding.storage_unit_id,):
        raise SqlResultMappingError("RETURNED_UNIT_OWNERSHIP_MISMATCH")
    qualifiers = request.render_manifest.logical_task.qualifiers
    currencies = _optional_scalar_array(
        row["currencies"], "RETURNED_AGGREGATE_CURRENCY_MISMATCH"
    )
    if qualifiers.currency_id is not None and currencies != (qualifiers.currency_id,):
        raise SqlResultMappingError("RETURNED_CURRENCY_OWNERSHIP_MISMATCH")
    dates = _optional_scalar_array(
        row["applicable_dates"],
        "RETURNED_AGGREGATE_DATE_MISMATCH",
        date_only=True,
    )
    if qualifiers.as_of_date is not None and dates != (qualifiers.as_of_date,):
        raise SqlResultMappingError("RETURNED_DATE_OWNERSHIP_MISMATCH")
    if not _identifier_array(
        row["evidence_ids"], "RETURNED_EVIDENCE_IDS_MALFORMED"
    ):
        raise SqlResultMappingError("RETURNED_EVIDENCE_IDS_MALFORMED")
    if not _identifier_array(
        row["source_ids"], "RETURNED_SOURCE_IDS_MALFORMED"
    ):
        raise SqlResultMappingError("RETURNED_SOURCE_IDS_MALFORMED")


def _collect_field_lineage(
    request, row, *, prefix: str, index: int, target: set[str]
) -> None:
    if prefix != "field":
        return
    requested = set(request.evidence_projection_ids)
    if EvidenceLocator.METRIC_DEFINITION in requested:
        metric = _identifier(row[f"metric_id_{index}"])
        version = _identifier(row[f"metric_definition_version_{index}"])
        target.add(f"metric-definition:{metric}:{version}")
    if EvidenceLocator.OBSERVATION_RECORD in requested:
        target.add("observation:" + _identifier(row[f"observation_id_{index}"]))
    if EvidenceLocator.EVIDENCE_RECORD in requested:
        for item in _identifier_array(row[f"evidence_id_{index}"], "RETURNED_EVIDENCE_IDS_MALFORMED"):
            target.add("evidence:" + item)
    if EvidenceLocator.SOURCE_RECORD in requested:
        for item in _identifier_array(row[f"source_id_{index}"], "RETURNED_SOURCE_IDS_MALFORMED"):
            target.add("source:" + item)


def _collect_aggregate_lineage(
    request,
    row: Mapping[str, object],
    target: set[str],
    *,
    empty_count: bool,
) -> None:
    count_value = row.get("aggregate_value")
    requested = set(request.evidence_projection_ids)
    columns = []
    if EvidenceLocator.OBSERVATION_RECORD in requested:
        columns.append(("observation_ids", "observation:"))
    if EvidenceLocator.RELATION_RECORD in requested:
        columns.append(("relation_ids", "relation:"))
    if EvidenceLocator.EVIDENCE_RECORD in requested:
        columns.append(("evidence_ids", "evidence:"))
    if EvidenceLocator.SOURCE_RECORD in requested:
        columns.append(("source_ids", "source:"))
    for column, prefix in columns:
        if column not in row:
            continue
        value = row[column]
        if value is None and empty_count:
            values = ()
        else:
            values = _identifier_array(
                value, f"RETURNED_{column.upper()}_MALFORMED"
            )
            if count_value is not None and count_value != 0 and not values:
                raise SqlResultMappingError(f"RETURNED_{column.upper()}_MALFORMED")
        for item in values:
            target.add(prefix + item)
    if EvidenceLocator.METRIC_DEFINITION in requested:
        if "metric_definition_refs" in row:
            value = row["metric_definition_refs"]
            if value is None and empty_count:
                refs = ()
            else:
                refs = _identifier_array(
                    value, "RETURNED_METRIC_DEFINITION_REFS_MALFORMED"
                )
                if count_value is not None and count_value != 0 and not refs:
                    raise SqlResultMappingError(
                        "RETURNED_METRIC_DEFINITION_REFS_MALFORMED"
                    )
            allowed = set(
                request.render_manifest.count_lineage_metric_definition_refs
            )
            for ref in refs:
                if ref not in allowed:
                    raise SqlResultMappingError(
                        "RETURNED_METRIC_DEFINITION_OWNERSHIP_MISMATCH"
                    )
                target.add("metric-definition:" + ref)
        elif "metric_ids" in row:
            metrics = _identifier_array(
                row["metric_ids"], "RETURNED_METRIC_IDS_MALFORMED"
            )
            versions = _identifier_array(
                row["metric_definition_versions"],
                "RETURNED_METRIC_DEFINITION_VERSIONS_MALFORMED",
            )
            if len(versions) != 1:
                raise SqlResultMappingError(
                    "RETURNED_METRIC_DEFINITION_VERSIONS_MALFORMED"
                )
            for metric in metrics:
                target.add(f"metric-definition:{metric}:{versions[0]}")


def _collect_manifest_relation_lineage(request, target: set[str]) -> None:
    requested = set(request.evidence_projection_ids)
    facts = request.render_manifest.readiness_facts
    operation = request.render_manifest.logical_task.operation
    if (
        isinstance(operation, LogicalAggregateOperationV2)
        and operation.aggregation.function_id is AggregationFunction.COUNT
    ):
        return
    if facts is None or facts.public_fund_manifest is None:
        return
    for edge in facts.public_fund_manifest.representative_share_edges:
        if EvidenceLocator.RELATION_RECORD in requested:
            target.add("relation:" + edge.relation_id)
        if EvidenceLocator.EVIDENCE_RECORD in requested:
            target.add("evidence:" + edge.evidence_id)
        if EvidenceLocator.SOURCE_RECORD in requested:
            target.add("source:" + edge.source_id)


def _validate_count_lineage(
    request: CompiledSqlRequest,
    row: Mapping[str, object],
    entity_ids: tuple[str, ...],
) -> None:
    operation = request.render_manifest.logical_task.operation
    if not (
        isinstance(operation, LogicalAggregateOperationV2)
        and operation.aggregation.function_id is AggregationFunction.COUNT
    ):
        return
    requested = set(request.evidence_projection_ids)
    columns = {
        EvidenceLocator.METRIC_DEFINITION: "metric_definition_refs",
        EvidenceLocator.OBSERVATION_RECORD: "observation_ids",
        EvidenceLocator.RELATION_RECORD: "relation_ids",
        EvidenceLocator.EVIDENCE_RECORD: "evidence_ids",
        EvidenceLocator.SOURCE_RECORD: "source_ids",
    }
    if row.get("aggregate_value") == 0:
        for locator, column in columns.items():
            if locator not in requested:
                continue
            value = row[column]
            if value not in (None, (), []):
                raise SqlResultMappingError("RETURNED_ZERO_COUNT_LINEAGE_NOT_EMPTY")
        for column in ("observation_lineage_refs", "relation_lineage_refs"):
            if column in row and row[column] not in (None, (), []):
                raise SqlResultMappingError("RETURNED_ZERO_COUNT_LINEAGE_NOT_EMPTY")
        return

    facts = request.render_manifest.readiness_facts
    if facts is None or facts.public_fund_manifest is None:
        return
    manifest = facts.public_fund_manifest
    population = set(entity_ids)
    ownerships = tuple(
        item
        for item in manifest.population_metric_ownerships
        if item.representative_id in population
    )
    edges = tuple(
        item
        for item in manifest.representative_share_edges
        if item.representative_id in population
    )
    if population != {item.representative_id for item in ownerships}:
        raise SqlResultMappingError("RETURNED_REPRESENTATIVE_LINEAGE_MISMATCH")
    expected = {
        EvidenceLocator.METRIC_DEFINITION: {
            f"{item.metric_id}:{item.metric_definition_version}"
            for item in ownerships
        },
        EvidenceLocator.OBSERVATION_RECORD: {
            item.observation_id for item in ownerships
        },
        EvidenceLocator.RELATION_RECORD: {item.relation_id for item in edges},
        EvidenceLocator.EVIDENCE_RECORD: {
            *(item.evidence_id for item in ownerships),
            *(item.evidence_id for item in edges),
        },
        EvidenceLocator.SOURCE_RECORD: {
            *(item.source_id for item in ownerships),
            *(item.source_id for item in edges),
        },
    }
    for locator, column in columns.items():
        if locator not in requested:
            continue
        actual = set(
            _identifier_array(
                row[column], f"RETURNED_{column.upper()}_MALFORMED"
            )
        )
        if actual != expected[locator]:
            code = (
                "RETURNED_METRIC_DEFINITION_OWNERSHIP_MISMATCH"
                if locator is EvidenceLocator.METRIC_DEFINITION
                else "RETURNED_REPRESENTATIVE_LINEAGE_MISMATCH"
            )
            raise SqlResultMappingError(code)
    expected_tuple_refs = {
        "observation_lineage_refs": {
            population_metric_ownership_lineage_ref(item) for item in ownerships
        },
        "relation_lineage_refs": {
            representative_share_edge_lineage_ref(item) for item in edges
        },
    }
    for column, expected_refs in expected_tuple_refs.items():
        if column not in row:
            raise SqlResultMappingError("RETURNED_REPRESENTATIVE_LINEAGE_MISMATCH")
        actual_refs = set(
            _identifier_array(
                row[column], f"RETURNED_{column.upper()}_MALFORMED"
            )
        )
        if actual_refs != expected_refs:
            raise SqlResultMappingError("RETURNED_REPRESENTATIVE_LINEAGE_MISMATCH")


def _validate_evidence_categories(request, rows, lineage: set[str]) -> None:
    if not rows:
        return
    operation = request.render_manifest.logical_task.operation
    if (
        isinstance(operation, LogicalAggregateOperationV2)
        and operation.aggregation.function_id is AggregationFunction.COUNT
        and len(rows) == 1
        and rows[0].get("aggregate_value") == 0
    ):
        return
    prefix_by_locator = {
        EvidenceLocator.METRIC_DEFINITION: "metric-definition:",
        EvidenceLocator.OBSERVATION_RECORD: "observation:",
        EvidenceLocator.RELATION_RECORD: "relation:",
        EvidenceLocator.EVIDENCE_RECORD: "evidence:",
        EvidenceLocator.SOURCE_RECORD: "source:",
    }
    requested = set(request.evidence_projection_ids)
    actual = {
        locator
        for locator, prefix in prefix_by_locator.items()
        if any(item.startswith(prefix) for item in lineage)
    }
    if actual != requested:
        raise SqlResultMappingError("RETURNED_EVIDENCE_PROJECTION_MISMATCH")


def _row_key(operation, row, descriptors):
    if not isinstance(operation, LogicalAggregateOperationV2):
        return ("entity", row["product_id"])
    groups = tuple(row[f"group_{index}"] for index, item in enumerate(descriptors) if item[2] == "group")
    return ("aggregate", *groups)


def _validate_cardinality(request, rows: list[ResultRow]) -> None:
    operation = request.render_manifest.logical_task.operation
    if isinstance(operation, LogicalRankOperationV2):
        limit = operation.limit if operation.limit is not None else 5
        if len(rows) > limit:
            raise SqlResultMappingError("RETURNED_CARDINALITY_EXCEEDED")
    elif isinstance(operation, LogicalCompareOperationV2):
        if len(rows) > len(operation.comparison.subject_refs):
            raise SqlResultMappingError("RETURNED_CARDINALITY_EXCEEDED")
    elif isinstance(operation, LogicalAggregateOperationV2):
        grouped = bool(operation.aggregation.group_by_field_concept_ids)
        if not grouped and len(rows) != 1:
            raise SqlResultMappingError("RETURNED_CARDINALITY_MISMATCH")


def _predicate_concepts(predicate) -> tuple[str, ...]:
    if predicate is None:
        return ()
    field = getattr(predicate, "field_concept_id", None)
    if field is not None:
        return (field,)
    child = getattr(predicate, "child", None)
    if child is not None:
        return _predicate_concepts(child)
    values = []
    for item in getattr(predicate, "children", ()):
        for concept in _predicate_concepts(item):
            if concept not in values:
                values.append(concept)
    return tuple(values)


def _typed_value(value: object, kind: SemanticValueKind):
    valid = {
        SemanticValueKind.DECIMAL: lambda item: isinstance(item, Decimal) and not isinstance(item, bool),
        SemanticValueKind.INTEGER: lambda item: isinstance(item, int) and not isinstance(item, bool),
        SemanticValueKind.STRING: lambda item: isinstance(item, str),
        SemanticValueKind.IDENTIFIER: lambda item: isinstance(item, str),
        SemanticValueKind.BOOLEAN: lambda item: isinstance(item, bool),
        SemanticValueKind.DATE: lambda item: isinstance(item, date)
        and not isinstance(item, datetime),
    }.get(kind)
    if valid is None or not valid(value):
        raise SqlResultMappingError("RETURNED_VALUE_TYPE_MISMATCH")
    return value


def _identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise SqlResultMappingError("RETURNED_IDENTIFIER_MALFORMED")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise SqlResultMappingError("RETURNED_VALUE_TYPE_MISMATCH")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, date):
        raise SqlResultMappingError("RETURNED_VALUE_TYPE_MISMATCH")
    return value


def _identifier_array(value: object, code: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(isinstance(item, (list, tuple)) for item in value):
        raise SqlResultMappingError(code)
    values = tuple(_identifier(item) for item in value)
    if len(set(values)) != len(values):
        raise SqlResultMappingError(code)
    return values


def _optional_scalar_array(value: object, code: str, *, date_only: bool = False):
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(isinstance(item, (list, tuple)) for item in value):
        raise SqlResultMappingError(code)
    if value and all(item is None for item in value):
        return ()
    if any(item is None for item in value):
        raise SqlResultMappingError(code)
    values = tuple(value)
    if len(set(values)) > 1:
        raise SqlResultMappingError(code)
    if date_only:
        if any(not isinstance(item, date) for item in values):
            raise SqlResultMappingError(code)
    elif any(not isinstance(item, str) for item in values):
        raise SqlResultMappingError(code)
    return values[:1]


def _missing_reason(row, *, prefix: str, index: int, value: object) -> str | None:
    if isinstance(value, str) and value.strip() in _SENTINEL_TEXT:
        return "SENTINEL_VALUE"
    if prefix != "field" or f"value_status_{index}" not in row:
        return "MISSING_VALUE" if value is None else None
    status = row[f"value_status_{index}"]
    reason = row[f"reason_code_{index}"]
    if status in {"present", "zero"}:
        if value is None or reason is not None:
            raise SqlResultMappingError("RETURNED_VALUE_STATUS_MISMATCH")
        return None
    reason_by_status = {
        "missing": "SOURCE_VALUE_MISSING",
        "placeholder": "SOURCE_VALUE_PLACEHOLDER",
        "unavailable": "SOURCE_VALUE_UNAVAILABLE",
        "inapplicable": "SOURCE_VALUE_INAPPLICABLE",
        "unknown": "SOURCE_VALUE_UNKNOWN",
    }
    if status not in reason_by_status or value is not None or not isinstance(reason, str) or not reason:
        raise SqlResultMappingError("RETURNED_VALUE_STATUS_MISMATCH")
    return reason_by_status[status]
