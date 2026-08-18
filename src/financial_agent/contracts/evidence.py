from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .base import (
    ContractModel,
    Identifier,
    RuntimeArtifact,
    Sha256Hex,
    UtcDateTime,
)
from .enums import (
    CalculationType,
    CheckStatus,
    CheckTargetType,
    ClaimType,
    CutoffStatus,
    EvidenceKind,
    Repairability,
    SupportKind,
)
from .validation import require_unique_ids
from .values import ContractValue, ScalarValue


class SourceLocator(ContractModel):
    locator_type: Identifier
    uri_or_object_key: str
    record_key: str | None = None
    sheet: str | None = None
    row: int | None = None
    column: str | None = None
    page: int | None = None
    section: str | None = None
    sentence_start: int | None = None
    sentence_end: int | None = None


class SourceRecord(ContractModel):
    source_id: Identifier
    publisher: Identifier
    publisher_type: Identifier
    source_title: str
    source_type: Identifier
    authority_tier: Identifier
    source_locator_root: str
    content_checksum: Sha256Hex
    license_or_usage_note: str | None = None
    eligible_for_claim: bool


class EvidenceRecord(ContractModel):
    evidence_id: Identifier
    evidence_kind: EvidenceKind
    source_id: Identifier
    dataset_version: Identifier
    subject_id: Identifier | None = None
    predicate_id: Identifier | None = None
    value_or_object_id: ScalarValue
    normalized_value: ScalarValue
    unit: Identifier | None = None
    currency: str | None = None
    applicable_date: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    published_at: UtcDateTime | None = None
    available_at: UtcDateTime | None = None
    vintage_date: date | None = None
    source_locator: SourceLocator
    raw_value_repr: str | None = None
    parser_version: Identifier
    mapping_version: Identifier
    cutoff_status: CutoffStatus
    record_hash: Sha256Hex
    scope_completeness: Literal["closed_world", "bounded_unknown"] | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> "EvidenceRecord":
        if self.evidence_kind is EvidenceKind.QUERY_SCOPE:
            if self.scope_completeness is None:
                raise ValueError("query scope evidence requires scope completeness")
        elif self.scope_completeness is not None:
            raise ValueError("scope completeness is only valid for query scope evidence")

        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError("valid_to must be on or after valid_from")
        return self


class CalculationParameter(ContractModel):
    parameter_id: Identifier
    value: ContractValue


class PopulationDefinition(ContractModel):
    population_id: Identifier
    scope_evidence_id: Identifier
    filter_ids: tuple[Identifier, ...]
    member_count: int = Field(ge=0)
    population_hash: Sha256Hex


class CalculationRecord(ContractModel):
    calculation_id: Identifier
    calculation_type: CalculationType
    formula_id: Identifier
    formula_version: Identifier
    input_evidence_ids: tuple[Identifier, ...] = ()
    input_calculation_ids: tuple[Identifier, ...] = ()
    parameters: tuple[CalculationParameter, ...] = ()
    population_definition: PopulationDefinition | None = None
    exclusion_evidence_ids: tuple[Identifier, ...] = ()
    tie_break_rule: Identifier | None = None
    result_value: ScalarValue
    unit: Identifier | None = None
    currency: str | None = None
    rounding_rule: Identifier | None = None
    calculation_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_calculation(self) -> "CalculationRecord":
        if not self.input_evidence_ids and not self.input_calculation_ids:
            raise ValueError("calculation requires at least one input")
        if (
            self.calculation_type
            in {CalculationType.RANKING, CalculationType.AGGREGATION}
            and self.population_definition is None
        ):
            raise ValueError("ranking and aggregation require a population definition")
        if (
            self.calculation_type is CalculationType.RANKING
            and self.tie_break_rule is None
        ):
            raise ValueError("ranking requires a tie-break rule")
        return self


class ClaimQualifier(ContractModel):
    qualifier_id: Identifier
    value: ContractValue


class AtomicClaim(ContractModel):
    claim_id: Identifier
    claim_type: ClaimType
    subtask_id: Identifier
    subject_id: Identifier
    predicate_id: Identifier
    object_id: Identifier | None = None
    value: ScalarValue | None
    unit: Identifier | None = None
    currency: str | None = None
    qualifiers: tuple[ClaimQualifier, ...] = ()
    display_policy_id: Identifier
    claim_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_claim_target(self) -> "AtomicClaim":
        has_object = self.object_id is not None
        has_value = self.value is not None
        if has_object and has_value:
            raise ValueError("claim must not have both an object and a value")
        if has_object or has_value:
            return self
        if self.claim_type not in {
            ClaimType.DATA_LIMITATION,
            ClaimType.POLICY_BOUNDARY,
        }:
            raise ValueError("claim requires exactly one object or value")
        if not self.qualifiers:
            raise ValueError("qualifier-only claim requires a structured qualifier")
        return self


class ClaimSupport(ContractModel):
    claim_id: Identifier
    support_kind: SupportKind
    evidence_id: Identifier | None = None
    calculation_id: Identifier | None = None
    support_role: Identifier
    ordinal: int

    @model_validator(mode="after")
    def validate_support_target(self) -> "ClaimSupport":
        if (self.evidence_id is None) == (self.calculation_id is None):
            raise ValueError("claim support requires exactly one support target")
        return self


class MissingData(ContractModel):
    subtask_id: Identifier
    requirement_id: Identifier
    reason_code: Identifier


class AppliedDefault(ContractModel):
    subtask_id: Identifier
    policy_id: Identifier
    value_id: Identifier


class Limitation(ContractModel):
    subtask_id: Identifier
    reason_code: Identifier
    related_evidence_ids: tuple[Identifier, ...] = ()


class EvidenceBundle(RuntimeArtifact):
    bundle_id: Identifier
    answered_subtasks: tuple[Identifier, ...]
    unanswered_subtasks: tuple[Identifier, ...]
    evidence_ids: tuple[Identifier, ...]
    calculation_ids: tuple[Identifier, ...]
    candidate_claim_ids: tuple[Identifier, ...]
    exclusion_evidence_ids: tuple[Identifier, ...] = ()
    missing_data: tuple[MissingData, ...] = ()
    applied_defaults: tuple[AppliedDefault, ...] = ()
    limitations: tuple[Limitation, ...] = ()
    bundle_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_bundle(self) -> "EvidenceBundle":
        for label, ids in (
            ("answered subtasks", self.answered_subtasks),
            ("unanswered subtasks", self.unanswered_subtasks),
            ("evidence", self.evidence_ids),
            ("calculations", self.calculation_ids),
            ("candidate claims", self.candidate_claim_ids),
            ("exclusion evidence", self.exclusion_evidence_ids),
        ):
            require_unique_ids(ids, label=label)
        if set(self.answered_subtasks) & set(self.unanswered_subtasks):
            raise ValueError("answered and unanswered subtasks must not overlap")
        return self


class CheckResult(ContractModel):
    check_id: Identifier
    target_type: CheckTargetType
    target_id: Identifier
    rule_id: Identifier
    rule_version: Identifier
    status: CheckStatus
    reason_code: Identifier
    related_evidence_ids: tuple[Identifier, ...] = ()
    repairability: Repairability
