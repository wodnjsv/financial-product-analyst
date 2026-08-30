"""Deterministic no-fallback coordination for official document discovery."""

from __future__ import annotations

from datetime import datetime
import hashlib
import logging
import re

from financial_agent.documents import (
    CoverageStatus,
    DocumentCandidate,
    DocumentRole,
    DocumentSourceAuditEntry,
    DocumentSourceAuditReport,
    DocumentSourceCandidate,
    DocumentSourceTarget,
    SourceAuditStatus,
    select_canonical_document,
    validate_document_source_report,
)

from .base import (
    DocumentDiscoveryContext,
    DocumentSourceAdapter,
    SourceAdapterResult,
    classify_access_error,
)


_LOGGER = logging.getLogger(__name__)
_STABLE_REASON = re.compile(r"^[a-z][a-z0-9_]*$")
_REGISTERED_ROLES = frozenset(
    {
        DocumentRole.INDEX_METHODOLOGY,
        DocumentRole.OFFICIAL_UPDATE,
        DocumentRole.POLICY_BASE,
    }
)
_SEC_IDENTITY_SCHEMES = frozenset(
    {"SEC_CIK", "SEC_SERIES_ID", "SEC_CLASS_ID"}
)
_REQUIRED_CLAIMS = {
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
_COVERAGE_TO_AUDIT = {
    CoverageStatus.DOCUMENT_NOT_FOUND: SourceAuditStatus.DOCUMENT_NOT_FOUND,
    CoverageStatus.AMBIGUOUS_ENTITY_BINDING: (
        SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
    ),
    CoverageStatus.AFTER_CUTOFF_ONLY: SourceAuditStatus.AFTER_CUTOFF_ONLY,
    CoverageStatus.VERSION_UNKNOWN: SourceAuditStatus.VERSION_UNKNOWN,
    CoverageStatus.NOT_APPLICABLE_CURRENT_SCOPE: (
        SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE
    ),
}
_COMPLETE_STATUSES = frozenset(
    {
        SourceAuditStatus.ELIGIBLE,
        SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE,
    }
)


def audit_document_sources(
    targets: tuple[DocumentSourceTarget, ...],
    adapters: tuple[DocumentSourceAdapter, ...],
    context: DocumentDiscoveryContext,
    generated_at: datetime,
) -> DocumentSourceAuditReport:
    """Audit every unique target through exactly one owning source adapter."""

    if not targets:
        raise ValueError("document source audit requires at least one target")

    dataset_versions = {target.dataset_version for target in targets}
    cutoff_dates = {target.cutoff_date for target in targets}
    if len(dataset_versions) != 1 or len(cutoff_dates) != 1:
        raise ValueError("document source audit targets must share one snapshot")
    cutoff_date = next(iter(cutoff_dates))
    if context.cutoff_date != cutoff_date:
        raise ValueError("document discovery context cutoff differs from targets")

    adapter_registry = _adapter_registry(adapters)
    unique_targets, conflicting_keys = _unique_targets(targets)
    entries = tuple(
        _audit_target(
            target,
            adapter_registry=adapter_registry,
            context=context,
            conflicting=_target_key(target) in conflicting_keys,
        )
        for target in unique_targets
    )
    report = DocumentSourceAuditReport(
        schema_version="1.0",
        generated_at=generated_at,
        cutoff_date=cutoff_date,
        dataset_version=next(iter(dataset_versions)),
        entries=entries,
    )
    validate_document_source_report(report)
    return report


def document_source_audit_passed(report: DocumentSourceAuditReport) -> bool:
    """Return whether every audited role is either eligible or out of scope."""

    validate_document_source_report(report)
    return bool(report.entries) and all(
        entry.status in _COMPLETE_STATUSES for entry in report.entries
    )


def _target_key(target: DocumentSourceTarget) -> tuple[str, str, str]:
    return (
        target.dataset_version,
        target.entity_id,
        target.required_role.value,
    )


def _audit_target(
    target: DocumentSourceTarget,
    *,
    adapter_registry: dict[str, tuple[DocumentSourceAdapter, ...]],
    context: DocumentDiscoveryContext,
    conflicting: bool,
) -> DocumentSourceAuditEntry:
    if conflicting:
        return _unavailable_entry(
            target,
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "duplicate_target_definition_conflict",
        )
    if _is_domestic_bond(target):
        return _unavailable_entry(
            target,
            SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE,
            "domestic_bond_not_in_document_scope",
        )

    route_key = _route_key(target)
    if route_key == "NOT_APPLICABLE":
        return _unavailable_entry(
            target,
            SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE,
            "document_role_not_in_current_scope",
        )

    route_adapters = adapter_registry.get(route_key, ())
    if not route_adapters:
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_adapter_missing",
        )
    if len(route_adapters) != 1:
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_adapter_registration_ambiguous",
        )

    try:
        result = route_adapters[0].discover(target, context)
        return _entry_from_result(target, result, route_key=route_key)
    except Exception as error:
        status = classify_access_error(error)
        return _unavailable_entry(
            target,
            status,
            f"{route_key.lower()}_{status.value}",
        )


def _entry_from_result(
    target: DocumentSourceTarget,
    result: SourceAdapterResult,
    *,
    route_key: str,
) -> DocumentSourceAuditEntry:
    if not isinstance(result, SourceAdapterResult):
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_adapter_result_invalid",
        )
    if result.status is not SourceAuditStatus.ELIGIBLE:
        status = result.status
        reason_code = _stable_reason(
            result.reason_code,
            fallback=f"{route_key.lower()}_{status.value}",
        )
        if (
            route_key == "REGISTERED"
            and target.product_family == "overseas_etf"
            and target.required_role is DocumentRole.PRODUCT_SUMMARY
            and status is SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE
        ):
            status = SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
            reason_code = "registered_jurisdictional_locator_unavailable"
        return _unavailable_entry(target, status, reason_code)
    if result.reason_code is not None or not result.candidates:
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_eligible_result_invalid",
        )

    candidates = tuple(sorted(result.candidates, key=_source_candidate_key))
    document_ids = [candidate.document_id for candidate in candidates]
    if len(document_ids) != len(set(document_ids)):
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_duplicate_document_id",
        )

    selection = select_canonical_document(
        tuple(_selection_candidate(item, target=target) for item in candidates),
        required_role=target.required_role,
        cutoff_date=target.cutoff_date,
    )
    if selection.rejected_document_ids:
        _LOGGER.debug(
            "official source candidates rejected target=%s role=%s ids=%s",
            target.entity_id,
            target.required_role.value,
            selection.rejected_document_ids,
        )
    if selection.coverage_status is CoverageStatus.INDEXED:
        selected = next(
            item
            for item in candidates
            if item.document_id == selection.document_id
        )
        return DocumentSourceAuditEntry(
            target=target,
            status=SourceAuditStatus.ELIGIBLE,
            reason_code=None,
            candidate=selected,
        )

    status = _COVERAGE_TO_AUDIT.get(
        selection.coverage_status,
        SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
    )
    reason_code = _stable_reason(
        selection.reason_code,
        fallback=f"canonical_{selection.coverage_status.value}",
    )
    return _unavailable_entry(target, status, reason_code)


def _selection_candidate(
    candidate: DocumentSourceCandidate,
    *,
    target: DocumentSourceTarget,
) -> DocumentCandidate:
    # Body-stage Claim/text gates are outside this metadata-only preflight. These
    # neutral proxy values are never persisted or exposed in the audit report.
    fingerprint = hashlib.sha256(
        "\0".join(
            (
                candidate.document_id,
                candidate.source_code,
                candidate.source_locator,
            )
        ).encode("utf-8")
    ).hexdigest()
    return DocumentCandidate(
        document_id=candidate.document_id,
        document_type=candidate.document_type,
        document_version=candidate.document_version,
        source_id=candidate.source_code,
        publisher_role=candidate.publisher_role,
        jurisdiction=candidate.jurisdiction,
        original_language=candidate.original_language,
        published_at=candidate.published_at,
        available_at=candidate.available_at,
        effective_from=candidate.effective_from,
        effective_to=candidate.effective_to,
        bound_entity_ids=(target.entity_id,),
        binding_role=target.binding_role,
        claim_types=_REQUIRED_CLAIMS[target.required_role],
        content_checksum=fingerprint,
        extraction_method="source_preflight",
        exact_text_available=True,
        source_locator=candidate.source_locator,
    )


def _route_key(target: DocumentSourceTarget) -> str:
    if target.product_family in {"domestic_etf", "public_fund"}:
        return "DART"
    if target.product_family == "overseas_etf":
        if target.required_role is DocumentRole.PRODUCT_SUMMARY:
            return "SEC" if _has_complete_sec_identity(target) else "REGISTERED"
        if target.required_role in _REGISTERED_ROLES:
            return "REGISTERED"
        return "NOT_APPLICABLE"
    if target.required_role in _REGISTERED_ROLES:
        return "REGISTERED"
    return "NOT_APPLICABLE"


def _has_complete_sec_identity(target: DocumentSourceTarget) -> bool:
    counts = {scheme: 0 for scheme in _SEC_IDENTITY_SCHEMES}
    for scheme, _ in target.identifiers:
        if scheme in counts:
            counts[scheme] += 1
    return all(count == 1 for count in counts.values())


def _adapter_registry(
    adapters: tuple[DocumentSourceAdapter, ...],
) -> dict[str, tuple[DocumentSourceAdapter, ...]]:
    grouped: dict[str, list[DocumentSourceAdapter]] = {}
    for adapter in adapters:
        source_code = getattr(adapter, "source_code", None)
        if isinstance(source_code, str):
            grouped.setdefault(source_code, []).append(adapter)
    return {source_code: tuple(items) for source_code, items in grouped.items()}


def _unique_targets(
    targets: tuple[DocumentSourceTarget, ...],
) -> tuple[tuple[DocumentSourceTarget, ...], frozenset[tuple[str, str, str]]]:
    grouped: dict[tuple[str, str, str], list[DocumentSourceTarget]] = {}
    for target in targets:
        grouped.setdefault(_target_key(target), []).append(target)

    selected: list[DocumentSourceTarget] = []
    conflicts: set[tuple[str, str, str]] = set()
    for key, items in grouped.items():
        ordered = sorted(items, key=_target_sort_key)
        selected.append(ordered[0])
        if any(item != ordered[0] for item in ordered[1:]):
            conflicts.add(key)
    return (
        tuple(
            sorted(
                selected,
                key=lambda target: (
                    target.entity_type,
                    target.entity_id,
                    target.required_role.value,
                    _target_sort_key(target),
                ),
            )
        ),
        frozenset(conflicts),
    )


def _target_sort_key(target: DocumentSourceTarget) -> tuple[object, ...]:
    return (
        target.dataset_version,
        target.entity_id,
        target.entity_type,
        target.canonical_name,
        target.product_family or "",
        target.required_role.value,
        target.binding_role,
        tuple(sorted(target.identifiers)),
        target.cutoff_date.isoformat(),
    )


def _source_candidate_key(
    candidate: DocumentSourceCandidate,
) -> tuple[object, ...]:
    return (
        candidate.document_id,
        candidate.source_code,
        candidate.authority_tier.value,
        candidate.publisher_code,
        candidate.publisher_role.value,
        candidate.document_type,
        candidate.document_version or "",
        candidate.source_locator,
        candidate.discovery_locator,
        candidate.jurisdiction,
        candidate.original_language,
        candidate.published_at.isoformat() if candidate.published_at else "",
        candidate.available_at.isoformat() if candidate.available_at else "",
        candidate.effective_from.isoformat() if candidate.effective_from else "",
        candidate.effective_to.isoformat() if candidate.effective_to else "",
        candidate.media_type or "",
        candidate.accession_or_receipt_id or "",
    )


def _stable_reason(reason_code: str | None, *, fallback: str) -> str:
    if isinstance(reason_code, str) and _STABLE_REASON.fullmatch(reason_code):
        return reason_code
    return fallback


def _unavailable_entry(
    target: DocumentSourceTarget,
    status: SourceAuditStatus,
    reason_code: str,
) -> DocumentSourceAuditEntry:
    return DocumentSourceAuditEntry(
        target=target,
        status=status,
        reason_code=reason_code,
        candidate=None,
    )


def _is_domestic_bond(target: DocumentSourceTarget) -> bool:
    return (
        target.product_family == "domestic_bond"
        or target.entity_type == "domestic_bond"
    )
