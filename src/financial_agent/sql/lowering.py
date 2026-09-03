"""Closed physical lowering helpers for normalized SQLAlchemy tables."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

import sqlalchemy as sa

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.values import encode_contract_value
from financial_agent.db.schema.evidence import (
    evidence_record,
    evidence_relation_origin,
    source_record,
)
from financial_agent.db.schema.observation import observation_record
from financial_agent.db.schema.relation import relation_record
from financial_agent.intent.query_contracts import (
    PredicateAllOfV2,
    PredicateAnyOfV2,
    PredicateAtomV2,
    PredicateNodeV2,
    PredicateNotV2,
    QueryOperatorId,
    SemanticValueKind,
    TypedSemanticValue,
)
from financial_agent.planning.physical_bindings import (
    ObservationValueColumn,
    PhysicalBindingDefinition,
    PhysicalReadinessFacts,
    SemanticSqlPolicyRegistry,
    TRUSTED_PUBLIC_FUND_MANIFEST_PINS,
)

from .contracts import (
    DeferredSqlParameter,
    SqlParameter,
    SqlParameterInput,
    SqlValueKind,
)


# Enum values are registry data; columns are imported code objects. Registry strings
# are never passed to getattr(), text(), literal_column(), or identifier constructors.
OBSERVATION_VALUE_COLUMNS = {
    ObservationValueColumn.DECIMAL: observation_record.c.numeric_value,
    ObservationValueColumn.INTEGER: observation_record.c.numeric_value,
    ObservationValueColumn.TEXT: observation_record.c.text_value,
    ObservationValueColumn.BOOLEAN: observation_record.c.boolean_value,
    ObservationValueColumn.DATE: observation_record.c.date_value,
}


class SqlCompileRejection(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class ParameterBuilder:
    parameters: list[SqlParameterInput] = field(default_factory=list)
    _counter: int = 0

    def bind(self, value, *, prefix: str = "value") -> sa.BindParameter:
        name = f"{prefix}_{self._counter}"
        self._counter += 1
        tagged = encode_contract_value(value)
        self.parameters.append(
            SqlParameter(
                name=name,
                value=tagged,
                value_kind=SqlValueKind(tagged.type),
            )
        )
        return sa.bindparam(name)

    def bind_prior_result(
        self,
        binding_id: str,
        entity_ids: tuple[str, ...] | None,
    ) -> sa.BindParameter:
        name = f"prior_result_{self._counter}"
        self._counter += 1
        if entity_ids is None:
            self.parameters.append(
                DeferredSqlParameter(name=name, binding_id=binding_id)
            )
        else:
            self.parameters.append(
                SqlParameter(
                    name=name,
                    value=encode_contract_value(entity_ids),
                    value_kind=SqlValueKind.TUPLE,
                )
            )
        return sa.bindparam(name, type_=sa.ARRAY(sa.String()))


def physical_value_column(binding: PhysicalBindingDefinition):
    if binding.value_column is None:
        raise SqlCompileRejection("PHYSICAL_VALUE_COLUMN_REQUIRED")
    column = OBSERVATION_VALUE_COLUMNS.get(binding.value_column)
    if column is None:
        raise SqlCompileRejection("PHYSICAL_VALUE_COLUMN_NOT_MAPPED")
    return column


def lower_predicate(
    predicate: PredicateNodeV2,
    *,
    expression_for: Callable[[str], tuple[sa.ColumnElement, PhysicalBindingDefinition, sa.ColumnElement]],
    parameters: ParameterBuilder,
) -> sa.ColumnElement:
    if isinstance(predicate, PredicateAtomV2):
        return _lower_atom_with_guard(
            predicate,
            expression_for=expression_for,
            parameters=parameters,
        )
    if isinstance(predicate, PredicateNotV2):
        core = _lower_boolean_core(
            predicate.child,
            expression_for=expression_for,
            parameters=parameters,
        )
        guards = _comparison_presence_guards(
            predicate.child,
            expression_for=expression_for,
            parameters=parameters,
        )
        negated = sa.not_(core)
        return sa.and_(*guards, negated) if guards else negated
    children = tuple(
        lower_predicate(child, expression_for=expression_for, parameters=parameters)
        for child in predicate.children
    )
    if isinstance(predicate, PredicateAllOfV2):
        return sa.and_(*children)
    if isinstance(predicate, PredicateAnyOfV2):
        return sa.or_(*children)
    raise SqlCompileRejection("PREDICATE_NODE_UNSUPPORTED")


def _lower_boolean_core(
    predicate: PredicateNodeV2,
    *,
    expression_for: Callable[
        [str], tuple[sa.ColumnElement, PhysicalBindingDefinition, sa.ColumnElement]
    ],
    parameters: ParameterBuilder,
) -> sa.ColumnElement:
    if isinstance(predicate, PredicateAtomV2):
        expression, binding, status = _validated_atom_parts(predicate, expression_for)
        return _lower_atom_core(predicate, expression, status, binding, parameters)
    if isinstance(predicate, PredicateNotV2):
        return sa.not_(
            _lower_boolean_core(
                predicate.child,
                expression_for=expression_for,
                parameters=parameters,
            )
        )
    children = tuple(
        _lower_boolean_core(
            child,
            expression_for=expression_for,
            parameters=parameters,
        )
        for child in predicate.children
    )
    if isinstance(predicate, PredicateAllOfV2):
        return sa.and_(*children)
    if isinstance(predicate, PredicateAnyOfV2):
        return sa.or_(*children)
    raise SqlCompileRejection("PREDICATE_NODE_UNSUPPORTED")


def _comparison_presence_guards(
    predicate: PredicateNodeV2,
    *,
    expression_for: Callable[
        [str], tuple[sa.ColumnElement, PhysicalBindingDefinition, sa.ColumnElement]
    ],
    parameters: ParameterBuilder,
) -> tuple[sa.ColumnElement, ...]:
    if isinstance(predicate, PredicateAtomV2):
        _, _, status = _validated_atom_parts(predicate, expression_for)
        if predicate.operator_id in {
            QueryOperatorId.IS_MISSING,
            QueryOperatorId.IS_PRESENT,
        }:
            return ()
        return (_present_status(status, parameters),)
    if isinstance(predicate, PredicateNotV2):
        return _comparison_presence_guards(
            predicate.child,
            expression_for=expression_for,
            parameters=parameters,
        )
    return tuple(
        guard
        for child in predicate.children
        for guard in _comparison_presence_guards(
            child,
            expression_for=expression_for,
            parameters=parameters,
        )
    )


def _lower_atom_with_guard(
    atom: PredicateAtomV2,
    *,
    expression_for: Callable[
        [str], tuple[sa.ColumnElement, PhysicalBindingDefinition, sa.ColumnElement]
    ],
    parameters: ParameterBuilder,
) -> sa.ColumnElement:
    expression, binding, status = _validated_atom_parts(atom, expression_for)
    core = _lower_atom_core(atom, expression, status, binding, parameters)
    if atom.operator_id in {QueryOperatorId.IS_MISSING, QueryOperatorId.IS_PRESENT}:
        return core
    return sa.and_(_present_status(status, parameters), core)


def _validated_atom_parts(atom, expression_for):
    expression, binding, status = expression_for(atom.field_concept_id)
    if atom.operator_id not in binding.supported_operator_ids:
        raise SqlCompileRejection("PHYSICAL_OPERATOR_UNSUPPORTED")
    if atom.null_policy_id != binding.missingness_policy_id:
        raise SqlCompileRejection("MISSINGNESS_POLICY_MISMATCH")
    return expression, binding, status


def lower_semantic_value(
    value: TypedSemanticValue,
    binding: PhysicalBindingDefinition,
):
    if value.kind is not binding.semantic_value_kind:
        raise SqlCompileRejection("PHYSICAL_VALUE_KIND_MISMATCH")
    if value.unit_id is not None and value.unit_id not in binding.accepted_semantic_unit_ids:
        raise SqlCompileRejection("SEMANTIC_UNIT_NOT_SUPPORTED")
    raw = {
        SemanticValueKind.STRING: value.string,
        SemanticValueKind.INTEGER: value.integer,
        SemanticValueKind.DECIMAL: Decimal(value.decimal) if value.decimal is not None else None,
        SemanticValueKind.BOOLEAN: value.boolean,
        SemanticValueKind.DATE: value.date,
        SemanticValueKind.DATETIME: value.datetime,
        SemanticValueKind.IDENTIFIER: value.identifier,
    }[value.kind]
    if binding.unit_conversion_policy_id == "semantic-percent-to-percentage-point.v1":
        if value.unit_id != "percent" or binding.storage_unit_id != "percentage_point":
            raise SqlCompileRejection("UNIT_CONVERSION_POLICY_MISMATCH")
        return raw
    if binding.unit_conversion_policy_id == "identity-unit.v1":
        return raw
    raise SqlCompileRejection("UNIT_CONVERSION_POLICY_UNSUPPORTED")


def verified_public_fund_proof(
    facts: PhysicalReadinessFacts | None,
    *,
    dataset_pin: str,
    policies: SemanticSqlPolicyRegistry,
    metric_ids: tuple[str, ...],
) -> bool:
    if facts is None or facts.public_fund_manifest is None or facts.public_fund_manifest_hash is None:
        return False
    manifest = facts.public_fund_manifest
    computed = canonical_sha256(manifest)
    if facts.public_fund_manifest_hash != computed:
        return False
    if TRUSTED_PUBLIC_FUND_MANIFEST_PINS.get(manifest.manifest_id) != (dataset_pin, computed):
        return False
    if (
        manifest.dataset_pin != dataset_pin
        or manifest.physical_policy_registry_version != policies.registry_version
        or manifest.physical_policy_registry_hash != policies.registry_hash
        or manifest.population_grain_policy_id != "representative-product.v1"
        or manifest.dedup_policy_id != "public-fund-representative-share.v1"
    ):
        return False
    sources = {item.source_id: item for item in manifest.source_records}
    evidence = {item.evidence_id: item for item in manifest.evidence_records}
    shares = set(manifest.authoritative_share_class_ids)
    edges = manifest.representative_share_edges
    if {edge.share_class_id for edge in edges} != shares:
        return False
    if any(
        edge.dataset_pin != dataset_pin
        or edge.predicate_id != "hasShareClass"
        or edge.evidence_id not in evidence
        or edge.source_id not in sources
        or evidence[edge.evidence_id].source_id != edge.source_id
        for edge in edges
    ):
        return False
    ownership = manifest.population_metric_ownerships
    return all(
        any(
            item.metric_id == metric_id
            and item.dataset_pin == dataset_pin
            and item.owner_entity_id == item.representative_id
            and item.evidence_id in evidence
            and item.source_id in sources
            and evidence[item.evidence_id].source_id == item.source_id
            for item in ownership
        )
        for metric_id in metric_ids
    )


def representative_product_cte(
    parameters: ParameterBuilder,
    facts: PhysicalReadinessFacts,
    *,
    dataset_version: str,
    prior_result_binding: str | None = None,
    prior_result_entity_ids: tuple[str, ...] | None = None,
):
    manifest = facts.public_fund_manifest
    if manifest is None:
        raise SqlCompileRejection("PUBLIC_FUND_VERIFIED_PROOF_REQUIRED")
    exact_edges = tuple(
        sa.and_(
            relation_record.c.relation_id
            == parameters.bind(edge.relation_id, prefix="relation_id"),
            relation_record.c.subject_id
            == parameters.bind(edge.representative_id, prefix="representative_id"),
            relation_record.c.object_id
            == parameters.bind(edge.share_class_id, prefix="share_class_id"),
            relation_record.c.predicate_id
            == parameters.bind(edge.predicate_id, prefix="relation_predicate"),
            evidence_relation_origin.c.evidence_id
            == parameters.bind(edge.evidence_id, prefix="relation_evidence_id"),
            evidence_record.c.source_id
            == parameters.bind(edge.source_id, prefix="relation_source_id"),
        )
        for edge in manifest.representative_share_edges
    )
    where = [
        relation_record.c.dataset_version
        == parameters.bind(dataset_version, prefix="manifest_dataset"),
        sa.or_(*exact_edges),
    ]
    if prior_result_binding is not None:
        prior_result = parameters.bind_prior_result(
            prior_result_binding,
            prior_result_entity_ids,
        )
        where.append(
            sa.or_(
                relation_record.c.subject_id == sa.any_(prior_result),
                relation_record.c.object_id == sa.any_(prior_result),
            )
        )
    return (
        sa.select(
            relation_record.c.dataset_version,
            relation_record.c.subject_id.label("entity_id"),
        )
        .select_from(
            relation_record.join(
                evidence_relation_origin,
                sa.and_(
                    evidence_relation_origin.c.dataset_version
                    == relation_record.c.dataset_version,
                    evidence_relation_origin.c.relation_id
                    == relation_record.c.relation_id,
                ),
            )
            .join(
                evidence_record,
                sa.and_(
                    evidence_record.c.dataset_version
                    == evidence_relation_origin.c.dataset_version,
                    evidence_record.c.evidence_id
                    == evidence_relation_origin.c.evidence_id,
                ),
            )
            .join(
                source_record,
                sa.and_(
                    source_record.c.dataset_version == evidence_record.c.dataset_version,
                    source_record.c.source_id == evidence_record.c.source_id,
                ),
            )
        )
        .where(*where)
        .distinct()
        .cte("representative_product")
    )


def _lower_atom_core(
    atom: PredicateAtomV2,
    expression: sa.ColumnElement,
    status: sa.ColumnElement,
    binding: PhysicalBindingDefinition,
    parameters: ParameterBuilder,
) -> sa.ColumnElement:
    operator = atom.operator_id
    if operator is QueryOperatorId.IS_MISSING:
        missing = tuple(
            parameters.bind(item, prefix="status")
            for item in ("missing", "placeholder", "unavailable", "inapplicable", "unknown")
        )
        return sa.and_(status.in_(missing), expression.is_(None))
    if operator is QueryOperatorId.IS_PRESENT:
        present = tuple(
            parameters.bind(item, prefix="status") for item in ("present", "zero")
        )
        return sa.and_(status.in_(present), expression.is_not(None))
    values = tuple(
        lower_semantic_value(item, binding)
        for item in ((atom.value,) if atom.value is not None else atom.values)
    )
    bound = tuple(parameters.bind(item) for item in values)
    if operator is QueryOperatorId.EQ:
        comparison = expression == bound[0]
    if operator is QueryOperatorId.NEQ:
        comparison = expression != bound[0]
    if operator is QueryOperatorId.LT:
        comparison = expression < bound[0]
    if operator is QueryOperatorId.LTE:
        comparison = expression <= bound[0]
    if operator is QueryOperatorId.GT:
        comparison = expression > bound[0]
    if operator is QueryOperatorId.GTE:
        comparison = expression >= bound[0]
    if operator is QueryOperatorId.BETWEEN:
        comparison = expression.between(bound[0], bound[1])
    if operator is QueryOperatorId.IN:
        comparison = expression.in_(bound)
    if operator is QueryOperatorId.NOT_IN:
        comparison = expression.not_in(bound)
    if operator is QueryOperatorId.CONTAINS:
        comparison = expression.contains(bound[0], autoescape=False)
    if operator not in {
        QueryOperatorId.EQ, QueryOperatorId.NEQ, QueryOperatorId.LT,
        QueryOperatorId.LTE, QueryOperatorId.GT, QueryOperatorId.GTE,
        QueryOperatorId.BETWEEN, QueryOperatorId.IN, QueryOperatorId.NOT_IN,
        QueryOperatorId.CONTAINS,
    }:
        raise SqlCompileRejection("PHYSICAL_OPERATOR_UNSUPPORTED")
    return comparison


def _present_status(
    status: sa.ColumnElement,
    parameters: ParameterBuilder,
) -> sa.ColumnElement:
    return status.in_(
        tuple(parameters.bind(item, prefix="status") for item in ("present", "zero"))
    )
