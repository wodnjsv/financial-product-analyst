from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_agent.contracts.enums import (
    Cardinality,
    ReferenceMentionType,
    ReferenceTargetKind as PlanReferenceTargetKind,
)
from financial_agent.contracts.query import (
    BindingSpec,
    DependencyEdge,
    EntityResolutionRequest,
    FilterSpec,
    MetricSpec,
    ResolvedReference,
)
from financial_agent.contracts.values import encode_contract_value
from financial_agent.intent.draft import SlotAssignment
from financial_agent.intent.resolution import ValidatedIntentResolutionV2
from financial_agent.intent.types import SlotKind, SlotMutationKind, SourceRole
from financial_agent.intent.view import ResolverView, ResolverViewLiteralCandidate

from .contracts import LoweringRecord


_MANY_ROLES = frozenset(
    {
        SourceRole.CANDIDATES,
        SourceRole.TOP_K_PRODUCTS,
        SourceRole.EXCLUDED_PRODUCTS,
        SourceRole.EVIDENCE_RECORDS,
    }
)


class LoweringError(ValueError):
    def __init__(self, code: str, related_ids: tuple[str, ...] = ()) -> None:
        self.code = code
        self.related_ids = related_ids
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LoweredInputs:
    assignments_by_frame: dict[str, tuple[SlotAssignment, ...]]
    entity_requests: tuple[EntityResolutionRequest, ...]
    resolved_references: tuple[ResolvedReference, ...]
    binding_specs: tuple[BindingSpec, ...]
    dependency_edges: tuple[DependencyEdge, ...]
    filters: tuple[FilterSpec, ...]
    metrics: tuple[MetricSpec, ...]
    link_parameters_by_frame: dict[str, tuple[str, ...]]
    records: tuple[LoweringRecord, ...]


def lower_inputs(
    resolution: ValidatedIntentResolutionV2,
    view: ResolverView,
) -> LoweredInputs:
    assignments_by_frame = _effective_assignments(resolution)
    literals = {item.literal_id: item for item in view.literal_candidates}
    filters: list[FilterSpec] = []
    metrics: list[MetricSpec] = []
    records: list[LoweringRecord] = []
    concept_ids = {item.concept_id for item in view.concept_definitions}

    for frame in resolution.canonical_frames:
        assignments = assignments_by_frame[frame.frame_id]
        by_kind = _by_kind(assignments)
        grouped_filters, consumed_filter_assignment_ids, filter_records = (
            _lower_filter_groups(frame.frame_id, assignments, literals)
        )
        filters.extend(grouped_filters)
        records.extend(filter_records)
        period_id = _one_canonical(by_kind.get(SlotKind.PERIOD, ()), literals)
        unit_id = _one_value(by_kind.get(SlotKind.UNIT, ()))
        currency = _one_canonical(by_kind.get(SlotKind.CURRENCY, ()), literals)
        for assignment in assignments:
            if assignment.slot_assignment_id in consumed_filter_assignment_ids:
                continue
            if assignment.slot_kind in {
                SlotKind.METRIC,
                SlotKind.SORT_KEY,
                SlotKind.COMPARISON_BASIS,
                SlotKind.SIMILARITY_ANCHOR,
            }:
                for metric_id in assignment.value_ids:
                    if metric_id not in concept_ids:
                        raise LoweringError("UNKNOWN_CONCEPT", (metric_id,))
                    metrics.append(
                        MetricSpec(
                            subtask_id=frame.frame_id,
                            metric_id=metric_id,
                            period_id=period_id,
                            unit_id=unit_id,
                            currency=currency,
                        )
                    )
                records.append(
                    LoweringRecord(
                        source_id=assignment.slot_assignment_id,
                        target_kind="metric",
                        target_ids=assignment.value_ids,
                    )
                )
            elif assignment.slot_kind in {
                SlotKind.RESULT_LIMIT,
                SlotKind.SORT_DIRECTION,
                SlotKind.DATE_SCOPE,
            }:
                if len(assignment.value_ids) != 1:
                    raise LoweringError(
                        "INVALID_LITERAL_CARDINALITY",
                        (assignment.slot_assignment_id,),
                    )
                literal = literals.get(assignment.value_ids[0])
                if literal is None:
                    raise LoweringError("UNKNOWN_LITERAL", assignment.value_ids)
                filters.append(
                    FilterSpec(
                        subtask_id=frame.frame_id,
                        field_id=assignment.slot_kind.value,
                        operator_id="assign",
                        value=encode_contract_value(_literal_primitive(literal)),
                    )
                )
                records.append(
                    LoweringRecord(
                        source_id=assignment.slot_assignment_id,
                        target_kind="filter",
                        target_ids=(assignment.slot_kind.value,),
                    )
                )
        records.append(
            LoweringRecord(
                source_id=frame.frame_id,
                target_kind="subtask",
                target_ids=(frame.frame_id,),
            )
        )

    bindings = tuple(
        BindingSpec(
            binding_name=_binding_name(frame.frame_id, role),
            value_type=role.value,
            producer_subtask_id=frame.frame_id,
            cardinality=(
                Cardinality.MANY if role in _MANY_ROLES else Cardinality.ONE
            ),
        )
        for frame in resolution.canonical_frames
        for role in frame.produced_result_roles
    )
    references_by_id = {item.reference_id: item for item in view.reference_candidates}
    resolved_references: list[ResolvedReference] = []
    edges: list[DependencyEdge] = []
    link_parameters: dict[str, list[str]] = {}
    for link in resolution.context_links:
        target = _binding_name(link.producer_frame_id, link.source_role)
        if target not in {item.binding_name for item in bindings}:
            raise LoweringError("MISSING_CONTEXT_BINDING", (link.context_link_id,))
        reference = references_by_id.get(link.reference_id)
        consumer = next(
            item for item in resolution.canonical_frames if item.frame_id == link.consumer_frame_id
        )
        resolved_references.append(
            ResolvedReference(
                reference_id=link.reference_id,
                segment_id=(reference.segment_id if reference else consumer.segment_ids[0]),
                mention_type=(
                    ReferenceMentionType.EXPLICIT
                    if reference
                    else ReferenceMentionType.ELLIPSIS
                ),
                target_kind=PlanReferenceTargetKind.BINDING,
                target_id=target,
            )
        )
        edges.append(
            DependencyEdge(
                upstream_subtask_id=link.producer_frame_id,
                downstream_subtask_id=link.consumer_frame_id,
            )
        )
        params = link_parameters.setdefault(link.consumer_frame_id, [])
        params.append(target)
        params.append(f"link:{link.link_type.value}")
        params.extend(f"selector:{item.value}" for item in link.selector)
        records.append(
            LoweringRecord(
                source_id=link.context_link_id,
                target_kind="context_binding",
                target_ids=(link.reference_id, target),
            )
        )

    entity_requests: list[EntityResolutionRequest] = []
    for hint in resolution.entity_hints:
        if hint.selected_candidate_ids:
            segment_id = _entity_segment_id(hint.evidence_span_ids, view)
            resolved_references.append(
                ResolvedReference(
                    reference_id=hint.entity_hint_id,
                    segment_id=segment_id,
                    mention_type=ReferenceMentionType.EXPLICIT,
                    target_kind=PlanReferenceTargetKind.ENTITY_MENTION,
                    target_id=hint.selected_candidate_ids[0],
                )
            )
            target_ids = hint.selected_candidate_ids
            target_kind = "resolved_entity"
        elif hint.mention_id:
            entity_requests.append(
                EntityResolutionRequest(
                    resolution_request_id=f"resolve:{hint.entity_hint_id}",
                    mention_id=hint.mention_id[0],
                    expected_entity_types=hint.expected_entity_type_ids,
                )
            )
            target_ids = (f"resolve:{hint.entity_hint_id}",)
            target_kind = "entity_request"
        else:
            raise LoweringError("ENTITY_HINT_UNRESOLVED", (hint.entity_hint_id,))
        records.append(
            LoweringRecord(
                source_id=hint.entity_hint_id,
                target_kind=target_kind,
                target_ids=target_ids,
            )
        )

    for frame in resolution.canonical_frames:
        for mutation in frame.slot_mutations:
            records.append(
                LoweringRecord(
                    source_id=mutation.slot_mutation_id,
                    target_kind="slot_mutation",
                    target_ids=(frame.frame_id, mutation.slot_kind.value),
                )
            )

    return LoweredInputs(
        assignments_by_frame=assignments_by_frame,
        entity_requests=tuple(entity_requests),
        resolved_references=tuple(resolved_references),
        binding_specs=bindings,
        dependency_edges=_unique_edges(edges),
        filters=tuple(filters),
        metrics=_unique_metrics(metrics),
        link_parameters_by_frame={
            key: tuple(sorted(set(value))) for key, value in link_parameters.items()
        },
        records=tuple(records),
    )


def _lower_filter_groups(
    frame_id: str,
    assignments: tuple[SlotAssignment, ...],
    literals: dict[str, ResolverViewLiteralCandidate],
) -> tuple[list[FilterSpec], set[str], list[LoweringRecord]]:
    relevant = tuple(
        item
        for item in assignments
        if item.slot_kind
        in {SlotKind.METRIC, SlotKind.FILTER_OPERATOR, SlotKind.FILTER_VALUE}
        and (
            item.slot_kind in {SlotKind.FILTER_OPERATOR, SlotKind.FILTER_VALUE}
            or item.evidence_span_ids
        )
    )
    filter_keys = {
        item.evidence_span_ids
        for item in relevant
        if item.slot_kind in {SlotKind.FILTER_OPERATOR, SlotKind.FILTER_VALUE}
    }
    if not filter_keys:
        return [], set(), []
    if () in filter_keys:
        raise LoweringError("UNPAIRED_FILTER_GROUP")

    filters: list[FilterSpec] = []
    consumed: set[str] = set()
    records: list[LoweringRecord] = []
    for key in sorted(filter_keys):
        grouped = tuple(item for item in relevant if item.evidence_span_ids == key)
        concepts = tuple(item for item in grouped if item.slot_kind is SlotKind.METRIC)
        operators = tuple(
            item for item in grouped if item.slot_kind is SlotKind.FILTER_OPERATOR
        )
        values = tuple(item for item in grouped if item.slot_kind is SlotKind.FILTER_VALUE)
        if (
            len(concepts) != 1
            or len(operators) != 1
            or len(values) != 1
            or len(concepts[0].value_ids) != 1
            or len(operators[0].value_ids) != 1
            or len(values[0].value_ids) != 1
        ):
            raise LoweringError(
                "AMBIGUOUS_FILTER_GROUP",
                tuple(item.slot_assignment_id for item in grouped),
            )
        literal_id = values[0].value_ids[0]
        literal = literals.get(literal_id)
        if literal is None:
            raise LoweringError("UNKNOWN_LITERAL", (literal_id,))
        field_id = concepts[0].value_ids[0]
        filters.append(
            FilterSpec(
                subtask_id=frame_id,
                field_id=field_id,
                operator_id=operators[0].value_ids[0],
                value=encode_contract_value(_literal_primitive(literal)),
            )
        )
        for assignment in (concepts[0], operators[0], values[0]):
            consumed.add(assignment.slot_assignment_id)
            records.append(
                LoweringRecord(
                    source_id=assignment.slot_assignment_id,
                    target_kind="filter",
                    target_ids=(field_id,),
                )
            )
    return filters, consumed, records


def _effective_assignments(
    resolution: ValidatedIntentResolutionV2,
) -> dict[str, tuple[SlotAssignment, ...]]:
    effective: dict[str, dict[SlotKind, list[SlotAssignment]]] = {}
    for frame in resolution.canonical_frames:
        current = _mutable_by_kind(frame.slot_assignments)
        for mutation in frame.slot_mutations:
            kind = mutation.slot_kind
            if mutation.mutation_kind in {
                SlotMutationKind.DELETE,
                SlotMutationKind.DONTCARE,
            }:
                current.pop(kind, None)
            elif mutation.mutation_kind is SlotMutationKind.CARRYOVER:
                if kind not in current:
                    if not mutation.source_frame_id:
                        raise LoweringError(
                            "CARRYOVER_SOURCE_REQUIRED",
                            (mutation.slot_mutation_id,),
                        )
                    source = effective.get(mutation.source_frame_id[0])
                    if source is None or kind not in source:
                        raise LoweringError(
                            "CARRYOVER_SOURCE_MISSING",
                            (mutation.slot_mutation_id,),
                        )
                    current[kind] = list(source[kind])
            elif mutation.mutation_kind is SlotMutationKind.UPDATE and kind not in current:
                raise LoweringError(
                    "UPDATE_VALUE_REQUIRED",
                    (mutation.slot_mutation_id,),
                )
        effective[frame.frame_id] = current
    return {
        frame_id: tuple(
            assignment
            for kind in SlotKind
            for assignment in assignments.get(kind, ())
        )
        for frame_id, assignments in effective.items()
    }


def _mutable_by_kind(
    assignments: tuple[SlotAssignment, ...],
) -> dict[SlotKind, list[SlotAssignment]]:
    result: dict[SlotKind, list[SlotAssignment]] = {}
    for assignment in assignments:
        result.setdefault(assignment.slot_kind, []).append(assignment)
    return result


def _by_kind(
    assignments: tuple[SlotAssignment, ...],
) -> dict[SlotKind, tuple[SlotAssignment, ...]]:
    result: dict[SlotKind, list[SlotAssignment]] = {}
    for assignment in assignments:
        result.setdefault(assignment.slot_kind, []).append(assignment)
    return {key: tuple(value) for key, value in result.items()}


def _one_value(assignments: tuple[SlotAssignment, ...]) -> str | None:
    values = tuple(value for item in assignments for value in item.value_ids)
    if len(values) > 1:
        raise LoweringError("AMBIGUOUS_SLOT_VALUE", values)
    return values[0] if values else None


def _one_canonical(
    assignments: tuple[SlotAssignment, ...],
    literals: dict[str, ResolverViewLiteralCandidate],
) -> str | None:
    value = _one_value(assignments)
    if value is None:
        return None
    literal = literals.get(value)
    if literal is None:
        raise LoweringError("UNKNOWN_LITERAL", (value,))
    return literal.canonical_value


def _literal_primitive(literal: ResolverViewLiteralCandidate):
    if literal.kind in {"result_limit", "rank_position"}:
        return int(literal.canonical_value)
    if literal.kind in {"number", "percentage", "money"}:
        return Decimal(literal.canonical_value)
    if literal.kind == "date":
        return date.fromisoformat(literal.canonical_value)
    return literal.canonical_value


def _binding_name(frame_id: str, role: SourceRole) -> str:
    return f"binding:{frame_id}:{role.value}"


def _entity_segment_id(evidence_ids: tuple[str, ...], view: ResolverView) -> str:
    evidence = {item.evidence_id: item for item in view.evidence_candidates}
    for evidence_id in evidence_ids:
        if evidence_id in evidence:
            return evidence[evidence_id].segment_id
    return "s1"


def _unique_edges(edges: list[DependencyEdge]) -> tuple[DependencyEdge, ...]:
    seen: set[tuple[str, str]] = set()
    result: list[DependencyEdge] = []
    for edge in edges:
        key = (edge.upstream_subtask_id, edge.downstream_subtask_id)
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return tuple(result)


def _unique_metrics(metrics: list[MetricSpec]) -> tuple[MetricSpec, ...]:
    seen: set[tuple[str, str]] = set()
    result: list[MetricSpec] = []
    for metric in metrics:
        key = (metric.subtask_id, metric.metric_id)
        if key not in seen:
            seen.add(key)
            result.append(metric)
    return tuple(result)
