from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class DocumentRole(str, Enum):
    PRODUCT_SUMMARY = "product_summary"
    PRODUCT_FULL = "product_full"
    INDEX_METHODOLOGY = "index_methodology"
    OFFICIAL_UPDATE = "official_update"
    POLICY_BASE = "policy_base"


class CoverageStatus(str, Enum):
    INDEXED = "indexed"
    DOCUMENT_NOT_FOUND = "document_not_found"
    AMBIGUOUS_ENTITY_BINDING = "ambiguous_entity_binding"
    AFTER_CUTOFF_ONLY = "after_cutoff_only"
    VERSION_UNKNOWN = "version_unknown"
    UNREADABLE_DOCUMENT = "unreadable_document"
    PUBLISHER_NOT_APPROVED = "publisher_not_approved"
    SECTION_MISSING = "section_missing"
    NOT_APPLICABLE_CURRENT_SCOPE = "not_applicable_current_scope"
    REVIEW_REQUIRED_CHUNK_BUDGET = "review_required_chunk_budget"


class SectionType(str, Enum):
    LEGAL_STRUCTURE = "legal_structure"
    INVESTMENT_OBJECTIVE = "investment_objective"
    INVESTMENT_STRATEGY = "investment_strategy"
    INDEX_METHODOLOGY = "index_methodology"
    THEME_DEFINITION = "theme_definition"
    SELECTION_RULES = "selection_rules"
    REBALANCING = "rebalancing"
    RISK_FACTOR = "risk_factor"
    OFFICIAL_UPDATE = "official_update"
    CHANGE_HISTORY = "change_history"
    CURRENCY_HEDGE = "currency_hedge"
    DERIVATIVES_LEVERAGE = "derivatives_leverage"
    GOVERNANCE = "governance"
    LEGACY_UNCLASSIFIED = "legacy_unclassified"


class PublisherRole(str, Enum):
    REGULATOR_DISCLOSURE = "regulator_disclosure"
    ASSET_MANAGER = "asset_manager"
    ISSUER = "issuer"
    INDEX_PROVIDER = "index_provider"
    POLICY_AUTHORITY = "policy_authority"
    POLICY_OPERATOR = "policy_operator"


@dataclass(frozen=True, slots=True)
class DocumentCandidate:
    document_id: str
    document_type: str
    document_version: str | None
    source_id: str
    publisher_role: PublisherRole
    jurisdiction: str
    original_language: str
    published_at: datetime | None
    available_at: datetime | None
    effective_from: date | None
    effective_to: date | None
    bound_entity_ids: tuple[str, ...]
    binding_role: str
    claim_types: frozenset[str]
    content_checksum: str
    extraction_method: str
    exact_text_available: bool
    source_locator: str


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    accepted: bool
    coverage_status: CoverageStatus
    reason_code: str | None
    candidate: DocumentCandidate


@dataclass(frozen=True, slots=True)
class CanonicalDocumentSelection:
    document_id: str | None
    coverage_status: CoverageStatus
    reason_code: str | None
    rejected_document_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentCoverageDraft:
    coverage_id: str
    dataset_version: str
    entity_id: str
    required_document_role: DocumentRole
    coverage_status: CoverageStatus
    document_id: str | None
    scope_evidence_id: str | None
    reason_code: str | None
    record_hash: str

    def __post_init__(self) -> None:
        if self.coverage_status is CoverageStatus.INDEXED:
            if (
                self.document_id is None
                or self.scope_evidence_id is not None
                or self.reason_code is not None
            ):
                raise ValueError("indexed coverage requires only a document")
            return
        if (
            self.document_id is not None
            or self.scope_evidence_id is None
            or not self.reason_code
        ):
            raise ValueError("negative coverage requires scope evidence only")


@dataclass(frozen=True, slots=True)
class DocumentChunkDraft:
    dataset_version: str
    chunk_id: str
    document_id: str
    ordinal: int
    page_start: int | None
    page_end: int | None
    section_type: SectionType
    section_path: str
    character_start: int
    character_end: int
    exact_text: str
    normalized_search_text: str
    embedding_text: str
    content_hash: str
    record_hash: str
