from typing import Annotated, ClassVar, Literal

from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.enums import Cardinality, ReferenceMentionType
from financial_agent.contracts.validation import require_unique_ids

from .types import (
    ChoiceState,
    ContextLinkType,
    EntitySemanticRole,
    ReferenceForm,
    ReferenceTargetKind,
    Selector,
    SemanticTag,
    SlotKind,
    SlotMutationKind,
    SourceRole,
    IntentType,
    ProductFamily,
)
from .proposal import FrameSemanticCoverage, require_valid_action_cardinality

OptionalIdentifier = Annotated[tuple[Identifier, ...], Field(max_length=1)]
OptionalSelector = Annotated[tuple[Selector, ...], Field(max_length=1)]
OptionalCardinality = Annotated[tuple[Cardinality, ...], Field(max_length=1)]
OptionalReferenceTargetKind = Annotated[
    tuple[ReferenceTargetKind, ...], Field(max_length=1)
]
OptionalSlotKind = Annotated[tuple[SlotKind, ...], Field(max_length=1)]


class EvidenceSpan(ContractModel):
    span_id: Identifier
    segment_id: Identifier
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    text: str


class AxisChoice(ContractModel):
    state: ChoiceState
    selected_ids: tuple[Identifier, ...]
    evidence_span_ids: tuple[Identifier, ...]
    reason_code: Identifier


class ActionChoice(AxisChoice):
    selected_ids: tuple[IntentType, ...]


class ProductFamilyChoice(AxisChoice):
    selected_ids: tuple[ProductFamily, ...]


class EntityHint(ContractModel):
    entity_hint_id: Identifier
    mention_id: OptionalIdentifier
    evidence_span_ids: tuple[Identifier, ...]
    expected_entity_type_ids: tuple[Identifier, ...]
    candidate_entity_ids: tuple[Identifier, ...]
    selected_candidate_ids: OptionalIdentifier
    reason_code: Identifier


class EntityHintV2(EntityHint):
    semantic_role: EntitySemanticRole
    relation_id: OptionalIdentifier
    expected_entity_type_ids: Annotated[
        tuple[Identifier, ...], Field(min_length=1)
    ]

    @model_validator(mode="after")
    def validate_role_shape(self) -> "EntityHintV2":
        validate_entity_hint_v2_shape(self)
        return self


class SlotAssignment(ContractModel):
    slot_assignment_id: Identifier
    slot_kind: SlotKind
    value_ids: tuple[Identifier, ...]
    evidence_span_ids: tuple[Identifier, ...]
    reason_code: Identifier


class ReferenceHint(ContractModel):
    reference_id: Identifier
    segment_id: Identifier
    evidence_span_ids: tuple[Identifier, ...]
    surface_presence: ReferenceMentionType
    reference_form: ReferenceForm
    grammatical_number: Annotated[
        tuple[Literal["singular", "plural", "unknown"], ...], Field(max_length=1)
    ]
    expected_target_kind: OptionalReferenceTargetKind
    expected_cardinality: OptionalCardinality
    candidate_target_frame_ids: tuple[Identifier, ...]
    candidate_target_mention_ids: tuple[Identifier, ...]
    status: Literal["resolved", "ambiguous", "unresolved"]
    reason_code: Identifier


class ContextLinkHint(ContractModel):
    context_link_id: Identifier
    reference_id: Identifier
    link_type: ContextLinkType
    source_role: SourceRole
    selector: OptionalSelector
    selector_literal_candidate_id: OptionalIdentifier
    producer_frame_id: Identifier
    consumer_frame_id: Identifier
    target_slot_kind: OptionalSlotKind


class SlotMutation(ContractModel):
    slot_mutation_id: Identifier
    consumer_frame_id: Identifier
    slot_kind: SlotKind
    mutation_kind: SlotMutationKind
    source_frame_id: OptionalIdentifier
    evidence_span_ids: tuple[Identifier, ...]
    reason_code: Identifier


class SemanticFlagHint(ContractModel):
    semantic_tag: SemanticTag
    evidence_span_ids: tuple[Identifier, ...]
    reason_code: Identifier


class IntentFrameDraft(ContractModel):
    frame_id: Identifier
    ordinal: int = Field(ge=0)
    segment_ids: tuple[Identifier, ...]
    evidence_span_ids: tuple[Identifier, ...]
    normalized_intent_argument: str
    action_choice: ActionChoice
    product_family_choice: ProductFamilyChoice
    entity_type_ids: tuple[Identifier, ...]
    entity_hint_ids: tuple[Identifier, ...]
    slot_assignments: tuple[SlotAssignment, ...]
    produced_result_hints: tuple[SourceRole, ...]

    @model_validator(mode="after")
    def validate_slot_assignments(self) -> "IntentFrameDraft":
        require_unique_ids(
            (assignment.slot_assignment_id for assignment in self.slot_assignments),
            label="slot assignments",
        )
        return self


class IntentFrameDraftV2(IntentFrameDraft):
    segment_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    semantic_coverage: Annotated[
        tuple[FrameSemanticCoverage, ...], Field(min_length=1, max_length=1)
    ]

    @model_validator(mode="after")
    def validate_v2_action_cardinality(self) -> "IntentFrameDraftV2":
        require_valid_action_cardinality(
            self.action_choice.state,
            self.action_choice.selected_ids,
            self.semantic_coverage[0].state,
        )
        return self


class IntentResolutionDraft(ContractModel):
    evidence_spans: tuple[EvidenceSpan, ...]
    intent_frames: Annotated[tuple[IntentFrameDraft, ...], Field(max_length=16)]
    entity_hints: tuple[EntityHint, ...]
    reference_hints: tuple[ReferenceHint, ...]
    context_link_hints: tuple[ContextLinkHint, ...]
    slot_mutations: tuple[SlotMutation, ...]
    semantic_flag_hints: tuple[SemanticFlagHint, ...]
    frame_limit_exceeded: bool

    @model_validator(mode="after")
    def validate_shape(self) -> "IntentResolutionDraft":
        require_unique_ids(
            (span.span_id for span in self.evidence_spans),
            label="evidence spans",
        )
        require_unique_ids(
            (frame.frame_id for frame in self.intent_frames),
            label="intent frames",
        )
        require_unique_ids(
            (hint.entity_hint_id for hint in self.entity_hints), label="entity hints"
        )
        require_unique_ids(
            (hint.reference_id for hint in self.reference_hints), label="reference hints"
        )
        require_unique_ids(
            (hint.context_link_id for hint in self.context_link_hints),
            label="context link hints",
        )
        require_unique_ids(
            (mutation.slot_mutation_id for mutation in self.slot_mutations),
            label="slot mutations",
        )
        if tuple(frame.ordinal for frame in self.intent_frames) != tuple(
            range(len(self.intent_frames))
        ):
            raise ValueError("intent frame ordinals must match tuple order")
        return self


class IntentResolutionDraftV2(IntentResolutionDraft):
    resolver_schema_version: ClassVar[str] = "2.0"
    intent_frames: Annotated[
        tuple[IntentFrameDraftV2, ...], Field(min_length=1, max_length=16)
    ]
    entity_hints: tuple[EntityHintV2, ...]

    @model_validator(mode="after")
    def validate_entity_hint_ownership(self) -> "IntentResolutionDraftV2":
        validate_v2_entity_hint_ownership(self.intent_frames, self.entity_hints)
        return self


class SemanticLinkDraftV3(ContractModel):
    semantic_link_id: Identifier
    frame_id: Identifier
    mention_id: Identifier
    semantic_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    state: Literal["selected", "ambiguous"]
    evidence_span_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    reason_code: Identifier

    @model_validator(mode="after")
    def validate_cardinality(self) -> "SemanticLinkDraftV3":
        if self.state == "selected" and len(self.semantic_ids) != 1:
            raise ValueError("selected semantic link requires exactly one semantic ID")
        if self.state == "ambiguous" and (
            len(self.semantic_ids) < 2
            or len(set(self.semantic_ids)) != len(self.semantic_ids)
        ):
            raise ValueError("ambiguous semantic link requires distinct semantic IDs")
        return self


class IntentResolutionDraftV3(IntentResolutionDraftV2):
    resolver_schema_version: ClassVar[str] = "3.0"
    semantic_links: tuple[SemanticLinkDraftV3, ...]

    @model_validator(mode="after")
    def validate_semantic_link_ownership(self) -> "IntentResolutionDraftV3":
        require_unique_ids(
            (link.semantic_link_id for link in self.semantic_links),
            label="semantic links",
        )
        frames = {frame.frame_id for frame in self.intent_frames}
        evidence = {span.span_id for span in self.evidence_spans}
        linked_mentions: set[tuple[str, str]] = set()
        for link in self.semantic_links:
            if link.frame_id not in frames:
                raise ValueError("semantic link frame references must exist")
            if not set(link.evidence_span_ids) <= evidence:
                raise ValueError("semantic link evidence references must exist")
            owner = (link.frame_id, link.mention_id)
            if owner in linked_mentions:
                raise ValueError("each frame mention may have one semantic link")
            linked_mentions.add(owner)
        return self


def validate_v2_entity_hint_ownership(
    frames: tuple[object, ...], hints: tuple[EntityHintV2, ...]
) -> None:
    """Require each canonical v2 entity selection to have one owning frame hint."""
    for hint in hints:
        validate_entity_hint_v2_shape(hint)
    hints_by_id = {hint.entity_hint_id: hint for hint in hints}
    if len(hints_by_id) != len(hints):
        raise ValueError("entity hints must be unique")
    owners: dict[str, int] = {hint_id: 0 for hint_id in hints_by_id}
    for frame in frames:
        hint_ids = tuple(getattr(frame, "entity_hint_ids"))
        if len(set(hint_ids)) != len(hint_ids):
            raise ValueError("frame entity hints must be unique")
        if not set(hint_ids) <= set(hints_by_id):
            raise ValueError("frame entity hint references must exist")
        for hint_id in hint_ids:
            owners[hint_id] += 1
        selected_entity_ids = tuple(
            entity_id
            for hint_id in hint_ids
            for entity_id in hints_by_id[hint_id].selected_candidate_ids
        )
        try:
            entity_assignments = tuple(
                assignment
                for assignment in getattr(frame, "slot_assignments")
                if SlotKind(assignment.slot_kind) is SlotKind.ENTITY
            )
        except ValueError as error:
            raise ValueError("v2 slot kind is invalid") from error
        projected_entity_ids = tuple(
            entity_id
            for assignment in entity_assignments
            for entity_id in assignment.value_ids
        )
        if (
            any(len(assignment.value_ids) != 1 for assignment in entity_assignments)
            or tuple(sorted(projected_entity_ids)) != tuple(sorted(selected_entity_ids))
            or len(entity_assignments) != len(selected_entity_ids)
        ):
            raise ValueError("v2 entity slots must project same-frame selected hints")
    if any(owner_count != 1 for owner_count in owners.values()):
        raise ValueError("each v2 entity hint must have exactly one owning frame")


def validate_entity_hint_v2_shape(hint: EntityHintV2) -> None:
    """Validate role-bearing hint fields even after a deserialized model is copied."""
    if not hint.expected_entity_type_ids:
        raise ValueError("entity hint expected types must be nonempty")
    if hint.semantic_role == EntitySemanticRole.FRAME_SUBJECT:
        if hint.relation_id:
            raise ValueError("frame subject cannot carry a relation ID")
    elif hint.semantic_role == EntitySemanticRole.RELATION_OBJECT:
        if len(hint.relation_id) != 1:
            raise ValueError("relation object requires exactly one relation ID")
    else:
        raise ValueError("entity hint semantic role is invalid")
