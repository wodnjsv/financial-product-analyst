"""Deterministic no-fallback coordination for official document discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
import re

from financial_agent.documents import (
    DocumentRole,
    DocumentSourceAuditEntry,
    DocumentSourceAuditReport,
    DocumentSourceCandidate,
    DocumentSourceTarget,
    PublisherRole,
    SourceAuditStatus,
    SourceAuthorityTier,
    binding_roles_for_document_role,
    document_types_for_role,
    publisher_roles_for_document_role,
    validate_document_source_report,
)
from financial_agent.documents.source_manifest import (
    source_timestamp_is_after_cutoff,
)

from .base import (
    DocumentDiscoveryContext,
    DocumentSourceAdapter,
    SourceAdapterResult,
    classify_access_error,
)
from .sec import has_complete_sec_identity


_LOGGER = logging.getLogger(__name__)
_STABLE_REASON = re.compile(r"^[a-z][a-z0-9_]*$")
_REGISTERED_ROLES = frozenset(
    {
        DocumentRole.INDEX_METHODOLOGY,
        DocumentRole.OFFICIAL_UPDATE,
        DocumentRole.POLICY_BASE,
    }
)
_TIER_2_PUBLISHERS = frozenset(
    {
        PublisherRole.INDEX_PROVIDER,
        PublisherRole.POLICY_AUTHORITY,
        PublisherRole.POLICY_OPERATOR,
    }
)
_TIER_3_PUBLISHERS = frozenset(
    {PublisherRole.EXCHANGE, PublisherRole.INDUSTRY_ASSOCIATION}
)
_COMPLETE_STATUSES = frozenset(
    {
        SourceAuditStatus.ELIGIBLE,
        SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE,
    }
)
_FAILURE_PRIORITY = (
    SourceAuditStatus.VERSION_UNKNOWN,
    SourceAuditStatus.AFTER_CUTOFF_ONLY,
)


@dataclass(frozen=True, slots=True)
class _SourceSelection:
    status: SourceAuditStatus
    reason_code: str | None
    candidate: DocumentSourceCandidate | None
    rejected_document_ids: tuple[str, ...]


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
    """Return whether all entries are valid source-metadata dispositions."""

    try:
        validate_document_source_report(report)
    except (TypeError, ValueError):
        return False
    if not report.entries:
        return False
    for entry in report.entries:
        if entry.status not in _COMPLETE_STATUSES:
            return False
        if entry.status is SourceAuditStatus.ELIGIBLE:
            route_key = _route_key(entry.target)
            candidate = entry.candidate
            if (
                candidate is None
                or route_key == "NOT_APPLICABLE"
                or _candidate_provenance_reason(
                    candidate,
                    target=entry.target,
                    route_key=route_key,
                )
                is not None
            ):
                return False
    return True


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
    if not _target_binding_is_valid(target):
        return _unavailable_entry(
            target,
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "binding_role_incompatible_with_document_role",
        )

    route_key = _route_key(target)
    if route_key == "NOT_APPLICABLE":
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
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

    adapter = route_adapters[0]
    try:
        if adapter.supports(target) is not True:
            return _unavailable_entry(
                target,
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                f"{route_key.lower()}_target_not_supported",
            )
        result = adapter.discover(target, context)
    except Exception as error:
        status = classify_access_error(error)
        return _unavailable_entry(
            target,
            status,
            f"{route_key.lower()}_{status.value}",
        )
    return _entry_from_result(target, result, route_key=route_key)


def _entry_from_result(
    target: DocumentSourceTarget,
    result: object,
    *,
    route_key: str,
) -> DocumentSourceAuditEntry:
    if not _adapter_result_is_valid(result):
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_adapter_result_invalid",
        )
    assert isinstance(result, SourceAdapterResult)
    if result.status is SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE:
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_target_not_supported",
        )
    if result.status is not SourceAuditStatus.ELIGIBLE:
        assert result.reason_code is not None
        return _unavailable_entry(target, result.status, result.reason_code)

    candidates = tuple(sorted(result.candidates, key=_source_candidate_key))
    document_ids = [candidate.document_id for candidate in candidates]
    if len(document_ids) != len(set(document_ids)):
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_duplicate_document_id",
        )
    provenance_reasons = tuple(
        reason
        for candidate in candidates
        if (
            reason := _candidate_provenance_reason(
                candidate,
                target=target,
                route_key=route_key,
            )
        )
        is not None
    )
    if provenance_reasons:
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            min(provenance_reasons),
        )

    selection = _select_source_candidate(candidates, target=target)
    if selection.rejected_document_ids:
        _LOGGER.debug(
            "official source candidates rejected target=%s role=%s ids=%s",
            target.entity_id,
            target.required_role.value,
            selection.rejected_document_ids,
        )
    return DocumentSourceAuditEntry(
        target=target,
        status=selection.status,
        reason_code=selection.reason_code,
        candidate=selection.candidate,
    )


def _select_source_candidate(
    candidates: tuple[DocumentSourceCandidate, ...],
    *,
    target: DocumentSourceTarget,
) -> _SourceSelection:
    relevant = tuple(
        candidate
        for candidate in candidates
        if candidate.document_type in document_types_for_role(target.required_role)
    )
    if not relevant:
        return _SourceSelection(
            SourceAuditStatus.DOCUMENT_NOT_FOUND,
            "no_candidate_for_required_role",
            None,
            tuple(sorted({candidate.document_id for candidate in candidates})),
        )

    dispositions = tuple(
        (candidate, *_candidate_disposition(candidate, cutoff_date=target.cutoff_date))
        for candidate in relevant
    )
    eligible = tuple(
        candidate
        for candidate, status, _ in dispositions
        if status is SourceAuditStatus.ELIGIBLE
    )
    if eligible:
        selected = min(
            eligible,
            key=lambda candidate: _candidate_precedence_key(
                candidate,
                required_role=target.required_role,
            ),
        )
        return _SourceSelection(
            SourceAuditStatus.ELIGIBLE,
            None,
            selected,
            _rejected_ids(candidates, selected.document_id),
        )

    for failure_status in _FAILURE_PRIORITY:
        failures = tuple(
            (candidate, reason)
            for candidate, status, reason in dispositions
            if status is failure_status
        )
        if failures:
            selected, reason_code = min(
                failures,
                key=lambda item: (
                    item[1],
                    _candidate_precedence_key(
                        item[0],
                        required_role=target.required_role,
                    ),
                ),
            )
            return _SourceSelection(
                failure_status,
                reason_code,
                selected,
                _rejected_ids(candidates, selected.document_id),
            )
    raise AssertionError("source candidate disposition is incomplete")


def _candidate_disposition(
    candidate: DocumentSourceCandidate,
    *,
    cutoff_date: date,
) -> tuple[SourceAuditStatus, str | None]:
    if candidate.published_at is None or candidate.available_at is None:
        return SourceAuditStatus.VERSION_UNKNOWN, "cutoff_timing_not_verified"
    if source_timestamp_is_after_cutoff(
        candidate.published_at,
        cutoff_date,
    ) or source_timestamp_is_after_cutoff(candidate.available_at, cutoff_date):
        return SourceAuditStatus.AFTER_CUTOFF_ONLY, "after_cutoff_only"
    if (
        candidate.document_version is None
        or candidate.effective_from is None
        or candidate.effective_from > cutoff_date
        or (
            candidate.effective_to is not None
            and candidate.effective_to < cutoff_date
        )
    ):
        return SourceAuditStatus.VERSION_UNKNOWN, "effective_version_not_verified"
    return SourceAuditStatus.ELIGIBLE, None


def _candidate_provenance_reason(
    candidate: DocumentSourceCandidate,
    *,
    target: DocumentSourceTarget,
    route_key: str,
) -> str | None:
    try:
        approved_publishers = publisher_roles_for_document_role(
            target.required_role,
            target.binding_role,
        )
    except (KeyError, ValueError):
        return "candidate_binding_not_approved"
    if candidate.publisher_role not in approved_publishers:
        return "publisher_role_not_approved"

    if route_key in {"DART", "SEC"}:
        if candidate.source_code != route_key:
            return f"{route_key.lower()}_candidate_source_mismatch"
        if (
            candidate.authority_tier
            is not SourceAuthorityTier.TIER_1_REGULATORY
            or candidate.publisher_role is not PublisherRole.REGULATOR_DISCLOSURE
        ):
            return f"{route_key.lower()}_candidate_authority_mismatch"
        return None

    if route_key == "REGISTERED":
        if (
            candidate.authority_tier is SourceAuthorityTier.TIER_2_CLAIM_OWNER
            and candidate.publisher_role in _TIER_2_PUBLISHERS
        ):
            return None
        if (
            candidate.authority_tier
            is SourceAuthorityTier.TIER_3_EXCHANGE_ASSOCIATION
            and candidate.publisher_role in _TIER_3_PUBLISHERS
        ):
            return None
        return "registered_candidate_authority_mismatch"
    return "candidate_source_owner_unverified"


def _route_key(target: DocumentSourceTarget) -> str:
    if target.required_role in _REGISTERED_ROLES:
        return "REGISTERED"
    if target.product_family in {"domestic_etf", "public_fund"}:
        return "DART"
    if (
        target.product_family == "overseas_etf"
        and target.required_role is DocumentRole.PRODUCT_SUMMARY
    ):
        return "SEC" if has_complete_sec_identity(target) else "REGISTERED"
    return "NOT_APPLICABLE"


def _target_binding_is_valid(target: DocumentSourceTarget) -> bool:
    try:
        return target.binding_role in binding_roles_for_document_role(
            target.required_role
        )
    except KeyError:
        return False


def _adapter_result_is_valid(result: object) -> bool:
    if not isinstance(result, SourceAdapterResult):
        return False
    if not isinstance(result.status, SourceAuditStatus):
        return False
    if not isinstance(result.candidates, tuple) or not all(
        isinstance(candidate, DocumentSourceCandidate)
        for candidate in result.candidates
    ):
        return False
    reason_is_stable = (
        isinstance(result.reason_code, str)
        and _STABLE_REASON.fullmatch(result.reason_code) is not None
    )
    if result.status is SourceAuditStatus.ELIGIBLE:
        return result.reason_code is None and bool(result.candidates)
    return reason_is_stable and not result.candidates


def _candidate_precedence_key(
    candidate: DocumentSourceCandidate,
    *,
    required_role: DocumentRole,
) -> tuple[object, ...]:
    summary_rank = 0
    if required_role is DocumentRole.PRODUCT_SUMMARY:
        summary_rank = 0 if candidate.document_type == "summary_prospectus" else 1
    effective_rank = (
        -candidate.effective_from.toordinal()
        if candidate.effective_from is not None
        else 0
    )
    published_rank = (
        -candidate.published_at.timestamp()
        if candidate.published_at is not None
        else 0
    )
    return (summary_rank, effective_rank, published_rank, candidate.document_id)


def _rejected_ids(
    candidates: tuple[DocumentSourceCandidate, ...],
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
