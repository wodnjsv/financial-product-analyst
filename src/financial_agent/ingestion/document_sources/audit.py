"""Deterministic no-fallback coordination for official document discovery."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
import logging
import re
from urllib.parse import parse_qsl, urlparse

from financial_agent.documents import (
    DocumentRole,
    DocumentSourceAuditEntry,
    DocumentSourceAuditReport,
    DocumentSourceCandidate,
    DocumentSourceAttempt,
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
    validate_document_source_candidate,
)

from .base import (
    DocumentDiscoveryContext,
    DocumentSourceAccessError,
    DocumentSourceAdapter,
    SourceAdapterResult,
    classify_access_error,
    sanitize_public_locator,
)
from .sec import has_complete_sec_identity
from .registered import ReviewedAuthorityContext, ReviewedLocator


_LOGGER = logging.getLogger(__name__)
_STABLE_REASON = re.compile(r"^[a-z][a-z0-9_]*$")
_REGISTERED_ROLES = frozenset(
    {
        DocumentRole.INDEX_METHODOLOGY,
        DocumentRole.OFFICIAL_UPDATE,
        DocumentRole.POLICY_BASE,
    }
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
    context = _prepare_registered_context(adapter_registry, context)
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


def document_source_audit_passed(
    report: DocumentSourceAuditReport,
    *,
    registered_authorities: ReviewedAuthorityContext | None = None,
) -> bool:
    """Return whether all entries are valid source-metadata dispositions."""

    if registered_authorities is not None and not isinstance(
        registered_authorities, ReviewedAuthorityContext
    ):
        return False
    try:
        validate_document_source_report(report)
    except (DocumentSourceAccessError, TypeError, ValueError):
        return False
    if not report.entries:
        return False
    for entry in report.entries:
        route_key = _route_key(entry.target)
        if entry.attempted_source is not None and _validated_attempted_source(
            entry.attempted_source,
            target=entry.target,
            route_key=route_key,
            registered_authorities=registered_authorities,
        ) != entry.attempted_source:
            return False
        if entry.status not in _COMPLETE_STATUSES:
            return False
        if entry.status is SourceAuditStatus.ELIGIBLE:
            candidate = entry.candidate
            if (
                candidate is None
                or route_key == "NOT_APPLICABLE"
                or _candidate_provenance_reason(
                    candidate,
                    target=entry.target,
                    route_key=route_key,
                    registered_authorities=registered_authorities,
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
            attempted_source=_attempt_for_route(_route_key(target)),
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
            attempted_source=_attempt_for_route(_route_key(target)),
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
            attempted_source=_attempt_for_route(route_key),
        )
    if len(route_adapters) != 1:
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_adapter_registration_ambiguous",
            attempted_source=_attempt_for_route(route_key),
        )

    adapter = route_adapters[0]
    registered_authorities: ReviewedAuthorityContext | None = None
    if route_key == "REGISTERED":
        value = context.registered_authorities
        if value is None:
            value = getattr(adapter, "reviewed_authorities", None)
        if not isinstance(value, ReviewedAuthorityContext):
            return _unavailable_entry(
                target,
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "registered_authority_context_missing",
                attempted_source=_attempt_for_route(route_key),
            )
        registered_authorities = value
    try:
        if adapter.supports(target) is not True:
            return _unavailable_entry(
                target,
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                f"{route_key.lower()}_target_not_supported",
                attempted_source=_attempt_for_route(route_key),
            )
        result = adapter.discover(target, context)
    except Exception as error:
        status = classify_access_error(error)
        return _unavailable_entry(
            target,
            status,
            f"{route_key.lower()}_{status.value}",
            attempted_source=_attempt_for_route(route_key),
        )
    return _entry_from_result(
        target,
        result,
        route_key=route_key,
        registered_authorities=registered_authorities,
    )


def _entry_from_result(
    target: DocumentSourceTarget,
    result: object,
    *,
    route_key: str,
    registered_authorities: ReviewedAuthorityContext | None,
) -> DocumentSourceAuditEntry:
    if not _adapter_result_is_valid(result):
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_adapter_result_invalid",
            attempted_source=_attempt_for_route(route_key),
        )
    assert isinstance(result, SourceAdapterResult)
    attempted_source = _validated_attempted_source(
        result.attempted_source,
        target=target,
        route_key=route_key,
        registered_authorities=registered_authorities,
    )
    if result.attempted_source is not None and attempted_source is None:
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_attempted_source_invalid",
            attempted_source=_attempt_for_route(route_key),
        )
    if attempted_source is None:
        attempted_source = _attempt_for_route(route_key)
    if result.status is SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE:
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_target_not_supported",
            attempted_source=attempted_source,
        )
    if result.status is not SourceAuditStatus.ELIGIBLE:
        assert result.reason_code is not None
        return _unavailable_entry(
            target,
            result.status,
            result.reason_code,
            attempted_source=attempted_source,
        )

    candidates = tuple(sorted(result.candidates, key=_source_candidate_key))
    document_ids = [candidate.document_id for candidate in candidates]
    if len(document_ids) != len(set(document_ids)):
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            f"{route_key.lower()}_duplicate_document_id",
            attempted_source=attempted_source,
        )
    provenance_reasons = tuple(
        reason
        for candidate in candidates
        if (
            reason := _candidate_provenance_reason(
                candidate,
                target=target,
                route_key=route_key,
                registered_authorities=registered_authorities,
            )
        )
        is not None
    )
    if provenance_reasons:
        return _unavailable_entry(
            target,
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            min(provenance_reasons),
            attempted_source=attempted_source,
        )

    selection = _select_source_candidate(candidates, target=target)
    if selection.rejected_document_ids:
        _LOGGER.debug(
            "official source candidates rejected target=%s role=%s ids=%s",
            target.entity_id,
            target.required_role.value,
            selection.rejected_document_ids,
        )
    selection_attempt = None
    if selection.status is not SourceAuditStatus.ELIGIBLE:
        selection_attempt = (
            _attempt_from_candidate(selection.candidate)
            if selection.candidate is not None
            else attempted_source
        )
    return DocumentSourceAuditEntry(
        target=target,
        status=selection.status,
        reason_code=selection.reason_code,
        candidate=selection.candidate,
        attempted_source=selection_attempt,
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
    registered_authorities: ReviewedAuthorityContext | None,
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
        if route_key == "DART":
            return _dart_candidate_provenance_reason(candidate, target=target)
        return _sec_candidate_provenance_reason(candidate, target=target)

    if route_key == "REGISTERED":
        if registered_authorities is None:
            return "registered_authority_context_missing"
        authority = registered_authorities.authority_for(candidate.source_code)
        if (
            authority is None
            or candidate.publisher_code != authority.publisher_code
        ):
            return "registered_candidate_authority_unreviewed"
        if (
            candidate.authority_tier is not authority.authority_tier
            or candidate.publisher_role is not authority.publisher_role
            or candidate.jurisdiction != authority.jurisdiction
        ):
            return "registered_candidate_authority_mismatch"
        if target.required_role not in authority.allowed_document_roles:
            return "registered_candidate_role_not_reviewed"
        if authority.terms_review_required:
            return "registered_candidate_terms_review_required"
        locator = registered_authorities.locator_for(
            target.entity_id,
            target.required_role,
        )
        if locator is None:
            return "registered_candidate_locator_unreviewed"
        if (
            locator.entity_type != target.entity_type
            or locator.binding_role != target.binding_role
        ):
            return "registered_candidate_locator_unreviewed"
        if (
            not _locator_uses_allowed_host(
                locator.source_locator,
                authority.allowed_hosts,
            )
            or not _locator_uses_allowed_host(
                locator.discovery_locator,
                authority.allowed_hosts,
            )
        ):
            return "registered_candidate_locator_host_not_allowed"
        if not _candidate_matches_reviewed_locator(candidate, locator):
            return "registered_candidate_locator_mismatch"
        return None
    return "candidate_source_owner_unverified"


_DART_RECEIPT = re.compile(r"^[0-9]{14}$")
_SEC_ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
_SEC_COMPACT_ACCESSION = re.compile(r"^[0-9]{18}$")
_SEC_PRIMARY_DOCUMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


def _dart_candidate_provenance_reason(
    candidate: DocumentSourceCandidate,
    *,
    target: DocumentSourceTarget,
) -> str | None:
    receipt = candidate.accession_or_receipt_id
    if (
        candidate.publisher_code != "FSS_DART"
        or candidate.jurisdiction != "KR"
        or not isinstance(receipt, str)
        or _DART_RECEIPT.fullmatch(receipt) is None
        or candidate.document_id != f"dart-rcept:{receipt}"
        or candidate.document_version != receipt
    ):
        return "dart_candidate_identity_mismatch"
    if candidate.target_entity_id != target.entity_id:
        return "dart_candidate_target_mismatch"
    if not _dart_viewer_locator_matches(candidate.source_locator, receipt=receipt):
        return "dart_candidate_locator_mismatch"
    if not _exact_https_locator(
        candidate.discovery_locator,
        host="opendart.fss.or.kr",
        path="/api/document.xml",
    ):
        return "dart_candidate_locator_mismatch"
    return None


def _sec_candidate_provenance_reason(
    candidate: DocumentSourceCandidate,
    *,
    target: DocumentSourceTarget,
) -> str | None:
    accession = candidate.accession_or_receipt_id
    cik = _target_sec_cik(target)
    if (
        candidate.publisher_code != "US_SEC_EDGAR"
        or candidate.jurisdiction != "US"
        or cik is None
        or not isinstance(accession, str)
        or _SEC_ACCESSION.fullmatch(accession) is None
        or candidate.document_id != f"sec-accession:{accession}"
        or candidate.document_version != accession
    ):
        return "sec_candidate_identity_mismatch"
    if candidate.target_entity_id != target.entity_id:
        return "sec_candidate_target_mismatch"
    compact_accession = accession.replace("-", "")
    if _sec_archive_document_identity(
        candidate.source_locator,
        cik=cik,
    ) != compact_accession:
        return "sec_candidate_locator_mismatch"
    if _sec_archive_index_identity(
        candidate.discovery_locator,
        cik=cik,
    ) != compact_accession:
        return "sec_candidate_locator_mismatch"
    return None


def _target_sec_cik(target: DocumentSourceTarget) -> str | None:
    values = tuple(
        value for scheme, value in target.identifiers if scheme == "SEC_CIK"
    )
    if len(values) != 1 or not values[0].isdigit() or int(values[0]) == 0:
        return None
    return str(int(values[0]))


def _sec_archive_document_identity(locator: str, *, cik: str) -> str | None:
    parts = _https_parts(locator)
    if parts is None:
        return None
    host, path, query = parts
    prefix = f"/Archives/edgar/data/{cik}/"
    remainder = path[len(prefix) :] if path.startswith(prefix) else ""
    segments = remainder.split("/")
    if len(segments) != 2:
        return None
    compact_accession, primary_document = segments
    if (
        host != "www.sec.gov"
        or query
        or _SEC_COMPACT_ACCESSION.fullmatch(compact_accession) is None
        or _SEC_PRIMARY_DOCUMENT.fullmatch(primary_document) is None
    ):
        return None
    return compact_accession


def _sec_archive_index_identity(locator: str, *, cik: str) -> str | None:
    parts = _https_parts(locator)
    if parts is None:
        return None
    host, path, query = parts
    prefix = f"/Archives/edgar/data/{cik}/"
    remainder = path[len(prefix) :] if path.startswith(prefix) else ""
    segments = remainder.split("/")
    if len(segments) != 2:
        return None
    compact_accession, filename = segments
    suffix = "-index.html"
    accession = filename[: -len(suffix)] if filename.endswith(suffix) else ""
    if (
        host != "www.sec.gov"
        or query
        or _SEC_COMPACT_ACCESSION.fullmatch(compact_accession) is None
        or _SEC_ACCESSION.fullmatch(accession) is None
        or accession.replace("-", "") != compact_accession
    ):
        return None
    return compact_accession


def _dart_viewer_locator_matches(locator: str, *, receipt: str) -> bool:
    parts = _https_parts(locator)
    return parts == (
        "dart.fss.or.kr",
        "/dsaf001/main.do",
        (("rcpNo", receipt),),
    )


def _exact_https_locator(locator: str, *, host: str, path: str) -> bool:
    return _https_parts(locator) == (host, path, ())


def _https_parts(
    locator: str,
) -> tuple[str, str, tuple[tuple[str, str], ...]] | None:
    try:
        parsed = urlparse(locator)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        return None
    return (
        parsed.hostname.lower(),
        parsed.path,
        tuple(parse_qsl(parsed.query, keep_blank_values=True)),
    )


def _locator_uses_allowed_host(
    locator: str,
    allowed_hosts: frozenset[str],
) -> bool:
    try:
        sanitize_public_locator(locator, allowed_hosts=allowed_hosts)
        parsed = urlparse(locator)
        return parsed.port in {None, 443}
    except (DocumentSourceAccessError, TypeError, ValueError):
        return False


def _candidate_matches_reviewed_locator(
    candidate: DocumentSourceCandidate,
    locator: ReviewedLocator,
) -> bool:
    try:
        reviewed_candidate = DocumentSourceCandidate(
            document_id=locator.document_id,
            source_code=locator.source_code,
            authority_tier=locator.authority_tier,
            publisher_code=locator.publisher_code,
            publisher_role=locator.publisher_role,
            document_type=locator.document_type,
            document_version=locator.document_version,
            source_locator=locator.source_locator,
            discovery_locator=locator.discovery_locator,
            jurisdiction=locator.jurisdiction,
            original_language=locator.original_language,
            published_at=locator.published_at,
            available_at=locator.available_at,
            effective_from=locator.effective_from,
            effective_to=locator.effective_to,
            media_type=locator.media_type,
            accession_or_receipt_id=locator.accession_or_receipt_id,
        )
    except (TypeError, ValueError):
        return False
    return candidate == reviewed_candidate


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
    if not isinstance(result.candidates, tuple):
        return False
    if result.attempted_source is not None and not isinstance(
        result.attempted_source, DocumentSourceAttempt
    ):
        return False
    try:
        for candidate in result.candidates:
            validate_document_source_candidate(candidate)
    except (AttributeError, TypeError, ValueError):
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


def _prepare_registered_context(
    adapter_registry: dict[str, tuple[DocumentSourceAdapter, ...]],
    context: DocumentDiscoveryContext,
) -> DocumentDiscoveryContext:
    if context.registered_authorities is not None:
        return context
    registered = adapter_registry.get("REGISTERED", ())
    if len(registered) != 1:
        return context
    adapter = registered[0]
    loader = getattr(adapter, "reviewed_context", None)
    try:
        value = loader(context) if callable(loader) else getattr(
            adapter,
            "reviewed_authorities",
            None,
        )
    except (OSError, UnicodeDecodeError, ValueError):
        return context
    if not isinstance(value, ReviewedAuthorityContext):
        return context
    return replace(context, registered_authorities=value)


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
        target.canonical_name or "",
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
    *,
    attempted_source: DocumentSourceAttempt | None = None,
) -> DocumentSourceAuditEntry:
    return DocumentSourceAuditEntry(
        target=target,
        status=status,
        reason_code=reason_code,
        candidate=None,
        attempted_source=attempted_source,
    )


def _attempt_for_route(route_key: str) -> DocumentSourceAttempt | None:
    if route_key not in {"DART", "SEC", "REGISTERED"}:
        return None
    return DocumentSourceAttempt(
        source_code=route_key,
        source_locator=None,
        discovery_locator=None,
    )


def _attempt_from_candidate(
    candidate: DocumentSourceCandidate,
) -> DocumentSourceAttempt:
    return DocumentSourceAttempt(
        source_code=candidate.source_code,
        source_locator=candidate.source_locator,
        discovery_locator=candidate.discovery_locator,
    )


def _validated_attempted_source(
    attempt: DocumentSourceAttempt | None,
    *,
    target: DocumentSourceTarget,
    route_key: str,
    registered_authorities: ReviewedAuthorityContext | None,
) -> DocumentSourceAttempt | None:
    if attempt is None:
        return None
    if route_key == "DART":
        return attempt if _dart_attempt_is_valid(attempt) else None
    if route_key == "SEC":
        return attempt if _sec_attempt_is_valid(attempt, target=target) else None
    if route_key != "REGISTERED":
        return None
    if attempt.source_code == "REGISTERED":
        return (
            attempt
            if attempt.source_locator is None
            and attempt.discovery_locator is None
            else None
        )
    if registered_authorities is None:
        return None
    authority = registered_authorities.authority_for(attempt.source_code)
    if authority is None:
        return None
    if attempt.source_locator is None and attempt.discovery_locator is None:
        return attempt
    locator = registered_authorities.locator_for(
        target.entity_id,
        target.required_role,
    )
    if (
        locator is None
        or locator.source_code != attempt.source_code
        or locator.entity_type != target.entity_type
        or locator.binding_role != target.binding_role
        or attempt.source_locator != locator.source_locator
        or attempt.discovery_locator != locator.discovery_locator
        or not _locator_uses_allowed_host(
            locator.source_locator,
            authority.allowed_hosts,
        )
        or not _locator_uses_allowed_host(
            locator.discovery_locator,
            authority.allowed_hosts,
        )
    ):
        return None
    return attempt


def _dart_attempt_is_valid(attempt: DocumentSourceAttempt) -> bool:
    if attempt.source_code != "DART":
        return False
    if attempt.source_locator is None and attempt.discovery_locator is None:
        return True
    if attempt.source_locator is not None:
        parts = _https_parts(attempt.source_locator)
        if parts is None:
            return False
        host, path, query = parts
        if (
            host != "dart.fss.or.kr"
            or path != "/dsaf001/main.do"
            or len(query) != 1
            or query[0][0] != "rcpNo"
            or _DART_RECEIPT.fullmatch(query[0][1]) is None
        ):
            return False
    if attempt.discovery_locator is not None and not any(
        _exact_https_locator(
            attempt.discovery_locator,
            host="opendart.fss.or.kr",
            path=path,
        )
        for path in ("/api/list.json", "/api/document.xml")
    ):
        return False
    return True


def _sec_attempt_is_valid(
    attempt: DocumentSourceAttempt,
    *,
    target: DocumentSourceTarget,
) -> bool:
    if attempt.source_code != "SEC":
        return False
    if attempt.source_locator is None and attempt.discovery_locator is None:
        return True
    cik = _target_sec_cik(target)
    if cik is None:
        return False
    padded_cik = cik.zfill(10)
    source_identity = None
    if attempt.source_locator is not None:
        source_identity = _sec_archive_document_identity(
            attempt.source_locator,
            cik=cik,
        )
        if source_identity is None:
            return False
    if attempt.discovery_locator is not None:
        if _exact_https_locator(
            attempt.discovery_locator,
            host="data.sec.gov",
            path=f"/submissions/CIK{padded_cik}.json",
        ):
            return source_identity is None
        discovery_identity = _sec_archive_index_identity(
            attempt.discovery_locator,
            cik=cik,
        )
        if discovery_identity is None or (
            source_identity is not None
            and discovery_identity != source_identity
        ):
            return False
    return True


def _is_domestic_bond(target: DocumentSourceTarget) -> bool:
    return (
        target.product_family == "domestic_bond"
        or target.entity_type == "domestic_bond"
    )
