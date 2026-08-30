from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from enum import Enum
import hashlib
from pathlib import Path

import pytest

from financial_agent.documents import DocumentRole, PublisherRole
from financial_agent.documents.source_manifest import (
    DocumentSourceAuditEntry,
    DocumentSourceAuditReport,
    DocumentSourceCandidate,
    DocumentSourceTarget,
    SourceAuditStatus,
    SourceAuthorityTier,
    validate_document_source_report,
    write_document_source_report,
)


CUTOFF = date(2026, 8, 24)
NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def target(
    *,
    entity_id: str = "product-a",
    entity_type: str = "product",
    product_family: str | None = "domestic_etf",
    required_role: DocumentRole = DocumentRole.PRODUCT_SUMMARY,
    cutoff_date: date = CUTOFF,
    identifiers: tuple[tuple[str, str], ...] = (("ISIN", "KR0000000001"),),
) -> DocumentSourceTarget:
    return DocumentSourceTarget(
        dataset_version="facts-v1",
        entity_id=entity_id,
        entity_type=entity_type,
        canonical_name="Sample product",
        product_family=product_family,
        required_role=required_role,
        binding_role="subject_product",
        identifiers=identifiers,
        cutoff_date=cutoff_date,
    )


def candidate(
    *,
    source_locator: str = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260820000123",
    discovery_locator: str = "https://dart.fss.or.kr/",
    published_at: datetime | None = NOW,
    available_at: datetime | None = NOW,
) -> DocumentSourceCandidate:
    return DocumentSourceCandidate(
        document_id="document-a",
        source_code="DART",
        authority_tier=SourceAuthorityTier.TIER_1_REGULATORY,
        publisher_code="FSS_DART",
        publisher_role=PublisherRole.REGULATOR_DISCLOSURE,
        document_type="summary_prospectus",
        document_version="2026.1",
        source_locator=source_locator,
        discovery_locator=discovery_locator,
        jurisdiction="KR",
        original_language="ko",
        published_at=published_at,
        available_at=available_at,
        effective_from=CUTOFF,
        effective_to=None,
        media_type="text/html",
        accession_or_receipt_id="20260820000123",
    )


def audit_entry(
    *,
    entity_id: str = "product-a",
    required_role: DocumentRole = DocumentRole.PRODUCT_SUMMARY,
) -> DocumentSourceAuditEntry:
    return DocumentSourceAuditEntry(
        target=target(entity_id=entity_id, required_role=required_role),
        status=SourceAuditStatus.ELIGIBLE,
        reason_code=None,
        candidate=candidate(),
    )


def report(
    *, entries: tuple[DocumentSourceAuditEntry, ...]
) -> DocumentSourceAuditReport:
    return DocumentSourceAuditReport(
        schema_version="1.0",
        generated_at=NOW,
        cutoff_date=CUTOFF,
        dataset_version="facts-v1",
        entries=entries,
    )


def test_report_is_canonical_across_entry_order(tmp_path: Path) -> None:
    first = audit_entry(entity_id="product-b")
    second = audit_entry(entity_id="product-a")
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"

    left_hash = write_document_source_report(report(entries=(first, second)), left)
    right_hash = write_document_source_report(report(entries=(second, first)), right)

    assert left.read_bytes() == right.read_bytes()
    assert left_hash == right_hash == hashlib.sha256(left.read_bytes()).hexdigest()
    assert b'"generated_at":"2026-08-24T12:00:00Z"' in left.read_bytes()


def test_unavailable_entry_requires_stable_reason_without_candidate() -> None:
    with pytest.raises(ValueError, match="unavailable audit entry"):
        DocumentSourceAuditEntry(
            target=target(),
            status=SourceAuditStatus.DOCUMENT_NOT_FOUND,
            reason_code=None,
            candidate=None,
        )


def test_report_rejects_duplicate_target_role_keys() -> None:
    with pytest.raises(ValueError, match="duplicate audit target"):
        validate_document_source_report(
            report(entries=(audit_entry(), audit_entry()))
        )


def test_target_rejects_noncanonical_cutoff() -> None:
    with pytest.raises(ValueError, match="cutoff"):
        target(cutoff_date=date(2026, 8, 23))


@pytest.mark.parametrize("entity_id", ("", " ", "\t"))
def test_target_rejects_blank_entity_id(entity_id: str) -> None:
    with pytest.raises(ValueError, match="entity_id"):
        target(entity_id=entity_id)


def test_candidate_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone"):
        candidate(published_at=datetime(2026, 8, 24, 12))


@pytest.mark.parametrize(
    ("published_at", "available_at", "expected_null"),
    (
        (None, NOW, b'"published_at":null'),
        (NOW, None, b'"available_at":null'),
    ),
)
def test_unavailable_candidate_serializes_missing_timestamp_as_null(
    tmp_path: Path,
    published_at: datetime | None,
    available_at: datetime | None,
    expected_null: bytes,
) -> None:
    unavailable = DocumentSourceAuditEntry(
        target=target(),
        status=SourceAuditStatus.VERSION_UNKNOWN,
        reason_code="timing_missing",
        candidate=candidate(published_at=published_at, available_at=available_at),
    )
    destination = tmp_path / "report.json"

    write_document_source_report(report(entries=(unavailable,)), destination)

    assert expected_null in destination.read_bytes()


@pytest.mark.parametrize(
    "source_locator",
    (
        "https://dart.fss.or.kr/dsaf001/main.do?api_key=synthetic-secret",
        "https://user:password@dart.fss.or.kr/dsaf001/main.do",
        "https://dart.fss.or.kr/dsaf001/main.do#private",
        "https://dart.fss.or.kr/dsaf001/main.do#",
        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260820000123;api_key=synthetic-secret",
        "http://dart.fss.or.kr/dsaf001/main.do",
    ),
)
def test_candidate_rejects_unsafe_source_locator(source_locator: str) -> None:
    with pytest.raises(ValueError, match="locator"):
        candidate(source_locator=source_locator)


def test_candidate_allows_only_public_query_keys() -> None:
    candidate(
        source_locator="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260820000123"
    )


def test_candidate_rejects_unapproved_authority_tier() -> None:
    class UnapprovedAuthorityTier(str, Enum):
        TIER_4 = "tier_4_unapproved"

    with pytest.raises(ValueError, match="authority_tier"):
        replace(candidate(), authority_tier=UnapprovedAuthorityTier.TIER_4)


def test_report_rejects_eligible_domestic_bond() -> None:
    bond = DocumentSourceAuditEntry(
        target=target(
            entity_id="bond-a",
            product_family="domestic_bond",
        ),
        status=SourceAuditStatus.ELIGIBLE,
        reason_code=None,
        candidate=candidate(),
    )

    with pytest.raises(ValueError, match="domestic bond"):
        validate_document_source_report(report(entries=(bond,)))
