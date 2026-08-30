from __future__ import annotations

import socket

import pytest

from financial_agent.documents.source_manifest import SourceAuditStatus
from financial_agent.ingestion.document_sources.base import (
    DocumentSourceAccessError,
    DocumentSourceAccessErrorCode,
    HttpStatusError,
    MissingRequiredEnvironmentError,
    classify_access_error,
    sanitize_public_locator,
)


@pytest.mark.parametrize(
    ("status_code", "expected"),
    (
        (401, SourceAuditStatus.ACCESS_DENIED),
        (403, SourceAuditStatus.ACCESS_DENIED),
        (404, SourceAuditStatus.DOCUMENT_NOT_FOUND),
        (429, SourceAuditStatus.RATE_LIMITED),
    ),
)
def test_http_status_maps_to_stable_audit_status(
    status_code: int,
    expected: SourceAuditStatus,
) -> None:
    assert classify_access_error(HttpStatusError(status_code)) is expected


@pytest.mark.parametrize(
    "error",
    (
        socket.gaierror("synthetic DNS failure"),
        TimeoutError("synthetic timeout"),
    ),
)
def test_network_failures_map_to_unverified_access_method(
    error: BaseException,
) -> None:
    assert (
        classify_access_error(error)
        is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    )


def test_missing_required_environment_maps_to_credentials_missing() -> None:
    assert (
        classify_access_error(MissingRequiredEnvironmentError("DART API key"))
        is SourceAuditStatus.CREDENTIALS_MISSING
    )


def test_disallowed_locator_host_is_access_denied() -> None:
    with pytest.raises(DocumentSourceAccessError) as caught:
        sanitize_public_locator(
            "https://unapproved.example.invalid/document.pdf",
            allowed_hosts=frozenset({"approved.example.invalid"}),
        )

    assert caught.value.code == "locator_host_not_allowed"
    assert caught.value.status is SourceAuditStatus.ACCESS_DENIED
    assert classify_access_error(caught.value) is SourceAuditStatus.ACCESS_DENIED


@pytest.mark.parametrize(
    "locator",
    (
        "http://approved.example.invalid/document.pdf",
        "https://user:password@approved.example.invalid/document.pdf",
        "https://approved.example.invalid/document.pdf#private",
        "https://approved.example.invalid/document.pdf?api_key=synthetic-secret",
    ),
)
def test_unsafe_locator_is_rejected_without_silent_sanitization(
    locator: str,
) -> None:
    with pytest.raises(DocumentSourceAccessError) as caught:
        sanitize_public_locator(
            locator,
            allowed_hosts=frozenset({"approved.example.invalid"}),
        )

    assert caught.value.code == "unsafe_locator"
    assert caught.value.status is SourceAuditStatus.ACCESS_DENIED


def test_public_locator_is_preserved_when_it_passes_manifest_validation() -> None:
    locator = "https://approved.example.invalid/document.pdf?CIK=0000000001"

    assert (
        sanitize_public_locator(
            locator,
            allowed_hosts=frozenset({"approved.example.invalid"}),
        )
        == locator
    )


def test_access_error_hides_chained_exception_text() -> None:
    try:
        try:
            raise RuntimeError("crtfc_key=synthetic-api-key")
        except RuntimeError as error:
            raise DocumentSourceAccessError(
                DocumentSourceAccessErrorCode.ACCESS_METHOD_UNVERIFIED,
                classify_access_error(error),
            ) from error
    except DocumentSourceAccessError as public_error:
        assert str(public_error) == "access_method_unverified"
        assert "synthetic-api-key" not in str(public_error)
        assert isinstance(public_error.__cause__, RuntimeError)


def test_secret_bearing_error_code_is_rejected_before_public_rendering() -> None:
    secret_bearing_code = "api_key=synthetic-secret"

    with pytest.raises(TypeError, match="must be stable") as caught:
        DocumentSourceAccessError(
            secret_bearing_code,
            SourceAuditStatus.ACCESS_DENIED,
        )

    assert secret_bearing_code not in str(caught.value)
