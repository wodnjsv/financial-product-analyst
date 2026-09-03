"""Strict, data-neutral contracts and metrics for offline resolver evaluation.

The production resolver never imports evaluation fixtures. Evaluation inputs are
provided at the offline boundary and validated before any metric is computed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
import json
from math import ceil
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    Field,
    RootModel,
    computed_field,
    field_validator,
    model_validator,
)

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.request import RequestContext
from financial_agent.contracts.canonical import canonical_sha256

from .catalog import SemanticCatalogSnapshot
from .context import validate_context_graph
from .draft import IntentResolutionDraft, IntentResolutionDraftV2
from .errors import ResolverContractError
from .normalization import NormalizedRequest
from .resolution import (
    ResolverBuildManifest,
    ValidatedIntentResolution,
    ValidatedIntentResolutionV2,
)
from .validation import validate_semantics
from .view import MAX_CANDIDATES_PER_MENTION, ResolverView


ResolutionStatusLabel = Literal[
    "resolved", "ambiguous", "unmapped", "context_unresolved"
]
ExpectedPipelineOutcome = Literal["semantic_resolution", "pre_model_rejected"]
ActualPipelineOutcome = Literal[
    "semantic_resolution", "pre_model_rejected", "model_resolution_failed"
]
OodType = Literal["combination", "vocabulary", "domain", "context"]
CoverageState = Literal["covered", "partial", "unmapped"]
CoverageReason = Literal[
    "none",
    "lexical_ood",
    "domain_ood",
    "unsupported_operation",
    "missing_critical_semantic",
]
EvaluationMode = Literal["decoupled", "full"]
ProbeKind = Literal["unknown_id", "invalid_context_graph"]
ProbeDecision = Literal["accepted", "rejected"]
_FALSE_FAST_OOD_TYPES = frozenset({"vocabulary", "domain", "context"})
_HYBRID_SEMANTIC_LINK_CASE_HASHES = {
    "HYB-LINK-001": "081c52c09dd6e346b92bff1cc50f11e2df072e1d6fc4c6204882ada182abb2ed",
    "HYB-LINK-002": "abe78ca47904d9a9f5b6cd4168ed33f888b1030397a8f2771de5125c748f54e2",
    "HYB-LINK-003": "24750ba5631f982d010e1f69e0f30d95c42834840e722ddb56227b047b2fc347",
    "HYB-LINK-004": "6b6cda1e6c5f5093c03d732f2ba99ffac02c39533006e656d263e291b722341c",
    "HYB-LINK-005": "a70f57b472f6a711fd457687dbd8187a4ad30757fac99bf1eb15c47031ed1c8e",
}
_HYBRID_SEMANTIC_LINK_CASE_COUNT = len(_HYBRID_SEMANTIC_LINK_CASE_HASHES)
_HYBRID_SEMANTIC_LINK_SPAN_COUNT = 5
_HYBRID_SEMANTIC_LINK_SEMANTIC_COUNT = 4
_HYBRID_SEMANTIC_LINK_OOD_COUNT = 1
_PROBE_CODES: dict[tuple[str, str], tuple[str, str]] = {
    ("unknown_id", "accepted"): ("UNKNOWN_ID_ACCEPTED", "UNKNOWN_ID_ACCEPTED"),
    ("unknown_id", "rejected"): ("UNKNOWN_ID_REJECTED", "MODEL_UNKNOWN_ID"),
    ("invalid_context_graph", "accepted"): (
        "INVALID_GRAPH_ACCEPTED",
        "INVALID_GRAPH_ACCEPTED",
    ),
    ("invalid_context_graph", "rejected"): (
        "INVALID_GRAPH_REJECTED",
        "INVALID_CONTEXT_GRAPH",
    ),
}


class EvaluationSegment(ContractModel):
    segment_id: Identifier
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)


class ExpectedSlot(ContractModel):
    slot_kind: Identifier
    value_ids: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> "ExpectedSlot":
        _require_sorted_unique(self.value_ids, "slot value IDs")
        return self


class EvaluationFrameCoverage(ContractModel):
    state: CoverageState = "covered"
    reason: CoverageReason = "none"

    @model_validator(mode="after")
    def validate_state_reason(self) -> "EvaluationFrameCoverage":
        if (self.state == "covered") != (self.reason == "none"):
            raise ValueError("coverage state and reason contradict each other")
        return self


class EvaluationEntityHint(ContractModel):
    """Sanitized role semantics used only for offline frame conformance."""

    semantic_role: Literal["frame_subject", "relation_object"]
    relation_id: tuple[Identifier, ...] = Field(max_length=1)
    expected_entity_type_ids: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_role_shape(self) -> "EvaluationEntityHint":
        _require_sorted_unique(
            self.expected_entity_type_ids, "evaluation entity hint type IDs"
        )
        if self.semantic_role == "frame_subject" and self.relation_id:
            raise ValueError("frame subject cannot carry a relation ID")
        if self.semantic_role == "relation_object" and len(self.relation_id) != 1:
            raise ValueError("relation object requires exactly one relation ID")
        return self


class EvaluationFrame(ContractModel):
    frame_id: Identifier
    ordinal: int = Field(ge=0)
    action_ids: tuple[Identifier, ...] = Field(
        validation_alias=AliasChoices("action_ids", "action_id")
    )
    product_family_ids: tuple[Identifier, ...]
    entity_type_ids: tuple[Identifier, ...]
    slots: tuple[ExpectedSlot, ...]
    semantic_coverage: EvaluationFrameCoverage = Field(
        default_factory=EvaluationFrameCoverage
    )
    entity_hints: tuple[EvaluationEntityHint, ...] | None = None

    @field_validator("action_ids", mode="before")
    @classmethod
    def accept_frozen_v2_action_id(cls, value: object) -> object:
        """Read frozen v2 fixtures without changing their bytes or labels."""
        if isinstance(value, str):
            return (value,)
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_semantic_sets(self) -> "EvaluationFrame":
        _require_sorted_unique(self.action_ids, "action IDs")
        _require_sorted_unique(self.product_family_ids, "product family IDs")
        _require_sorted_unique(self.entity_type_ids, "entity type IDs")
        _require_unique((slot.slot_kind for slot in self.slots), "slot kinds")
        return self

    @property
    def action_id(self) -> str:
        if len(self.action_ids) != 1:
            raise AttributeError("frame does not have exactly one action")
        return self.action_ids[0]


class ExpectedReference(ContractModel):
    reference_id: Identifier
    reference_form: Identifier
    status: Literal["resolved", "ambiguous", "unresolved"]


class ExpectedContextLink(ContractModel):
    context_link_id: Identifier
    reference_id: Identifier
    link_type: Identifier
    source_role: Identifier
    selector: Identifier | None = None
    producer_frame_id: Identifier
    consumer_frame_id: Identifier
    target_cardinality: Identifier | None = None


class ExpectedSlotMutation(ContractModel):
    slot_mutation_id: Identifier
    consumer_frame_id: Identifier
    slot_kind: Identifier
    mutation_kind: Identifier
    source_frame_id: Identifier | None = None


class EvaluationProbe(ContractModel):
    probe_id: Identifier
    kind: ProbeKind
    subject_id: Identifier | None = None
    frame_ordinal: int | None = Field(default=None, ge=0)
    slot_kind: Identifier | None = None
    link_ordinal: int | None = Field(default=None, ge=0)
    graph_field: Literal["consumer_frame_id"] | None = None
    # Frozen v2 compatibility only. New/default fixtures use executable specs above.
    subject_ids: tuple[Identifier, ...] = ()
    expected_rejection_code: Identifier

    @model_validator(mode="after")
    def validate_probe(self) -> "EvaluationProbe":
        _require_sorted_unique(self.subject_ids, "probe subject IDs")
        expected = _PROBE_CODES[(self.kind, "rejected")][1]
        if self.expected_rejection_code != expected:
            raise ValueError("evaluation probe rejection code does not match kind")
        legacy = bool(self.subject_ids)
        executable = self.subject_id is not None
        if legacy == executable:
            raise ValueError("probe must be exactly one of frozen-v2 or executable")
        if legacy:
            if any(
                value is not None
                for value in (
                    self.frame_ordinal,
                    self.slot_kind,
                    self.link_ordinal,
                    self.graph_field,
                )
            ):
                raise ValueError("frozen-v2 probe cannot carry mutation target")
        elif self.kind == "unknown_id":
            if (
                self.frame_ordinal is None
                or self.slot_kind is None
                or self.link_ordinal is not None
                or self.graph_field is not None
            ):
                raise ValueError("unknown-ID probe target is incomplete")
        elif (
            self.link_ordinal is None
            or self.graph_field != "consumer_frame_id"
            or self.frame_ordinal is not None
            or self.slot_kind is not None
        ):
            raise ValueError("invalid-graph probe target is incomplete")
        return self

    @property
    def executable(self) -> bool:
        return self.subject_id is not None


class EvaluationCase(ContractModel):
    case_id: Identifier
    category: Identifier
    subcategory: Identifier
    question: str = Field(min_length=1)
    segments: tuple[EvaluationSegment, ...] = Field(min_length=1)
    expected_candidate_ids: tuple[Identifier, ...]
    expected_frames: tuple[EvaluationFrame, ...]
    expected_references: tuple[ExpectedReference, ...]
    expected_context_links: tuple[ExpectedContextLink, ...]
    expected_slot_mutations: tuple[ExpectedSlotMutation, ...]
    expected_resolution_status: ResolutionStatusLabel
    expected_tags: tuple[Identifier, ...]
    expected_pipeline_outcome: ExpectedPipelineOutcome
    validation_probes: tuple[EvaluationProbe, ...]
    ood_type: OodType | None = None
    expected_semantic_coverage: EvaluationFrameCoverage | None = None

    @model_validator(mode="after")
    def validate_case(self) -> "EvaluationCase":
        if tuple(segment.ordinal for segment in self.segments) != tuple(
            range(len(self.segments))
        ):
            raise ValueError("evaluation segment ordinals must be contiguous")
        if self.question != " ".join(segment.text for segment in self.segments):
            raise ValueError("evaluation question must preserve ordered segment text")
        _validate_frames(self.expected_frames, "evaluation")
        _require_unique(self.expected_candidate_ids, "expected candidate IDs")
        _require_unique(
            (item.reference_id for item in self.expected_references),
            "expected reference IDs",
        )
        _require_unique(
            (item.context_link_id for item in self.expected_context_links),
            "expected context link IDs",
        )
        _require_unique(
            (item.slot_mutation_id for item in self.expected_slot_mutations),
            "expected slot mutation IDs",
        )
        _require_sorted_unique(self.expected_tags, "expected tags")
        _require_unique((item.probe_id for item in self.validation_probes), "probe IDs")
        if self.expected_pipeline_outcome == "pre_model_rejected" and any(
            probe.executable for probe in self.validation_probes
        ):
            raise ValueError("pre-model rejected case cannot carry validation probes")
        _validate_graph(
            self.expected_frames,
            self.expected_references,
            self.expected_context_links,
            self.expected_slot_mutations,
            allow_dangling=False,
        )
        return self


class EvaluationDataset(ContractModel):
    schema_version: Literal["2.0", "3.0"] = "3.0"
    split_id: Identifier
    cases: tuple[EvaluationCase, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "EvaluationDataset":
        _require_unique((case.case_id for case in self.cases), "evaluation case IDs")
        probes = tuple(probe for case in self.cases for probe in case.validation_probes)
        if self.schema_version == "3.0" and any(not probe.executable for probe in probes):
            raise ValueError("v3 evaluation probes must be executable")
        if self.schema_version == "2.0" and any(probe.executable for probe in probes):
            raise ValueError("v2 evaluation probes must retain frozen shape")
        return self


class HybridSemanticLinkCase(ContractModel):
    """Authoritative V3 span/link expectation with no executable-schema detail."""

    case_id: Identifier
    question: str = Field(min_length=1)
    expected_action_ids: tuple[Identifier, ...]
    expected_product_family_ids: tuple[Identifier, ...]
    expected_span_texts: tuple[str, ...]
    expected_semantic_ids: tuple[Identifier, ...]
    expected_coverage_state: CoverageState
    expected_ood: bool

    @model_validator(mode="after")
    def validate_semantic_sets(self) -> "HybridSemanticLinkCase":
        _require_sorted_unique(self.expected_action_ids, "hybrid action IDs")
        _require_sorted_unique(
            self.expected_product_family_ids, "hybrid product family IDs"
        )
        _require_unique(self.expected_span_texts, "hybrid span texts")
        _require_sorted_unique(self.expected_semantic_ids, "hybrid semantic IDs")
        return self


class HybridSemanticLinkDataset(RootModel[tuple[HybridSemanticLinkCase, ...]]):
    """Strict top-level array used only by the focused V3 semantic-link fixture."""

    @model_validator(mode="after")
    def validate_case_ids(self) -> "HybridSemanticLinkDataset":
        _require_unique((case.case_id for case in self.root), "hybrid case IDs")
        return self


class HybridSemanticLinkPrediction(ContractModel):
    """Data-neutral V3 prediction projected from model and server evidence."""

    case_id: Identifier
    offered_span_texts: tuple[str, ...]
    hint_semantic_ids_at_5: tuple[Identifier, ...]
    selectable_semantic_ids: tuple[Identifier, ...]
    predicted_action_ids: tuple[Identifier, ...]
    predicted_product_family_ids: tuple[Identifier, ...]
    predicted_semantic_ids: tuple[Identifier, ...]
    predicted_coverage_state: CoverageState
    predicted_ood: bool

    @model_validator(mode="after")
    def validate_prediction_sets(self) -> "HybridSemanticLinkPrediction":
        _require_unique(self.offered_span_texts, "hybrid offered span texts")
        for values, label in (
            (self.hint_semantic_ids_at_5, "hybrid hint semantic IDs"),
            (self.selectable_semantic_ids, "hybrid selectable semantic IDs"),
            (self.predicted_action_ids, "hybrid predicted action IDs"),
            (
                self.predicted_product_family_ids,
                "hybrid predicted product family IDs",
            ),
            (self.predicted_semantic_ids, "hybrid predicted semantic IDs"),
        ):
            _require_sorted_unique(values, label)
        return self


class HybridPredictionMetrics(ContractModel):
    """Per-case V3 scores; stages remain independent by construction."""

    required_span_preservation: Decimal
    hint_recall_at_5: Decimal
    catalog_selectability: Decimal
    action_exact_match: Decimal
    product_family_exact_match: Decimal
    semantic_link_recall: Decimal
    semantic_link_exact_match: Decimal
    frame_exact_match: Decimal
    coverage_exact_match: Decimal
    ood_false_fast: Decimal


def evaluate_hybrid_prediction(
    case: HybridSemanticLinkCase,
    prediction: HybridSemanticLinkPrediction,
) -> HybridPredictionMetrics:
    """Score one V3 semantic-link case without coupling hints to selectability."""

    if case.case_id != prediction.case_id:
        raise ValueError("HYBRID_EVALUATION_CASE_MISMATCH")
    expected_semantics = set(case.expected_semantic_ids)

    def recall(values: Sequence[str]) -> Decimal:
        if not expected_semantics:
            return Decimal("1")
        return Decimal(len(expected_semantics & set(values))) / Decimal(
            len(expected_semantics)
        )

    action_exact = Decimal(
        case.expected_action_ids == prediction.predicted_action_ids
    )
    family_exact = Decimal(
        case.expected_product_family_ids
        == prediction.predicted_product_family_ids
    )
    semantic_exact = Decimal(
        case.expected_semantic_ids == prediction.predicted_semantic_ids
    )
    coverage_exact = Decimal(
        case.expected_coverage_state == prediction.predicted_coverage_state
    )
    false_fast = Decimal(case.expected_ood and not prediction.predicted_ood)
    return HybridPredictionMetrics(
        required_span_preservation=Decimal(
            set(case.expected_span_texts) <= set(prediction.offered_span_texts)
        ),
        hint_recall_at_5=recall(prediction.hint_semantic_ids_at_5),
        catalog_selectability=recall(prediction.selectable_semantic_ids),
        action_exact_match=action_exact,
        product_family_exact_match=family_exact,
        semantic_link_recall=recall(prediction.predicted_semantic_ids),
        semantic_link_exact_match=semantic_exact,
        frame_exact_match=Decimal(
            bool(action_exact and family_exact and semantic_exact and coverage_exact)
        ),
        coverage_exact_match=coverage_exact,
        ood_false_fast=false_fast,
    )


class CandidateGroup(ContractModel):
    mention_id: Identifier
    candidate_ids: tuple[Identifier, ...] = Field(
        max_length=MAX_CANDIDATES_PER_MENTION
    )

    @model_validator(mode="after")
    def validate_candidates(self) -> "CandidateGroup":
        _require_unique(self.candidate_ids, "candidate IDs within mention")
        return self


class FirstPassSchemaOutcome(ContractModel):
    status: Literal["not_attempted", "valid", "invalid"]
    validator_event_code: Literal[
        "SCHEMA_NOT_ATTEMPTED", "SCHEMA_VALID", "SCHEMA_INVALID"
    ]

    @model_validator(mode="after")
    def validate_pair(self) -> "FirstPassSchemaOutcome":
        expected = {
            "not_attempted": "SCHEMA_NOT_ATTEMPTED",
            "valid": "SCHEMA_VALID",
            "invalid": "SCHEMA_INVALID",
        }[self.status]
        if self.validator_event_code != expected:
            raise ValueError("schema status contradicts validator event")
        return self


class RepairOutcome(ContractModel):
    status: Literal["not_attempted", "succeeded", "failed"]
    validator_event_code: Literal[
        "REPAIR_NOT_ATTEMPTED", "REPAIR_SUCCEEDED", "REPAIR_FAILED"
    ]

    @model_validator(mode="after")
    def validate_pair(self) -> "RepairOutcome":
        expected = {
            "not_attempted": "REPAIR_NOT_ATTEMPTED",
            "succeeded": "REPAIR_SUCCEEDED",
            "failed": "REPAIR_FAILED",
        }[self.status]
        if self.validator_event_code != expected:
            raise ValueError("repair status contradicts validator event")
        return self


class ValidationProbeOutcome(ContractModel):
    probe_id: Identifier
    kind: ProbeKind
    subject_ids: tuple[Identifier, ...] = Field(min_length=1)
    decision: ProbeDecision
    validator_event_code: Identifier
    stable_code: Identifier

    @model_validator(mode="after")
    def validate_pair(self) -> "ValidationProbeOutcome":
        _require_sorted_unique(self.subject_ids, "probe outcome subject IDs")
        event_code, stable_code = _PROBE_CODES[(self.kind, self.decision)]
        if self.validator_event_code != event_code or self.stable_code != stable_code:
            raise ValueError("probe decision contradicts validator evidence")
        return self


class EvaluationPrediction(ContractModel):
    case_id: Identifier
    candidate_groups: tuple[CandidateGroup, ...]
    candidate_reproducible: bool | None
    frames: tuple[EvaluationFrame, ...]
    references: tuple[ExpectedReference, ...]
    context_links: tuple[ExpectedContextLink, ...]
    slot_mutations: tuple[ExpectedSlotMutation, ...]
    resolution_status: ResolutionStatusLabel
    pipeline_outcome: ActualPipelineOutcome
    provider_success: bool | None = True
    predicted_ood_type: OodType | None = None
    tags: tuple[Identifier, ...]
    blocking_issue_codes: tuple[Identifier, ...]
    first_pass_schema: FirstPassSchemaOutcome
    repair: RepairOutcome
    validation_probe_outcomes: tuple[ValidationProbeOutcome, ...]
    latency_ms: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    stable_error_codes: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_prediction(self) -> "EvaluationPrediction":
        _require_unique(
            (group.mention_id for group in self.candidate_groups),
            "prediction candidate mention IDs",
        )
        _validate_frames(self.frames, "prediction")
        _require_unique(
            (item.reference_id for item in self.references),
            "prediction reference IDs",
        )
        _require_unique(
            (item.context_link_id for item in self.context_links),
            "prediction context link IDs",
        )
        _require_unique(
            (item.slot_mutation_id for item in self.slot_mutations),
            "prediction slot mutation IDs",
        )
        _require_sorted_unique(self.tags, "prediction tags")
        _require_sorted_unique(
            self.blocking_issue_codes, "prediction blocking issue codes"
        )
        _require_sorted_unique(self.stable_error_codes, "prediction stable error codes")
        _require_unique(
            (item.probe_id for item in self.validation_probe_outcomes),
            "prediction probe outcome IDs",
        )
        if (
            self.pipeline_outcome == "pre_model_rejected"
            and self.candidate_reproducible is not None
        ):
            raise ValueError("pre-model prediction cannot claim candidate reproducibility")
        return self


class ResolverViewCaseArtifact(ContractModel):
    case_id: Identifier
    artifact: ResolverView | None


class ResolverViewBundle(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Identifier
    cases: tuple[ResolverViewCaseArtifact, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "ResolverViewBundle":
        _require_unique((case.case_id for case in self.cases), "view bundle case IDs")
        return self


class IntentDraftCaseArtifact(ContractModel):
    case_id: Identifier
    artifact: IntentResolutionDraft | None


class IntentDraftBundle(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Identifier
    cases: tuple[IntentDraftCaseArtifact, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "IntentDraftBundle":
        _require_unique((case.case_id for case in self.cases), "draft bundle case IDs")
        return self


# Explicit aliases preserve the frozen v1 model names and schema titles while
# allowing artifact readers to dispatch by the pinned resolver schema version.
IntentDraftCaseArtifactV1 = IntentDraftCaseArtifact
IntentDraftBundleV1 = IntentDraftBundle


class IntentDraftCaseArtifactV2(ContractModel):
    case_id: Identifier
    artifact: IntentResolutionDraftV2 | None


class IntentDraftBundleV2(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    dataset_id: Identifier
    cases: tuple[IntentDraftCaseArtifactV2, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "IntentDraftBundleV2":
        _require_unique((case.case_id for case in self.cases), "draft bundle case IDs")
        return self


class ValidatedResolutionCaseArtifact(ContractModel):
    case_id: Identifier
    artifact: ValidatedIntentResolution | None


class ValidatedResolutionBundle(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Identifier
    cases: tuple[ValidatedResolutionCaseArtifact, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "ValidatedResolutionBundle":
        _require_unique(
            (case.case_id for case in self.cases), "resolution bundle case IDs"
        )
        return self


ValidatedResolutionCaseArtifactV1 = ValidatedResolutionCaseArtifact
ValidatedResolutionBundleV1 = ValidatedResolutionBundle


class ValidatedResolutionCaseArtifactV2(ContractModel):
    case_id: Identifier
    artifact: ValidatedIntentResolutionV2 | None


class ValidatedResolutionBundleV2(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    dataset_id: Identifier
    cases: tuple[ValidatedResolutionCaseArtifactV2, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "ValidatedResolutionBundleV2":
        _require_unique(
            (case.case_id for case in self.cases), "resolution bundle case IDs"
        )
        return self


IntentDraftBundleAny = IntentDraftBundle | IntentDraftBundleV2
ValidatedResolutionBundleAny = (
    ValidatedResolutionBundle | ValidatedResolutionBundleV2
)


class AttemptTrace(ContractModel):
    """Sanitized attempt evidence; raw model content is deliberately absent."""

    payload_sha256: Sha256Hex
    payload_size_bytes: int = Field(gt=0)
    parser_event: Literal["draft_parsed", "schema_rejected"]
    validator_event: Literal["validated", "validator_rejected", "not_run"]
    stable_code: Identifier
    parsed_draft_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def validate_trace_pair(self) -> "AttemptTrace":
        if self.parser_event == "schema_rejected":
            if (
                self.validator_event != "not_run"
                or self.stable_code != "MODEL_SCHEMA_INVALID"
                or self.parsed_draft_sha256 is not None
            ):
                raise ValueError("schema-rejected attempt trace is contradictory")
        elif self.parsed_draft_sha256 is None or self.validator_event == "not_run":
            raise ValueError("parsed attempt trace lacks validator evidence")
        elif (self.validator_event == "validated") != (
            self.stable_code == "RESOLUTION_VALIDATED"
        ):
            raise ValueError("validated attempt trace is contradictory")
        return self


class IntentRunTrace(ContractModel):
    case_id: Identifier
    model_event: Literal["model_called", "model_not_called"]
    first_attempt: AttemptTrace | None
    repair_attempt: AttemptTrace | None
    repair_event: Literal["not_attempted", "succeeded", "failed"]
    latency_ms: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    stable_error_codes: tuple[Identifier, ...]

    @property
    def terminal_model_failure(self) -> bool:
        if self.model_event != "model_called":
            return False
        final_attempt = (
            self.first_attempt
            if self.repair_event == "not_attempted"
            else self.repair_attempt
        )
        return final_attempt is None or final_attempt.validator_event != "validated"

    @model_validator(mode="after")
    def validate_trace(self) -> "IntentRunTrace":
        _require_sorted_unique(self.stable_error_codes, "run trace error codes")
        if self.model_event == "model_not_called":
            if (
                self.first_attempt is not None
                or self.repair_attempt is not None
                or self.repair_event != "not_attempted"
                or self.prompt_tokens != 0
                or self.completion_tokens != 0
                or self.stable_error_codes != ("REQUEST_CONTRACT_INVALID",)
            ):
                raise ValueError("model-not-called trace is contradictory")
            return self
        if self.first_attempt is None:
            raise ValueError("model-called trace requires first attempt")
        if self.repair_event == "not_attempted":
            if self.repair_attempt is not None:
                raise ValueError("unattempted repair cannot carry attempt evidence")
        elif self.repair_attempt is None:
            raise ValueError("attempted repair requires attempt evidence")
        elif self.first_attempt.validator_event == "validated":
            raise ValueError("repair cannot follow a validated first attempt")
        elif (self.repair_event == "succeeded") != (
            self.repair_attempt.validator_event == "validated"
        ):
            raise ValueError("repair trace is contradictory")
        if self.repair_event != "not_attempted" and self.repair_attempt is not None:
            if self.first_attempt.payload_sha256 == self.repair_attempt.payload_sha256:
                raise ValueError("repair attempt evidence must differ")
            first_draft = self.first_attempt.parsed_draft_sha256
            repair_draft = self.repair_attempt.parsed_draft_sha256
            if (
                first_draft is not None
                and repair_draft is not None
                and first_draft == repair_draft
            ):
                raise ValueError("repair attempt evidence must differ")
        rejected_codes = tuple(
            sorted(
                {
                    attempt.stable_code
                    for attempt in (self.first_attempt, self.repair_attempt)
                    if attempt is not None and attempt.validator_event != "validated"
                }
            )
        )
        if rejected_codes != self.stable_error_codes:
            raise ValueError("run trace error codes do not match rejected attempts")
        return self


class IntentRunTraceBundle(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Identifier
    cases: tuple[IntentRunTrace, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "IntentRunTraceBundle":
        _require_unique((case.case_id for case in self.cases), "run trace case IDs")
        return self


class PredictionDataset(ContractModel):
    """Stored-run manifest. Semantic results live only in validated sidecars."""

    schema_version: Literal["3.0"] = "3.0"
    mode: EvaluationMode
    dataset_id: Identifier
    evaluation_dataset_sha256: Sha256Hex
    dataset_version: Identifier
    dataset_manifest_hash: Sha256Hex
    build_manifest: ResolverBuildManifest
    model_id: Identifier
    bounded_view_bundle_raw_sha256: Sha256Hex | None = None
    bounded_view_bundle_canonical_sha256: Sha256Hex | None = None
    draft_bundle_raw_sha256: Sha256Hex | None = None
    draft_bundle_canonical_sha256: Sha256Hex | None = None
    resolution_bundle_raw_sha256: Sha256Hex | None = None
    resolution_bundle_canonical_sha256: Sha256Hex | None = None
    run_trace_bundle_raw_sha256: Sha256Hex
    run_trace_bundle_canonical_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_mode_evidence(self) -> "PredictionDataset":
        decoupled_values = (
            self.bounded_view_bundle_raw_sha256,
            self.bounded_view_bundle_canonical_sha256,
            self.draft_bundle_raw_sha256,
            self.draft_bundle_canonical_sha256,
        )
        full_values = (
            self.resolution_bundle_raw_sha256,
            self.resolution_bundle_canonical_sha256,
        )
        if self.mode == "decoupled":
            if any(value is None for value in decoupled_values) or any(
                value is not None for value in full_values
            ):
                raise ValueError("decoupled prediction evidence is incomplete")
        elif any(value is None for value in (*decoupled_values, *full_values)):
            raise ValueError("full prediction evidence is incomplete")
        return self


class RegressionAxes(ContractModel):
    intent_label: Identifier
    product_family_ids: tuple[Identifier, ...]
    entity_type_ids: tuple[Identifier, ...]
    semantic_ids: tuple[Identifier, ...]
    expected_disposition: Identifier


class RegressionContextLabel(ContractModel):
    mention: str = Field(min_length=1)
    binds_to: str | tuple[str, ...] | None
    expected: Identifier
    candidates: tuple[str, ...] = ()


class RegressionCase(ContractModel):
    case_id: Identifier
    expected_axes: RegressionAxes
    expected_context: tuple[RegressionContextLabel, ...]


class RegressionSource(ContractModel):
    relative_path: str = Field(min_length=1)
    sha256: Sha256Hex
    label_policy: Identifier


class RegressionDataset(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    split_id: Identifier
    source: RegressionSource
    cases: tuple[RegressionCase, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "RegressionDataset":
        _require_unique((case.case_id for case in self.cases), "regression case IDs")
        return self


class CountMetric(ContractModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_count(self) -> "CountMetric":
        if self.numerator > self.denominator:
            raise ValueError("metric numerator cannot exceed denominator")
        return self

    @computed_field
    @property
    def value(self) -> Decimal:
        """Exact ratio; zero denominator is numeric zero but explicitly undefined."""
        if self.denominator == 0:
            return Decimal("0")
        return Decimal(self.numerator) / Decimal(self.denominator)

    @computed_field
    @property
    def defined(self) -> bool:
        return self.denominator > 0

    @computed_field
    @property
    def evidence_sufficient(self) -> bool:
        return self.denominator > 0


class CoverageMetric(CountMetric):
    @computed_field
    @property
    def evidence_sufficient(self) -> bool:
        return self.denominator > 0 and self.numerator == self.denominator


PromotionGateName = Literal[
    "entity_type_reachability",
    "unknown_registered_id_acceptance",
    "invalid_context_graph_acceptance",
    "deterministic_candidate_reproducibility",
    "candidate_recall_at_5",
    "first_pass_structured_output_validity",
    "held_out_joint_frame_exact_match",
    "held_out_context_link_exact_match",
    "ood_false_fast_rate",
]
PromotionGateStatus = Literal["passed", "failed", "unmeasured"]
PromotionComparison = Literal["equal", "at_least", "at_most"]
_FROZEN_PROMOTION_DATASET_SHA256 = (
    "bd40481c57975d66a84a98005b771761c023ae5461cbd3c232508522bbf4c7de"
)
_ENTITY_TYPE_REACHABILITY_POPULATION = 155


class EntityTypeReachabilityEvidence(ContractModel):
    total: int = Field(ge=0)
    reachable: int = Field(ge=0)
    unreachable_case_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_counts(self) -> "EntityTypeReachabilityEvidence":
        if self.reachable + len(self.unreachable_case_ids) != self.total:
            raise ValueError("entity-type reachability counts must cover population")
        return self


class PromotionEvidence(ContractModel):
    evaluation_dataset_sha256: Sha256Hex | None = None
    entity_type_reachability: EntityTypeReachabilityEvidence | None = None
    unknown_registered_id_acceptance: CountMetric | None = None
    invalid_context_graph_acceptance: CountMetric | None = None
    validation_probe_coverage: CoverageMetric | None = None
    deterministic_candidate_reproducibility: CountMetric | None = None
    deterministic_candidate_reproducibility_coverage: CoverageMetric | None = None
    candidate_recall_at_5: CountMetric | None = None
    first_pass_structured_output_validity: CountMetric | None = None
    held_out_joint_frame_exact_match: CountMetric | None = None
    held_out_joint_frame_role_coverage: CoverageMetric | None = None
    held_out_context_link_exact_match: CountMetric | None = None
    ood_false_fast_rate: CountMetric | None = None


class PromotionGateResult(ContractModel):
    name: PromotionGateName
    status: PromotionGateStatus
    metric: CountMetric | None
    comparison: PromotionComparison
    threshold: Decimal


class PromotionDecision(ContractModel):
    eligible: bool
    blocking_gate_names: tuple[PromotionGateName, ...]
    gates: tuple[PromotionGateResult, ...] = Field(min_length=9, max_length=9)


_PROMOTION_GATE_DEFINITIONS: tuple[
    tuple[
        PromotionGateName,
        PromotionComparison,
        Decimal,
        Literal[
            "validation_probe_coverage",
            "deterministic_candidate_reproducibility_coverage",
        ]
        | None,
    ],
    ...,
] = (
    (
        "unknown_registered_id_acceptance",
        "equal",
        Decimal("0"),
        "validation_probe_coverage",
    ),
    (
        "invalid_context_graph_acceptance",
        "equal",
        Decimal("0"),
        "validation_probe_coverage",
    ),
    (
        "deterministic_candidate_reproducibility",
        "equal",
        Decimal("1"),
        "deterministic_candidate_reproducibility_coverage",
    ),
    ("candidate_recall_at_5", "at_least", Decimal("0.99"), None),
    (
        "first_pass_structured_output_validity",
        "at_least",
        Decimal("0.99"),
        None,
    ),
    (
        "held_out_joint_frame_exact_match",
        "at_least",
        Decimal("0.90"),
        None,
    ),
    (
        "held_out_context_link_exact_match",
        "at_least",
        Decimal("0.95"),
        None,
    ),
    ("ood_false_fast_rate", "at_most", Decimal("0.02"), None),
)
_PROMOTION_GATE_POPULATIONS: dict[PromotionGateName, int] = {
    "unknown_registered_id_acceptance": 10,
    "invalid_context_graph_acceptance": 10,
    "deterministic_candidate_reproducibility": 155,
    "candidate_recall_at_5": 196,
    "first_pass_structured_output_validity": 155,
    "held_out_joint_frame_exact_match": 155,
    "held_out_context_link_exact_match": 155,
    "ood_false_fast_rate": 30,
}
_PROMOTION_COVERAGE_POPULATIONS = {
    "validation_probe_coverage": 20,
    "deterministic_candidate_reproducibility_coverage": 155,
}


def assess_promotion(evidence: PromotionEvidence) -> PromotionDecision:
    """Require complete measured evidence for every approved promotion gate."""
    if type(evidence) is not PromotionEvidence:
        raise TypeError("promotion evidence must be exact PromotionEvidence")
    declared_fields = tuple(PromotionEvidence.model_fields)
    if set(evidence.__dict__) != set(declared_fields):
        raise ValueError("promotion evidence stored fields do not match contract")
    evidence = PromotionEvidence.model_validate_json(
        json.dumps(
            {name: evidence.__dict__[name] for name in declared_fields},
            allow_nan=False,
            default=_promotion_json_default,
            separators=(",", ":"),
            sort_keys=True,
        )
    )

    dataset_matches = (
        evidence.evaluation_dataset_sha256 == _FROZEN_PROMOTION_DATASET_SHA256
    )
    reachability = evidence.entity_type_reachability
    reachability_metric = (
        None
        if reachability is None
        else CountMetric(
            numerator=reachability.reachable,
            denominator=reachability.total,
        )
    )
    reachability_sufficient = (
        dataset_matches
        and reachability is not None
        and reachability.total == _ENTITY_TYPE_REACHABILITY_POPULATION
    )
    if not reachability_sufficient:
        reachability_status: PromotionGateStatus = "unmeasured"
    elif (
        reachability.reachable == _ENTITY_TYPE_REACHABILITY_POPULATION
        and not reachability.unreachable_case_ids
    ):
        reachability_status = "passed"
    else:
        reachability_status = "failed"
    gates: list[PromotionGateResult] = [
        PromotionGateResult(
            name="entity_type_reachability",
            status=reachability_status,
            metric=reachability_metric,
            comparison="equal",
            threshold=Decimal("1"),
        )
    ]
    for name, comparison, threshold, coverage_name in _PROMOTION_GATE_DEFINITIONS:
        metric = getattr(evidence, name)
        coverage = None if coverage_name is None else getattr(evidence, coverage_name)
        sufficient = (
            dataset_matches
            and metric is not None
            and metric.evidence_sufficient
            and metric.denominator == _PROMOTION_GATE_POPULATIONS[name]
        )
        if coverage_name is not None:
            sufficient = (
                sufficient
                and coverage is not None
                and coverage.evidence_sufficient
                and coverage.numerator
                == _PROMOTION_COVERAGE_POPULATIONS[coverage_name]
                and coverage.denominator
                == _PROMOTION_COVERAGE_POPULATIONS[coverage_name]
            )
        if name == "held_out_joint_frame_exact_match":
            role_coverage = evidence.held_out_joint_frame_role_coverage
            sufficient = (
                sufficient
                and role_coverage is not None
                and role_coverage.evidence_sufficient
            )
        if not sufficient:
            status: PromotionGateStatus = "unmeasured"
        elif comparison == "equal":
            status = "passed" if metric.value == threshold else "failed"
        elif comparison == "at_least":
            status = "passed" if metric.value >= threshold else "failed"
        else:
            status = "passed" if metric.value <= threshold else "failed"
        gates.append(
            PromotionGateResult(
                name=name,
                status=status,
                metric=metric,
                comparison=comparison,
                threshold=threshold,
            )
        )

    blocking = tuple(gate.name for gate in gates if gate.status != "passed")
    return PromotionDecision(
        eligible=not blocking,
        blocking_gate_names=blocking,
        gates=tuple(gates),
    )


def _promotion_json_default(value: object) -> dict[str, object]:
    if isinstance(value, ContractModel):
        return dict(value.__dict__)
    raise TypeError(f"promotion evidence contains non-JSON value: {type(value)!r}")


class PrecisionRecallF1(ContractModel):
    precision: CountMetric
    recall: CountMetric
    f1: CountMetric


class CandidateMetrics(ContractModel):
    recall_at_1: CountMetric
    recall_at_3: CountMetric
    recall_at_5: CountMetric
    reproducibility: CountMetric
    reproducibility_coverage: CoverageMetric


class FrameMetrics(ContractModel):
    joint_exact_match: CountMetric
    action: PrecisionRecallF1
    product_family: PrecisionRecallF1
    entity_type: PrecisionRecallF1
    slot: PrecisionRecallF1
    role_conformance: CountMetric
    role_coverage: CoverageMetric


class ContextMetrics(ContractModel):
    reference_exact_match: CountMetric
    link_exact_match: CountMetric
    selector_exact_match: CountMetric
    cardinality_exact_match: CountMetric
    mutation_exact_match: CountMetric


class OodConfusionCount(ContractModel):
    expected: Identifier
    predicted: Identifier
    count: int = Field(ge=0)


class OodMetrics(ContractModel):
    confusion: tuple[OodConfusionCount, ...]
    false_fast_rate: CountMetric


class CoverageMetrics(ContractModel):
    lexical_ood: CountMetric
    domain_ood: CountMetric
    combination_ood: CountMetric
    context_unresolved: CountMetric
    policy_tags: PrecisionRecallF1


class ValidationMetrics(ContractModel):
    schema_validity: CountMetric
    unknown_id_acceptance: CountMetric
    invalid_graph_acceptance: CountMetric
    repair_rate: CountMetric
    probe_coverage: CoverageMetric


class DiagnosticMetrics(ContractModel):
    resolution_status_exact: CountMetric
    tags_exact: CountMetric
    tags: PrecisionRecallF1
    pipeline_outcome_exact: CountMetric


class StableErrorCount(ContractModel):
    code: Identifier
    count: int = Field(ge=1)


class RuntimeMetrics(ContractModel):
    provider_success: CountMetric
    p50_latency_ms: int | None = Field(default=None, ge=0)
    p95_latency_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    stable_error_counts: tuple[StableErrorCount, ...]


class HybridStageMetric(CountMetric):
    """V3 count whose authority is explicit; partial evidence stays unmeasured."""

    authoritative_denominator: int | None = Field(default=None, ge=0)
    observed_population_count: int | None = Field(default=None, ge=0)
    authoritative_population_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_population_counts(self) -> "HybridStageMetric":
        if (self.observed_population_count is None) != (
            self.authoritative_population_count is None
        ):
            raise ValueError("hybrid population counts must be declared together")
        if (
            self.observed_population_count is not None
            and self.authoritative_population_count is not None
            and self.observed_population_count > self.authoritative_population_count
        ):
            raise ValueError("hybrid observed population exceeds authority")
        return self

    @computed_field
    @property
    def status(self) -> Literal["measured", "unmeasured"]:
        if (
            self.authoritative_denominator is None
            or self.authoritative_denominator == 0
            or self.denominator != self.authoritative_denominator
            or self.observed_population_count != self.authoritative_population_count
        ):
            return "unmeasured"
        return "measured"

    @computed_field
    @property
    def reason_code(
        self,
    ) -> Literal[
        "NEEDS_CONTEXT",
        "AUTHORITATIVE_POPULATION_EMPTY",
        "EVIDENCE_MISSING",
        "PARTIAL_AUTHORITATIVE_DENOMINATOR",
    ] | None:
        if self.authoritative_denominator is None:
            return "NEEDS_CONTEXT"
        if self.authoritative_denominator == 0:
            return "AUTHORITATIVE_POPULATION_EMPTY"
        if self.denominator == 0:
            return "EVIDENCE_MISSING"
        if self.denominator != self.authoritative_denominator:
            return "PARTIAL_AUTHORITATIVE_DENOMINATOR"
        if self.observed_population_count != self.authoritative_population_count:
            return "PARTIAL_AUTHORITATIVE_DENOMINATOR"
        return None

    @computed_field
    @property
    def evidence_sufficient(self) -> bool:
        return self.status == "measured"


class HybridProviderTelemetry(ContractModel):
    provider_success: HybridStageMetric
    provider_calls: int = Field(ge=0)
    successful_provider_calls: int = Field(ge=0)
    repair_calls: int = Field(ge=0)
    candidate_judge_calls: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    p50_latency_ms: int | None = Field(default=None, ge=0)
    p95_latency_ms: int | None = Field(default=None, ge=0)
    stable_error_counts: tuple[StableErrorCount, ...]

    @model_validator(mode="after")
    def validate_provider_counts(self) -> "HybridProviderTelemetry":
        if self.successful_provider_calls > self.provider_calls:
            raise ValueError("successful provider calls exceed total calls")
        if (
            self.p50_latency_ms is not None
            and self.p95_latency_ms is not None
            and self.p50_latency_ms > self.p95_latency_ms
        ):
            raise ValueError("provider latency percentiles are reversed")
        return self


class HybridEvaluationReport(ContractModel):
    """Stage-separated V3 evidence without conflating deterministic reachability."""

    required_span_preservation: HybridStageMetric
    hint_recall_at_5: HybridStageMetric
    exact_lock_precision: HybridStageMetric
    compact_catalog_selectability: HybridStageMetric
    first_pass_structured_validity: HybridStageMetric
    repaired_structured_validity: HybridStageMetric
    action_exact_match: HybridStageMetric
    product_family_exact_match: HybridStageMetric
    semantic_link_recall: HybridStageMetric
    semantic_link_exact_match: HybridStageMetric
    joint_frame_exact_match: HybridStageMetric
    context_link_exact_match: HybridStageMetric
    ood_false_fast_rate: HybridStageMetric
    complete_contract_exact_match: HybridStageMetric
    planning_readiness: HybridStageMetric
    provider: HybridProviderTelemetry


def validate_hybrid_semantic_link_authority(
    cases: Sequence[HybridSemanticLinkCase],
) -> dict[str, HybridSemanticLinkCase]:
    """Validate any observed slice against the pinned five-case authority."""

    case_index = _unique_index(cases, lambda item: item.case_id)
    if not set(case_index) <= set(_HYBRID_SEMANTIC_LINK_CASE_HASHES):
        raise ValueError("HYBRID_EVALUATION_UNKNOWN_CASE_ID")
    if any(
        canonical_sha256(case)
        != _HYBRID_SEMANTIC_LINK_CASE_HASHES[case.case_id]
        for case in case_index.values()
    ):
        raise ValueError("HYBRID_EVALUATION_CASE_AUTHORITY_MISMATCH")
    return case_index


def evaluate_hybrid_predictions(
    cases: Sequence[HybridSemanticLinkCase],
    predictions: Sequence[HybridSemanticLinkPrediction],
) -> HybridEvaluationReport:
    """Aggregate V3 link predictions without inventing later-stage evidence."""

    case_index = validate_hybrid_semantic_link_authority(cases)
    prediction_index = _unique_index(predictions, lambda item: item.case_id)
    authoritative_ids = set(_HYBRID_SEMANTIC_LINK_CASE_HASHES)
    if not set(prediction_index) <= authoritative_ids:
        raise ValueError("HYBRID_EVALUATION_UNKNOWN_CASE_ID")
    if not set(prediction_index) <= set(case_index):
        raise ValueError("HYBRID_EVALUATION_PREDICTION_WITHOUT_CASE")
    aligned = tuple(
        (case_index[case_id], prediction_index[case_id])
        for case_id in sorted(set(case_index) & set(prediction_index))
    )
    scores = tuple(
        evaluate_hybrid_prediction(case, prediction)
        for case, prediction in aligned
    )
    expected_span_total = sum(len(case.expected_span_texts) for case, _ in aligned)
    expected_semantic_total = sum(
        len(case.expected_semantic_ids) for case, _ in aligned
    )
    ood_total = sum(case.expected_ood for case, _ in aligned)

    def metric(
        numerator: int, denominator: int, authoritative: int | None = None
    ) -> HybridStageMetric:
        return HybridStageMetric(
            numerator=numerator,
            denominator=denominator,
            authoritative_denominator=(
                denominator if authoritative is None else authoritative
            ),
            observed_population_count=len(aligned),
            authoritative_population_count=_HYBRID_SEMANTIC_LINK_CASE_COUNT,
        )

    def unavailable(authoritative: int | None) -> HybridStageMetric:
        return HybridStageMetric(
            numerator=0,
            denominator=0,
            authoritative_denominator=authoritative,
            observed_population_count=len(aligned),
            authoritative_population_count=_HYBRID_SEMANTIC_LINK_CASE_COUNT,
        )

    return HybridEvaluationReport(
        required_span_preservation=metric(
            sum(
                len(
                    set(case.expected_span_texts)
                    & set(prediction.offered_span_texts)
                )
                for case, prediction in aligned
            ),
            expected_span_total,
            _HYBRID_SEMANTIC_LINK_SPAN_COUNT,
        ),
        hint_recall_at_5=metric(
            sum(
                len(
                    set(case.expected_semantic_ids)
                    & set(prediction.hint_semantic_ids_at_5)
                )
                for case, prediction in aligned
            ),
            expected_semantic_total,
            _HYBRID_SEMANTIC_LINK_SEMANTIC_COUNT,
        ),
        exact_lock_precision=unavailable(None),
        compact_catalog_selectability=metric(
            sum(
                len(
                    set(case.expected_semantic_ids)
                    & set(prediction.selectable_semantic_ids)
                )
                for case, prediction in aligned
            ),
            expected_semantic_total,
            _HYBRID_SEMANTIC_LINK_SEMANTIC_COUNT,
        ),
        first_pass_structured_validity=unavailable(
            _HYBRID_SEMANTIC_LINK_CASE_COUNT
        ),
        repaired_structured_validity=unavailable(None),
        action_exact_match=metric(
            sum(score.action_exact_match == 1 for score in scores),
            len(aligned),
            _HYBRID_SEMANTIC_LINK_CASE_COUNT,
        ),
        product_family_exact_match=metric(
            sum(score.product_family_exact_match == 1 for score in scores),
            len(aligned),
            _HYBRID_SEMANTIC_LINK_CASE_COUNT,
        ),
        semantic_link_recall=metric(
            sum(
                len(
                    set(case.expected_semantic_ids)
                    & set(prediction.predicted_semantic_ids)
                )
                for case, prediction in aligned
            ),
            expected_semantic_total,
            _HYBRID_SEMANTIC_LINK_SEMANTIC_COUNT,
        ),
        semantic_link_exact_match=metric(
            sum(score.semantic_link_exact_match == 1 for score in scores),
            len(aligned),
            _HYBRID_SEMANTIC_LINK_CASE_COUNT,
        ),
        joint_frame_exact_match=metric(
            sum(score.frame_exact_match == 1 for score in scores),
            len(aligned),
            _HYBRID_SEMANTIC_LINK_CASE_COUNT,
        ),
        context_link_exact_match=unavailable(None),
        ood_false_fast_rate=metric(
            sum(int(score.ood_false_fast) for score in scores),
            ood_total,
            _HYBRID_SEMANTIC_LINK_OOD_COUNT,
        ),
        complete_contract_exact_match=unavailable(None),
        planning_readiness=unavailable(None),
        provider=HybridProviderTelemetry(
            provider_success=unavailable(_HYBRID_SEMANTIC_LINK_CASE_COUNT),
            provider_calls=0,
            successful_provider_calls=0,
            repair_calls=0,
            candidate_judge_calls=0,
            prompt_tokens=0,
            completion_tokens=0,
            p50_latency_ms=None,
            p95_latency_ms=None,
            stable_error_counts=(),
        ),
    )


class EvaluationReport(ContractModel):
    candidate: CandidateMetrics
    frame: FrameMetrics
    context: ContextMetrics
    ood: OodMetrics
    coverage: CoverageMetrics
    validation: ValidationMetrics
    diagnostics: DiagnosticMetrics
    runtime: RuntimeMetrics

    @property
    def candidate_recall_at_5(self) -> Decimal:
        return self.candidate.recall_at_5.value

    @property
    def joint_frame_exact_match(self) -> Decimal:
        return self.frame.joint_exact_match.value

    @property
    def context_link_exact_match(self) -> Decimal:
        return self.context.link_exact_match.value

    @property
    def ood_false_fast_rate(self) -> Decimal:
        return self.ood.false_fast_rate.value


def parse_strict_json[T](payload: bytes, model: type[T]) -> T:
    """Reject duplicate keys/non-JSON numbers before strict model validation."""
    json.loads(
        payload,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda _value: _reject_non_json_number(),
    )
    validator = getattr(model, "model_validate_json")
    return validator(payload)


def evaluate_candidates(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> CandidateMetrics:
    aligned = _align(cases, predictions)
    total_gold = sum(len(case.expected_candidate_ids) for case, _ in aligned)

    def recall_at(limit: int) -> CountMetric:
        hits = 0
        for case, prediction in aligned:
            selected = {
                candidate_id
                for group in prediction.candidate_groups
                for candidate_id in group.candidate_ids[:limit]
            }
            hits += len(set(case.expected_candidate_ids) & selected)
        return CountMetric(numerator=hits, denominator=total_gold)

    eligible_reproducibility = tuple(
        (case, prediction)
        for case, prediction in aligned
        if case.expected_pipeline_outcome == "semantic_resolution"
    )
    attempted_reproducibility = tuple(
        prediction
        for _, prediction in eligible_reproducibility
        if prediction.candidate_reproducible is not None
    )
    return CandidateMetrics(
        recall_at_1=recall_at(1),
        recall_at_3=recall_at(3),
        recall_at_5=recall_at(5),
        reproducibility=CountMetric(
            numerator=sum(
                prediction.candidate_reproducible is True
                for prediction in attempted_reproducibility
            ),
            denominator=len(attempted_reproducibility),
        ),
        reproducibility_coverage=CoverageMetric(
            numerator=len(attempted_reproducibility),
            denominator=len(eligible_reproducibility),
        ),
    )


def evaluate_frames(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> FrameMetrics:
    aligned = _align(cases, predictions)
    semantic = tuple(
        (case, prediction)
        for case, prediction in aligned
        if _is_semantic_result(prediction)
    )
    required_roles: list[tuple[EvaluationFrame, EvaluationFrame | None]] = []
    for case, prediction in semantic:
        predicted_by_ordinal = {
            frame.ordinal: frame for frame in prediction.frames
        }
        required_roles.extend(
            (expected, predicted_by_ordinal.get(expected.ordinal))
            for expected in case.expected_frames
            if _requires_entity_role_evidence(expected)
        )
    return FrameMetrics(
        joint_exact_match=CountMetric(
            numerator=sum(
                _joint_frame_match(case.expected_frames, prediction.frames)
                for case, prediction in semantic
            ),
            denominator=len(semantic),
        ),
        action=_micro_prf(
            aligned,
            lambda case: _frame_axis(case.expected_frames, lambda frame: frame.action_ids),
            lambda prediction: _frame_axis(prediction.frames, lambda frame: frame.action_ids),
        ),
        product_family=_micro_prf(
            aligned,
            lambda case: _frame_axis(case.expected_frames, lambda frame: frame.product_family_ids),
            lambda prediction: _frame_axis(
                prediction.frames, lambda frame: frame.product_family_ids
            ),
        ),
        entity_type=_micro_prf(
            aligned,
            lambda case: _frame_axis(case.expected_frames, lambda frame: frame.entity_type_ids),
            lambda prediction: _frame_axis(prediction.frames, lambda frame: frame.entity_type_ids),
        ),
        slot=_micro_prf(
            aligned,
            lambda case: _slot_axis(case.expected_frames),
            lambda prediction: _slot_axis(prediction.frames),
        ),
        role_conformance=CountMetric(
            numerator=sum(
                expected.entity_hints is not None
                and predicted is not None
                and predicted.entity_hints is not None
                and expected.entity_hints == predicted.entity_hints
                for expected, predicted in required_roles
            ),
            denominator=len(required_roles),
        ),
        role_coverage=CoverageMetric(
            numerator=sum(
                expected.entity_hints is not None
                and predicted is not None
                and predicted.entity_hints is not None
                for expected, predicted in required_roles
            ),
            denominator=len(required_roles),
        ),
    )


def evaluate_context(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> ContextMetrics:
    aligned = _align(cases, predictions)
    return ContextMetrics(
        reference_exact_match=_semantic_exact_match(
            aligned,
            lambda case: _reference_signatures(case.expected_references),
            lambda prediction: _reference_signatures(prediction.references),
        ),
        link_exact_match=_semantic_exact_match(
            aligned,
            lambda case: _context_link_signatures(
                case.expected_frames,
                case.expected_references,
                case.expected_context_links,
                include_selector=True,
                include_cardinality=True,
            ),
            lambda prediction: _context_link_signatures(
                prediction.frames,
                prediction.references,
                prediction.context_links,
                include_selector=True,
                include_cardinality=True,
            ),
        ),
        selector_exact_match=_semantic_exact_match(
            aligned,
            lambda case: _context_link_signatures(
                case.expected_frames,
                case.expected_references,
                case.expected_context_links,
                include_selector=True,
                include_cardinality=False,
            ),
            lambda prediction: _context_link_signatures(
                prediction.frames,
                prediction.references,
                prediction.context_links,
                include_selector=True,
                include_cardinality=False,
            ),
        ),
        cardinality_exact_match=_semantic_exact_match(
            aligned,
            lambda case: _context_link_signatures(
                case.expected_frames,
                case.expected_references,
                case.expected_context_links,
                include_selector=False,
                include_cardinality=True,
            ),
            lambda prediction: _context_link_signatures(
                prediction.frames,
                prediction.references,
                prediction.context_links,
                include_selector=False,
                include_cardinality=True,
            ),
        ),
        mutation_exact_match=_semantic_exact_match(
            aligned,
            lambda case: _mutation_signatures(case.expected_frames, case.expected_slot_mutations),
            lambda prediction: _mutation_signatures(prediction.frames, prediction.slot_mutations),
        ),
    )


def evaluate_ood(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> OodMetrics:
    aligned = _align(cases, predictions)
    confusion: Counter[tuple[str, str]] = Counter()
    false_fast = 0
    ood_total = 0
    for case, prediction in aligned:
        if not _is_semantic_result(prediction):
            continue
        expected = case.ood_type or "in_domain"
        predicted = (
            "fast"
            if prediction.pipeline_outcome == "semantic_resolution"
            and prediction.resolution_status == "resolved"
            and not prediction.blocking_issue_codes
            else prediction.predicted_ood_type or prediction.pipeline_outcome
        )
        confusion[(expected, predicted)] += 1
        if case.ood_type in _FALSE_FAST_OOD_TYPES:
            ood_total += 1
            false_fast += int(predicted == "fast")
    return OodMetrics(
        confusion=tuple(
            OodConfusionCount(expected=expected, predicted=predicted, count=count)
            for (expected, predicted), count in sorted(confusion.items())
        ),
        false_fast_rate=CountMetric(numerator=false_fast, denominator=ood_total),
    )


def evaluate_coverage(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> CoverageMetrics:
    aligned = tuple(
        (case, prediction)
        for case, prediction in _align(cases, predictions)
        if _is_semantic_result(prediction)
    )

    def ood_coverage(ood_type: OodType) -> CountMetric:
        values = tuple(
            (case, prediction)
            for case, prediction in aligned
            if case.ood_type == ood_type
        )

        def expected_coverage(case: EvaluationCase) -> tuple[CoverageState, CoverageReason]:
            if case.expected_semantic_coverage is not None:
                return (
                    case.expected_semantic_coverage.state,
                    case.expected_semantic_coverage.reason,
                )
            return (
                "covered",
                "none",
            ) if ood_type == "combination" else (
                "unmapped",
                "lexical_ood" if ood_type == "vocabulary" else "domain_ood",
            )

        if ood_type == "context":
            return _exact_match(
                values,
                lambda _case: "context_unresolved",
                lambda prediction: prediction.resolution_status,
            )
        if ood_type == "combination":
            return CountMetric(
                numerator=sum(
                    bool(prediction.frames)
                    and all(
                        (state, reason) == expected_coverage(case)
                        for state, reason in _coverage_outcomes(prediction.frames)
                    )
                    for case, prediction in values
                ),
                denominator=len(values),
            )
        return CountMetric(
            numerator=sum(
                any(
                    (state, reason) == expected_coverage(case)
                    for state, reason in _coverage_outcomes(prediction.frames)
                )
                for case, prediction in values
            ),
            denominator=len(values),
        )

    policy = tuple(
        (case, prediction)
        for case, prediction in aligned
        if case.category == "policy_injection_unicode_oversized"
        and case.subcategory == "policy"
    )
    return CoverageMetrics(
        lexical_ood=ood_coverage("vocabulary"),
        domain_ood=ood_coverage("domain"),
        combination_ood=ood_coverage("combination"),
        context_unresolved=ood_coverage("context"),
        policy_tags=_micro_prf(
            policy,
            lambda case: frozenset(case.expected_tags),
            lambda prediction: frozenset(prediction.tags),
        ),
    )


def evaluate_predictions(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> EvaluationReport:
    aligned = _align(cases, predictions)
    for case, prediction in aligned:
        _validate_evidence_alignment(case, prediction)
    values = tuple(prediction for _, prediction in aligned)
    expected_probes = tuple(
        probe
        for case, _ in aligned
        for probe in case.validation_probes
    )
    probes = tuple(
        (probe, outcome)
        for case, prediction in aligned
        for probe in case.validation_probes
        if (outcome := _probe_index(prediction).get(probe.probe_id)) is not None
    )
    unknown = tuple(item for item in probes if item[0].kind == "unknown_id")
    invalid_graph = tuple(
        item for item in probes if item[0].kind == "invalid_context_graph"
    )
    errors = Counter(code for item in values for code in item.stable_error_codes)
    errors.update(
        outcome.stable_code
        for _, outcome in probes
        if outcome.decision == "accepted"
    )
    latencies = tuple(sorted(item.latency_ms for item in values))
    return EvaluationReport(
        candidate=evaluate_candidates(cases, predictions),
        frame=evaluate_frames(cases, predictions),
        context=evaluate_context(cases, predictions),
        ood=evaluate_ood(cases, predictions),
        coverage=evaluate_coverage(cases, predictions),
        validation=ValidationMetrics(
            schema_validity=CountMetric(
                numerator=sum(item.first_pass_schema.status == "valid" for item in values),
                denominator=sum(
                    item.first_pass_schema.status != "not_attempted" for item in values
                ),
            ),
            unknown_id_acceptance=CountMetric(
                numerator=sum(outcome.decision == "accepted" for _, outcome in unknown),
                denominator=len(unknown),
            ),
            invalid_graph_acceptance=CountMetric(
                numerator=sum(outcome.decision == "accepted" for _, outcome in invalid_graph),
                denominator=len(invalid_graph),
            ),
            repair_rate=CountMetric(
                numerator=sum(item.repair.status != "not_attempted" for item in values),
                denominator=sum(
                    item.first_pass_schema.status != "not_attempted" for item in values
                ),
            ),
            probe_coverage=CoverageMetric(
                numerator=len(probes), denominator=len(expected_probes)
            ),
        ),
        diagnostics=DiagnosticMetrics(
            resolution_status_exact=_semantic_exact_match(
                aligned,
                lambda case: case.expected_resolution_status,
                lambda prediction: prediction.resolution_status,
            ),
            tags_exact=_semantic_exact_match(
                aligned,
                lambda case: case.expected_tags,
                lambda prediction: prediction.tags,
            ),
            tags=_micro_prf(
                aligned,
                lambda case: frozenset(case.expected_tags),
                lambda prediction: frozenset(prediction.tags),
            ),
            pipeline_outcome_exact=_exact_match(
                aligned,
                lambda case: case.expected_pipeline_outcome,
                lambda prediction: prediction.pipeline_outcome,
            ),
        ),
        runtime=RuntimeMetrics(
            provider_success=CountMetric(
                numerator=sum(
                    prediction.provider_success is True
                    for prediction in values
                ),
                denominator=sum(
                    prediction.provider_success is not None
                    for prediction in values
                ),
            ),
            p50_latency_ms=_nearest_rank(latencies, 50),
            p95_latency_ms=_nearest_rank(latencies, 95),
            prompt_tokens=sum(item.prompt_tokens for item in values),
            completion_tokens=sum(item.completion_tokens for item in values),
            stable_error_counts=tuple(
                StableErrorCount(code=code, count=count)
                for code, count in sorted(errors.items())
            ),
        ),
    )


def _validate_evidence_alignment(
    case: EvaluationCase, prediction: EvaluationPrediction
) -> None:
    expected = {item.probe_id: item for item in case.validation_probes}
    actual = _probe_index(prediction)
    if prediction.pipeline_outcome == "model_resolution_failed":
        if actual:
            raise ValueError("EVALUATION_VALIDATION_PROBE_SET_MISMATCH")
    elif set(expected) != set(actual):
        raise ValueError("EVALUATION_VALIDATION_PROBE_SET_MISMATCH")
    for probe_id, probe in expected.items():
        if probe_id not in actual:
            continue
        outcome = actual[probe_id]
        if (
            probe.kind != outcome.kind
            or _probe_subject_ids(probe) != outcome.subject_ids
            or (
                outcome.decision == "rejected"
                and outcome.stable_code != probe.expected_rejection_code
            )
        ):
            raise ValueError("EVALUATION_VALIDATION_EVIDENCE_MISMATCH")

    dangling = _validate_graph(
        prediction.frames,
        prediction.references,
        prediction.context_links,
        prediction.slot_mutations,
        allow_dangling=True,
    )
    covered = {
        subject_id
        for outcome in prediction.validation_probe_outcomes
        if outcome.kind == "invalid_context_graph"
        for subject_id in outcome.subject_ids
    }
    if dangling and not dangling <= covered:
        raise ValueError("EVALUATION_VALIDATION_EVIDENCE_MISMATCH")


def replay_validation_probes(
    case: EvaluationCase,
    draft: IntentResolutionDraft,
    context: RequestContext,
    normalized: NormalizedRequest,
    view: ResolverView,
    catalog: SemanticCatalogSnapshot,
) -> tuple[ValidationProbeOutcome, ...]:
    """Execute v3 gold mutations through the production validators."""

    baseline_semantic = validate_semantics(draft, context, normalized, view, catalog)
    validate_context_graph(baseline_semantic)
    outcomes: list[ValidationProbeOutcome] = []
    for probe in case.validation_probes:
        if not probe.executable:
            raise ValueError("EVALUATION_PROBE_NOT_EXECUTABLE")
        mutated = _mutate_probe_draft(draft, probe)
        if canonical_sha256(mutated) == canonical_sha256(draft):
            raise ValueError("EVALUATION_PROBE_MUTATION_INVALID")
        decision: ProbeDecision = "accepted"
        stable_code = _PROBE_CODES[(probe.kind, decision)][1]
        try:
            semantic = validate_semantics(mutated, context, normalized, view, catalog)
            validate_context_graph(semantic)
        except ResolverContractError as error:
            decision = "rejected"
            stable_code = error.code
            if stable_code != probe.expected_rejection_code:
                raise ValueError("EVALUATION_PROBE_REJECTION_CODE_MISMATCH") from error
        event_code, expected_stable_code = _PROBE_CODES[(probe.kind, decision)]
        if decision == "accepted":
            stable_code = expected_stable_code
        outcomes.append(
            ValidationProbeOutcome(
                probe_id=probe.probe_id,
                kind=probe.kind,
                subject_ids=_probe_subject_ids(probe),
                decision=decision,
                validator_event_code=event_code,
                stable_code=stable_code,
            )
        )
    return tuple(outcomes)


def _mutate_probe_draft(
    draft: IntentResolutionDraft, probe: EvaluationProbe
) -> IntentResolutionDraft:
    subject = probe.subject_id
    if subject is None:
        raise ValueError("EVALUATION_PROBE_NOT_EXECUTABLE")
    if probe.kind == "unknown_id":
        assert probe.frame_ordinal is not None and probe.slot_kind is not None
        if probe.frame_ordinal >= len(draft.intent_frames):
            raise ValueError("EVALUATION_PROBE_MUTATION_INVALID")
        frame = draft.intent_frames[probe.frame_ordinal]
        matches = tuple(
            (index, assignment)
            for index, assignment in enumerate(frame.slot_assignments)
            if assignment.slot_kind.value == probe.slot_kind
        )
        if len(matches) != 1:
            raise ValueError("EVALUATION_PROBE_MUTATION_INVALID")
        assignment_index, assignment = matches[0]
        if subject in assignment.value_ids:
            raise ValueError("EVALUATION_PROBE_MUTATION_INVALID")
        assignments = list(frame.slot_assignments)
        assignments[assignment_index] = assignment.model_copy(
            update={"value_ids": tuple(sorted((*assignment.value_ids, subject)))}
        )
        frames = list(draft.intent_frames)
        frames[probe.frame_ordinal] = frame.model_copy(
            update={"slot_assignments": tuple(assignments)}
        )
        return draft.model_copy(update={"intent_frames": tuple(frames)})

    assert probe.link_ordinal is not None
    if probe.link_ordinal >= len(draft.context_link_hints):
        raise ValueError("EVALUATION_PROBE_MUTATION_INVALID")
    link = draft.context_link_hints[probe.link_ordinal]
    if probe.graph_field != "consumer_frame_id" or link.consumer_frame_id == subject:
        raise ValueError("EVALUATION_PROBE_MUTATION_INVALID")
    links = list(draft.context_link_hints)
    links[probe.link_ordinal] = link.model_copy(update={"consumer_frame_id": subject})
    return draft.model_copy(update={"context_link_hints": tuple(links)})


def _probe_index(prediction: EvaluationPrediction) -> dict[str, ValidationProbeOutcome]:
    return {item.probe_id: item for item in prediction.validation_probe_outcomes}


def _probe_subject_ids(probe: EvaluationProbe) -> tuple[str, ...]:
    return probe.subject_ids or ((probe.subject_id,) if probe.subject_id is not None else ())


def _align(
    cases: Sequence[EvaluationCase],
    predictions: Sequence[EvaluationPrediction],
) -> tuple[tuple[EvaluationCase, EvaluationPrediction], ...]:
    case_index = _unique_index(cases, lambda item: item.case_id)
    prediction_index = _unique_index(predictions, lambda item: item.case_id)
    if set(case_index) != set(prediction_index):
        raise ValueError("EVALUATION_CASE_SET_MISMATCH")
    return tuple(
        (case_index[case_id], prediction_index[case_id])
        for case_id in sorted(case_index)
    )


def _unique_index[T](items: Sequence[T], key: Callable[[T], str]) -> dict[str, T]:
    result = {key(item): item for item in items}
    if len(result) != len(items):
        raise ValueError("EVALUATION_DUPLICATE_CASE_ID")
    return result


def _exact_match[T, U, V](
    aligned: Sequence[tuple[T, U]],
    expected: Callable[[T], V],
    predicted: Callable[[U], V],
) -> CountMetric:
    return CountMetric(
        numerator=sum(expected(case) == predicted(prediction) for case, prediction in aligned),
        denominator=len(aligned),
    )


def _semantic_exact_match[V](
    aligned: Sequence[tuple[EvaluationCase, EvaluationPrediction]],
    expected: Callable[[EvaluationCase], V],
    predicted: Callable[[EvaluationPrediction], V],
) -> CountMetric:
    semantic = tuple(
        (case, prediction)
        for case, prediction in aligned
        if _is_semantic_result(prediction)
    )
    return CountMetric(
        numerator=sum(
            expected(case) == predicted(prediction) for case, prediction in semantic
        ),
        denominator=len(semantic),
    )


def _is_semantic_result(prediction: EvaluationPrediction) -> bool:
    return (
        prediction.pipeline_outcome != "pre_model_rejected"
        and prediction.provider_success is True
    )


def _coverage_outcomes(
    frames: Sequence[EvaluationFrame],
) -> tuple[tuple[CoverageState, CoverageReason], ...]:
    return tuple(
        (frame.semantic_coverage.state, frame.semantic_coverage.reason)
        for frame in frames
    )


def _coverage_states(frames: Sequence[EvaluationFrame]) -> tuple[CoverageState, ...]:
    return tuple(frame.semantic_coverage.state for frame in frames)


def _frame_axis(
    frames: Sequence[EvaluationFrame],
    values: Callable[[EvaluationFrame], Iterable[str]],
) -> frozenset[tuple[int, str]]:
    return frozenset(
        (frame.ordinal, value) for frame in frames for value in values(frame)
    )


def _frame_signatures(frames: Sequence[EvaluationFrame]) -> tuple[object, ...]:
    return tuple(
        (
            frame.ordinal,
            frame.action_ids,
            frame.product_family_ids,
            frame.entity_type_ids,
            (
                frame.semantic_coverage.state,
                frame.semantic_coverage.reason,
            ),
            tuple(
                sorted(
                    ((slot.slot_kind, slot.value_ids) for slot in frame.slots),
                    key=lambda item: item[0],
                )
            ),
        )
        for frame in frames
    )


def _requires_entity_role_evidence(frame: EvaluationFrame) -> bool:
    return any(slot.slot_kind in {"entity", "relation"} for slot in frame.slots)


def _joint_frame_match(
    expected: Sequence[EvaluationFrame], predicted: Sequence[EvaluationFrame]
) -> bool:
    if _frame_signatures(expected) != _frame_signatures(predicted):
        return False
    predicted_by_ordinal = {frame.ordinal: frame for frame in predicted}
    return all(
        not _requires_entity_role_evidence(frame)
        or frame.entity_hints is None
        or (
            (actual := predicted_by_ordinal.get(frame.ordinal)) is not None
            and actual.entity_hints == frame.entity_hints
        )
        for frame in expected
    )


def _reference_signatures(
    references: Sequence[ExpectedReference],
) -> tuple[tuple[int, str, str], ...]:
    return tuple(
        (index, reference.reference_form, reference.status)
        for index, reference in enumerate(references)
    )


def _context_link_signatures(
    frames: Sequence[EvaluationFrame],
    references: Sequence[ExpectedReference],
    links: Sequence[ExpectedContextLink],
    *,
    include_selector: bool,
    include_cardinality: bool,
) -> tuple[object, ...]:
    frame_ordinals = {frame.frame_id: frame.ordinal for frame in frames}
    reference_ordinals = {
        reference.reference_id: index for index, reference in enumerate(references)
    }

    def local_ordinal(identifier: str, values: dict[str, int]) -> object:
        return values.get(identifier, ("unresolved-local-id", identifier))

    signatures = []
    for link in links:
        signature: list[object] = [
            local_ordinal(link.reference_id, reference_ordinals),
            link.link_type,
            link.source_role,
            local_ordinal(link.producer_frame_id, frame_ordinals),
            local_ordinal(link.consumer_frame_id, frame_ordinals),
        ]
        if include_selector:
            signature.append(link.selector)
        if include_cardinality:
            signature.append(link.target_cardinality)
        signatures.append(tuple(signature))
    return tuple(sorted(signatures, key=repr))


def _mutation_signatures(
    frames: Sequence[EvaluationFrame],
    mutations: Sequence[ExpectedSlotMutation],
) -> tuple[object, ...]:
    frame_ordinals = {frame.frame_id: frame.ordinal for frame in frames}

    def local_ordinal(identifier: str | None) -> object:
        if identifier is None:
            return None
        return frame_ordinals.get(identifier, ("unresolved-local-id", identifier))

    return tuple(
        sorted(
            (
                (
                    local_ordinal(mutation.consumer_frame_id),
                    mutation.slot_kind,
                    mutation.mutation_kind,
                    local_ordinal(mutation.source_frame_id),
                )
                for mutation in mutations
            ),
            key=repr,
        )
    )


def _slot_axis(
    frames: Sequence[EvaluationFrame],
) -> frozenset[tuple[int, str, str]]:
    return frozenset(
        (frame.ordinal, slot.slot_kind, value)
        for frame in frames
        for slot in frame.slots
        for value in slot.value_ids
    )


def _micro_prf[T, U, V](
    aligned: Sequence[tuple[T, U]],
    expected: Callable[[T], frozenset[V]],
    predicted: Callable[[U], frozenset[V]],
) -> PrecisionRecallF1:
    true_positive = false_positive = false_negative = 0
    for case, prediction in aligned:
        if isinstance(prediction, EvaluationPrediction) and not _is_semantic_result(
            prediction
        ):
            continue
        expected_items = expected(case)
        predicted_items = predicted(prediction)
        true_positive += len(expected_items & predicted_items)
        false_positive += len(predicted_items - expected_items)
        false_negative += len(expected_items - predicted_items)
    return PrecisionRecallF1(
        precision=CountMetric(
            numerator=true_positive, denominator=true_positive + false_positive
        ),
        recall=CountMetric(
            numerator=true_positive, denominator=true_positive + false_negative
        ),
        f1=CountMetric(
            numerator=2 * true_positive,
            denominator=2 * true_positive + false_positive + false_negative,
        ),
    )


def _nearest_rank(values: Sequence[int], percentile: int) -> int | None:
    if not values:
        return None
    index = ceil(Decimal(percentile) * Decimal(len(values)) / Decimal(100)) - 1
    return values[index]


def _validate_frames(frames: Sequence[EvaluationFrame], label: str) -> None:
    _require_unique((frame.frame_id for frame in frames), f"{label} frame IDs")
    if tuple(frame.ordinal for frame in frames) != tuple(range(len(frames))):
        raise ValueError(f"{label} frame ordinals must be contiguous")


def _validate_graph(
    frames: Sequence[EvaluationFrame],
    references: Sequence[ExpectedReference],
    links: Sequence[ExpectedContextLink],
    mutations: Sequence[ExpectedSlotMutation],
    *,
    allow_dangling: bool,
) -> set[str]:
    frame_ordinals = {frame.frame_id: frame.ordinal for frame in frames}
    reference_ids = {reference.reference_id for reference in references}
    dangling: set[str] = set()
    for link in links:
        if link.reference_id not in reference_ids:
            dangling.add(link.reference_id)
        if link.producer_frame_id not in frame_ordinals:
            dangling.add(link.producer_frame_id)
        if link.consumer_frame_id not in frame_ordinals:
            dangling.add(link.consumer_frame_id)
        if (
            link.producer_frame_id in frame_ordinals
            and link.consumer_frame_id in frame_ordinals
            and frame_ordinals[link.producer_frame_id]
            >= frame_ordinals[link.consumer_frame_id]
        ):
            raise ValueError("context links must point from earlier to later frames")
    for mutation in mutations:
        if mutation.consumer_frame_id not in frame_ordinals:
            dangling.add(mutation.consumer_frame_id)
        if mutation.source_frame_id is not None and mutation.source_frame_id not in frame_ordinals:
            dangling.add(mutation.source_frame_id)
    if dangling and not allow_dangling:
        raise ValueError("evaluation context graph contains dangling IDs")
    return dangling


def _require_unique(values: Iterable[str], label: str) -> None:
    materialized = tuple(values)
    if len(set(materialized)) != len(materialized):
        raise ValueError(f"{label} must be unique")


def _require_sorted_unique(values: Iterable[str], label: str) -> None:
    materialized = tuple(values)
    if materialized != tuple(sorted(set(materialized))):
        raise ValueError(f"{label} must be sorted and unique")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_non_json_number() -> Any:
    raise ValueError("non-JSON number")
