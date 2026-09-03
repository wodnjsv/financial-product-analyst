from typing import Annotated, ClassVar, Literal

from pydantic import Field, model_validator

from financial_agent.contracts.base import (
    ContractModel,
    Identifier,
    RuntimeArtifact,
    Sha256Hex,
)
from financial_agent.contracts.enums import Cardinality
from financial_agent.contracts.validation import require_unique_ids

from .draft import (
    ActionChoice,
    EntityHintV2,
    ProductFamilyChoice,
    SemanticLinkDraftV3,
    SlotAssignment,
    validate_v2_entity_hint_ownership,
)
from .proposal import FrameSemanticCoverage, require_valid_action_cardinality
from .types import (
    ContextLinkType,
    ReferenceTargetKind,
    ResolutionStatus,
    Selector,
    SemanticTag,
    SlotKind,
    SlotMutationKind,
    SourceRole,
)

INTERNAL_SCHEMA_VERSION = "1.0"
OptionalIdentifier = Annotated[tuple[Identifier, ...], Field(max_length=1)]
OptionalSelector = Annotated[tuple[Selector, ...], Field(max_length=1)]
OptionalCardinality = Annotated[tuple[Cardinality, ...], Field(max_length=1)]
OptionalReferenceTargetKind = Annotated[
    tuple[ReferenceTargetKind, ...], Field(max_length=1)
]
OptionalSlotKind = Annotated[tuple[SlotKind, ...], Field(max_length=1)]


class ContractFileHash(ContractModel):
    relative_path: str
    sha256: Sha256Hex


class ResolverBuildManifest(ContractModel):
    schema_version: Literal["1.0"] = INTERNAL_SCHEMA_VERSION
    catalog_version: Identifier
    catalog_hash: Sha256Hex
    ontology_hashes: tuple[ContractFileHash, ...]
    overlay_version: Identifier
    overlay_hash: Sha256Hex
    normalizer_version: Identifier
    candidate_policy_version: Identifier
    resolver_schema_version: Identifier
    prompt_version: Identifier
    adapter_version: Identifier

    @model_validator(mode="after")
    def validate_ontology_hashes(self) -> "ResolverBuildManifest":
        paths = tuple(item.relative_path for item in self.ontology_hashes)
        if paths != tuple(sorted(paths)):
            raise ValueError("ontology hashes must be ordered by relative path")
        require_unique_ids(paths, label="ontology hash paths")
        return self


class ValidatedSlotMutation(ContractModel):
    slot_mutation_id: Identifier
    consumer_frame_id: Identifier
    slot_kind: SlotKind
    mutation_kind: SlotMutationKind
    source_frame_id: OptionalIdentifier


class ValidatedIntentFrame(ContractModel):
    frame_id: Identifier
    ordinal: int = Field(ge=0)
    frame_status: ResolutionStatus
    segment_ids: tuple[Identifier, ...]
    evidence_span_ids: tuple[Identifier, ...]
    action_choice: ActionChoice
    product_family_choice: ProductFamilyChoice
    entity_type_ids: tuple[Identifier, ...]
    entity_hint_ids: tuple[Identifier, ...]
    slot_assignments: tuple[SlotAssignment, ...]
    produced_result_roles: tuple[SourceRole, ...]
    slot_mutations: tuple[ValidatedSlotMutation, ...]

    @model_validator(mode="after")
    def validate_nested_ids(self) -> "ValidatedIntentFrame":
        require_unique_ids(
            (assignment.slot_assignment_id for assignment in self.slot_assignments),
            label="slot assignments",
        )
        require_unique_ids(
            (mutation.slot_mutation_id for mutation in self.slot_mutations),
            label="slot mutations",
        )
        return self


class ValidatedIntentFrameV2(ValidatedIntentFrame):
    segment_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    semantic_coverage: Annotated[
        tuple[FrameSemanticCoverage, ...], Field(min_length=1, max_length=1)
    ]

    @model_validator(mode="after")
    def validate_v2_action_cardinality(self) -> "ValidatedIntentFrameV2":
        require_valid_action_cardinality(
            self.action_choice.state,
            self.action_choice.selected_ids,
            self.semantic_coverage[0].state,
        )
        return self


class ValidatedContextLink(ContractModel):
    context_link_id: Identifier
    reference_id: Identifier
    link_type: ContextLinkType
    source_role: SourceRole
    selector: OptionalSelector
    selector_literal_candidate_id: OptionalIdentifier
    producer_frame_id: Identifier
    consumer_frame_id: Identifier
    target_kind: OptionalReferenceTargetKind
    target_cardinality: OptionalCardinality
    target_slot_kind: OptionalSlotKind


class ResolutionIssue(ContractModel):
    issue_id: Identifier
    code: Identifier
    related_ids: tuple[Identifier, ...]
    evidence_span_ids: tuple[Identifier, ...]


class ValidationEvent(ContractModel):
    event_id: Identifier
    stage: Identifier
    code: Identifier
    related_ids: tuple[Identifier, ...]


class ValidatedIntentResolution(RuntimeArtifact):
    resolution_id: Identifier
    draft_hash: Sha256Hex
    canonical_frames: Annotated[
        tuple[ValidatedIntentFrame, ...], Field(max_length=16)
    ]
    context_links: tuple[ValidatedContextLink, ...]
    final_tags: tuple[SemanticTag, ...]
    resolution_status: ResolutionStatus
    issues: tuple[ResolutionIssue, ...]
    validation_events: tuple[ValidationEvent, ...]
    build_manifest: ResolverBuildManifest
    active_dataset_manifest_hash: Sha256Hex
    repair_used: bool
    invalid_attempt_hashes: tuple[Sha256Hex, ...]

    @model_validator(mode="after")
    def validate_shape(self) -> "ValidatedIntentResolution":
        require_unique_ids(
            (frame.frame_id for frame in self.canonical_frames),
            label="canonical frames",
        )
        if tuple(frame.ordinal for frame in self.canonical_frames) != tuple(
            range(len(self.canonical_frames))
        ):
            raise ValueError("canonical frame ordinals must match tuple order")
        require_unique_ids(
            (link.context_link_id for link in self.context_links),
            label="validated context links",
        )
        require_unique_ids(
            (issue.issue_id for issue in self.issues),
            label="issues",
        )
        require_unique_ids(
            (event.event_id for event in self.validation_events),
            label="validation events",
        )
        return self


class ValidatedIntentResolutionV2(ValidatedIntentResolution):
    resolver_schema_version: ClassVar[str] = "2.0"
    canonical_frames: Annotated[
        tuple[ValidatedIntentFrameV2, ...], Field(min_length=1, max_length=16)
    ]
    entity_hints: tuple[EntityHintV2, ...]

    @model_validator(mode="after")
    def validate_v2_provenance(self) -> "ValidatedIntentResolutionV2":
        expected = type(self).resolver_schema_version
        if self.build_manifest.resolver_schema_version != expected:
            raise ValueError(
                f"{expected} validated resolutions require resolver schema version {expected}"
            )
        validate_v2_entity_hint_ownership(self.canonical_frames, self.entity_hints)
        return self


class ValidatedSemanticLinkV3(SemanticLinkDraftV3):
    pass


class ValidatedIntentResolutionV3(ValidatedIntentResolutionV2):
    resolver_schema_version: ClassVar[str] = "3.0"
    semantic_links: tuple[ValidatedSemanticLinkV3, ...]

    @model_validator(mode="after")
    def validate_v3_semantic_links(self) -> "ValidatedIntentResolutionV3":
        require_unique_ids(
            (link.semantic_link_id for link in self.semantic_links),
            label="validated semantic links",
        )
        frames = {frame.frame_id for frame in self.canonical_frames}
        if any(link.frame_id not in frames for link in self.semantic_links):
            raise ValueError("validated semantic link frame references must exist")
        owners = tuple(
            (link.frame_id, link.mention_id) for link in self.semantic_links
        )
        if len(set(owners)) != len(owners):
            raise ValueError("each validated frame mention may have one semantic link")
        return self
