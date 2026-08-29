from datetime import UTC, date, datetime

import pytest

from financial_agent.documents.models import (
    CoverageStatus,
    DocumentCandidate,
    DocumentCoverageDraft,
    DocumentRole,
    PublisherRole,
)
from financial_agent.documents.policy import admit_document, select_canonical_document


def candidate(
    document_id: str,
    *,
    document_type: str = "summary_prospectus",
    document_version: str | None = "2026.1",
    publisher_role: PublisherRole | str = PublisherRole.REGULATOR_DISCLOSURE,
    published_at: datetime | None = datetime(2026, 8, 1, tzinfo=UTC),
    available_at: datetime | None = datetime(2026, 8, 1, tzinfo=UTC),
    effective_from: date | None = date(2026, 8, 1),
    effective_to: date | None = None,
    bound_entity_ids: tuple[str, ...] = ("product-a",),
    claim_types: set[str] | None = None,
    exact_text_available: bool = True,
    content_checksum: str | None = None,
) -> DocumentCandidate:
    return DocumentCandidate(
        document_id=document_id,
        document_type=document_type,
        document_version=document_version,
        source_id="source-a",
        publisher_role=publisher_role,
        jurisdiction="KR",
        original_language="ko",
        published_at=published_at,
        available_at=available_at,
        effective_from=effective_from,
        effective_to=effective_to,
        bound_entity_ids=bound_entity_ids,
        binding_role="subject_product",
        claim_types=frozenset(
            claim_types or {"investment_strategy", "risk_factor"}
        ),
        content_checksum=content_checksum or (document_id * 64)[:64],
        extraction_method="official_html",
        exact_text_available=exact_text_available,
        source_locator=f"https://example.test/{document_id}",
    )


def test_summary_wins_when_it_covers_all_required_claims() -> None:
    selected = select_canonical_document(
        (
            candidate(
                "summary",
                document_type="summary_prospectus",
                claim_types={"investment_strategy", "risk_factor"},
            ),
            candidate(
                "full",
                document_type="full_prospectus",
                claim_types={"investment_strategy", "risk_factor"},
            ),
        ),
        required_role=DocumentRole.PRODUCT_SUMMARY,
        cutoff_date=date(2026, 8, 24),
    )

    assert selected.document_id == "summary"
    assert selected.coverage_status is CoverageStatus.INDEXED


def test_after_cutoff_document_is_not_selected() -> None:
    selected = select_canonical_document(
        (candidate("late", available_at=datetime(2026, 8, 25, tzinfo=UTC)),),
        required_role=DocumentRole.PRODUCT_SUMMARY,
        cutoff_date=date(2026, 8, 24),
    )

    assert selected.document_id is None
    assert selected.coverage_status is CoverageStatus.AFTER_CUTOFF_ONLY


def test_ambiguous_entity_binding_fails_closed() -> None:
    decision = admit_document(
        candidate("ambiguous", bound_entity_ids=("product-a", "product-b")),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.accepted is False
    assert decision.coverage_status is CoverageStatus.AMBIGUOUS_ENTITY_BINDING


def test_rejects_unapproved_publisher() -> None:
    decision = admit_document(
        candidate("unapproved", publisher_role="unofficial"),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.accepted is False
    assert decision.coverage_status is CoverageStatus.PUBLISHER_NOT_APPROVED


def test_rejects_unknown_version() -> None:
    decision = admit_document(
        candidate("unknown-version", document_version=None),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.accepted is False
    assert decision.coverage_status is CoverageStatus.VERSION_UNKNOWN


def test_rejects_unreadable_text() -> None:
    decision = admit_document(
        candidate("unreadable", exact_text_available=False),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.accepted is False
    assert decision.coverage_status is CoverageStatus.UNREADABLE_DOCUMENT


def test_exact_duplicate_documents_use_stable_document_id_tie_break() -> None:
    selected = select_canonical_document(
        (
            candidate("z-copy", content_checksum="a" * 64),
            candidate("a-copy", content_checksum="a" * 64),
        ),
        required_role=DocumentRole.PRODUCT_SUMMARY,
        cutoff_date=date(2026, 8, 24),
    )

    assert selected.document_id == "a-copy"
    assert selected.rejected_document_ids == ("z-copy",)


def test_full_prospectus_is_used_when_summary_lacks_required_claims() -> None:
    selected = select_canonical_document(
        (
            candidate(
                "summary-missing-risk",
                claim_types={"investment_strategy"},
            ),
            candidate(
                "full-complete",
                document_type="full_prospectus",
                claim_types={"investment_strategy", "risk_factor"},
            ),
        ),
        required_role=DocumentRole.PRODUCT_SUMMARY,
        cutoff_date=date(2026, 8, 24),
    )

    assert selected.document_id == "full-complete"
    assert selected.coverage_status is CoverageStatus.INDEXED


def test_coverage_draft_rejects_document_on_negative_coverage() -> None:
    with pytest.raises(ValueError, match="negative coverage"):
        DocumentCoverageDraft(
            coverage_id="coverage-a",
            dataset_version="dataset-20260824",
            entity_id="product-a",
            required_document_role=DocumentRole.PRODUCT_SUMMARY,
            coverage_status=CoverageStatus.DOCUMENT_NOT_FOUND,
            document_id="invented-document",
            scope_evidence_id="scope-a",
            reason_code="document_not_found",
            record_hash="a" * 64,
        )
