"""Strict V3 proposal contract for source-mention semantic linking."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier

from .proposal import (
    ProposedAxisChoice,
    ProposedContextLink,
    ProposedEntityHint,
    ProposedReference,
    ProposedSemanticFlag,
    ProposedSlotMutation,
    require_valid_action_cardinality,
)
from .types import SemanticCoverageReason, SemanticCoverageState, SourceRole


class ProposedSemanticLinkV3(ContractModel):
    mention_id: Identifier
    state: Literal["selected", "ambiguous"]
    semantic_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    reason_code: Literal["explicit", "implicit", "ambiguous"]

    @model_validator(mode="after")
    def validate_link_cardinality(self) -> "ProposedSemanticLinkV3":
        if self.state == "selected" and len(self.semantic_ids) != 1:
            raise ValueError("selected semantic link requires exactly one semantic ID")
        if self.state == "ambiguous" and (
            len(self.semantic_ids) < 2
            or len(set(self.semantic_ids)) != len(self.semantic_ids)
        ):
            raise ValueError("ambiguous semantic link requires distinct semantic IDs")
        return self


class FrameSemanticCoverageV3(ContractModel):
    state: SemanticCoverageState
    reason: SemanticCoverageReason


class ProposedIntentFrameV3(ContractModel):
    segment_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    action_choice: ProposedAxisChoice
    product_family_choice: ProposedAxisChoice
    entity_type_ids: tuple[Identifier, ...]
    semantic_links: tuple[ProposedSemanticLinkV3, ...]
    unmapped_mention_ids: tuple[Identifier, ...]
    semantic_coverage: FrameSemanticCoverageV3
    entity_hints: tuple[ProposedEntityHint, ...]
    produced_result_hints: tuple[SourceRole, ...]

    @model_validator(mode="after")
    def validate_semantic_shape(self) -> "ProposedIntentFrameV3":
        require_valid_action_cardinality(
            self.action_choice.state,
            self.action_choice.selected_ids,
            self.semantic_coverage.state,
        )
        linked_mentions = tuple(link.mention_id for link in self.semantic_links)
        if len(set(linked_mentions)) != len(linked_mentions):
            raise ValueError("semantic links must use each mention at most once")
        if set(linked_mentions) & set(self.unmapped_mention_ids):
            raise ValueError("a mention cannot be both linked and unmapped")
        coverage = self.semantic_coverage
        if coverage.state is SemanticCoverageState.COVERED:
            if (
                coverage.reason is not SemanticCoverageReason.NONE
                or self.unmapped_mention_ids
            ):
                raise ValueError(
                    "covered semantic coverage requires no OOD reason or mentions"
                )
        elif coverage.reason is SemanticCoverageReason.NONE or not self.unmapped_mention_ids:
            raise ValueError(
                "uncovered semantic coverage requires an OOD reason and mention"
            )
        return self


class IntentResolutionProposalV3(ContractModel):
    proposal_schema_version: Literal["3.0"] = "3.0"
    frames: Annotated[
        tuple[ProposedIntentFrameV3, ...], Field(min_length=1, max_length=16)
    ]
    references: tuple[ProposedReference, ...]
    context_links: tuple[ProposedContextLink, ...]
    slot_mutations: tuple[ProposedSlotMutation, ...]
    semantic_flag_hints: tuple[ProposedSemanticFlag, ...]
    frame_limit_exceeded: bool
