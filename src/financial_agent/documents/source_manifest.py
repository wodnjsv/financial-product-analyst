from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qsl, urlparse

from .models import DocumentRole, PublisherRole
from .policy import (
    binding_roles_for_document_role,
    document_types_for_role,
    publisher_roles_for_document_role,
)


_CUTOFF_DATE = date(2026, 8, 24)
_ASIA_SEOUL = timezone(timedelta(hours=9))
_PUBLIC_QUERY_KEYS = frozenset({"rcpNo", "CIK", "accession_number"})
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]*$")


class SourceAuthorityTier(str, Enum):
    TIER_1_REGULATORY = "tier_1_regulatory"
    TIER_2_CLAIM_OWNER = "tier_2_claim_owner"
    TIER_3_EXCHANGE_ASSOCIATION = "tier_3_exchange_association"


class SourceAuditStatus(str, Enum):
    ELIGIBLE = "eligible"
    NOT_APPLICABLE_CURRENT_SCOPE = "not_applicable_current_scope"
    DOCUMENT_NOT_FOUND = "document_not_found"
    IDENTIFIER_MISSING = "identifier_missing"
    AMBIGUOUS_ENTITY_BINDING = "ambiguous_entity_binding"
    CREDENTIALS_MISSING = "credentials_missing"
    ACCESS_DENIED = "access_denied"
    RATE_LIMITED = "rate_limited"
    ACCESS_METHOD_UNVERIFIED = "access_method_unverified"
    TERMS_REVIEW_REQUIRED = "terms_review_required"
    AFTER_CUTOFF_ONLY = "after_cutoff_only"
    VERSION_UNKNOWN = "version_unknown"
    MEDIA_TYPE_UNSUPPORTED = "media_type_unsupported"


@dataclass(frozen=True, slots=True)
class DocumentSourceTarget:
    dataset_version: str
    entity_id: str
    entity_type: str
    canonical_name: str
    product_family: str | None
    required_role: DocumentRole
    binding_role: str
    identifiers: tuple[tuple[str, str], ...]
    cutoff_date: date

    def __post_init__(self) -> None:
        _require_text(self.dataset_version, "dataset_version")
        _require_text(self.entity_id, "entity_id")
        _require_text(self.entity_type, "entity_type")
        _require_text(self.canonical_name, "canonical_name")
        _require_text(self.binding_role, "binding_role")
        if self.product_family is not None:
            _require_text(self.product_family, "product_family")
        if self.cutoff_date != _CUTOFF_DATE:
            raise ValueError("document source cutoff must be 2026-08-24")
        _validate_identifiers(self.identifiers)


@dataclass(frozen=True, slots=True)
class DocumentSourceCandidate:
    document_id: str
    source_code: str
    authority_tier: SourceAuthorityTier
    publisher_code: str
    publisher_role: PublisherRole
    document_type: str
    document_version: str | None
    source_locator: str
    discovery_locator: str
    jurisdiction: str
    original_language: str
    published_at: datetime | None
    available_at: datetime | None
    effective_from: date | None
    effective_to: date | None
    media_type: str | None
    accession_or_receipt_id: str | None

    def __post_init__(self) -> None:
        validate_document_source_candidate(self)


def validate_document_source_candidate(candidate: DocumentSourceCandidate) -> None:
    """Deep-validate typed source metadata, including untrusted adapter output."""

    if not isinstance(candidate, DocumentSourceCandidate):
        raise ValueError("source candidate type is invalid")
    if not isinstance(candidate.authority_tier, SourceAuthorityTier):
        raise ValueError("authority_tier must be an approved source authority tier")
    if not isinstance(candidate.publisher_role, PublisherRole):
        raise ValueError("publisher_role must be an approved publisher role")
    for value, name in (
        (candidate.document_id, "document_id"),
        (candidate.source_code, "source_code"),
        (candidate.publisher_code, "publisher_code"),
        (candidate.document_type, "document_type"),
        (candidate.jurisdiction, "jurisdiction"),
        (candidate.original_language, "original_language"),
    ):
        _require_text(value, name)
    for value, name in (
        (candidate.document_version, "document_version"),
        (candidate.media_type, "media_type"),
        (candidate.accession_or_receipt_id, "accession_or_receipt_id"),
    ):
        if value is not None:
            _require_text(value, name)
    _validate_locator(candidate.source_locator)
    _validate_locator(candidate.discovery_locator)
    _validate_timestamp(candidate.published_at, "published_at")
    _validate_timestamp(candidate.available_at, "available_at")
    _validate_date(candidate.effective_from, "effective_from")
    _validate_date(candidate.effective_to, "effective_to")
    if (
        candidate.effective_from is not None
        and candidate.effective_to is not None
        and candidate.effective_to < candidate.effective_from
    ):
        raise ValueError("effective_to precedes effective_from")


@dataclass(frozen=True, slots=True)
class DocumentSourceAuditEntry:
    target: DocumentSourceTarget
    status: SourceAuditStatus
    reason_code: str | None
    candidate: DocumentSourceCandidate | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, SourceAuditStatus):
            raise ValueError("audit entry status must be an approved status")
        if self.reason_code is not None:
            _require_text(self.reason_code, "reason_code")
            if _REASON_CODE.fullmatch(self.reason_code) is None:
                raise ValueError("reason_code must be a stable code")
        if self.status is SourceAuditStatus.ELIGIBLE:
            if self.candidate is None or self.reason_code is not None:
                raise ValueError("eligible audit entry requires only a candidate")
            return
        if self.candidate is None and self.reason_code is None:
            raise ValueError(
                "unavailable audit entry requires a stable reason without candidate"
            )


@dataclass(frozen=True, slots=True)
class DocumentSourceAuditReport:
    schema_version: str
    generated_at: datetime
    cutoff_date: date
    dataset_version: str
    entries: tuple[DocumentSourceAuditEntry, ...]


def validate_document_source_report(report: DocumentSourceAuditReport) -> str:
    if report.schema_version != "1.0":
        raise ValueError("document source report schema_version must be 1.0")
    _require_text(report.dataset_version, "dataset_version")
    _validate_timestamp(report.generated_at)
    if report.cutoff_date != _CUTOFF_DATE:
        raise ValueError("document source report cutoff must be 2026-08-24")

    target_keys: set[tuple[str, str, str]] = set()
    for entry in report.entries:
        target = entry.target
        if target.dataset_version != report.dataset_version:
            raise ValueError("audit target dataset_version differs from report")
        if target.cutoff_date != report.cutoff_date:
            raise ValueError("audit target cutoff differs from report")
        key = (target.dataset_version, target.entity_id, target.required_role.value)
        if key in target_keys:
            raise ValueError("duplicate audit target role")
        target_keys.add(key)
        if _is_domestic_bond(target):
            if entry.status is SourceAuditStatus.ELIGIBLE:
                raise ValueError("domestic bond cannot be eligible in the current scope")
        elif entry.status is SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE:
            raise ValueError("not_applicable is reserved for domestic bonds")
        if entry.status is SourceAuditStatus.ELIGIBLE:
            _validate_eligible_candidate(
                target,
                entry.candidate,
                report.cutoff_date,
            )

    payload = _canonical_report_bytes(report)
    return hashlib.sha256(payload).hexdigest()


def write_document_source_report(
    report: DocumentSourceAuditReport, destination: Path
) -> str:
    report_hash = validate_document_source_report(report)
    payload = _canonical_report_bytes(report)
    temporary_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".document-source-audit-",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return report_hash


def _canonical_report_bytes(report: DocumentSourceAuditReport) -> bytes:
    return json.dumps(
        {
            "cutoff_date": report.cutoff_date.isoformat(),
            "dataset_version": report.dataset_version,
            "entries": [
                _entry_mapping(entry)
                for entry in sorted(
                    report.entries,
                    key=lambda item: (
                        item.target.entity_type,
                        item.target.entity_id,
                        item.target.required_role.value,
                    ),
                )
            ],
            "generated_at": _datetime_text(report.generated_at),
            "schema_version": report.schema_version,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _entry_mapping(entry: DocumentSourceAuditEntry) -> dict[str, object]:
    return {
        "candidate": (
            _candidate_mapping(entry.candidate)
            if entry.candidate is not None
            else None
        ),
        "reason_code": entry.reason_code,
        "status": entry.status.value,
        "target": {
            "binding_role": entry.target.binding_role,
            "canonical_name": entry.target.canonical_name,
            "cutoff_date": entry.target.cutoff_date.isoformat(),
            "dataset_version": entry.target.dataset_version,
            "entity_id": entry.target.entity_id,
            "entity_type": entry.target.entity_type,
            "identifiers": [
                {"scheme": scheme, "value": value}
                for scheme, value in sorted(entry.target.identifiers)
            ],
            "product_family": entry.target.product_family,
            "required_role": entry.target.required_role.value,
        },
    }


def _candidate_mapping(candidate: DocumentSourceCandidate) -> dict[str, object]:
    return {
        "accession_or_receipt_id": candidate.accession_or_receipt_id,
        "authority_tier": candidate.authority_tier.value,
        "available_at": _datetime_text(candidate.available_at),
        "discovery_locator": candidate.discovery_locator,
        "document_id": candidate.document_id,
        "document_type": candidate.document_type,
        "document_version": candidate.document_version,
        "effective_from": _date_text(candidate.effective_from),
        "effective_to": _date_text(candidate.effective_to),
        "jurisdiction": candidate.jurisdiction,
        "media_type": candidate.media_type,
        "original_language": candidate.original_language,
        "published_at": _datetime_text(candidate.published_at),
        "publisher_code": candidate.publisher_code,
        "publisher_role": candidate.publisher_role.value,
        "source_code": candidate.source_code,
        "source_locator": candidate.source_locator,
    }


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _validate_identifiers(identifiers: tuple[tuple[str, str], ...]) -> None:
    normalized: set[tuple[str, str]] = set()
    for item in identifiers:
        if len(item) != 2:
            raise ValueError("identifier must contain a scheme and value")
        scheme, value = item
        _require_text(scheme, "identifier scheme")
        _require_text(value, "identifier value")
        if (scheme, value) in normalized:
            raise ValueError("duplicate identifier")
        normalized.add((scheme, value))


def _validate_timestamp(value: datetime | None, field_name: str = "timestamp") -> None:
    if value is not None and not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must include a timezone")


def _validate_date(value: date | None, field_name: str) -> None:
    if value is not None and (
        not isinstance(value, date) or isinstance(value, datetime)
    ):
        raise ValueError(f"{field_name} must be a date")


def _validate_locator(locator: str) -> None:
    _require_text(locator, "locator")
    parsed = urlparse(locator)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "#" in locator
        or ";" in parsed.query
    ):
        raise ValueError("document source locator is unsafe")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("document source locator is unsafe") from error
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if key not in _PUBLIC_QUERY_KEYS:
            raise ValueError("document source locator is unsafe")


def _is_domestic_bond(target: DocumentSourceTarget) -> bool:
    return (
        target.product_family == "domestic_bond"
        or target.entity_type == "domestic_bond"
    )


def _validate_eligible_candidate(
    target: DocumentSourceTarget,
    candidate: DocumentSourceCandidate | None,
    cutoff_date: date,
) -> None:
    if candidate is None:
        raise ValueError("eligible audit entry requires a candidate")
    validate_document_source_candidate(candidate)
    if target.binding_role not in binding_roles_for_document_role(
        target.required_role
    ):
        raise ValueError("eligible candidate binding is incompatible with role")
    if candidate.document_type not in document_types_for_role(
        target.required_role
    ):
        raise ValueError("eligible candidate document type is incompatible with role")
    if candidate.publisher_role not in publisher_roles_for_document_role(
        target.required_role,
        target.binding_role,
    ):
        raise ValueError("eligible candidate publisher is not approved for role")
    if not _authority_matches_publisher(candidate):
        raise ValueError("eligible candidate authority tier does not match publisher")
    timestamps = (candidate.published_at, candidate.available_at)
    if any(value is None for value in timestamps):
        raise ValueError("eligible candidate timing is missing")
    if any(
        source_timestamp_is_after_cutoff(value, cutoff_date)
        for value in timestamps
        if value
    ):
        raise ValueError("eligible candidate is after the approved cutoff")
    if (
        candidate.document_version is None
        or candidate.effective_from is None
        or candidate.effective_from > cutoff_date
        or (
            candidate.effective_to is not None
            and candidate.effective_to < cutoff_date
        )
    ):
        raise ValueError("eligible candidate effective version is not verified")


def _authority_matches_publisher(candidate: DocumentSourceCandidate) -> bool:
    if candidate.authority_tier is SourceAuthorityTier.TIER_1_REGULATORY:
        return candidate.publisher_role is PublisherRole.REGULATOR_DISCLOSURE
    if candidate.authority_tier is SourceAuthorityTier.TIER_2_CLAIM_OWNER:
        return candidate.publisher_role in {
            PublisherRole.INDEX_PROVIDER,
            PublisherRole.POLICY_AUTHORITY,
            PublisherRole.POLICY_OPERATOR,
        }
    return candidate.publisher_role in {
        PublisherRole.EXCHANGE,
        PublisherRole.INDUSTRY_ASSOCIATION,
    }


def source_timestamp_is_after_cutoff(
    value: datetime,
    cutoff_date: date,
) -> bool:
    """Return whether an aware source timestamp falls after the Seoul cutoff day."""

    return value.astimezone(_ASIA_SEOUL).date() > cutoff_date
