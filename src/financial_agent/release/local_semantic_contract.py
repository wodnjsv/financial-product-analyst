"""Independently check grounded local rows against their approved SQL task."""

from __future__ import annotations

from collections.abc import Sequence

from financial_agent.contracts.values import decode_contract_value
from financial_agent.intent.query_contracts import (
    OrderingDirection, PredicateAllOfV2, PredicateAnyOfV2, PredicateAtomV2,
    PredicateNotV2, QueryOperatorId,
)
from financial_agent.planning.logical_query import (
    LogicalCompareOperationV2, LogicalLookupOperationV2, LogicalRankOperationV2,
    LogicalScreenOperationV2,
)
from financial_agent.planning.physical_bindings import SemanticQualifierId
from financial_agent.sql.contracts import CompiledSqlRequest
from financial_agent.sql.lowering import SqlCompileRejection, lower_semantic_value

from .local_semantic_results import VerifiedSemanticRow


class LocalSemanticContractError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def validate_semantic_task(
    request: CompiledSqlRequest, verified_rows: Sequence[VerifiedSemanticRow], *,
    total_count: int, display_limit: int,
) -> tuple[str, ...]:
    """Verify returned scope/order, not the true top-N of an unseen population."""
    manifest = request.render_manifest
    task = manifest.logical_task
    operation = task.operation
    if not isinstance(operation, (
        LogicalLookupOperationV2, LogicalScreenOperationV2,
        LogicalRankOperationV2, LogicalCompareOperationV2,
    )):
        raise LocalSemanticContractError('LOCAL_RESULT_OPERATION_UNSUPPORTED')
    if (type(total_count) is not int or total_count < 0
            or type(display_limit) is not int or not 1 <= display_limit <= 50):
        raise LocalSemanticContractError('LOCAL_RESULT_COUNT_INVALID')
    products = [row.row.entity_ids[0] if len(row.row.entity_ids) == 1 else None
                for row in verified_rows]
    if None in products:
        raise LocalSemanticContractError('LOCAL_RESULT_SCOPE_MISMATCH')
    if len(set(products)) != len(products):
        raise LocalSemanticContractError('LOCAL_RESULT_DUPLICATE_SUBJECT')
    bounded = manifest.screen_display_limit
    if (bounded is not None and (display_limit != bounded or len(products) != min(total_count, bounded))
            or bounded is None and total_count != len(products)):
        raise LocalSemanticContractError('LOCAL_RESULT_COUNT_INVALID')
    bindings = {binding.semantic_concept_id: binding for binding in manifest.binding_definitions}
    families = {family.value for family in manifest.effective_product_family_ids}
    predicate = getattr(operation, 'predicate', None)
    expected_fields = set(_predicate_fields(predicate))
    if isinstance(operation, LogicalLookupOperationV2):
        expected_fields.update(operation.projections.field_concept_ids)
    elif isinstance(operation, LogicalRankOperationV2):
        expected_fields.update(item.field_concept_id for item in operation.ordering)
    elif isinstance(operation, LogicalCompareOperationV2):
        expected_fields.update(operation.comparison.metric_concept_ids)
    values_by_row = []
    for verified, product in zip(verified_rows, products, strict=True):
        if (task.scope.entity_refs and product not in task.scope.entity_refs
                or task.scope.prior_result_binding and (
                    manifest.prior_result_entity_ids is None or product not in manifest.prior_result_entity_ids)
                or isinstance(operation, LogicalCompareOperationV2)
                and product not in operation.comparison.subject_refs
                or not verified.facts or any(
                    fact.get('subject_product_family') not in families for fact in verified.facts)):
            raise LocalSemanticContractError('LOCAL_RESULT_SCOPE_MISMATCH')
        fields = {field.field_id: field for field in verified.row.fields if field.field_id != 'product_name'}
        missing = {field for field, _ in verified.missing_fields}
        if (len(fields) + 1 != len(verified.row.fields) or fields.keys() & missing
                or len(missing) != len(verified.missing_fields)
                or fields.keys() | missing != expected_fields):
            raise LocalSemanticContractError('LOCAL_RESULT_FIELD_MISMATCH')
        values = {}
        for concept in fields.keys() | missing:
            binding = bindings.get(concept)
            if binding is None:
                raise LocalSemanticContractError('LOCAL_RESULT_FIELD_MISMATCH')
            facts = [fact for fact in verified.facts if fact.get('evidence_kind') == 'observation'
                     and fact.get('metric_id') in binding.approved_metric_ids]
            if not facts:
                raise LocalSemanticContractError('LOCAL_RESULT_FIELD_MISMATCH')
            value = decode_contract_value(fields[concept].value) if concept in fields else None
            statuses = {fact['value_status'] for fact in facts}
            if len(statuses) != 1:
                raise LocalSemanticContractError('LOCAL_RESULT_FIELD_MISMATCH')
            values[concept] = (value, next(iter(statuses)))
            _qualifiers(task.qualifiers, binding, facts)
        if predicate is not None and _predicate(predicate, values, bindings) is not True:
            raise LocalSemanticContractError('LOCAL_RESULT_PREDICATE_MISMATCH')
        values_by_row.append(values)
    rules = ['local-scope.v1', 'local-cardinality.v1', 'local-qualifiers.v1']
    if predicate is not None:
        rules.append('local-predicate.v1')
    if isinstance(operation, LogicalRankOperationV2):
        _rank(operation, products, values_by_row)
        rules.append('local-rank-order.v1')
    return tuple(rules)


def _predicate_fields(node):
    if node is None:
        return ()
    if isinstance(node, PredicateAtomV2):
        return (node.field_concept_id,)
    if isinstance(node, PredicateNotV2):
        return _predicate_fields(node.child)
    return tuple(field for child in node.children for field in _predicate_fields(child))


def _qualifiers(qualifiers, binding, facts):
    supported = set(binding.supported_qualifier_ids)
    for fact in facts:
        mismatch = (
            qualifiers.as_of_date is not None and SemanticQualifierId.AS_OF in supported
            and fact['observation_date'] != qualifiers.as_of_date
            or qualifiers.currency_id is not None and SemanticQualifierId.CURRENCY in supported
            and fact['observation_currency'] != qualifiers.currency_id
            or qualifiers.unit_id is not None and SemanticQualifierId.UNIT in supported
            and qualifiers.unit_id in binding.accepted_semantic_unit_ids
            and fact['observation_unit'] != binding.storage_unit_id
        )
        if qualifiers.period_id is not None and SemanticQualifierId.PERIOD in supported:
            mismatch = mismatch or (
                qualifiers.period_id != 'P1Y'
                or binding.semantic_concept_id != 'trailing_1y_historical_cumulative_return'
                or fact['period_end'] != fact['observation_date']
            )
        if mismatch:
            raise LocalSemanticContractError('LOCAL_RESULT_QUALIFIER_MISMATCH')


def _predicate(node, values, bindings, *, guarded=True):
    """Match SQL three-valued Boolean logic and comparison presence guards."""
    if isinstance(node, PredicateAtomV2):
        binding = bindings.get(node.field_concept_id)
        if (binding is None or node.operator_id not in binding.supported_operator_ids
                or node.null_policy_id != binding.missingness_policy_id):
            raise LocalSemanticContractError('LOCAL_RESULT_PREDICATE_UNSUPPORTED')
        if node.field_concept_id not in values:
            raise LocalSemanticContractError('LOCAL_RESULT_FIELD_MISMATCH')
        value, status = values[node.field_concept_id]
        present = status in ('present', 'zero') and value is not None
        operator = node.operator_id
        if operator is QueryOperatorId.IS_PRESENT:
            return present
        if operator is QueryOperatorId.IS_MISSING:
            return status in ('missing', 'placeholder', 'unavailable', 'inapplicable', 'unknown') and value is None
        try:
            operands = [lower_semantic_value(item, binding) for item in (
                (node.value,) if node.value is not None else node.values)]
        except SqlCompileRejection:
            raise LocalSemanticContractError('LOCAL_RESULT_PREDICATE_UNSUPPORTED') from None
        if not present:
            return False if guarded else None
        try:
            if operator is QueryOperatorId.EQ:
                return value == operands[0]
            if operator is QueryOperatorId.NEQ:
                return value != operands[0]
            if operator is QueryOperatorId.LT:
                return value < operands[0]
            if operator is QueryOperatorId.LTE:
                return value <= operands[0]
            if operator is QueryOperatorId.GT:
                return value > operands[0]
            if operator is QueryOperatorId.GTE:
                return value >= operands[0]
            if operator is QueryOperatorId.BETWEEN:
                return operands[0] <= value <= operands[1]
            if operator is QueryOperatorId.IN:
                return value in operands
            if operator is QueryOperatorId.NOT_IN:
                return value not in operands
        except TypeError:
            raise LocalSemanticContractError('LOCAL_RESULT_PREDICATE_MISMATCH') from None
        raise LocalSemanticContractError('LOCAL_RESULT_PREDICATE_UNSUPPORTED')
    if isinstance(node, PredicateNotV2):
        core = _predicate(node.child, values, bindings, guarded=False)
        if guarded and not _comparisons_present(node.child, values):
            return False
        return None if core is None else not core
    children = [_predicate(child, values, bindings, guarded=guarded) for child in node.children]
    if isinstance(node, PredicateAllOfV2):
        return False if False in children else (None if None in children else True)
    if isinstance(node, PredicateAnyOfV2):
        return True if True in children else (None if None in children else False)
    raise LocalSemanticContractError('LOCAL_RESULT_PREDICATE_UNSUPPORTED')


def _comparisons_present(node, values):
    if isinstance(node, PredicateAtomV2):
        if node.operator_id in (QueryOperatorId.IS_MISSING, QueryOperatorId.IS_PRESENT):
            return True
        value, status = values[node.field_concept_id]
        return status in ('present', 'zero') and value is not None
    if isinstance(node, PredicateNotV2):
        return _comparisons_present(node.child, values)
    return all(_comparisons_present(child, values) for child in node.children)


def _rank(operation, products, rows):
    limit = operation.limit
    if limit is None:
        if operation.limit_policy_id != 'default-limit-5.v1':
            raise LocalSemanticContractError('LOCAL_RESULT_RANK_INVALID')
        limit = 5
    if len(rows) > limit:
        raise LocalSemanticContractError('LOCAL_RESULT_RANK_INVALID')
    for ordering in operation.ordering:
        if (ordering.nulls_policy_id != 'exclude_missing.v1'
                or ordering.tie_break_policy_id != 'stable-product-id.v1'
                or ordering.direction is None
                and ordering.direction_policy_id != 'default-direction-descending.v1'):
            raise LocalSemanticContractError('LOCAL_RESULT_RANK_INVALID')
        if any(ordering.field_concept_id not in row
               or row[ordering.field_concept_id][0] is None
               or row[ordering.field_concept_id][1] not in ('present', 'zero') for row in rows):
            raise LocalSemanticContractError('LOCAL_RESULT_RANK_INVALID')
    for index in range(1, len(rows)):
        ordered = False
        for ordering in operation.ordering:
            left = rows[index - 1][ordering.field_concept_id][0]
            right = rows[index][ordering.field_concept_id][0]
            if left == right:
                continue
            direction = ordering.direction or OrderingDirection.DESC
            if (left > right if direction is OrderingDirection.ASC else left < right):
                raise LocalSemanticContractError('LOCAL_RESULT_RANK_INVALID')
            ordered = True
            break
        if not ordered and products[index - 1] > products[index]:
            raise LocalSemanticContractError('LOCAL_RESULT_RANK_INVALID')
