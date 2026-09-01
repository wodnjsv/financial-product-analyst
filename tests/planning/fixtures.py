from datetime import datetime, timezone

from financial_agent.contracts.enums import Cardinality, IntentType, ProductFamily
from financial_agent.intent.draft import (
    ActionChoice,
    EntityHintV2,
    ProductFamilyChoice,
    SlotAssignment,
)
from financial_agent.intent.proposal import FrameSemanticCoverage
from financial_agent.intent.resolution import (
    ResolverBuildManifest,
    ValidatedContextLink,
    ValidatedIntentFrameV2,
    ValidatedIntentResolutionV2,
    ValidatedSlotMutation,
)
from financial_agent.intent.types import (
    ChoiceState,
    ContextLinkType,
    EntitySemanticRole,
    ReferenceTargetKind,
    ResolutionStatus,
    Selector,
    SemanticCoverageReason,
    SemanticCoverageState,
    SemanticTag,
    SlotKind,
    SlotMutationKind,
    SourceRole,
)
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    ActiveDatasetPin,
    AxisDefinition,
    ResolverView,
    ResolverViewConcept,
    ResolverViewEntityCandidate,
    ResolverViewEntityCandidateGroup,
    ResolverViewSemanticCandidateGroup,
    ResolverViewLiteralCandidate,
    ResolverViewReferenceCandidate,
    build_manifest,
)
from financial_agent.intent.catalog import load_catalog
from pathlib import Path


NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)
REQUEST_KEY = "a" * 64
DATASET_HASH = "f" * 64
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(PROJECT_ROOT)


def manifest() -> ResolverBuildManifest:
    return build_manifest(
        CATALOG,
        {
            "normalizer_version": NORMALIZER_VERSION,
            "candidate_policy_version": CANDIDATE_POLICY_VERSION,
            "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "adapter_version": ADAPTER_VERSION,
        },
    )


def axis_definitions() -> tuple[AxisDefinition, ...]:
    return tuple(
        AxisDefinition(
            axis_kind=kind,
            axis_id=item.value,
            preferred_label_ko=item.value,
            definition_ko=item.value,
            surface_forms=(),
        )
        for kind, enum_type in (
            ("product_family", ProductFamily),
            ("action", IntentType),
        )
        for item in enum_type
    )


def concept(concept_id: str, kind: str = "metric") -> ResolverViewConcept:
    return ResolverViewConcept(
        concept_id=concept_id,
        kind=kind,
        definition_ko=concept_id,
        value_kind="decimal" if kind == "metric" else kind,
        allowed_product_families=(
            "domestic_etf",
            "overseas_etf",
            "public_fund",
        ),
        allowed_ontology_types=("FinancialProduct",),
        required_qualifiers=(),
        allowed_operators=("equals", "greater_than", "less_than"),
        missingness_sensitive=True,
        normalization_rule="none",
    )


def view(*, context: bool = False) -> ResolverView:
    references = (
        (
            ResolverViewReferenceCandidate(
                reference_id="reference-1",
                segment_id="s2",
                text="그 상품",
                start_char=0,
                end_char=4,
            ),
        )
        if context
        else ()
    )
    return ResolverView(
        build_manifest=manifest(),
        active_dataset_pin=ActiveDatasetPin(
            dataset_version="dataset-v1",
            manifest_hash=DATASET_HASH,
        ),
        product_family_ids=tuple(item.value for item in ProductFamily),
        action_ids=tuple(item.value for item in IntentType),
        entity_type_ids=("ETF", "FinancialProduct"),
        semantic_candidates=(),
        concept_definitions=(
            concept("aum"),
            concept("product_risk_grade", "attribute"),
            concept("trailing_1y_historical_cumulative_return"),
        ),
        relation_definitions=(),
        literal_candidates=(
            ResolverViewLiteralCandidate(
                literal_id="literal-limit-5",
                segment_id="s1",
                kind="result_limit",
                original_text="5개",
                start_char=7,
                end_char=9,
                canonical_value="5",
            ),
            ResolverViewLiteralCandidate(
                literal_id="literal-limit-1",
                segment_id="s2",
                kind="result_limit",
                original_text="1위",
                start_char=12,
                end_char=14,
                canonical_value="1",
            ),
            ResolverViewLiteralCandidate(
                literal_id="literal-risk-3",
                segment_id="s1",
                kind="number",
                original_text="3",
                start_char=5,
                end_char=6,
                canonical_value="3",
            ),
        ),
        entity_candidates=(
            ResolverViewEntityCandidateGroup(
                mention_id="mention-etf",
                items=(
                    ResolverViewEntityCandidate(
                        entity_id="entity-kodex-200",
                        canonical_name="KODEX 200",
                        ontology_type_ids=("ETF", "FinancialProduct"),
                        product_family="domestic_etf",
                        match_kind="exact_name",
                        score=1_000_000,
                    ),
                ),
            ),
        ),
        axis_definitions=axis_definitions(),
        evidence_candidates=(),
        reference_candidates=references,
    )


def slot(
    assignment_id: str,
    kind: SlotKind,
    values: tuple[str, ...],
    evidence: tuple[str, ...] = (),
) -> SlotAssignment:
    return SlotAssignment(
        slot_assignment_id=assignment_id,
        slot_kind=kind,
        value_ids=values,
        evidence_span_ids=evidence,
        reason_code="explicit",
    )


def frame(
    frame_id: str,
    ordinal: int,
    *,
    metric_id: str,
    limit_id: str,
    produced: tuple[SourceRole, ...] = (),
    mutations: tuple[ValidatedSlotMutation, ...] = (),
    coverage: SemanticCoverageState = SemanticCoverageState.COVERED,
    action: IntentType = IntentType.RANK,
    assignments: tuple[SlotAssignment, ...] | None = None,
) -> ValidatedIntentFrameV2:
    reason = (
        SemanticCoverageReason.NONE
        if coverage is SemanticCoverageState.COVERED
        else SemanticCoverageReason.LEXICAL_OOD
    )
    return ValidatedIntentFrameV2(
        frame_id=frame_id,
        ordinal=ordinal,
        frame_status=(
            ResolutionStatus.RESOLVED
            if coverage is SemanticCoverageState.COVERED
            else ResolutionStatus.UNMAPPED
        ),
        segment_ids=(f"s{ordinal + 1}",),
        evidence_span_ids=(),
        action_choice=ActionChoice(
            state=ChoiceState.SELECTED,
            selected_ids=(action,),
            evidence_span_ids=(),
            reason_code="explicit",
        ),
        product_family_choice=ProductFamilyChoice(
            state=ChoiceState.SELECTED,
            selected_ids=(ProductFamily.DOMESTIC_ETF,),
            evidence_span_ids=(),
            reason_code="explicit",
        ),
        entity_type_ids=("ETF",),
        entity_hint_ids=(),
        slot_assignments=assignments or (
            slot(f"slot-{frame_id}-sort", SlotKind.SORT_KEY, (metric_id,)),
            slot(f"slot-{frame_id}-limit", SlotKind.RESULT_LIMIT, (limit_id,)),
        ),
        produced_result_roles=produced,
        slot_mutations=mutations,
        semantic_coverage=(
            FrameSemanticCoverage(
                state=coverage,
                reason=reason,
                evidence_ids=() if coverage is SemanticCoverageState.COVERED else ("e1",),
            ),
        ),
    )


def screen_resolution(*, ambiguous_filter: bool = False) -> ValidatedIntentResolutionV2:
    evidence = ("e-filter",)
    assignments = (
        slot("slot-filter-field", SlotKind.METRIC, ("product_risk_grade",), evidence),
        slot("slot-filter-op", SlotKind.FILTER_OPERATOR, ("less_than",), evidence),
        slot("slot-filter-value", SlotKind.FILTER_VALUE, ("literal-risk-3",), evidence),
    )
    if ambiguous_filter:
        assignments += (
            slot("slot-filter-op-2", SlotKind.FILTER_OPERATOR, ("greater_than",), evidence),
        )
    screen_frame = frame(
        "frame-1",
        0,
        metric_id="product_risk_grade",
        limit_id="literal-limit-5",
        action=IntentType.SCREEN,
        assignments=assignments,
    )
    return ValidatedIntentResolutionV2(
        request_key=REQUEST_KEY,
        run_id="run-1",
        dataset_version="dataset-v1",
        producer="intent-resolver",
        created_at=NOW,
        resolution_id="resolution-screen",
        draft_hash="e" * 64,
        canonical_frames=(screen_frame,),
        context_links=(),
        final_tags=(SemanticTag.MISSINGNESS_SENSITIVE,),
        resolution_status=ResolutionStatus.RESOLVED,
        issues=(),
        validation_events=(),
        build_manifest=manifest(),
        active_dataset_manifest_hash=DATASET_HASH,
        repair_used=False,
        invalid_attempt_hashes=(),
        entity_hints=(),
    )


def resolution(
    *,
    context: bool = False,
    tags: tuple[SemanticTag, ...] = (),
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    coverage: SemanticCoverageState = SemanticCoverageState.COVERED,
) -> ValidatedIntentResolutionV2:
    first = frame(
        "frame-1",
        0,
        metric_id="aum",
        limit_id="literal-limit-5",
        produced=(SourceRole.TOP_K_PRODUCTS,) if context else (),
        coverage=coverage,
    )
    frames = (first,)
    links: tuple[ValidatedContextLink, ...] = ()
    if context:
        second = frame(
            "frame-2",
            1,
            metric_id="trailing_1y_historical_cumulative_return",
            limit_id="literal-limit-1",
            mutations=(
                ValidatedSlotMutation(
                    slot_mutation_id="mutation-sort",
                    consumer_frame_id="frame-2",
                    slot_kind=SlotKind.SORT_KEY,
                    mutation_kind=SlotMutationKind.UPDATE,
                    source_frame_id=("frame-1",),
                ),
            ),
        )
        frames = (first, second)
        links = (
            ValidatedContextLink(
                context_link_id="link-1",
                reference_id="reference-1",
                link_type=ContextLinkType.CONSUME_RESULT_SET,
                source_role=SourceRole.TOP_K_PRODUCTS,
                selector=(Selector.ALL,),
                selector_literal_candidate_id=(),
                producer_frame_id="frame-1",
                consumer_frame_id="frame-2",
                target_kind=(ReferenceTargetKind.RESULT_SET,),
                target_cardinality=(Cardinality.MANY,),
                target_slot_kind=(),
            ),
        )
        tags = tuple(
            sorted(
                set(tags)
                | {SemanticTag.MULTI_STEP, SemanticTag.CONTEXT_DEPENDENT},
                key=lambda item: item.value,
            )
        )
    return ValidatedIntentResolutionV2(
        request_key=REQUEST_KEY,
        run_id="run-1",
        dataset_version="dataset-v1",
        producer="intent-resolver",
        created_at=NOW,
        resolution_id="resolution-1",
        draft_hash="d" * 64,
        canonical_frames=frames,
        context_links=links,
        final_tags=tags,
        resolution_status=status,
        issues=(),
        validation_events=(),
        build_manifest=manifest(),
        active_dataset_manifest_hash=DATASET_HASH,
        repair_used=False,
        invalid_attempt_hashes=(),
        entity_hints=(),
    )


def cross_family_resolution() -> ValidatedIntentResolutionV2:
    source = resolution(
        tags=(SemanticTag.CROSS_FAMILY, SemanticTag.NORMALIZATION_REQUIRED)
    )
    cross_family_frame = source.canonical_frames[0].model_copy(
        update={
            "product_family_choice": source.canonical_frames[
                0
            ].product_family_choice.model_copy(
                update={
                    "selected_ids": (
                        ProductFamily.DOMESTIC_ETF,
                        ProductFamily.OVERSEAS_ETF,
                    )
                }
            )
        }
    )
    return source.model_copy(
        update={
            "canonical_frames": (cross_family_frame,),
            "resolution_id": "resolution-cross-family",
        }
    )
