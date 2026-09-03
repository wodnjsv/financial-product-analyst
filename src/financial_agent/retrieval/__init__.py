"""Bounded document-candidate retrieval."""

from .documents import (
    ClaimAuthorityRule,
    DocumentCandidateHit,
    DocumentCandidateRepository,
    DocumentSearchRequest,
    claim_authority_rules,
    reciprocal_rank_fusion,
)
from .document_evidence import (
    DocumentEvidencePromoter,
    DocumentEvidencePromotionError,
    PromotedDocumentEvidence,
)

__all__ = [
    "ClaimAuthorityRule",
    "DocumentCandidateHit",
    "DocumentCandidateRepository",
    "DocumentEvidencePromoter",
    "DocumentEvidencePromotionError",
    "DocumentSearchRequest",
    "PromotedDocumentEvidence",
    "claim_authority_rules",
    "reciprocal_rank_fusion",
]
