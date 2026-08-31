from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.draft import (
    ActionChoice,
    AxisChoice,
    ContextLinkHint,
    EntityHint,
    EvidenceSpan,
    IntentFrameDraft,
    IntentResolutionDraft,
    ProductFamilyChoice,
    SlotAssignment,
)
from financial_agent.intent.errors import ResolverContractError
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.resolution import ContractFileHash, ResolverBuildManifest
from financial_agent.intent.types import (
    ChoiceState,
    ContextLinkType,
    ResolutionStatus,
    SemanticTag,
    SlotKind,
    SourceRole,
)
from financial_agent.intent.validation import (
    STATUS_PRECEDENCE,
    VALIDATION_STAGES,
    validate_semantics,
)
from financial_agent.intent.view import (
    ActiveDatasetPin,
    ResolverView,
    ResolverViewConcept,
    ResolverViewEntityCandidate,
    ResolverViewEntityCandidateGroup,
    ResolverViewLiteralCandidate,
    ResolverViewRelationDefinition,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ValidationInputs:
    draft: IntentResolutionDraft
    context: RequestContext
    normalized: object
    view: ResolverView
    catalog: object

    @property
    def rest(self) -> dict[str, object]:
        return {
            "context": self.context,
            "normalized": self.normalized,
            "view": self.view,
            "catalog": self.catalog,
        }


def _slot(slot_id: str, kind: SlotKind, *value_ids: str) -> SlotAssignment:
    return SlotAssignment(
        slot_assignment_id=slot_id,
        slot_kind=kind,
        value_ids=value_ids,
        evidence_span_ids=("span-1",),
        reason_code="explicit",
    )


def _frame(
    frame_id: str,
    ordinal: int,
    family: str,
    *,
    entity_types: tuple[str, ...] = ("FinancialProduct",),
    slots: tuple[SlotAssignment, ...] = (),
) -> IntentFrameDraft:
    return IntentFrameDraft(
        frame_id=frame_id,
        ordinal=ordinal,
        segment_ids=("s1",),
        evidence_span_ids=("span-1",),
        normalized_intent_argument="ETF 질문",
        action_choice=ActionChoice(
            state=ChoiceState.SELECTED,
            selected_ids=(IntentType.COMPARE,),
            evidence_span_ids=("span-1",),
            reason_code="explicit",
        ),
        product_family_choice=ProductFamilyChoice(
            state=ChoiceState.SELECTED,
            selected_ids=(ProductFamily(family),),
            evidence_span_ids=("span-1",),
            reason_code="explicit",
        ),
        entity_type_ids=entity_types,
        entity_hint_ids=(),
        slot_assignments=slots,
        produced_result_hints=(SourceRole.CANDIDATES,),
    )


@pytest.fixture
def validation_inputs() -> ValidationInputs:
    question = "국내 ETF와 해외 ETF의 AUM을 1년 기준으로 비교하고 운용사를 알려줘"
    created_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key("q-validation", question, "dataset-v1", "1.0"),
        run_id="run-validation",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q-validation",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=created_at + timedelta(seconds=10),
    )
    catalog = load_catalog(PROJECT_ROOT)
    span = EvidenceSpan(
        span_id="span-1",
        segment_id="s1",
        start_char=0,
        end_char=2,
        text="국내",
    )
    frames = (
        _frame(
            "f1",
            0,
            "domestic_etf",
            slots=(
                _slot("slot-metric", SlotKind.METRIC, "aum"),
                _slot("slot-period", SlotKind.PERIOD, "lit-period"),
            ),
        ),
        _frame(
            "f2",
            1,
            "overseas_etf",
            slots=(
                _slot("slot-relation", SlotKind.RELATION, "managedBy"),
            ),
        ),
    )
    draft = IntentResolutionDraft(
        evidence_spans=(span,),
        intent_frames=frames,
        entity_hints=(),
        reference_hints=(),
        context_link_hints=(
            ContextLinkHint(
                context_link_id="link-1",
                reference_id="reference-1",
                link_type=ContextLinkType.CONSUME_RESULT_SET,
                source_role=SourceRole.CANDIDATES,
                selector=(),
                selector_literal_candidate_id=(),
                producer_frame_id="f1",
                consumer_frame_id="f2",
                target_slot_kind=(),
            ),
        ),
        slot_mutations=(),
        semantic_flag_hints=(),
        frame_limit_exceeded=False,
    )
    view = ResolverView(
        build_manifest=ResolverBuildManifest(
            catalog_version="catalog-v1",
            catalog_hash="b" * 64,
            ontology_hashes=(
                ContractFileHash(relative_path="ontology.ttl", sha256="c" * 64),
            ),
            overlay_version="overlay-v1",
            overlay_hash="d" * 64,
            normalizer_version="normalizer-v1",
            candidate_policy_version="candidate-policy-v1",
            resolver_schema_version="1.0",
            prompt_version="prompt-v1",
            adapter_version="adapter-v1",
        ),
        active_dataset_pin=ActiveDatasetPin(
            dataset_version="dataset-v1", manifest_hash="a" * 64
        ),
        product_family_ids=("domestic_etf", "overseas_etf"),
        action_ids=("compare",),
        semantic_candidates=(),
        concept_definitions=(
            ResolverViewConcept(
                concept_id="aum",
                kind="metric",
                definition_ko="순자산총액",
                value_kind="decimal",
                allowed_product_families=(
                    "domestic_etf",
                    "overseas_etf",
                    "public_fund",
                ),
                allowed_ontology_types=("FinancialProduct",),
                required_qualifiers=("as_of",),
                allowed_operators=("equals", "greater_than", "less_than"),
                missingness_sensitive=True,
                normalization_rule="currency_normalization_required",
            ),
            ResolverViewConcept(
                concept_id="credit_grade",
                kind="attribute",
                definition_ko="채권 신용등급",
                value_kind="classification",
                allowed_product_families=("domestic_bond",),
                allowed_ontology_types=("CreditGrade", "FinancialProduct"),
                required_qualifiers=(),
                allowed_operators=("equals",),
                missingness_sensitive=True,
                normalization_rule="credit_grade_order",
            ),
        ),
        relation_definitions=(
            ResolverViewRelationDefinition(
                relation_id="managedBy",
                definition_ko="상품을 운용하는 기관",
                subject_ontology_types=("FinancialProduct",),
                object_ontology_types=("AssetManager",),
                required_qualifiers=(),
            ),
        ),
        literal_candidates=(
            ResolverViewLiteralCandidate(
                literal_id="lit-period",
                segment_id="s1",
                kind="period",
                original_text="1년",
                start_char=21,
                end_char=23,
                canonical_value="P1Y",
            ),
        ),
        entity_candidates=(
            ResolverViewEntityCandidateGroup(
                mention_id="mention-entity",
                items=(
                    ResolverViewEntityCandidate(
                        entity_id="entity-product",
                        canonical_name="KODEX 200",
                        entity_type="ETF",
                        product_family="domestic_etf",
                        match_kind="exact_name",
                        score=1_000_000,
                    ),
                    ResolverViewEntityCandidate(
                        entity_id="entity-manager",
                        canonical_name="운용사",
                        entity_type="AssetManager",
                        product_family=None,
                        match_kind="exact_name",
                        score=1_000_000,
                    ),
                ),
            ),
        ),
    )
    return ValidationInputs(
        draft=draft,
        context=context,
        normalized=normalize_request(context),
        view=view,
        catalog=catalog,
    )


def replace_metric(draft: IntentResolutionDraft, metric_id: str) -> IntentResolutionDraft:
    frame = draft.intent_frames[0]
    replacement = _slot("slot-metric", SlotKind.METRIC, metric_id)
    return draft.model_copy(
        update={
            "intent_frames": (
                frame.model_copy(update={"slot_assignments": (replacement, frame.slot_assignments[1])}),
                *draft.intent_frames[1:],
            )
        }
    )


def replace_span_text(draft: IntentResolutionDraft, text: str) -> IntentResolutionDraft:
    return draft.model_copy(
        update={"evidence_spans": (draft.evidence_spans[0].model_copy(update={"text": text}),)}
    )


def _entity_hint(
    *,
    candidate_ids: tuple[str, ...],
    selected_ids: tuple[str, ...],
    expected_type_ids: tuple[str, ...] = ("FinancialProduct",),
) -> EntityHint:
    return EntityHint(
        entity_hint_id="hint-1",
        mention_id=("mention-entity",),
        evidence_span_ids=("span-1",),
        expected_entity_type_ids=expected_type_ids,
        candidate_entity_ids=candidate_ids,
        selected_candidate_ids=selected_ids,
        reason_code="explicit",
    )


def _draft_with_entity_hint(
    draft: IntentResolutionDraft, hint: EntityHint
) -> IntentResolutionDraft:
    first = draft.intent_frames[0].model_copy(update={"entity_hint_ids": (hint.entity_hint_id,)})
    return draft.model_copy(
        update={"intent_frames": (first, *draft.intent_frames[1:]), "entity_hints": (hint,)}
    )


def test_unknown_id_is_contract_failure(validation_inputs: ValidationInputs) -> None:
    """Catches accepting a model-invented metric instead of failing closed."""
    draft = replace_metric(validation_inputs.draft, "invented_metric")

    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_ID"):
        validate_semantics(draft=draft, **validation_inputs.rest)


def test_span_text_must_match_original_segment(validation_inputs: ValidationInputs) -> None:
    """Catches evidence text being trusted without checking the original segment."""
    draft = replace_span_text(validation_inputs.draft, "다른 문장")

    with pytest.raises(ResolverContractError, match="LITERAL_SPAN_MISMATCH"):
        validate_semantics(draft=draft, **validation_inputs.rest)


def test_concept_outside_selected_family_is_contract_failure(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches treating domestic-bond credit grades as applicable to an ETF frame."""
    draft = replace_metric(validation_inputs.draft, "credit_grade")

    with pytest.raises(ResolverContractError, match="MODEL_INAPPLICABLE_CONCEPT"):
        validate_semantics(draft=draft, **validation_inputs.rest)


def test_unit_slot_is_rejected_without_a_registered_unit_authority(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches arbitrary units bypassing the bounded resolver vocabulary."""
    first = validation_inputs.draft.intent_frames[0]
    draft = validation_inputs.draft.model_copy(
        update={
            "intent_frames": (
                first.model_copy(
                    update={
                        "slot_assignments": (
                            *first.slot_assignments,
                            _slot("slot-unit", SlotKind.UNIT, "invented_unit"),
                        )
                    }
                ),
                *validation_inputs.draft.intent_frames[1:],
            )
        }
    )

    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_ID"):
        validate_semantics(draft=draft, **validation_inputs.rest)


def test_entity_selection_must_be_present_in_its_model_candidate_list(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches selecting an offered entity that the model was not presented."""
    draft = _draft_with_entity_hint(
        validation_inputs.draft,
        _entity_hint(
            candidate_ids=("entity-product",), selected_ids=("entity-manager",)
        ),
    )

    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_ID"):
        validate_semantics(draft=draft, **validation_inputs.rest)


def test_entity_selection_must_satisfy_hint_and_frame_type_constraints(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches an AssetManager selected where the hint and frame require a product."""
    draft = _draft_with_entity_hint(
        validation_inputs.draft,
        _entity_hint(
            candidate_ids=("entity-manager",), selected_ids=("entity-manager",)
        ),
    )

    with pytest.raises(ResolverContractError, match="MODEL_INVALID_ENTITY_TYPE"):
        validate_semantics(draft=draft, **validation_inputs.rest)


def test_entity_subclass_satisfies_hint_and_frame_type_constraints(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches rejecting an ETF that the pinned TBox defines as a product."""
    draft = _draft_with_entity_hint(
        validation_inputs.draft,
        _entity_hint(
            candidate_ids=("entity-product",), selected_ids=("entity-product",)
        ),
    )

    assert validate_semantics(draft=draft, **validation_inputs.rest).resolution_status is ResolutionStatus.RESOLVED


def test_entity_transitive_subclass_satisfies_an_intermediate_type(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches dropping DomesticETF-to-ETF ancestry during validation."""
    group = validation_inputs.view.entity_candidates[0]
    domestic_etf = group.items[0].model_copy(update={"entity_type": "DomesticETF"})
    view = validation_inputs.view.model_copy(
        update={
            "entity_candidates": (
                group.model_copy(update={"items": (domestic_etf, *group.items[1:])}),
            ),
            "relation_definitions": (
                *validation_inputs.view.relation_definitions,
                ResolverViewRelationDefinition(
                    relation_id="tracksIndex",
                    definition_ko="상품이 추종하는 지수",
                    subject_ontology_types=("ETF",),
                    object_ontology_types=("Index",),
                    required_qualifiers=(),
                ),
            ),
        }
    )
    inputs = replace(validation_inputs, view=view)
    draft = _draft_with_entity_hint(
        inputs.draft,
        _entity_hint(
            candidate_ids=("entity-product",),
            selected_ids=("entity-product",),
            expected_type_ids=("ETF",),
        ),
    )

    assert validate_semantics(draft=draft, **inputs.rest).resolution_status is ResolutionStatus.RESOLVED


def test_entity_hint_without_mention_cannot_select_a_dataset_candidate(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches an unbounded entity selection bypassing mention-scoped candidates."""
    hint = _entity_hint(
        candidate_ids=("entity-product",), selected_ids=("entity-product",)
    ).model_copy(update={"mention_id": ()})
    draft = _draft_with_entity_hint(validation_inputs.draft, hint)

    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_ID"):
        validate_semantics(draft=draft, **validation_inputs.rest)


def test_unknown_storage_entity_type_cannot_be_selected_as_an_ontology_type(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches a raw candidate category becoming an approved ontology type."""
    group = validation_inputs.view.entity_candidates[0]
    unknown_candidate = group.items[0].model_copy(
        update={"entity_type": "UnknownStorageCategory"}
    )
    view = validation_inputs.view.model_copy(
        update={
            "entity_candidates": (
                group.model_copy(update={"items": (unknown_candidate, *group.items[1:])}),
            )
        }
    )
    inputs = replace(validation_inputs, view=view)
    draft = _draft_with_entity_hint(
        inputs.draft,
        _entity_hint(
            candidate_ids=("entity-product",),
            selected_ids=("entity-product",),
            expected_type_ids=("UnknownStorageCategory",),
        ),
    )

    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_ID"):
        validate_semantics(draft=draft, **inputs.rest)


def test_unknown_storage_entity_type_cannot_bypass_empty_constraints(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches selected raw candidate types when no compatibility constraint is present."""
    group = validation_inputs.view.entity_candidates[0]
    unknown_candidate = group.items[0].model_copy(
        update={"entity_type": "UnknownStorageCategory"}
    )
    view = validation_inputs.view.model_copy(
        update={
            "entity_candidates": (
                group.model_copy(update={"items": (unknown_candidate, *group.items[1:])}),
            )
        }
    )
    inputs = replace(validation_inputs, view=view)
    draft_with_hint = _draft_with_entity_hint(
        inputs.draft,
        _entity_hint(
            candidate_ids=("entity-product",),
            selected_ids=("entity-product",),
            expected_type_ids=(),
        ),
    )
    first = draft_with_hint.intent_frames[0].model_copy(update={"entity_type_ids": ()})
    draft = draft_with_hint.model_copy(
        update={"intent_frames": (first, *draft_with_hint.intent_frames[1:])}
    )

    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_ID"):
        validate_semantics(draft=draft, **inputs.rest)


def test_relation_direction_must_satisfy_the_catalog_endpoint_types(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches reversing managedBy so an asset manager becomes its subject."""
    second = validation_inputs.draft.intent_frames[1].model_copy(
        update={"entity_type_ids": ("AssetManager",)}
    )
    draft = validation_inputs.draft.model_copy(
        update={"intent_frames": (validation_inputs.draft.intent_frames[0], second)}
    )

    with pytest.raises(ResolverContractError, match="MODEL_INVALID_RELATION"):
        validate_semantics(draft=draft, **validation_inputs.rest)


def test_relation_requires_a_nonempty_subject_type(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches accepting a relation whose subject class was left unspecified."""
    second = validation_inputs.draft.intent_frames[1].model_copy(
        update={"entity_type_ids": ()}
    )
    draft = validation_inputs.draft.model_copy(
        update={"intent_frames": (validation_inputs.draft.intent_frames[0], second)}
    )

    with pytest.raises(ResolverContractError, match="MODEL_INVALID_RELATION"):
        validate_semantics(draft=draft, **validation_inputs.rest)


def test_relation_subject_type_accepts_a_pinned_tbox_subclass(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches rejecting ETF as a managedBy subject despite its product ancestry."""
    second = validation_inputs.draft.intent_frames[1].model_copy(
        update={"entity_type_ids": ("ETF",)}
    )
    draft = validation_inputs.draft.model_copy(
        update={"intent_frames": (validation_inputs.draft.intent_frames[0], second)}
    )

    assert validate_semantics(draft=draft, **validation_inputs.rest).resolution_status is ResolutionStatus.RESOLVED


def test_concept_type_allows_a_pinned_tbox_subclass(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches rejecting an ETF where AUM permits the FinancialProduct superclass."""
    first = validation_inputs.draft.intent_frames[0].model_copy(
        update={"entity_type_ids": ("ETF",)}
    )
    draft = validation_inputs.draft.model_copy(
        update={"intent_frames": (first, *validation_inputs.draft.intent_frames[1:])}
    )

    assert validate_semantics(draft=draft, **validation_inputs.rest).resolution_status is ResolutionStatus.RESOLVED


def test_valid_multiframe_semantics_derive_sorted_tags(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches losing structural tags or deriving them in nondeterministic order."""
    state = validate_semantics(draft=validation_inputs.draft, **validation_inputs.rest)

    assert {
        SemanticTag.CROSS_FAMILY,
        SemanticTag.MULTI_STEP,
        SemanticTag.CONTEXT_DEPENDENT,
        SemanticTag.TEMPORAL,
    } <= set(state.final_tags)
    assert state.final_tags == tuple(sorted(state.final_tags, key=lambda item: item.value))


def test_valid_unmapped_and_ambiguous_choices_remain_typed_issues(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches converting valid OOD and ambiguity states into planner exceptions."""
    first = validation_inputs.draft.intent_frames[0]
    unmapped_action = ActionChoice(
        state=ChoiceState.UNMAPPED,
        selected_ids=(),
        evidence_span_ids=("span-1",),
        reason_code="lexical_ood",
    )
    ambiguous_family = AxisChoice(
        state=ChoiceState.AMBIGUOUS,
        selected_ids=(),
        evidence_span_ids=("span-1",),
        reason_code="ambiguous_scope",
    )
    draft = validation_inputs.draft.model_copy(
        update={
            "intent_frames": (
                first.model_copy(
                    update={
                        "action_choice": unmapped_action,
                        "product_family_choice": ambiguous_family,
                    }
                ),
                *validation_inputs.draft.intent_frames[1:],
            )
        }
    )

    state = validate_semantics(draft=draft, **validation_inputs.rest)

    assert state.resolution_status is ResolutionStatus.UNMAPPED
    assert {issue.code for issue in state.issues} >= {
        "SEMANTIC_CONCEPT_UNMAPPED",
        "AMBIGUITY_UNRESOLVED",
    }


def test_validation_stage_and_status_orders_are_frozen() -> None:
    """Catches a stage reordering that would change fail-closed precedence."""
    assert VALIDATION_STAGES == (
        "schema",
        "offered_ids",
        "evidence_spans",
        "applicability",
        "ontology_relations",
        "literal_types",
        "frame_order",
        "slot_mutations",
        "tag_derivation",
        "resolution_status",
    )
    assert STATUS_PRECEDENCE == (
        ResolutionStatus.UNMAPPED,
        ResolutionStatus.CONTEXT_UNRESOLVED,
        ResolutionStatus.AMBIGUOUS,
        ResolutionStatus.RESOLVED,
    )


def test_semantic_state_carries_only_offered_target_mentions(
    validation_inputs: ValidationInputs,
) -> None:
    """Catches context validation accepting a mention absent from the ResolverView."""
    state = validate_semantics(draft=validation_inputs.draft, **validation_inputs.rest)

    assert state.offered_target_mention_ids == ("mention-entity",)
