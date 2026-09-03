from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from enum import Enum
import hashlib
import json
from pathlib import Path

import pytest

from financial_agent.db.schema import catalog as catalog_schema
from financial_agent.documents import DocumentRole, PublisherRole
from financial_agent.documents.source_manifest import (
    DocumentSourceAuditEntry,
    DocumentSourceAuditReport,
    DocumentSourceAttempt,
    DocumentSourceCandidate,
    DocumentSourceTarget,
    SourceAuditStatus,
    SourceAuthorityTier,
    validate_document_source_report,
    write_document_source_report,
)
from financial_agent.ingestion.document_sources.audit import (
    document_source_audit_passed,
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
    binding_role: str = "subject_product",
) -> DocumentSourceTarget:
    return DocumentSourceTarget(
        dataset_version="facts-v1",
        entity_id=entity_id,
        entity_type=entity_type,
        canonical_name="Sample product",
        product_family=product_family,
        required_role=required_role,
        binding_role=binding_role,
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


def unresolved_policy_target(
    entity_type: str = "product",
) -> DocumentSourceTarget:
    return replace(
        target(
            entity_id="policy-missing",
            entity_type=entity_type,
            product_family=None,
            required_role=DocumentRole.POLICY_BASE,
            identifiers=(),
            binding_role="subject_policy",
        ),
        canonical_name=None,
    )


def policy_candidate() -> DocumentSourceCandidate:
    return replace(
        candidate(),
        source_code="POLICY_AUTHORITY",
        authority_tier=SourceAuthorityTier.TIER_2_CLAIM_OWNER,
        publisher_code="POLICY_AUTHORITY",
        publisher_role=PublisherRole.POLICY_AUTHORITY,
        document_type="policy_base",
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


def test_unavailable_entry_serializes_attempted_source_without_candidate(
    tmp_path: Path,
) -> None:
    unavailable = DocumentSourceAuditEntry(
        target=target(),
        status=SourceAuditStatus.ACCESS_DENIED,
        reason_code="dart_access_denied",
        candidate=None,
        attempted_source=DocumentSourceAttempt(
            source_code="DART",
            source_locator=None,
            discovery_locator="https://dart.fss.or.kr/",
        ),
    )
    destination = tmp_path / "report.json"

    write_document_source_report(report(entries=(unavailable,)), destination)

    entry = json.loads(destination.read_text(encoding="utf-8"))["entries"][0]
    assert entry["candidate"] is None
    assert entry["attempted_source"] == {
        "discovery_locator": "https://dart.fss.or.kr/",
        "source_code": "DART",
        "source_locator": None,
    }


@pytest.mark.parametrize(
    "locator",
    (
        "https://dart.fss.or.kr/?api_key=SYNTHETIC-SECRET",
        "https://user:password@dart.fss.or.kr/",
        "http://dart.fss.or.kr/",
    ),
)
def test_attempted_source_rejects_unsafe_public_locator(locator: str) -> None:
    with pytest.raises(ValueError, match="locator"):
        DocumentSourceAttempt(
            source_code="DART",
            source_locator=locator,
            discovery_locator=None,
        )


def test_audit_entry_rejects_untyped_attempted_source() -> None:
    with pytest.raises(ValueError, match="attempted_source"):
        DocumentSourceAuditEntry(
            target=target(),
            status=SourceAuditStatus.ACCESS_DENIED,
            reason_code="dart_access_denied",
            candidate=None,
            attempted_source="DART",  # type: ignore[arg-type]
        )


def test_report_rejects_duplicate_target_role_keys() -> None:
    with pytest.raises(ValueError, match="duplicate audit target"):
        validate_document_source_report(
            report(entries=(audit_entry(), audit_entry()))
        )


def test_target_rejects_noncanonical_cutoff() -> None:
    with pytest.raises(ValueError, match="cutoff"):
        target(cutoff_date=date(2026, 8, 23))


@pytest.mark.parametrize("entity_type", ("product", "institution"))
def test_unresolved_policy_target_allows_truthful_missing_name(
    tmp_path: Path,
    entity_type: str,
) -> None:
    unavailable = DocumentSourceAuditEntry(
        target=unresolved_policy_target(entity_type),
        status=SourceAuditStatus.IDENTIFIER_MISSING,
        reason_code="policy_entity_missing",
        candidate=None,
        attempted_source=DocumentSourceAttempt(
            source_code="POLICY_AUTHORITY",
            source_locator=None,
            discovery_locator=None,
        ),
    )
    destination = tmp_path / "report.json"

    write_document_source_report(report(entries=(unavailable,)), destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["entries"][0]["target"]["canonical_name"] is None
    assert payload["entries"][0]["target"]["entity_type"] == entity_type


def test_policy_target_uses_only_real_catalog_entity_types() -> None:
    assert set(catalog_schema.ENTITY_TYPES) == {
        "product",
        "security",
        "company",
        "institution",
        "index",
        "theme",
    }
    assert "policy" not in catalog_schema.ENTITY_TYPES

    with pytest.raises(ValueError, match="entity_type"):
        target(
            entity_id="policy-invented-subtype",
            entity_type="policy",
            product_family=None,
            required_role=DocumentRole.POLICY_BASE,
            identifiers=(),
            binding_role="subject_policy",
        )


@pytest.mark.parametrize(
    ("status", "reason_code", "source_candidate"),
    (
        (SourceAuditStatus.ELIGIBLE, None, policy_candidate()),
        (
            SourceAuditStatus.DOCUMENT_NOT_FOUND,
            "policy_entity_missing",
            None,
        ),
        (
            SourceAuditStatus.IDENTIFIER_MISSING,
            "policy_document_missing",
            None,
        ),
        (
            SourceAuditStatus.IDENTIFIER_MISSING,
            "policy_entity_missing",
            policy_candidate(),
        ),
    ),
)
def test_unresolved_policy_target_rejects_any_other_disposition(
    status: SourceAuditStatus,
    reason_code: str | None,
    source_candidate: DocumentSourceCandidate | None,
) -> None:
    with pytest.raises(ValueError, match="unresolved policy"):
        DocumentSourceAuditEntry(
            target=unresolved_policy_target(),
            status=status,
            reason_code=reason_code,
            candidate=source_candidate,
        )


def test_unresolved_policy_target_requires_absent_identifiers() -> None:
    with pytest.raises(ValueError, match="canonical_name"):
        replace(
            unresolved_policy_target(),
            identifiers=(("POLICY_ID", "policy-missing"),),
        )


def test_truthful_unresolved_policy_report_cannot_pass_completeness() -> None:
    unavailable = DocumentSourceAuditEntry(
        target=unresolved_policy_target(),
        status=SourceAuditStatus.IDENTIFIER_MISSING,
        reason_code="policy_entity_missing",
        candidate=None,
    )

    assert document_source_audit_passed(report(entries=(unavailable,))) is False


def test_non_policy_target_still_requires_canonical_name() -> None:
    with pytest.raises(ValueError, match="canonical_name"):
        replace(target(), canonical_name=None)


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


def test_candidate_rejects_unapproved_publisher_role_type() -> None:
    with pytest.raises(ValueError, match="publisher_role"):
        replace(candidate(), publisher_role="regulator_disclosure")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field_name", "malformed_value", "message"),
    (
        ("published_at", "2026-08-24T12:00:00Z", "published_at"),
        ("available_at", CUTOFF, "available_at"),
        ("effective_from", "2026-08-24", "effective_from"),
        ("effective_to", NOW, "effective_to"),
    ),
)
def test_candidate_rejects_malformed_typed_temporal_fields(
    field_name: str,
    malformed_value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(candidate(), **{field_name: malformed_value})


def test_audit_entry_rejects_non_enum_status() -> None:
    with pytest.raises(ValueError, match="status"):
        DocumentSourceAuditEntry(
            target=target(),
            status="eligible",  # type: ignore[arg-type]
            reason_code=None,
            candidate=candidate(),
        )


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


def test_report_rejects_non_bond_not_applicable_status() -> None:
    required_product = DocumentSourceAuditEntry(
        target=target(),
        status=SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE,
        reason_code="adapter_target_not_supported",
        candidate=None,
    )

    with pytest.raises(ValueError, match="not_applicable"):
        validate_document_source_report(report(entries=(required_product,)))


@pytest.mark.parametrize(
    "forged_candidate",
    (
        replace(candidate(), document_type="index_methodology"),
        replace(candidate(), publisher_role=PublisherRole.INDEX_PROVIDER),
        replace(
            candidate(),
            authority_tier=SourceAuthorityTier.TIER_2_CLAIM_OWNER,
        ),
        replace(candidate(), document_version=None),
        replace(candidate(), effective_from=None),
        replace(
            candidate(),
            effective_from=date(2026, 8, 1),
            effective_to=date(2026, 8, 23),
        ),
    ),
)
def test_report_rejects_forged_eligible_candidate_metadata(
    forged_candidate: DocumentSourceCandidate,
) -> None:
    forged = DocumentSourceAuditEntry(
        target=target(),
        status=SourceAuditStatus.ELIGIBLE,
        reason_code=None,
        candidate=forged_candidate,
    )

    with pytest.raises(ValueError):
        validate_document_source_report(report(entries=(forged,)))


def test_report_rejects_eligible_candidate_with_incompatible_binding() -> None:
    forged = DocumentSourceAuditEntry(
        target=target(binding_role="subject_index"),
        status=SourceAuditStatus.ELIGIBLE,
        reason_code=None,
        candidate=candidate(),
    )

    with pytest.raises(ValueError, match="binding"):
        validate_document_source_report(report(entries=(forged,)))
