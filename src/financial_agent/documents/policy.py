from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from .models import (
    AdmissionDecision,
    CanonicalDocumentSelection,
    CoverageStatus,
    DocumentCandidate,
    DocumentRole,
    PublisherRole,
)


_SEOUL = ZoneInfo("Asia/Seoul")
_BINDING_ROLES = frozenset(
    {"subject_product", "subject_index", "subject_policy"}
)
_ROLE_DOCUMENT_TYPES = {
    DocumentRole.PRODUCT_SUMMARY: frozenset(
        {"summary_prospectus", "full_prospectus"}
    ),
    DocumentRole.PRODUCT_FULL: frozenset({"full_prospectus"}),
    DocumentRole.INDEX_METHODOLOGY: frozenset({"index_methodology"}),
    DocumentRole.OFFICIAL_UPDATE: frozenset({"official_update"}),
    DocumentRole.POLICY_BASE: frozenset({"policy_base"}),
}
_DOCUMENT_TYPE_ROLES = {
    "summary_prospectus": DocumentRole.PRODUCT_SUMMARY,
    "full_prospectus": DocumentRole.PRODUCT_FULL,
    "index_methodology": DocumentRole.INDEX_METHODOLOGY,
    "official_update": DocumentRole.OFFICIAL_UPDATE,
    "policy_base": DocumentRole.POLICY_BASE,
}
_ROLE_BINDING_ROLES = {
    DocumentRole.PRODUCT_SUMMARY: frozenset({"subject_product"}),
    DocumentRole.PRODUCT_FULL: frozenset({"subject_product"}),
    DocumentRole.INDEX_METHODOLOGY: frozenset({"subject_index"}),
    DocumentRole.OFFICIAL_UPDATE: _BINDING_ROLES,
    DocumentRole.POLICY_BASE: frozenset({"subject_policy"}),
}
_REQUIRED_CLAIM_TYPES = {
    DocumentRole.PRODUCT_SUMMARY: frozenset(
        {"investment_strategy", "risk_factor"}
    ),
    DocumentRole.PRODUCT_FULL: frozenset(
        {"investment_strategy", "risk_factor"}
    ),
    DocumentRole.INDEX_METHODOLOGY: frozenset(
        {"index_methodology", "selection_rules", "rebalancing"}
    ),
    DocumentRole.OFFICIAL_UPDATE: frozenset({"official_update"}),
    DocumentRole.POLICY_BASE: frozenset(
        {"legal_structure", "investment_strategy"}
    ),
}
_PRODUCT_PUBLISHERS = frozenset(
    {
        PublisherRole.REGULATOR_DISCLOSURE,
        PublisherRole.ASSET_MANAGER,
        PublisherRole.ISSUER,
    }
)
_ROLE_PUBLISHERS = {
    DocumentRole.PRODUCT_SUMMARY: _PRODUCT_PUBLISHERS,
    DocumentRole.PRODUCT_FULL: _PRODUCT_PUBLISHERS,
    DocumentRole.INDEX_METHODOLOGY: frozenset({PublisherRole.INDEX_PROVIDER}),
    DocumentRole.POLICY_BASE: frozenset(
        {PublisherRole.POLICY_AUTHORITY, PublisherRole.POLICY_OPERATOR}
    ),
}
_OFFICIAL_UPDATE_PUBLISHERS = {
    "subject_product": _PRODUCT_PUBLISHERS,
    "subject_index": frozenset({PublisherRole.INDEX_PROVIDER}),
    "subject_policy": frozenset(
        {PublisherRole.POLICY_AUTHORITY, PublisherRole.POLICY_OPERATOR}
    ),
}
_FAILURE_PRIORITY = (
    CoverageStatus.AMBIGUOUS_ENTITY_BINDING,
    CoverageStatus.PUBLISHER_NOT_APPROVED,
    CoverageStatus.VERSION_UNKNOWN,
    CoverageStatus.AFTER_CUTOFF_ONLY,
    CoverageStatus.UNREADABLE_DOCUMENT,
)


def _rejected(
    candidate: DocumentCandidate,
    status: CoverageStatus,
    reason_code: str,
) -> AdmissionDecision:
    return AdmissionDecision(False, status, reason_code, candidate)


def _binding_reason(
    candidate: DocumentCandidate,
    required_role: DocumentRole,
) -> str | None:
    if len(candidate.bound_entity_ids) != 1:
        return "exact_entity_binding_required"
    if candidate.binding_role not in _BINDING_ROLES:
        return "binding_role_not_approved"
    if candidate.binding_role not in binding_roles_for_document_role(required_role):
        return "binding_role_incompatible_with_document_role"
    return None


def _is_aware(value: datetime | None) -> bool:
    return (
        value is not None
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def document_types_for_role(required_role: DocumentRole) -> frozenset[str]:
    """Return the immutable document-type authority for a document role."""

    return _ROLE_DOCUMENT_TYPES[required_role]


def binding_roles_for_document_role(
    required_role: DocumentRole,
) -> frozenset[str]:
    """Return the immutable Entity-binding authority for a document role."""

    return _ROLE_BINDING_ROLES[required_role]


def publisher_roles_for_document_role(
    required_role: DocumentRole,
    binding_role: str,
) -> frozenset[PublisherRole]:
    """Return publishers approved for one exact document/binding context."""

    if binding_role not in _ROLE_BINDING_ROLES[required_role]:
        raise ValueError("binding role is not approved for document role")
    if required_role is DocumentRole.OFFICIAL_UPDATE:
        return _OFFICIAL_UPDATE_PUBLISHERS[binding_role]
    return _ROLE_PUBLISHERS[required_role]


def _admit(
    candidate: DocumentCandidate,
    *,
    cutoff_date: date,
    required_role: DocumentRole,
) -> AdmissionDecision:
    binding_reason = _binding_reason(candidate, required_role)
    if binding_reason is not None:
        return _rejected(
            candidate,
            CoverageStatus.AMBIGUOUS_ENTITY_BINDING,
            binding_reason,
        )
    if candidate.publisher_role not in publisher_roles_for_document_role(
        required_role, candidate.binding_role
    ):
        return _rejected(
            candidate,
            CoverageStatus.PUBLISHER_NOT_APPROVED,
            "publisher_role_not_approved",
        )
    if not _is_aware(candidate.published_at) or not _is_aware(
        candidate.available_at
    ):
        return _rejected(
            candidate,
            CoverageStatus.VERSION_UNKNOWN,
            "cutoff_timing_not_verified",
        )
    assert candidate.published_at is not None
    assert candidate.available_at is not None
    if (
        candidate.published_at.astimezone(_SEOUL).date() > cutoff_date
        or candidate.available_at.astimezone(_SEOUL).date() > cutoff_date
    ):
        return _rejected(
            candidate,
            CoverageStatus.AFTER_CUTOFF_ONLY,
            "after_cutoff_only",
        )
    if (
        not candidate.document_version
        or candidate.effective_from is None
        or candidate.effective_from > cutoff_date
        or (
            candidate.effective_to is not None
            and (
                candidate.effective_to < candidate.effective_from
                or candidate.effective_to < cutoff_date
            )
        )
    ):
        return _rejected(
            candidate,
            CoverageStatus.VERSION_UNKNOWN,
            "effective_version_not_verified",
        )
    if not candidate.exact_text_available:
        return _rejected(
            candidate,
            CoverageStatus.UNREADABLE_DOCUMENT,
            "round_trippable_text_required",
        )
    return AdmissionDecision(True, CoverageStatus.INDEXED, None, candidate)


def admit_document(
    candidate: DocumentCandidate,
    *,
    cutoff_date: date,
) -> AdmissionDecision:
    """Admit a candidate only when its identity and official text are provable."""
    required_role = _DOCUMENT_TYPE_ROLES.get(candidate.document_type)
    if required_role is None:
        return _rejected(
            candidate,
            CoverageStatus.PUBLISHER_NOT_APPROVED,
            "document_type_not_approved",
        )
    return _admit(candidate, cutoff_date=cutoff_date, required_role=required_role)


def _selection_key(candidate: DocumentCandidate, required_role: DocumentRole) -> tuple:
    summary_rank = 0
    if required_role is DocumentRole.PRODUCT_SUMMARY:
        summary_rank = 0 if candidate.document_type == "summary_prospectus" else 1
    assert candidate.effective_from is not None
    assert candidate.published_at is not None
    return (
        summary_rank,
        -candidate.effective_from.toordinal(),
        -candidate.published_at.timestamp(),
        candidate.document_id,
    )


def _rejected_ids(
    candidates: tuple[DocumentCandidate, ...],
    selected_document_id: str | None,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                candidate.document_id
                for candidate in candidates
                if candidate.document_id != selected_document_id
            }
        )
    )


def _binding_selection(
    candidates: tuple[DocumentCandidate, ...],
    required_role: DocumentRole,
) -> CanonicalDocumentSelection | None:
    binding_failures = tuple(
        (reason, candidate.document_id)
        for candidate in candidates
        if (reason := _binding_reason(candidate, required_role)) is not None
    )
    if binding_failures:
        reason_code, _ = min(binding_failures)
        return CanonicalDocumentSelection(
            None,
            CoverageStatus.AMBIGUOUS_ENTITY_BINDING,
            reason_code,
            _rejected_ids(candidates, None),
        )
    if len({candidate.bound_entity_ids[0] for candidate in candidates}) != 1:
        return CanonicalDocumentSelection(
            None,
            CoverageStatus.AMBIGUOUS_ENTITY_BINDING,
            "candidate_entities_mismatch",
            _rejected_ids(candidates, None),
        )
    return None


def _failure_selection(
    candidates: tuple[DocumentCandidate, ...],
    decisions: tuple[AdmissionDecision, ...],
) -> CanonicalDocumentSelection:
    for status in _FAILURE_PRIORITY:
        failures = tuple(
            (decision.reason_code or "", decision.candidate.document_id)
            for decision in decisions
            if decision.coverage_status is status
        )
        if failures:
            reason_code, _ = min(failures)
            return CanonicalDocumentSelection(
                None,
                status,
                reason_code,
                _rejected_ids(candidates, None),
            )
    return CanonicalDocumentSelection(
        None,
        CoverageStatus.DOCUMENT_NOT_FOUND,
        "no_candidate_for_required_role",
        _rejected_ids(candidates, None),
    )


def select_canonical_document(
    candidates: tuple[DocumentCandidate, ...],
    *,
    required_role: DocumentRole,
    cutoff_date: date,
) -> CanonicalDocumentSelection:
    """Select one admissible document without using title or similarity signals."""
    relevant_candidates = tuple(
        candidate
        for candidate in candidates
        if candidate.document_type in document_types_for_role(required_role)
    )
    if not relevant_candidates:
        return CanonicalDocumentSelection(
            None,
            CoverageStatus.DOCUMENT_NOT_FOUND,
            "no_candidate_for_required_role",
            (),
        )
    binding_selection = _binding_selection(relevant_candidates, required_role)
    if binding_selection is not None:
        return binding_selection
    decisions = tuple(
        _admit(
            candidate,
            cutoff_date=cutoff_date,
            required_role=required_role,
        )
        for candidate in relevant_candidates
    )
    role_candidates = tuple(
        decision.candidate for decision in decisions if decision.accepted
    )
    covered_candidates = tuple(
        candidate
        for candidate in role_candidates
        if _REQUIRED_CLAIM_TYPES[required_role] <= candidate.claim_types
    )
    if covered_candidates:
        selected = min(
            covered_candidates,
            key=lambda candidate: _selection_key(candidate, required_role),
        )
        return CanonicalDocumentSelection(
            selected.document_id,
            CoverageStatus.INDEXED,
            None,
            _rejected_ids(relevant_candidates, selected.document_id),
        )
    if role_candidates:
        return CanonicalDocumentSelection(
            None,
            CoverageStatus.SECTION_MISSING,
            "required_claim_coverage_missing",
            _rejected_ids(relevant_candidates, None),
        )
    return _failure_selection(relevant_candidates, decisions)
