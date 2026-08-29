from __future__ import annotations

from datetime import date

from .models import (
    AdmissionDecision,
    CanonicalDocumentSelection,
    CoverageStatus,
    DocumentCandidate,
    DocumentRole,
    PublisherRole,
)


_APPROVED_PUBLISHER_ROLES = frozenset(PublisherRole)
_ROLE_DOCUMENT_TYPES = {
    DocumentRole.PRODUCT_SUMMARY: frozenset(
        {"summary_prospectus", "full_prospectus"}
    ),
    DocumentRole.PRODUCT_FULL: frozenset({"full_prospectus"}),
    DocumentRole.INDEX_METHODOLOGY: frozenset({"index_methodology"}),
    DocumentRole.OFFICIAL_UPDATE: frozenset({"official_update"}),
    DocumentRole.POLICY_BASE: frozenset({"policy_base"}),
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
_FAILURE_PRIORITY = (
    CoverageStatus.AMBIGUOUS_ENTITY_BINDING,
    CoverageStatus.PUBLISHER_NOT_APPROVED,
    CoverageStatus.AFTER_CUTOFF_ONLY,
    CoverageStatus.VERSION_UNKNOWN,
    CoverageStatus.UNREADABLE_DOCUMENT,
)


def _rejected(
    candidate: DocumentCandidate,
    status: CoverageStatus,
    reason_code: str,
) -> AdmissionDecision:
    return AdmissionDecision(False, status, reason_code, candidate)


def admit_document(
    candidate: DocumentCandidate,
    *,
    cutoff_date: date,
) -> AdmissionDecision:
    """Admit a candidate only when its identity and official text are provable."""
    if len(candidate.bound_entity_ids) != 1:
        return _rejected(
            candidate,
            CoverageStatus.AMBIGUOUS_ENTITY_BINDING,
            "exact_entity_binding_required",
        )
    if candidate.publisher_role not in _APPROVED_PUBLISHER_ROLES:
        return _rejected(
            candidate,
            CoverageStatus.PUBLISHER_NOT_APPROVED,
            "publisher_role_not_approved",
        )
    if candidate.published_at is None or candidate.available_at is None:
        return _rejected(
            candidate,
            CoverageStatus.AFTER_CUTOFF_ONLY,
            "cutoff_timing_not_verified",
        )
    if (
        candidate.published_at.date() > cutoff_date
        or candidate.available_at.date() > cutoff_date
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


def _failure_selection(
    candidates: tuple[DocumentCandidate, ...],
    decisions: tuple[AdmissionDecision, ...],
) -> CanonicalDocumentSelection:
    for status in _FAILURE_PRIORITY:
        if any(decision.coverage_status is status for decision in decisions):
            return CanonicalDocumentSelection(
                None,
                status,
                next(
                    decision.reason_code
                    for decision in decisions
                    if decision.coverage_status is status
                ),
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
    decisions = tuple(
        admit_document(candidate, cutoff_date=cutoff_date)
        for candidate in candidates
    )
    role_candidates = tuple(
        decision.candidate
        for decision in decisions
        if decision.accepted
        and decision.candidate.document_type in _ROLE_DOCUMENT_TYPES[required_role]
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
            _rejected_ids(candidates, selected.document_id),
        )
    if role_candidates:
        return CanonicalDocumentSelection(
            None,
            CoverageStatus.SECTION_MISSING,
            "required_claim_coverage_missing",
            _rejected_ids(candidates, None),
        )
    return _failure_selection(candidates, decisions)
