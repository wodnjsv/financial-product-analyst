"""Fail-closed interfaces shared by official document source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
import socket
from typing import AbstractSet, Protocol
from urllib.parse import urlparse

from financial_agent.documents.source_manifest import (
    DocumentSourceCandidate,
    DocumentSourceTarget,
    SourceAuditStatus,
    _validate_locator,
)


@dataclass(frozen=True, slots=True)
class DocumentDiscoveryContext:
    cutoff_date: date
    dart_api_key: str | None
    sec_user_agent: str | None
    locator_registry_path: Path | None


@dataclass(frozen=True, slots=True)
class SourceAdapterResult:
    status: SourceAuditStatus
    reason_code: str | None
    candidates: tuple[DocumentSourceCandidate, ...]


class DocumentSourceAdapter(Protocol):
    source_code: str

    def supports(self, target: DocumentSourceTarget) -> bool: ...

    def discover(
        self,
        target: DocumentSourceTarget,
        context: DocumentDiscoveryContext,
    ) -> SourceAdapterResult: ...


class DocumentSourceAccessErrorCode(str, Enum):
    ACCESS_METHOD_UNVERIFIED = "access_method_unverified"
    CREDENTIALS_MISSING = "credentials_missing"
    UNSAFE_LOCATOR = "unsafe_locator"
    LOCATOR_HOST_NOT_ALLOWED = "locator_host_not_allowed"


class DocumentSourceAccessError(Exception):
    """A safe public error that keeps only a stable code and audit status."""

    def __init__(
        self,
        code: DocumentSourceAccessErrorCode,
        status: SourceAuditStatus,
    ) -> None:
        if not isinstance(code, DocumentSourceAccessErrorCode):
            raise TypeError("document source access error code must be stable")
        self.code = code
        self.status = status
        super().__init__(code.value)


class HttpStatusError(Exception):
    """HTTP failure marker for adapters that hide upstream response details."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(str(status_code))


class MissingRequiredEnvironmentError(Exception):
    """Raised internally when a source-specific credential is unavailable."""


def classify_access_error(error: BaseException) -> SourceAuditStatus:
    """Map untrusted source failures to the stable manifest status taxonomy."""
    if isinstance(error, DocumentSourceAccessError):
        return error.status
    if isinstance(error, MissingRequiredEnvironmentError):
        return SourceAuditStatus.CREDENTIALS_MISSING
    if isinstance(error, (socket.gaierror, TimeoutError)):
        return SourceAuditStatus.ACCESS_METHOD_UNVERIFIED

    status_code = _http_status_code(error)
    if status_code in {401, 403}:
        return SourceAuditStatus.ACCESS_DENIED
    if status_code == 404:
        return SourceAuditStatus.DOCUMENT_NOT_FOUND
    if status_code == 429:
        return SourceAuditStatus.RATE_LIMITED
    return SourceAuditStatus.ACCESS_METHOD_UNVERIFIED


def sanitize_public_locator(
    locator: str,
    *,
    allowed_hosts: AbstractSet[str],
) -> str:
    """Return an approved locator unchanged or raise a stable access error."""
    try:
        _validate_locator(locator)
    except ValueError as error:
        raise DocumentSourceAccessError(
            DocumentSourceAccessErrorCode.UNSAFE_LOCATOR,
            SourceAuditStatus.ACCESS_DENIED,
        ) from error

    hostname = urlparse(locator).hostname
    if hostname is None or hostname.lower() not in allowed_hosts:
        raise DocumentSourceAccessError(
            DocumentSourceAccessErrorCode.LOCATOR_HOST_NOT_ALLOWED,
            SourceAuditStatus.ACCESS_DENIED,
        )
    return locator


def _http_status_code(error: BaseException) -> int | None:
    status_code = getattr(error, "status_code", None)
    if not isinstance(status_code, int):
        status_code = getattr(error, "code", None)
    return status_code if isinstance(status_code, int) else None
