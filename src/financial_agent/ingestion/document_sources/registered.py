"""Fail-closed preflight for manually reviewed Tier 2 and Tier 3 locators."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import BinaryIO
from urllib.parse import urljoin, urlparse

from financial_agent.documents import (
    DocumentRole,
    DocumentSourceCandidate,
    DocumentSourceTarget,
    PublisherRole,
    SourceAuditStatus,
    SourceAuthorityTier,
)
from financial_agent.documents.policy import (
    binding_roles_for_document_role,
    document_types_for_role,
    publisher_roles_for_document_role,
)
from financial_agent.documents.source_manifest import (
    source_timestamp_is_after_cutoff,
)

from .base import (
    DocumentDiscoveryContext,
    DocumentSourceAccessError,
    DocumentSourceAccessErrorCode,
    HttpStatusError,
    SourceAdapterResult,
    classify_access_error,
    sanitize_public_locator,
)


_SOURCE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_JURISDICTION = re.compile(r"^[A-Z]{2}$")
_HOST = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)
_LANGUAGE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
_MEDIA_TYPES = frozenset({"application/pdf", "text/html"})
_REQUEST_TIMEOUT_SECONDS = 15.0
_MAX_REDIRECTS = 3
_MAX_REGISTRY_BYTES = 8 * 1024 * 1024

_AUTHORITY_KEYS = frozenset({"schema_version", "authorities"})
_AUTHORITY_RULE_KEYS = frozenset(
    {
        "source_code",
        "authority_tier",
        "publisher_role",
        "jurisdiction",
        "allowed_hosts",
        "allowed_document_roles",
    }
)
_LOCATOR_KEYS = frozenset({"schema_version", "locators"})
_LOCATOR_ENTRY_KEYS = frozenset(
    {
        "entity_id",
        "entity_type",
        "required_role",
        "binding_role",
        "document_id",
        "source_code",
        "authority_tier",
        "publisher_code",
        "publisher_role",
        "source_locator",
        "discovery_locator",
        "document_type",
        "document_version",
        "published_at",
        "available_at",
        "effective_from",
        "effective_to",
        "original_language",
        "jurisdiction",
        "media_type",
        "accession_or_receipt_id",
    }
)
_TIER_PUBLISHERS = {
    SourceAuthorityTier.TIER_2_CLAIM_OWNER: frozenset(
        {
            PublisherRole.INDEX_PROVIDER,
            PublisherRole.POLICY_AUTHORITY,
            PublisherRole.POLICY_OPERATOR,
        }
    ),
    SourceAuthorityTier.TIER_3_EXCHANGE_ASSOCIATION: frozenset(
        {PublisherRole.EXCHANGE, PublisherRole.INDUSTRY_ASSOCIATION}
    ),
}
_PUBLISHER_DOCUMENT_ROLES = {
    PublisherRole.INDEX_PROVIDER: frozenset(
        {DocumentRole.INDEX_METHODOLOGY, DocumentRole.OFFICIAL_UPDATE}
    ),
    PublisherRole.POLICY_AUTHORITY: frozenset(
        {DocumentRole.POLICY_BASE, DocumentRole.OFFICIAL_UPDATE}
    ),
    PublisherRole.POLICY_OPERATOR: frozenset(
        {DocumentRole.POLICY_BASE, DocumentRole.OFFICIAL_UPDATE}
    ),
    PublisherRole.EXCHANGE: frozenset({DocumentRole.OFFICIAL_UPDATE}),
    PublisherRole.INDUSTRY_ASSOCIATION: frozenset(
        {DocumentRole.OFFICIAL_UPDATE}
    ),
}


@dataclass(frozen=True, slots=True)
class ReviewedAuthority:
    """Authority identity and scope loaded from the reviewed registry."""

    source_code: str
    publisher_code: str
    authority_tier: SourceAuthorityTier
    publisher_role: PublisherRole
    jurisdiction: str
    allowed_document_roles: frozenset[DocumentRole]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_code, str)
            or _SOURCE_CODE.fullmatch(self.source_code) is None
            or self.publisher_code != self.source_code
        ):
            raise ValueError("reviewed authority source identity is invalid")
        if self.authority_tier not in _TIER_PUBLISHERS:
            raise ValueError("reviewed authority tier is invalid")
        if self.publisher_role not in _TIER_PUBLISHERS[self.authority_tier]:
            raise ValueError("reviewed authority publisher is invalid")
        if (
            not isinstance(self.jurisdiction, str)
            or _JURISDICTION.fullmatch(self.jurisdiction) is None
        ):
            raise ValueError("reviewed authority jurisdiction is invalid")
        if (
            not isinstance(self.allowed_document_roles, frozenset)
            or not self.allowed_document_roles
            or not all(
                isinstance(role, DocumentRole)
                for role in self.allowed_document_roles
            )
            or not self.allowed_document_roles.issubset(
                _PUBLISHER_DOCUMENT_ROLES[self.publisher_role]
            )
        ):
            raise ValueError("reviewed authority document roles are invalid")


@dataclass(frozen=True, slots=True)
class ReviewedAuthorityContext:
    """Immutable authority snapshot supplied with registered audit evidence."""

    authorities: tuple[ReviewedAuthority, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.authorities, tuple) or not self.authorities:
            raise ValueError("reviewed authority context must be nonempty")
        if not all(isinstance(item, ReviewedAuthority) for item in self.authorities):
            raise ValueError("reviewed authority context contains an invalid authority")
        source_codes = tuple(item.source_code for item in self.authorities)
        if len(source_codes) != len(set(source_codes)):
            raise ValueError("reviewed authority context source_code is duplicated")
        if source_codes != tuple(sorted(source_codes)):
            raise ValueError("reviewed authority context must be canonical")

    def authority_for(self, source_code: str) -> ReviewedAuthority | None:
        return next(
            (
                authority
                for authority in self.authorities
                if authority.source_code == source_code
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class _AuthorityRule:
    source_code: str
    authority_tier: SourceAuthorityTier
    publisher_role: PublisherRole
    jurisdiction: str
    allowed_hosts: frozenset[str]
    allowed_document_roles: frozenset[DocumentRole]
    terms_review_required: bool


@dataclass(frozen=True, slots=True)
class _ReviewedLocator:
    entity_id: str
    entity_type: str
    required_role: DocumentRole
    binding_role: str
    document_id: str
    source_code: str
    authority_tier: SourceAuthorityTier
    publisher_code: str
    publisher_role: PublisherRole
    source_locator: str
    discovery_locator: str
    document_type: str
    document_version: str
    published_at: datetime
    available_at: datetime
    effective_from: date
    effective_to: date | None
    original_language: str
    jurisdiction: str
    media_type: str
    accession_or_receipt_id: str | None


class _RegistryError(Exception):
    pass


class _RegisteredResultError(Exception):
    def __init__(self, status: SourceAuditStatus, reason_code: str) -> None:
        self.status = status
        self.reason_code = reason_code
        super().__init__(reason_code)


class _MalformedResponse(Exception):
    pass


class RegisteredDocumentSourceAdapter:
    """Validate an exact reviewed locator and perform one bounded access probe."""

    source_code = "REGISTERED"

    def __init__(self, opener: object, authority_registry: Path) -> None:
        self._opener = opener
        self._authorities = _load_authority_registry(authority_registry)
        self.reviewed_authorities = _reviewed_authority_context(self._authorities)

    def supports(self, target: DocumentSourceTarget) -> bool:
        if target.required_role not in {
            DocumentRole.INDEX_METHODOLOGY,
            DocumentRole.POLICY_BASE,
            DocumentRole.OFFICIAL_UPDATE,
        }:
            return False
        try:
            allowed_bindings = binding_roles_for_document_role(target.required_role)
        except KeyError:
            return False
        return target.binding_role in allowed_bindings

    def discover(
        self,
        target: DocumentSourceTarget,
        context: DocumentDiscoveryContext,
    ) -> SourceAdapterResult:
        if not self.supports(target):
            return _unavailable(
                SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE,
                "registered_target_not_supported",
            )
        if context.cutoff_date != target.cutoff_date:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "registered_cutoff_mismatch",
            )
        if context.locator_registry_path is None:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "registered_locator_registry_missing",
            )

        try:
            locators = _load_locator_registry(context.locator_registry_path)
        except (
            OSError,
            TypeError,
            ValueError,
            _RegistryError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "registered_locator_registry_invalid",
            )

        locator = locators.get((target.entity_id, target.required_role))
        if locator is None:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "registered_locator_missing",
            )
        authority = self._authorities.get(locator.source_code)
        if authority is None:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "registered_source_code_unknown",
            )

        try:
            _validate_locator_for_target(locator, authority=authority, target=target)
            _validate_cutoff(locator, cutoff_date=context.cutoff_date)
        except _RegisteredResultError as error:
            return _unavailable(error.status, error.reason_code)

        if authority.terms_review_required:
            return _unavailable(
                SourceAuditStatus.TERMS_REVIEW_REQUIRED,
                "registered_terms_review_required",
            )

        try:
            _preflight(
                self._opener,
                locator.source_locator,
                allowed_hosts=authority.allowed_hosts,
                expected_media_type=locator.media_type,
            )
        except _RegisteredResultError as error:
            return _unavailable(error.status, error.reason_code)
        except DocumentSourceAccessError:
            return _unavailable(
                SourceAuditStatus.ACCESS_DENIED,
                "registered_locator_unsafe",
            )
        except _MalformedResponse:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "registered_response_malformed",
            )
        except Exception as error:
            status = classify_access_error(error)
            return _unavailable(status, f"registered_{status.value}")

        return SourceAdapterResult(
            status=SourceAuditStatus.ELIGIBLE,
            reason_code=None,
            candidates=(_candidate(locator),),
        )


def _load_authority_registry(path: Path) -> dict[str, _AuthorityRule]:
    try:
        payload = _read_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("authority_registry is unreadable") from error
    if not isinstance(payload, dict) or set(payload) != _AUTHORITY_KEYS:
        raise ValueError("authority_registry has invalid top-level fields")
    if payload.get("schema_version") != "1.0":
        raise ValueError("authority_registry schema_version must be 1.0")
    entries = payload.get("authorities")
    if not isinstance(entries, list) or not entries:
        raise ValueError("authority_registry authorities must be nonempty")

    authorities: dict[str, _AuthorityRule] = {}
    for entry in entries:
        rule = _parse_authority_rule(entry)
        if rule.source_code in authorities:
            raise ValueError("authority_registry source_code is duplicated")
        authorities[rule.source_code] = rule
    return authorities


def _reviewed_authority_context(
    authorities: dict[str, _AuthorityRule],
) -> ReviewedAuthorityContext:
    return ReviewedAuthorityContext(
        tuple(
            ReviewedAuthority(
                source_code=rule.source_code,
                publisher_code=rule.source_code,
                authority_tier=rule.authority_tier,
                publisher_role=rule.publisher_role,
                jurisdiction=rule.jurisdiction,
                allowed_document_roles=rule.allowed_document_roles,
            )
            for rule in sorted(authorities.values(), key=lambda item: item.source_code)
        )
    )


def _parse_authority_rule(value: object) -> _AuthorityRule:
    if not isinstance(value, dict):
        raise ValueError("authority_registry authority must be an object")
    keys = set(value)
    allowed_keys = _AUTHORITY_RULE_KEYS | {"terms_review_required"}
    if not _AUTHORITY_RULE_KEYS.issubset(keys) or not keys.issubset(allowed_keys):
        raise ValueError("authority_registry authority fields are invalid")

    source_code = _required_text(value, "source_code")
    if _SOURCE_CODE.fullmatch(source_code) is None:
        raise ValueError("authority_registry source_code is invalid")
    authority_tier = _enum_value(
        SourceAuthorityTier, value.get("authority_tier"), "authority_tier"
    )
    if authority_tier not in _TIER_PUBLISHERS:
        raise ValueError("authority_registry authority_tier is not Tier 2 or Tier 3")
    publisher_role = _enum_value(
        PublisherRole, value.get("publisher_role"), "publisher_role"
    )
    if publisher_role not in _TIER_PUBLISHERS[authority_tier]:
        raise ValueError(
            "authority_registry publisher_role does not match authority_tier"
        )
    jurisdiction = _required_text(value, "jurisdiction")
    if _JURISDICTION.fullmatch(jurisdiction) is None:
        raise ValueError("authority_registry jurisdiction is invalid")

    allowed_hosts = _unique_text_list(value.get("allowed_hosts"), "allowed_hosts")
    if any(
        host != host.lower() or _HOST.fullmatch(host) is None
        for host in allowed_hosts
    ):
        raise ValueError("authority_registry allowed_hosts is invalid")
    role_values = _unique_text_list(
        value.get("allowed_document_roles"), "allowed_document_roles"
    )
    try:
        roles = frozenset(DocumentRole(item) for item in role_values)
    except ValueError as error:
        raise ValueError(
            "authority_registry allowed_document_roles is invalid"
        ) from error
    if not roles.issubset(_PUBLISHER_DOCUMENT_ROLES[publisher_role]):
        raise ValueError(
            "authority_registry allowed_document_roles does not match publisher_role"
        )
    terms_review_required = value.get("terms_review_required", False)
    if not isinstance(terms_review_required, bool):
        raise ValueError("authority_registry terms_review_required must be boolean")
    return _AuthorityRule(
        source_code=source_code,
        authority_tier=authority_tier,
        publisher_role=publisher_role,
        jurisdiction=jurisdiction,
        allowed_hosts=frozenset(allowed_hosts),
        allowed_document_roles=roles,
        terms_review_required=terms_review_required,
    )


def _load_locator_registry(
    path: Path,
) -> dict[tuple[str, DocumentRole], _ReviewedLocator]:
    payload = _read_json(path)
    if not isinstance(payload, dict) or set(payload) != _LOCATOR_KEYS:
        raise _RegistryError
    if payload.get("schema_version") != "1.0":
        raise _RegistryError
    entries = payload.get("locators")
    if not isinstance(entries, list):
        raise _RegistryError

    locators: dict[tuple[str, DocumentRole], _ReviewedLocator] = {}
    for value in entries:
        try:
            locator = _parse_reviewed_locator(value)
        except (TypeError, ValueError) as error:
            raise _RegistryError from error
        key = (locator.entity_id, locator.required_role)
        if key in locators:
            raise _RegistryError
        locators[key] = locator
    return locators


def _parse_reviewed_locator(value: object) -> _ReviewedLocator:
    if not isinstance(value, dict) or set(value) != _LOCATOR_ENTRY_KEYS:
        raise _RegistryError
    try:
        required_role = DocumentRole(_required_text(value, "required_role"))
        authority_tier = SourceAuthorityTier(
            _required_text(value, "authority_tier")
        )
        publisher_role = PublisherRole(_required_text(value, "publisher_role"))
        published_at = _datetime_value(value.get("published_at"))
        available_at = _datetime_value(value.get("available_at"))
        effective_from = _date_value(value.get("effective_from"), optional=False)
        effective_to = _date_value(value.get("effective_to"), optional=True)
    except (TypeError, ValueError) as error:
        raise _RegistryError from error
    assert effective_from is not None

    accession = value.get("accession_or_receipt_id")
    if accession is not None and (
        not isinstance(accession, str) or not accession.strip()
    ):
        raise _RegistryError
    media_type = _required_text(value, "media_type")
    if media_type not in _MEDIA_TYPES:
        raise _RegistryError
    language = _required_text(value, "original_language")
    if _LANGUAGE.fullmatch(language) is None:
        raise _RegistryError
    jurisdiction = _required_text(value, "jurisdiction")
    if _JURISDICTION.fullmatch(jurisdiction) is None:
        raise _RegistryError

    return _ReviewedLocator(
        entity_id=_required_text(value, "entity_id"),
        entity_type=_required_text(value, "entity_type"),
        required_role=required_role,
        binding_role=_required_text(value, "binding_role"),
        document_id=_required_text(value, "document_id"),
        source_code=_required_text(value, "source_code"),
        authority_tier=authority_tier,
        publisher_code=_required_text(value, "publisher_code"),
        publisher_role=publisher_role,
        source_locator=_required_text(value, "source_locator"),
        discovery_locator=_required_text(value, "discovery_locator"),
        document_type=_required_text(value, "document_type"),
        document_version=_required_text(value, "document_version"),
        published_at=published_at,
        available_at=available_at,
        effective_from=effective_from,
        effective_to=effective_to,
        original_language=language,
        jurisdiction=jurisdiction,
        media_type=media_type,
        accession_or_receipt_id=accession,
    )


def _validate_locator_for_target(
    locator: _ReviewedLocator,
    *,
    authority: _AuthorityRule,
    target: DocumentSourceTarget,
) -> None:
    if locator.authority_tier is not authority.authority_tier:
        raise _RegisteredResultError(
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_authority_tier_mismatch",
        )
    if locator.publisher_role is not authority.publisher_role:
        raise _RegisteredResultError(
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_publisher_role_mismatch",
        )
    if locator.publisher_code != authority.source_code:
        raise _RegisteredResultError(
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_publisher_code_mismatch",
        )
    if locator.jurisdiction != authority.jurisdiction:
        raise _RegisteredResultError(
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_jurisdiction_mismatch",
        )
    if locator.required_role not in authority.allowed_document_roles:
        raise _RegisteredResultError(
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_document_role_not_allowed",
        )
    if (
        locator.entity_type != target.entity_type
        or locator.binding_role != target.binding_role
    ):
        raise _RegisteredResultError(
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "registered_entity_binding_mismatch",
        )
    if locator.document_type not in document_types_for_role(target.required_role):
        raise _RegisteredResultError(
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_document_type_mismatch",
        )
    try:
        allowed_publishers = publisher_roles_for_document_role(
            target.required_role, target.binding_role
        )
    except ValueError as error:
        raise _RegisteredResultError(
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "registered_entity_binding_mismatch",
        ) from error
    if locator.publisher_role not in allowed_publishers:
        raise _RegisteredResultError(
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_publisher_role_not_approved",
        )
    try:
        _sanitize_exact_host(locator.source_locator, authority.allowed_hosts)
        _sanitize_exact_host(locator.discovery_locator, authority.allowed_hosts)
    except DocumentSourceAccessError as error:
        reason = (
            "registered_locator_host_not_allowed"
            if "host_not_allowed" in error.code.value
            else "registered_locator_unsafe"
        )
        raise _RegisteredResultError(SourceAuditStatus.ACCESS_DENIED, reason) from error


def _validate_cutoff(locator: _ReviewedLocator, *, cutoff_date: date) -> None:
    if (
        source_timestamp_is_after_cutoff(locator.published_at, cutoff_date)
        or source_timestamp_is_after_cutoff(locator.available_at, cutoff_date)
        or locator.effective_from > cutoff_date
    ):
        raise _RegisteredResultError(
            SourceAuditStatus.AFTER_CUTOFF_ONLY,
            "registered_after_cutoff_only",
        )
    if (
        locator.effective_to is not None
        and locator.effective_to < locator.effective_from
    ):
        raise _RegisteredResultError(
            SourceAuditStatus.VERSION_UNKNOWN,
            "registered_effective_range_invalid",
        )


def _preflight(
    opener: object,
    source_locator: str,
    *,
    allowed_hosts: frozenset[str],
    expected_media_type: str,
) -> None:
    current_url = source_locator
    for redirect_count in range(_MAX_REDIRECTS + 1):
        response = _open_no_redirect(opener, current_url)
        try:
            status_code = _response_status(response)
        except Exception:
            response.close()
            raise
        if 300 <= status_code < 400:
            try:
                location = _response_header(response, "Location")
            finally:
                response.close()
            if redirect_count >= _MAX_REDIRECTS:
                raise _RegisteredResultError(
                    SourceAuditStatus.ACCESS_DENIED,
                    "registered_redirect_limit_exceeded",
                )
            redirected_url = urljoin(current_url, location)
            try:
                _sanitize_exact_host(redirected_url, allowed_hosts)
            except DocumentSourceAccessError as error:
                reason = (
                    "registered_redirect_host_not_allowed"
                    if "host_not_allowed" in error.code.value
                    else "registered_redirect_unsafe"
                )
                raise _RegisteredResultError(
                    SourceAuditStatus.ACCESS_DENIED, reason
                ) from error
            current_url = redirected_url
            continue
        if status_code not in {200, 206}:
            response.close()
            raise HttpStatusError(status_code)
        try:
            actual_media_type = _response_header(response, "Content-Type").split(
                ";", 1
            )[0].strip().lower()
            if actual_media_type != expected_media_type:
                raise _RegisteredResultError(
                    SourceAuditStatus.MEDIA_TYPE_UNSUPPORTED,
                    "registered_media_type_mismatch",
                )
            content_length = _optional_response_header(response, "Content-Length")
            if content_length is not None and (
                not content_length.isascii()
                or not content_length.isdigit()
                or int(content_length) <= 0
            ):
                raise _RegisteredResultError(
                    SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                    "registered_content_length_invalid",
                )
            first_byte = response.read(1)
            if not isinstance(first_byte, bytes) or len(first_byte) != 1:
                raise _RegisteredResultError(
                    SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                    "registered_empty_response",
                )
        finally:
            response.close()
        return
    raise _RegisteredResultError(
        SourceAuditStatus.ACCESS_DENIED,
        "registered_redirect_limit_exceeded",
    )


def _sanitize_exact_host(locator: str, allowed_hosts: frozenset[str]) -> str:
    sanitized = sanitize_public_locator(locator, allowed_hosts=allowed_hosts)
    try:
        port = urlparse(sanitized).port
    except ValueError as error:
        raise DocumentSourceAccessError(
            DocumentSourceAccessErrorCode.UNSAFE_LOCATOR,
            SourceAuditStatus.ACCESS_DENIED,
        ) from error
    if port not in {None, 443}:
        raise DocumentSourceAccessError(
            DocumentSourceAccessErrorCode.UNSAFE_LOCATOR,
            SourceAuditStatus.ACCESS_DENIED,
        )
    return sanitized


def _open_no_redirect(opener: object, url: str) -> BinaryIO:
    open_method = getattr(opener, "open_no_redirect", None)
    if not callable(open_method):
        raise TypeError("registered opener must provide open_no_redirect()")
    return open_method(  # type: ignore[no-any-return]
        url,
        method="GET",
        headers={"Accept-Encoding": "identity", "Range": "bytes=0-0"},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )


def _response_status(response: BinaryIO) -> int:
    status_code = getattr(response, "status", None)
    if not isinstance(status_code, int) or isinstance(status_code, bool):
        raise _MalformedResponse
    return status_code


def _response_header(response: BinaryIO, name: str) -> str:
    value = _optional_response_header(response, name)
    if value is None or not value.strip():
        raise _MalformedResponse
    return value


def _optional_response_header(response: BinaryIO, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        raise _MalformedResponse
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    if value is not None and not isinstance(value, str):
        raise _MalformedResponse
    return value.strip() if isinstance(value, str) else None


def _candidate(locator: _ReviewedLocator) -> DocumentSourceCandidate:
    return DocumentSourceCandidate(
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


def _read_json(path: Path) -> object:
    if not isinstance(path, Path):
        raise TypeError("registry path must be a pathlib.Path")
    if path.stat().st_size > _MAX_REGISTRY_BYTES:
        raise OSError("registry exceeds the bounded size")
    return json.loads(path.read_text(encoding="utf-8"))


def _required_text(mapping: dict[object, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonblank")
    return value


def _unique_text_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"authority_registry {field} must be nonempty")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"authority_registry {field} must contain strings")
    typed = tuple(item for item in value if isinstance(item, str))
    if len(typed) != len(set(typed)):
        raise ValueError(f"authority_registry {field} contains duplicates")
    return typed


def _enum_value(enum_type: type, value: object, field: str):
    if not isinstance(value, str):
        raise ValueError(f"authority_registry {field} is invalid")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"authority_registry {field} is invalid") from error


def _datetime_value(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError
    return parsed


def _date_value(value: object, *, optional: bool) -> date | None:
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    return date.fromisoformat(value)


def _unavailable(status: SourceAuditStatus, reason_code: str) -> SourceAdapterResult:
    return SourceAdapterResult(status=status, reason_code=reason_code, candidates=())
