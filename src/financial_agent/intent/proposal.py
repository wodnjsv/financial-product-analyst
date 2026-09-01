"""Strict model-facing intent-resolution proposal contract, version 2."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.enums import Cardinality, ReferenceMentionType

from .types import (
    ChoiceState,
    ContextLinkType,
    ReferenceForm,
    ReferenceTargetKind,
    Selector,
    SemanticCoverageReason,
    SemanticCoverageState,
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
OptionalFrameOrdinal = Annotated[tuple[int, ...], Field(max_length=1)]
FrameOrdinal = Annotated[int, Field(ge=0, le=15)]


class FrameSemanticCoverage(ContractModel):
    state: SemanticCoverageState
    reason: SemanticCoverageReason
    evidence_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_state_reason_evidence(self) -> "FrameSemanticCoverage":
        if self.state is SemanticCoverageState.COVERED:
            if self.reason is not SemanticCoverageReason.NONE or self.evidence_ids:
                raise ValueError("covered semantic coverage requires no OOD reason or evidence")
        elif self.reason is SemanticCoverageReason.NONE or not self.evidence_ids:
            raise ValueError("uncovered semantic coverage requires an OOD reason and evidence")
        return self


class ProposedAxisChoice(ContractModel):
    state: ChoiceState
    selected_ids: tuple[Identifier, ...]
    evidence_ids: tuple[Identifier, ...]
    reason_code: Identifier


class ProposedSlotAssignment(ContractModel):
    slot_kind: SlotKind
    value_ids: tuple[Identifier, ...]
    evidence_ids: tuple[Identifier, ...]
    reason_code: Identifier


class ProposedEntityHint(ContractModel):
    mention_id: OptionalIdentifier
    candidate_entity_ids: tuple[Identifier, ...]


class ProposedIntentFrame(ContractModel):
    segment_ids: tuple[Identifier, ...]
    action_choice: ProposedAxisChoice
    product_family_choice: ProposedAxisChoice
    semantic_coverage: FrameSemanticCoverage
    slot_assignments: tuple[ProposedSlotAssignment, ...]
    entity_hints: tuple[ProposedEntityHint, ...]
    produced_result_hints: tuple[SourceRole, ...]


class ProposedReference(ContractModel):
    reference_id: Identifier
    producer_frame_ordinals: tuple[FrameOrdinal, ...]
    surface_presence: ReferenceMentionType
    reference_form: ReferenceForm
    grammatical_number: Annotated[
        tuple[Literal["singular", "plural", "unknown"], ...], Field(max_length=1)
    ]
    expected_target_kind: OptionalReferenceTargetKind
    expected_cardinality: OptionalCardinality
    status: Literal["resolved", "ambiguous", "unresolved"]
    reason_code: Identifier


class ProposedContextLink(ContractModel):
    reference_id: Identifier
    link_type: ContextLinkType
    source_role: SourceRole
    selector: OptionalSelector
    selector_literal_candidate_id: OptionalIdentifier
    producer_frame_ordinal: FrameOrdinal
    consumer_frame_ordinal: FrameOrdinal
    target_slot_kind: OptionalSlotKind


class ProposedSlotMutation(ContractModel):
    consumer_frame_ordinal: FrameOrdinal
    slot_kind: SlotKind
    mutation_kind: SlotMutationKind
    source_frame_ordinal: OptionalFrameOrdinal
    evidence_ids: tuple[Identifier, ...]
    reason_code: Identifier


class ProposedSemanticFlag(ContractModel):
    semantic_tag: SemanticTag
    evidence_ids: tuple[Identifier, ...]
    reason_code: Identifier


class IntentResolutionProposalV2(ContractModel):
    proposal_schema_version: Literal["2.0"] = "2.0"
    frames: Annotated[tuple[ProposedIntentFrame, ...], Field(max_length=16)]
    references: tuple[ProposedReference, ...]
    context_links: tuple[ProposedContextLink, ...]
    slot_mutations: tuple[ProposedSlotMutation, ...]
    semantic_flag_hints: tuple[ProposedSemanticFlag, ...]
    frame_limit_exceeded: bool
