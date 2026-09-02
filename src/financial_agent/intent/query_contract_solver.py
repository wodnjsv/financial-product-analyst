"""Bounded deterministic solving of registered semantic query contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import combinations, product
import re
from typing import Iterable

from pydantic import Field

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import Cardinality, IntentType, ProductFamily

from .axis_locks import ExactSemanticLock, validate_exact_semantic_locks
from .query_contract_registry import OperatorArity, QueryContractRegistry
from .query_contracts import (
    AggregationBucketPolicyId,
    AggregationFunction,
    AggregationSpecV2,
    ComparisonSpecV2,
    ContractReadiness,
    ContractReadinessRecordV2,
    ExplanationSpecV2,
    OrderingDirection,
    OrderingSpecV2,
    PredicateAllOfV2,
    PredicateAtomV2,
    ProjectionSpecV2,
    ProvenanceSourceKind,
    QueryOperatorId,
    QueryQualifiersV2,
    QueryRegistryPinsV2,
    QueryResultShape,
    QueryScopeV2,
    ResolvedInputProvenanceV2,
    SemanticValueKind,
    SimilaritySpecV2,
    SolvedQueryContractCandidateV2,
    TypedSemanticValue,
    _AggregateQueryContractCandidateV2,
    _CompareQueryContractCandidateV2,
    _ExplainQueryContractCandidateV2,
    _LookupQueryContractCandidateV2,
    _RankQueryContractCandidateV2,
    _ScreenQueryContractCandidateV2,
    _SimilarQueryContractCandidateV2,
)
from .resolution import ValidatedIntentFrameV2, ValidatedIntentResolutionV2
from .types import (
    ChoiceState,
    ContextLinkType,
    EntitySemanticRole,
    ReferenceTargetKind,
    SlotKind,
)
from .view import ResolverView, ResolverViewConcept, ResolverViewLiteralCandidate


MAX_CANDIDATES_PER_ROLE = 8
MAX_COMPLETE_CANDIDATES_PER_FRAME = 64
_MATCH_PRIORITY = {
    "canonical_id": 0,
    "direct_alias": 1,
    "group_alias": 2,
    "ambiguous_alias": 3,
    "trigram": 4,
}
class CandidateRejection(ContractModel):
    frame_id: Identifier
    contract_variant_id: Identifier
    role_id: Identifier
    candidate_ids: tuple[Identifier, ...]
    reason_code: Identifier


class QueryContractCandidate(ContractModel):
    candidate_id: Identifier
    contract: SolvedQueryContractCandidateV2


class QueryContractFrameCandidateSet(ContractModel):
    frame_id: Identifier
    complete_candidates: tuple[QueryContractCandidate, ...] = Field(
        max_length=MAX_COMPLETE_CANDIDATES_PER_FRAME
    )
    rejections: tuple[CandidateRejection, ...]
    contract_readiness: ContractReadinessRecordV2


class QueryContractCandidateSet(ContractModel):
    frames: tuple[QueryContractFrameCandidateSet, ...] = Field(min_length=1, max_length=16)

    @property
    def complete_candidates(self) -> tuple[QueryContractCandidate, ...]:
        return tuple(item for frame in self.frames for item in frame.complete_candidates)

    @property
    def rejections(self) -> tuple[CandidateRejection, ...]:
        return tuple(item for frame in self.frames for item in frame.rejections)


@dataclass(frozen=True, slots=True)
class _FieldOffer:
    concept: ResolverViewConcept
    segment_id: str | None
    start_char: int | None


@dataclass(frozen=True, slots=True)
class _LiteralOffer:
    literal: ResolverViewLiteralCandidate


def solve_query_contracts(
    *,
    resolution: ValidatedIntentResolutionV2,
    view: ResolverView,
    exact_locks: tuple[ExactSemanticLock, ...],
    registry: QueryContractRegistry,
) -> QueryContractCandidateSet:
    """Enumerate only complete registered semantic contracts in frame order."""

    locks = validate_exact_semantic_locks(exact_locks)
    frames = tuple(
        _solve_frame(
            resolution=resolution,
            frame=frame,
            view=view,
            exact_locks=_locks_for_frame(frame, resolution, locks, view),
            registry=registry,
        )
        for frame in resolution.canonical_frames
    )
    return QueryContractCandidateSet(frames=frames)


def _solve_frame(
    *,
    resolution: ValidatedIntentResolutionV2,
    frame: ValidatedIntentFrameV2,
    view: ResolverView,
    exact_locks: tuple[ExactSemanticLock, ...],
    registry: QueryContractRegistry,
) -> QueryContractFrameCandidateSet:
    rejections: list[CandidateRejection] = []
    if (
        frame.action_choice.state is not ChoiceState.SELECTED
        or len(frame.action_choice.selected_ids) != 1
    ):
        return _frame_result(frame.frame_id, (), (
            _rejection(frame, "unresolved.v2", "action", (), "AXIS_UNRESOLVED"),
        ))

    action = frame.action_choice.selected_ids[0]
    variants = tuple(
        item for item in registry.variants_by_id.values() if item.action_id is action
    )
    if not variants:
        return _frame_result(frame.frame_id, (), (
            _rejection(frame, "unresolved.v2", "variant", (), "CONTRACT_VARIANT_NOT_REGISTERED"),
        ))

    unknown_locks = _unknown_exact_locks(view, exact_locks, registry)
    if unknown_locks:
        return _frame_result(
            frame.frame_id,
            (),
            (
                _rejection(
                    frame,
                    variants[0].id,
                    "exact_lock",
                    tuple(item.canonical_id for item in unknown_locks),
                    "EXACT_LOCK_NOT_OFFERED",
                ),
            ),
        )
    incompatible_locks = _incompatible_exact_locks(action, frame, view, exact_locks)
    if incompatible_locks:
        return _frame_result(
            frame.frame_id,
            (),
            (
                _rejection(
                    frame,
                    variants[0].id,
                    "exact_lock",
                    tuple(item.canonical_id for item in incompatible_locks),
                    "EXACT_LOCK_ROLE_INCOMPATIBLE",
                ),
            ),
        )

    scopes = _scopes(frame, resolution, view, exact_locks, rejections, variants[0].id)
    if not scopes:
        return _frame_result(frame.frame_id, (), tuple(rejections))
    qualifiers = _qualifiers(frame, view)
    fields, field_bound = _field_offers(
        frame, view, exact_locks, scopes[0], rejections, variants[0].id
    )
    if field_bound:
        return _frame_result(
            frame.frame_id,
            (),
            (*rejections, _rejection(frame, variants[0].id, "field", (), "CANDIDATE_BOUND_REACHED")),
            bound=True,
        )
    overflow_role = _overflow_role(action, frame, resolution, view, exact_locks)
    if overflow_role is not None:
        return _frame_result(
            frame.frame_id,
            (),
            (
                *rejections,
                _rejection(
                    frame,
                    variants[0].id,
                    overflow_role,
                    (),
                    "CANDIDATE_BOUND_REACHED",
                ),
            ),
            bound=True,
        )
    pins = _pins(registry)

    contracts: list[SolvedQueryContractCandidateV2] = []
    for variant in variants:
        for scope in scopes:
            if action is IntentType.LOOKUP:
                contracts.extend(_lookup(frame, variant.id, scope, qualifiers, fields, pins))
            elif action is IntentType.SCREEN:
                contracts.extend(
                    _screen(
                        frame, variant.id, scope, qualifiers, fields, view,
                        exact_locks, registry, pins, rejections,
                    )
                )
            elif action is IntentType.RANK:
                contracts.extend(
                    _rank(
                        frame, variant.id, scope, qualifiers, fields, view,
                        exact_locks, registry, pins, rejections,
                    )
                )
            elif action is IntentType.COMPARE:
                contracts.extend(
                    _compare(frame, variant.id, scope, qualifiers, fields, pins)
                )
            elif action is IntentType.AGGREGATE:
                contracts.extend(
                    _aggregate(
                        frame, variant.id, scope, qualifiers, fields, view,
                        exact_locks, pins, registry, rejections,
                    )
                )
            elif action is IntentType.SIMILAR:
                contracts.extend(_similar(frame, variant.id, scope, qualifiers, fields, view, pins))
            elif action is IntentType.EXPLAIN:
                contracts.extend(_explain(frame, variant.id, scope, qualifiers, fields, pins))
            elif action is IntentType.CALCULATE:
                rejections.append(
                    _rejection(frame, variant.id, "calculation.recipe", (), "RECIPE_NOT_OFFERED")
                )

        if len(contracts) > MAX_COMPLETE_CANDIDATES_PER_FRAME:
            candidates = _canonical_candidates(contracts, exact_locks)[
                :MAX_COMPLETE_CANDIDATES_PER_FRAME
            ]
            rejections.append(
                _rejection(frame, variant.id, "complete_contract", (), "CANDIDATE_BOUND_REACHED")
            )
            return _frame_result(
                frame.frame_id, candidates, tuple(rejections), bound=True
            )

    candidates = _canonical_candidates(contracts, exact_locks)
    if not candidates and not rejections:
        rejections.append(
            _rejection(frame, variants[0].id, "contract", (), "REQUIRED_SEMANTIC_INPUT_MISSING")
        )
    return _frame_result(frame.frame_id, candidates, tuple(rejections))


def _scopes(
    frame: ValidatedIntentFrameV2,
    resolution: ValidatedIntentResolutionV2,
    view: ResolverView,
    locks: tuple[ExactSemanticLock, ...],
    rejections: list[CandidateRejection],
    variant_id: str,
) -> tuple[QueryScopeV2, ...]:
    selected = tuple(frame.product_family_choice.selected_ids)
    locked_ids = tuple(
        lock.canonical_id for lock in locks if lock.role == "product_family"
    )
    offered_family_ids = set(view.product_family_ids)
    if any(item not in offered_family_ids for item in locked_ids):
        rejections.append(
            _rejection(frame, variant_id, "scope.product_family", locked_ids, "EXACT_LOCK_NOT_OFFERED")
        )
        return ()
    locked = tuple(ProductFamily(item) for item in locked_ids)
    if selected and locked and not set(locked) <= set(selected):
        rejections.append(
            _rejection(frame, variant_id, "scope.product_family", locked_ids, "EXACT_LOCK_CONFLICT")
        )
        return ()
    families = tuple(
        sorted(set(locked if locked else selected), key=lambda item: item.value)
    )

    hints = {item.entity_hint_id: item for item in resolution.entity_hints}
    fixed_entity_refs = {
        value_id
        for assignment in frame.slot_assignments
        if assignment.slot_kind is SlotKind.ENTITY
        for value_id in assignment.value_ids
    }
    entity_choice_groups = []
    for hint_id in frame.entity_hint_ids:
        hint = hints.get(hint_id)
        if hint is None or hint.semantic_role is not EntitySemanticRole.FRAME_SUBJECT:
            continue
        choices = hint.selected_candidate_ids or hint.candidate_entity_ids
        if choices:
            entity_choice_groups.append(tuple(choices))
    prior_links = tuple(
        link
        for link in resolution.context_links
        if link.consumer_frame_id == frame.frame_id
        and (
            link.link_type is ContextLinkType.CONSUME_RESULT_SET
            or link.target_kind == (ReferenceTargetKind.RESULT_SET,)
        )
    )
    if any(link.target_cardinality not in {(), (Cardinality.MANY,)} for link in prior_links):
        rejections.append(
            _rejection(frame, variant_id, "scope.prior_result", (), "CONTEXT_CARDINALITY_MISMATCH")
        )
        return ()
    prior_ids = tuple(sorted({link.producer_frame_id for link in prior_links}))
    if len(prior_ids) > 1:
        rejections.append(
            _rejection(frame, variant_id, "scope.prior_result", prior_ids, "CONTEXT_CARDINALITY_MISMATCH")
        )
        return ()
    entity_options = (
        tuple(product(*entity_choice_groups)) if entity_choice_groups else ((),)
    )
    entity_ref_options = tuple(
        tuple(sorted(fixed_entity_refs | set(option))) for option in entity_options
    )
    if not (families or any(entity_ref_options) or prior_ids):
        rejections.append(_rejection(frame, variant_id, "scope", (), "QUERY_SCOPE_REQUIRED"))
        return ()
    return tuple(
        QueryScopeV2(
            product_family_ids=families,
            entity_refs=entity_refs,
            prior_result_binding=prior_ids[0] if prior_ids else None,
        )
        for entity_refs in entity_ref_options
    )


def _field_offers(
    frame: ValidatedIntentFrameV2,
    view: ResolverView,
    locks: tuple[ExactSemanticLock, ...],
    scope: QueryScopeV2,
    rejections: list[CandidateRejection],
    variant_id: str,
) -> tuple[tuple[_FieldOffer, ...], bool]:
    concepts = {item.concept_id: item for item in view.concept_definitions}
    locked = tuple(lock for lock in locks if lock.role == "field")
    offers: dict[str, _FieldOffer] = {}
    if locked:
        for lock in locked:
            concept = concepts.get(lock.canonical_id)
            if concept is None:
                rejections.append(
                    _rejection(frame, variant_id, "field", (lock.canonical_id,), "EXACT_LOCK_NOT_OFFERED")
                )
                continue
            offers[concept.concept_id] = _FieldOffer(
                concept=concept,
                segment_id=_source_segment(lock.evidence_span_ids[0], view),
                start_char=_source_start(lock.evidence_span_ids[0], view),
            )
    else:
        for group in view.semantic_candidates:
            segment_id = _source_segment(group.mention_id, view)
            if segment_id is not None and segment_id not in frame.segment_ids:
                continue
            for candidate in sorted(
                group.items,
                key=lambda item: (
                    _MATCH_PRIORITY.get(item.match_kind, 99), -item.score, item.semantic_id
                ),
            ):
                concept = concepts.get(candidate.semantic_id)
                if concept is None or concept.kind not in {"metric", "attribute", "document_topic"}:
                    continue
                offers.setdefault(
                    concept.concept_id,
                    _FieldOffer(
                        concept=concept,
                        segment_id=segment_id,
                        start_char=_source_start(group.mention_id, view),
                    ),
                )

    families = {item.value for item in scope.product_family_ids}
    applicable: list[_FieldOffer] = []
    for offer in offers.values():
        if families and not families <= set(offer.concept.allowed_product_families):
            rejections.append(
                _rejection(
                    frame, variant_id, "field", (offer.concept.concept_id,),
                    "FIELD_NOT_APPLICABLE_TO_FAMILY",
                )
            )
        else:
            applicable.append(offer)
    applicable.sort(key=lambda item: item.concept.concept_id)
    return tuple(applicable[:MAX_CANDIDATES_PER_ROLE]), len(applicable) > MAX_CANDIDATES_PER_ROLE


def _lookup(frame, variant_id, scope, qualifiers, fields, pins):
    if fields:
        projections = tuple(
            ProjectionSpecV2(field_concept_ids=(offer.concept.concept_id,))
            for offer in fields
            if offer.concept.kind != "document_topic"
        )
    else:
        projections = (ProjectionSpecV2(default_profile_id="default-product-projection.v1"),)
    return tuple(
        _LookupQueryContractCandidateV2(
            **_base(frame, variant_id, scope, qualifiers, QueryResultShape.PRODUCT_LIST, pins),
            projections=item,
        )
        for item in projections
    )


def _screen(
    frame, variant_id, scope, qualifiers, fields, view, locks, registry, pins, rejections
):
    predicates = _predicate_candidates(
        frame, variant_id, fields, view, locks, registry, rejections, required=True
    )
    return tuple(
        _ScreenQueryContractCandidateV2(
            **_base(frame, variant_id, scope, qualifiers, QueryResultShape.PRODUCT_LIST, pins),
            predicate=predicate,
        )
        for predicate in predicates
    )


def _predicate_candidates(
    frame, variant_id, fields, view, locks, registry, rejections, *, required
):
    operators = tuple(lock for lock in locks if lock.role == "operator")
    literal_locks = tuple(lock for lock in locks if lock.role == "literal")
    literals_by_id = {item.literal_id: item for item in view.literal_candidates}
    if not operators:
        if required:
            rejections.append(_rejection(frame, variant_id, "predicate.operator", (), "PREDICATE_OPERATOR_REQUIRED"))
            return ()
        return (None,)
    unknown = tuple(lock.canonical_id for lock in operators if lock.canonical_id not in registry.operators_by_id)
    if unknown:
        rejections.append(_rejection(frame, variant_id, "predicate.operator", unknown, "EXACT_LOCK_NOT_OFFERED"))
        return ()
    if literal_locks:
        missing = tuple(lock.canonical_id for lock in literal_locks if lock.canonical_id not in literals_by_id)
        if missing:
            rejections.append(_rejection(frame, variant_id, "predicate.value", missing, "EXACT_LOCK_NOT_OFFERED"))
            return ()
        literals = tuple(
            _LiteralOffer(literals_by_id[lock.canonical_id])
            for lock in literal_locks
        )
    else:
        literals = tuple(
            _LiteralOffer(item)
            for item in view.literal_candidates
            if item.segment_id in frame.segment_ids
            and item.kind not in {"result_limit", "sort_direction", "period", "currency"}
        )
    atom_groups: list[tuple[PredicateAtomV2, ...]] = []
    for operator_lock in operators:
        definition = registry.operators_by_id[operator_lock.canonical_id]
        operator = QueryOperatorId(operator_lock.canonical_id)
        compatible_fields = tuple(
            item for item in fields if _field_operator_compatible(item.concept, operator)
        )
        compatible_literals = tuple(
            item for item in literals
            if _literal_kind(item.literal) in set(definition.allowed_value_kinds)
        )
        compatible_fields = _nearest_fields(compatible_fields, operator_lock, view)
        compatible_literals = _nearest_literals(compatible_literals, operator_lock, view, definition.arity)
        atoms: list[PredicateAtomV2] = []
        for field in compatible_fields:
            value_groups = _literal_groups(compatible_literals, definition.arity)
            for value_group in value_groups:
                if value_group and not all(
                    _field_literal_compatible(field.concept, item.literal)
                    for item in value_group
                ):
                    continue
                values = tuple(_typed_value(item.literal) for item in value_group)
                kwargs = {"value": None, "values": ()}
                if definition.arity is OperatorArity.ONE:
                    kwargs["value"] = values[0]
                elif definition.arity in {OperatorArity.TWO, OperatorArity.ONE_OR_MORE}:
                    kwargs["values"] = values
                atoms.append(
                    PredicateAtomV2(
                        field_concept_id=field.concept.concept_id,
                        operator_id=operator,
                        null_policy_id="exclude_missing.v1",
                        **kwargs,
                    )
                )
        if not atoms:
            rejections.append(
                _rejection(
                    frame, variant_id, "predicate", (operator_lock.canonical_id,),
                    "FIELD_OPERATOR_VALUE_INCOMPATIBLE",
                )
            )
            return ()
        atom_groups.append(tuple(atoms))

    predicates = []
    for atoms in product(*atom_groups):
        predicate = atoms[0] if len(atoms) == 1 else PredicateAllOfV2(children=atoms)
        predicates.append(predicate)
    return tuple(predicates)


def _rank(
    frame, variant_id, scope, qualifiers, fields, view, locks, registry, pins, rejections
):
    usable = tuple(item for item in fields if item.concept.kind in {"metric", "attribute"})
    directions = tuple(
        item for item in view.literal_candidates
        if item.segment_id in frame.segment_ids and item.kind == "sort_direction"
    )
    limits = tuple(
        item for item in view.literal_candidates
        if item.segment_id in frame.segment_ids and item.kind == "result_limit"
    )
    direction_values = tuple(OrderingDirection(item.canonical_value) for item in directions) or (None,)
    limit_values = tuple(int(item.canonical_value) for item in limits) or (None,)
    predicates = _predicate_candidates(
        frame, variant_id, fields, view, locks, registry, rejections, required=False
    )
    return tuple(
        _RankQueryContractCandidateV2(
            **_base(frame, variant_id, scope, qualifiers, QueryResultShape.TOP_K, pins),
            ordering=(
                OrderingSpecV2(
                    field_concept_id=field.concept.concept_id,
                    direction=direction,
                    direction_policy_id=(None if direction else "default-direction-descending.v1"),
                    nulls_policy_id="exclude_missing.v1",
                    tie_break_policy_id="stable-product-id.v1",
                ),
            ),
            limit=limit,
            limit_policy_id=None if limit else "default-limit-5.v1",
            predicate=predicate,
        )
        for field, direction, limit, predicate in product(
            usable, direction_values, limit_values, predicates
        )
    )


def _compare(frame, variant_id, scope, qualifiers, fields, pins):
    subjects = scope.entity_refs
    group_basis = scope.prior_result_binding
    if len(subjects) < 2 and group_basis is None:
        return ()
    cross_family = len(scope.product_family_ids) > 1
    return tuple(
        _CompareQueryContractCandidateV2(
            **_base(frame, variant_id, scope, qualifiers, QueryResultShape.COMPARISON_TABLE, pins),
            comparison=ComparisonSpecV2(
                subject_refs=subjects,
                group_basis_id=group_basis,
                metric_concept_ids=(field.concept.concept_id,),
                basis_policy_id="same-definition-period-unit.v1",
                normalization_policy_id=("approved-cross-family.v1" if cross_family else None),
            ),
        )
        for field in fields
        if field.concept.kind in {"metric", "attribute"}
    )


def _aggregate(
    frame, variant_id, scope, qualifiers, fields, view, locks, pins, registry, rejections
):
    public_fund = ProductFamily.PUBLIC_FUND in scope.product_family_ids
    grain = "representative-product.v1" if public_fund else "source-product.v1"
    dedup = "public-fund-representative-share.v1" if public_fund else "no-dedup.v1"
    contracts = []
    usable = tuple(item for item in fields if item.concept.kind in {"metric", "attribute"})
    predicates = _predicate_candidates(
        frame, variant_id, fields, view, locks, registry, rejections, required=False
    )
    if not predicates:
        return ()
    if variant_id == "aggregate.scalar.v2":
        for field in usable:
            for function, predicate in product((
                AggregationFunction.SUM,
                AggregationFunction.AVG,
                AggregationFunction.MIN,
                AggregationFunction.MAX,
                AggregationFunction.COUNT_DISTINCT,
            ), predicates):
                contracts.append(
                    _AggregateQueryContractCandidateV2(
                        **_base(frame, variant_id, scope, qualifiers, QueryResultShape.SINGLE_VALUE, pins),
                        aggregation=AggregationSpecV2(
                            function_id=function,
                            target_field_concept_id=field.concept.concept_id,
                            population_grain_id=grain,
                            dedup_policy_id=dedup,
                        ),
                        predicate=predicate,
                    )
                )
        for predicate in predicates:
            contracts.append(
                _AggregateQueryContractCandidateV2(
                    **_base(frame, variant_id, scope, qualifiers, QueryResultShape.SINGLE_VALUE, pins),
                    aggregation=AggregationSpecV2(
                        function_id=AggregationFunction.COUNT,
                        count_population_id=grain,
                        population_grain_id=grain,
                        dedup_policy_id=dedup,
                    ),
                    predicate=predicate,
                )
            )
    elif variant_id == "aggregate.grouped.v2":
        for target, grouping, predicate in product(usable, usable, predicates):
            if target.concept.concept_id == grouping.concept.concept_id:
                continue
            contracts.append(
                _AggregateQueryContractCandidateV2(
                    **_base(frame, variant_id, scope, qualifiers, QueryResultShape.GROUPED_TABLE, pins),
                    aggregation=AggregationSpecV2(
                        function_id=AggregationFunction.SUM,
                        target_field_concept_id=target.concept.concept_id,
                        group_by_field_concept_ids=(grouping.concept.concept_id,),
                        population_grain_id=grain,
                        dedup_policy_id=dedup,
                    ),
                    predicate=predicate,
                )
            )
    elif variant_id == "aggregate.distribution.v2":
        for field, predicate in product(usable, predicates):
            contracts.append(
                _AggregateQueryContractCandidateV2(
                    **_base(frame, variant_id, scope, qualifiers, QueryResultShape.DISTRIBUTION, pins),
                    aggregation=AggregationSpecV2(
                        function_id=AggregationFunction.DISTRIBUTION,
                        target_field_concept_id=field.concept.concept_id,
                        bucket_policy_id=AggregationBucketPolicyId.EQUAL_WIDTH_10,
                        population_grain_id=grain,
                        dedup_policy_id=dedup,
                    ),
                    predicate=predicate,
                )
            )
    return tuple(contracts)


def _similar(frame, variant_id, scope, qualifiers, fields, view, pins):
    anchors = scope.entity_refs
    if not anchors and scope.prior_result_binding:
        anchors = (scope.prior_result_binding,)
    if len(anchors) != 1:
        return ()
    dimensions = tuple(
        item.concept.concept_id for item in fields if item.concept.kind in {"metric", "attribute"}
    )
    if not dimensions:
        return ()
    limit_literals = tuple(
        item for item in view.literal_candidates
        if item.segment_id in frame.segment_ids and item.kind == "result_limit"
    )
    limit = int(limit_literals[0].canonical_value) if len(limit_literals) == 1 else 5
    specs = (
        SimilaritySpecV2(
            anchor_ref=anchors[0],
            policy_id="cosine-complete-dimensions.v1",
            dimension_concept_ids=dimensions,
            coverage_threshold="1",
            limit=limit,
        ),
    )
    return tuple(
        _SimilarQueryContractCandidateV2(
            **_base(frame, variant_id, scope, qualifiers, QueryResultShape.PRODUCT_LIST, pins),
            similarity=spec,
        )
        for spec in specs
    )


def _explain(frame, variant_id, scope, qualifiers, fields, pins):
    topics = tuple(item for item in fields if item.concept.kind == "document_topic")
    specs = tuple(
        ExplanationSpecV2(topic_concept_id=item.concept.concept_id) for item in topics
    ) or (ExplanationSpecV2(profile_id="default-explanation-profile.v1"),)
    return tuple(
        _ExplainQueryContractCandidateV2(
            **_base(frame, variant_id, scope, qualifiers, QueryResultShape.EXPLANATION, pins),
            explanation=spec,
        )
        for spec in specs
    )


def _base(frame, variant_id, scope, qualifiers, result_shape, pins):
    provenance = [
        ResolvedInputProvenanceV2(
            semantic_input_id="scope",
            source_kind=(
                ProvenanceSourceKind.PRIOR_RESULT
                if scope.prior_result_binding
                else ProvenanceSourceKind.AXIS_RESOLUTION
            ),
            source_ref=scope.prior_result_binding or frame.frame_id,
        )
    ]
    return {
        "contract_variant_id": variant_id,
        "frame_id": frame.frame_id,
        "action_id": frame.action_choice.selected_ids[0],
        "scope": scope,
        "qualifiers": qualifiers,
        "result_shape": result_shape,
        "provenance": tuple(provenance),
        "registry_pins": pins,
    }


def _pins(registry: QueryContractRegistry) -> QueryRegistryPinsV2:
    return QueryRegistryPinsV2(
        contract_registry_version=registry.contract_registry_version,
        contract_registry_hash=registry.contract_registry_hash,
        operator_registry_version=registry.operator_registry_version,
        operator_registry_hash=registry.operator_registry_hash,
        policy_registry_version=registry.policy_registry_version,
        policy_registry_hash=registry.policy_registry_hash,
    )


def _qualifiers(frame: ValidatedIntentFrameV2, view: ResolverView) -> QueryQualifiersV2:
    literals = tuple(item for item in view.literal_candidates if item.segment_id in frame.segment_ids)
    period = next((item.canonical_value for item in literals if item.kind == "period"), None)
    currency = next((item.canonical_value for item in literals if item.kind == "currency"), None)
    as_of = next((date.fromisoformat(item.canonical_value) for item in literals if item.kind == "date"), None)
    return QueryQualifiersV2(period_id=period, currency_id=currency, as_of_date=as_of)


def _typed_value(literal: ResolverViewLiteralCandidate) -> TypedSemanticValue:
    kind = _literal_kind(literal)
    values = {
        "string": None,
        "integer": None,
        "decimal": None,
        "boolean": None,
        "date": None,
        "datetime": None,
        "identifier": None,
    }
    if kind is SemanticValueKind.INTEGER:
        values["integer"] = int(literal.canonical_value)
    elif kind is SemanticValueKind.DECIMAL:
        values["decimal"] = literal.canonical_value
    elif kind is SemanticValueKind.DATE:
        values["date"] = date.fromisoformat(literal.canonical_value)
    else:
        values["string"] = literal.canonical_value
    unit = "percent" if literal.kind == "percentage" else literal.currency
    return TypedSemanticValue(kind=kind, unit_id=unit, **values)


def _literal_kind(literal: ResolverViewLiteralCandidate) -> SemanticValueKind:
    return {
        "date": SemanticValueKind.DATE,
        "rank_position": SemanticValueKind.INTEGER,
        "result_limit": SemanticValueKind.INTEGER,
        "money": SemanticValueKind.DECIMAL,
        "number": SemanticValueKind.DECIMAL,
        "percentage": SemanticValueKind.DECIMAL,
    }.get(literal.kind, SemanticValueKind.STRING)


def _field_value_kind(concept: ResolverViewConcept) -> SemanticValueKind:
    return {
        "text": SemanticValueKind.STRING,
        "string": SemanticValueKind.STRING,
        "classification": SemanticValueKind.STRING,
        "status": SemanticValueKind.STRING,
        "currency": SemanticValueKind.STRING,
        "document_topic": SemanticValueKind.STRING,
        "integer": SemanticValueKind.INTEGER,
        "decimal": SemanticValueKind.DECIMAL,
        "boolean": SemanticValueKind.BOOLEAN,
        "date": SemanticValueKind.DATE,
        "datetime": SemanticValueKind.DATETIME,
        "identifier": SemanticValueKind.IDENTIFIER,
    }.get(concept.value_kind, SemanticValueKind.STRING)


def _field_operator_compatible(concept: ResolverViewConcept, operator: QueryOperatorId) -> bool:
    value_kind = _field_value_kind(concept)
    language_operator = {
        QueryOperatorId.EQ: "equals",
        QueryOperatorId.NEQ: "equals",
        QueryOperatorId.LT: "less_than",
        QueryOperatorId.LTE: "less_than",
        QueryOperatorId.GT: "greater_than",
        QueryOperatorId.GTE: "greater_than",
        QueryOperatorId.BETWEEN: "greater_than",
        QueryOperatorId.IN: "equals",
        QueryOperatorId.NOT_IN: "equals",
        QueryOperatorId.CONTAINS: "contains",
    }.get(operator)
    if language_operator is not None and language_operator not in concept.allowed_operators:
        return False
    if operator in {QueryOperatorId.LT, QueryOperatorId.LTE, QueryOperatorId.GT, QueryOperatorId.GTE, QueryOperatorId.BETWEEN}:
        return value_kind in {
            SemanticValueKind.INTEGER, SemanticValueKind.DECIMAL,
            SemanticValueKind.DATE, SemanticValueKind.DATETIME,
        }
    if operator is QueryOperatorId.CONTAINS:
        return value_kind is SemanticValueKind.STRING
    return True


def _field_literal_compatible(
    concept: ResolverViewConcept, literal: ResolverViewLiteralCandidate
) -> bool:
    field_kind = _field_value_kind(concept)
    literal_kind = _literal_kind(literal)
    return field_kind is literal_kind or {
        field_kind,
        literal_kind,
    } == {SemanticValueKind.INTEGER, SemanticValueKind.DECIMAL}


def _literal_groups(literals: tuple[_LiteralOffer, ...], arity: OperatorArity):
    if arity is OperatorArity.ZERO:
        return ((),)
    if arity is OperatorArity.ONE:
        return tuple((item,) for item in literals)
    if arity is OperatorArity.TWO:
        return tuple(combinations(literals, 2))
    return (literals,) if literals else ()


def _nearest_fields(fields, lock, view):
    segment = _source_segment(lock.evidence_span_ids[0], view)
    start = _source_start(lock.evidence_span_ids[0], view)
    if segment is None or start is None:
        return fields
    preceding = tuple(
        item for item in fields
        if item.segment_id == segment and item.start_char is not None and item.start_char <= start
    )
    if not preceding:
        return fields
    nearest = max(item.start_char for item in preceding if item.start_char is not None)
    return tuple(item for item in preceding if item.start_char == nearest)


def _nearest_literals(literals, lock, view, arity):
    segment = _source_segment(lock.evidence_span_ids[0], view)
    start = _source_start(lock.evidence_span_ids[0], view)
    if segment is None or start is None or arity is OperatorArity.ZERO:
        return literals
    preceding = tuple(
        item for item in literals
        if item.literal.segment_id == segment and item.literal.start_char <= start
    )
    count = 2 if arity is OperatorArity.TWO else 1
    return tuple(sorted(preceding, key=lambda item: item.literal.start_char)[-count:]) or literals


def _canonical_candidates(
    contracts: Iterable[SolvedQueryContractCandidateV2],
    exact_locks: tuple[ExactSemanticLock, ...],
):
    candidates: dict[str, QueryContractCandidate] = {}
    for contract in contracts:
        semantic_content = contract.model_dump(
            mode="json",
            exclude={"frame_id", "provenance", "registry_pins"},
        )
        digest = canonical_sha256(semantic_content)
        contract = contract.model_copy(
            update={"provenance": _resolved_input_provenance(contract, exact_locks)}
        )
        candidates.setdefault(
            digest,
            QueryContractCandidate(candidate_id=f"query-contract-{digest}", contract=contract),
        )
    return tuple(sorted(candidates.values(), key=lambda item: item.candidate_id))


def _resolved_input_provenance(
    contract: SolvedQueryContractCandidateV2,
    exact_locks: tuple[ExactSemanticLock, ...],
) -> tuple[ResolvedInputProvenanceV2, ...]:
    exact_by_value = {lock.canonical_id: lock for lock in exact_locks}
    payload = contract.model_dump(
        mode="json",
        exclude={
            "contract_schema_version",
            "frame_id",
            "provenance",
            "registry_pins",
        },
    )
    records: list[ResolvedInputProvenanceV2] = []
    for path, value in _semantic_leaves(payload):
        if value is None or value == "":
            continue
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        lock = exact_by_value.get(rendered)
        if lock is not None:
            source_kind = ProvenanceSourceKind.EXACT_LOCK
            source_ref = lock.lock_id
        elif path == "scope.prior_result_binding":
            source_kind = ProvenanceSourceKind.PRIOR_RESULT
            source_ref = rendered
        elif (
            rendered.endswith(".v1")
            or path == "contract_variant_id"
            or "policy" in path
            or "profile" in path
        ):
            source_kind = ProvenanceSourceKind.REGISTRY_DEFAULT
            source_ref = rendered
        else:
            source_kind = ProvenanceSourceKind.AXIS_RESOLUTION
            source_ref = rendered
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", source_ref):
            source_ref = f"semantic-{canonical_sha256(source_ref)[:16]}"
        records.append(
            ResolvedInputProvenanceV2(
                semantic_input_id=path,
                source_kind=source_kind,
                source_ref=source_ref,
            )
        )
    return tuple(records)


def _semantic_leaves(value: object, path: str = ""):
    if isinstance(value, dict):
        for key in sorted(value):
            child_path = f"{path}.{key}" if path else key
            yield from _semantic_leaves(value[key], child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _semantic_leaves(item, f"{path}.{index}")
    else:
        yield path, value


def _frame_result(frame_id, candidates, rejections, *, bound=False):
    ordered_rejections = tuple(
        sorted(
            {canonical_sha256(item): item for item in rejections}.values(),
            key=lambda item: (
                item.contract_variant_id, item.role_id, item.reason_code, item.candidate_ids
            ),
        )
    )
    reason_codes = (
        ("CANDIDATE_BOUND_REACHED",)
        if bound
        else ()
        if len(candidates) == 1
        else tuple(sorted({item.reason_code for item in ordered_rejections}))
    )
    readiness = (
        ContractReadiness.AMBIGUOUS
        if bound or len(candidates) > 1
        else ContractReadiness.COMPLETE
        if len(candidates) == 1
        else ContractReadiness.BLOCKED
    )
    return QueryContractFrameCandidateSet(
        frame_id=frame_id,
        complete_candidates=tuple(candidates),
        rejections=ordered_rejections,
        contract_readiness=ContractReadinessRecordV2(
            readiness=readiness, reason_codes=reason_codes
        ),
    )


def _rejection(frame, variant_id, role_id, candidate_ids, reason):
    return CandidateRejection(
        frame_id=frame.frame_id,
        contract_variant_id=variant_id,
        role_id=role_id,
        candidate_ids=tuple(sorted(candidate_ids)),
        reason_code=reason,
    )


def _locks_for_frame(frame, resolution, locks, view):
    if len(resolution.canonical_frames) == 1:
        return locks
    selected = []
    for lock in locks:
        segments = {
            segment
            for source_ref in lock.evidence_span_ids
            if (segment := _source_segment(source_ref, view)) is not None
        }
        if not segments or segments & set(frame.segment_ids):
            selected.append(lock)
    return tuple(selected)


def _overflow_role(
    action: IntentType,
    frame: ValidatedIntentFrameV2,
    resolution: ValidatedIntentResolutionV2,
    view: ResolverView,
    locks: tuple[ExactSemanticLock, ...],
) -> str | None:
    if action is IntentType.SCREEN:
        operators = tuple(item for item in locks if item.role == "operator")
        literal_locks = tuple(item for item in locks if item.role == "literal")
        values = literal_locks or tuple(
            item
            for item in view.literal_candidates
            if item.segment_id in frame.segment_ids
            and item.kind not in {"result_limit", "sort_direction", "period", "currency"}
        )
        if len(operators) > MAX_CANDIDATES_PER_ROLE:
            return "predicate.operator"
        if len(values) > MAX_CANDIDATES_PER_ROLE:
            return "predicate.value"
    if action in {IntentType.RANK, IntentType.SIMILAR}:
        for kind, role in (
            ("result_limit", "limit"),
            ("sort_direction", "ordering.direction"),
        ):
            count = sum(
                item.segment_id in frame.segment_ids and item.kind == kind
                for item in view.literal_candidates
            )
            if count > MAX_CANDIDATES_PER_ROLE:
                return role
    if action in {IntentType.COMPARE, IntentType.SIMILAR, IntentType.EXPLAIN}:
        hints = {item.entity_hint_id: item for item in resolution.entity_hints}
        candidate_counts = (
            len(hints[hint_id].candidate_entity_ids)
            for hint_id in frame.entity_hint_ids
            if hint_id in hints
        )
        if any(count > MAX_CANDIDATES_PER_ROLE for count in candidate_counts):
            return "entity"
    return None


def _incompatible_exact_locks(
    action: IntentType,
    frame: ValidatedIntentFrameV2,
    view: ResolverView,
    locks: tuple[ExactSemanticLock, ...],
) -> tuple[ExactSemanticLock, ...]:
    if action in {IntentType.SCREEN, IntentType.AGGREGATE, IntentType.CALCULATE}:
        return ()
    incompatible: list[ExactSemanticLock] = []
    operators = tuple(item for item in locks if item.role == "operator")
    if operators and action is not IntentType.RANK:
        incompatible.extend(operators)
    literals = {item.literal_id: item for item in view.literal_candidates}
    allowed_literal_kinds = {
        IntentType.LOOKUP: {"period", "currency", "date"},
        IntentType.RANK: {
            "result_limit", "sort_direction", "period", "currency", "date"
        },
        IntentType.COMPARE: {"period", "currency", "date"},
        IntentType.SIMILAR: {"result_limit", "period", "currency", "date"},
        IntentType.EXPLAIN: {"period", "currency", "date"},
    }.get(action, set())
    for lock in locks:
        if lock.role != "literal":
            continue
        literal = literals.get(lock.canonical_id)
        if literal is None:
            continue
        if literal.kind not in allowed_literal_kinds and not (
            action is IntentType.RANK and operators
        ):
            incompatible.append(lock)
    return tuple(sorted(set(incompatible), key=lambda item: item.lock_id))


def _unknown_exact_locks(
    view: ResolverView,
    locks: tuple[ExactSemanticLock, ...],
    registry: QueryContractRegistry,
) -> tuple[ExactSemanticLock, ...]:
    offered = {
        "product_family": set(view.product_family_ids),
        "field": {item.concept_id for item in view.concept_definitions},
        "operator": set(registry.operators_by_id),
        "literal": {item.literal_id for item in view.literal_candidates},
    }
    return tuple(
        lock for lock in locks if lock.canonical_id not in offered[lock.role]
    )


def _source_segment(source_ref: str, view: ResolverView) -> str | None:
    literal = next((item for item in view.literal_candidates if item.literal_id == source_ref), None)
    if literal is not None:
        return literal.segment_id
    evidence = next((item for item in view.evidence_candidates if item.evidence_id == source_ref), None)
    if evidence is not None:
        return evidence.segment_id
    segments = sorted(
        {
            *(item.segment_id for item in view.literal_candidates),
            *(item.segment_id for item in view.evidence_candidates),
            *(item.segment_id for item in view.reference_candidates),
        },
        key=len,
        reverse=True,
    )
    return next((item for item in segments if re.search(rf"(?:^|-){re.escape(item)}(?:-|$)", source_ref)), None)


def _source_start(source_ref: str, view: ResolverView) -> int | None:
    literal = next((item for item in view.literal_candidates if item.literal_id == source_ref), None)
    if literal is not None:
        return literal.start_char
    evidence = next((item for item in view.evidence_candidates if item.evidence_id == source_ref), None)
    if evidence is not None:
        return evidence.start_char
    numbers = re.findall(r"-(\d+)(?=-|$)", source_ref)
    return int(numbers[-2] if len(numbers) >= 2 else numbers[0]) if numbers else None
