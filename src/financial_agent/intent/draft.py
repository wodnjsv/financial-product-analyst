from typing import Annotated, Literal

from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.enums import Cardinality, ReferenceMentionType
from financial_agent.contracts.validation import require_unique_ids

from .types import (
    ChoiceState,
    ContextLinkType,
    ReferenceForm,
    ReferenceTargetKind,
    Selector,
    SemanticTag,
    SlotKind,
    SlotMutationKind,
    SourceRole,
)

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


class EntityHint(ContractModel):
    entity_hint_id: Identifier
    mention_id: OptionalIdentifier
    evidence_span_ids: tuple[Identifier, ...]
    expected_entity_type_ids: tuple[Identifier, ...]
    candidate_entity_ids: tuple[Identifier, ...]
    selected_candidate_ids: OptionalIdentifier
    reason_code: Identifier


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
    action_choice: AxisChoice
    product_family_choice: AxisChoice
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
