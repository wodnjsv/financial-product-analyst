from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from financial_agent.documents.models import (
    CoverageStatus,
    DocumentCandidate,
    DocumentCoverageDraft,
    DocumentRole,
    PublisherRole,
)
from financial_agent.documents.policy import (
    admit_document,
    binding_roles_for_document_role,
    document_types_for_role,
    publisher_roles_for_document_role,
    select_canonical_document,
)


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
    binding_role: str = "subject_product",
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
        binding_role=binding_role,
        claim_types=frozenset(
            claim_types or {"investment_strategy", "risk_factor"}
        ),
        content_checksum=content_checksum or (document_id * 64)[:64],
        extraction_method="official_html",
        exact_text_available=exact_text_available,
        source_locator=f"https://example.test/{document_id}",
    )


def test_authority_helpers_expose_the_same_read_only_policy_matrices() -> None:
    assert document_types_for_role(DocumentRole.PRODUCT_SUMMARY) == frozenset(
        {"summary_prospectus", "full_prospectus"}
    )
    assert binding_roles_for_document_role(
        DocumentRole.INDEX_METHODOLOGY
    ) == frozenset({"subject_index"})
    assert publisher_roles_for_document_role(
        DocumentRole.OFFICIAL_UPDATE, "subject_policy"
    ) == frozenset(
        {PublisherRole.POLICY_AUTHORITY, PublisherRole.POLICY_OPERATOR}
    )
    assert publisher_roles_for_document_role(
        DocumentRole.OFFICIAL_UPDATE, "subject_product"
    ) == frozenset(
        {
            PublisherRole.REGULATOR_DISCLOSURE,
            PublisherRole.EXCHANGE,
            PublisherRole.INDUSTRY_ASSOCIATION,
        }
    )
    assert publisher_roles_for_document_role(
        DocumentRole.PRODUCT_SUMMARY, "subject_product"
    ) == frozenset({PublisherRole.REGULATOR_DISCLOSURE})
    assert publisher_roles_for_document_role(
        DocumentRole.OFFICIAL_UPDATE, "subject_index"
    ) == frozenset({PublisherRole.INDEX_PROVIDER})
    with pytest.raises(ValueError, match="binding role"):
        publisher_roles_for_document_role(
            DocumentRole.OFFICIAL_UPDATE, "unsupported_binding"
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


@pytest.mark.parametrize(
    "publisher_role",
    (PublisherRole.ASSET_MANAGER, PublisherRole.ISSUER),
)
def test_product_document_rejects_manager_or_issuer_fallback(
    publisher_role: PublisherRole,
) -> None:
    decision = admit_document(
        candidate(
            "direct-copy",
            document_type="summary_prospectus",
            publisher_role=publisher_role,
            binding_role="subject_product",
        ),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.accepted is False
    assert decision.coverage_status is CoverageStatus.PUBLISHER_NOT_APPROVED
    assert decision.reason_code == "publisher_role_not_approved"


@pytest.mark.parametrize(
    "publisher_role",
    (PublisherRole.EXCHANGE, PublisherRole.INDUSTRY_ASSOCIATION),
)
def test_product_change_accepts_tier_three_claim_owner(
    publisher_role: PublisherRole,
) -> None:
    decision = admit_document(
        candidate(
            "tier-three-update",
            document_type="official_update",
            publisher_role=publisher_role,
            binding_role="subject_product",
            claim_types={"official_update"},
        ),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.accepted is True


def test_rejects_unknown_version() -> None:
    decision = admit_document(
        candidate("unknown-version", document_version=None),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.accepted is False
    assert decision.coverage_status is CoverageStatus.VERSION_UNKNOWN


@pytest.mark.parametrize(
    "document_version",
    (" ", "\t", "\n", "\r", "\f", "\v", " \t\n\r\f\v "),
)
def test_rejects_whitespace_only_version_as_unknown(
    document_version: str,
) -> None:
    decision = admit_document(
        candidate("blank-version", document_version=document_version),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.accepted is False
    assert decision.coverage_status is CoverageStatus.VERSION_UNKNOWN


def test_version_with_surrounding_whitespace_is_accepted_verbatim() -> None:
    version = " \t\n 2026.1 \r\f\v "
    decision = admit_document(
        candidate("verbatim-version", document_version=version),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.accepted is True
    assert decision.candidate.document_version == version


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


def test_cutoff_uses_seoul_calendar_day_for_utc_timestamps() -> None:
    seoul = ZoneInfo("Asia/Seoul")
    cutoff = date(2026, 8, 24)
    last_kst = datetime(2026, 8, 24, 23, 59, 59, 999999, tzinfo=seoul)
    equivalent_utc = datetime(2026, 8, 24, 14, 59, 59, 999999, tzinfo=UTC)
    first_late = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)

    assert admit_document(
        candidate("last-kst", published_at=last_kst, available_at=last_kst),
        cutoff_date=cutoff,
    ).accepted
    assert admit_document(
        candidate("last-utc", published_at=equivalent_utc, available_at=equivalent_utc),
        cutoff_date=cutoff,
    ).accepted
    late = admit_document(
        candidate("first-late", published_at=first_late, available_at=first_late),
        cutoff_date=cutoff,
    )
    assert late.coverage_status is CoverageStatus.AFTER_CUTOFF_ONLY


@pytest.mark.parametrize(
    ("published_at", "available_at"),
    [
        (None, datetime(2026, 8, 1, tzinfo=UTC)),
        (datetime(2026, 8, 1), datetime(2026, 8, 1, tzinfo=UTC)),
    ],
)
def test_missing_or_naive_timing_is_version_unknown(
    published_at: datetime | None,
    available_at: datetime | None,
) -> None:
    decision = admit_document(
        candidate(
            "unverifiable-time",
            published_at=published_at,
            available_at=available_at,
        ),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.coverage_status is CoverageStatus.VERSION_UNKNOWN


@pytest.mark.parametrize(
    ("required_role", "document_type", "publisher_role", "binding_role"),
    [
        (
            DocumentRole.PRODUCT_SUMMARY,
            "summary_prospectus",
            PublisherRole.POLICY_OPERATOR,
            "subject_product",
        ),
        (
            DocumentRole.INDEX_METHODOLOGY,
            "index_methodology",
            PublisherRole.ISSUER,
            "subject_index",
        ),
        (
            DocumentRole.OFFICIAL_UPDATE,
            "official_update",
            PublisherRole.INDEX_PROVIDER,
            "subject_product",
        ),
    ],
)
def test_known_but_wrong_publisher_role_is_rejected_for_selection(
    required_role: DocumentRole,
    document_type: str,
    publisher_role: PublisherRole,
    binding_role: str,
) -> None:
    selected = select_canonical_document(
        (
            candidate(
                "wrong-authority",
                document_type=document_type,
                publisher_role=publisher_role,
                binding_role=binding_role,
                claim_types={
                    "investment_strategy",
                    "risk_factor",
                    "index_methodology",
                    "selection_rules",
                    "rebalancing",
                    "official_update",
                },
            ),
        ),
        required_role=required_role,
        cutoff_date=date(2026, 8, 24),
    )

    assert selected.document_id is None
    assert selected.coverage_status is CoverageStatus.PUBLISHER_NOT_APPROVED


def test_invalid_or_empty_binding_fails_closed() -> None:
    invalid_role = admit_document(
        candidate("invalid-role", binding_role="title_similarity"),
        cutoff_date=date(2026, 8, 24),
    )
    empty_binding = admit_document(
        candidate("empty-binding", bound_entity_ids=()),
        cutoff_date=date(2026, 8, 24),
    )

    assert invalid_role.coverage_status is CoverageStatus.AMBIGUOUS_ENTITY_BINDING
    assert empty_binding.coverage_status is CoverageStatus.AMBIGUOUS_ENTITY_BINDING


def test_candidates_for_one_role_must_share_an_exact_entity() -> None:
    selected = select_canonical_document(
        (
            candidate("entity-a", bound_entity_ids=("entity-a",)),
            candidate("entity-b", bound_entity_ids=("entity-b",)),
        ),
        required_role=DocumentRole.PRODUCT_SUMMARY,
        cutoff_date=date(2026, 8, 24),
    )

    assert selected.document_id is None
    assert selected.coverage_status is CoverageStatus.AMBIGUOUS_ENTITY_BINDING


def test_unrelated_rejected_documents_do_not_affect_required_role_coverage() -> None:
    selected = select_canonical_document(
        (
            candidate(
                "late-index",
                document_type="index_methodology",
                binding_role="subject_index",
                available_at=datetime(2026, 8, 25, tzinfo=UTC),
            ),
        ),
        required_role=DocumentRole.PRODUCT_SUMMARY,
        cutoff_date=date(2026, 8, 24),
    )

    assert selected.document_id is None
    assert selected.coverage_status is CoverageStatus.DOCUMENT_NOT_FOUND


def test_failure_selection_is_stable_and_prefers_unverifiable_timing() -> None:
    candidates = (
        candidate("unknown-time", published_at=None, available_at=None),
        candidate("late", available_at=datetime(2026, 8, 25, tzinfo=UTC)),
    )
    first = select_canonical_document(
        candidates,
        required_role=DocumentRole.PRODUCT_SUMMARY,
        cutoff_date=date(2026, 8, 24),
    )
    second = select_canonical_document(
        tuple(reversed(candidates)),
        required_role=DocumentRole.PRODUCT_SUMMARY,
        cutoff_date=date(2026, 8, 24),
    )

    assert first == second
    assert first.coverage_status is CoverageStatus.VERSION_UNKNOWN
    assert first.reason_code == "cutoff_timing_not_verified"


@pytest.mark.parametrize("document_id", [None, "", "   "])
def test_indexed_coverage_requires_trimmed_document_id(
    document_id: str | None,
) -> None:
    with pytest.raises(ValueError, match="indexed coverage"):
        DocumentCoverageDraft(
            coverage_id="coverage-a",
            dataset_version="dataset-20260824",
            entity_id="product-a",
            required_document_role=DocumentRole.PRODUCT_SUMMARY,
            coverage_status=CoverageStatus.INDEXED,
            document_id=document_id,
            scope_evidence_id=None,
            reason_code=None,
            record_hash="a" * 64,
        )


@pytest.mark.parametrize(
    ("scope_evidence_id", "reason_code"),
    [(None, "missing"), ("", "missing"), ("  ", "missing"), ("scope-a", ""), ("scope-a", "  ")],
)
def test_negative_coverage_requires_trimmed_scope_evidence_and_reason(
    scope_evidence_id: str | None,
    reason_code: str | None,
) -> None:
    with pytest.raises(ValueError, match="negative coverage"):
        DocumentCoverageDraft(
            coverage_id="coverage-a",
            dataset_version="dataset-20260824",
            entity_id="product-a",
            required_document_role=DocumentRole.PRODUCT_SUMMARY,
            coverage_status=CoverageStatus.DOCUMENT_NOT_FOUND,
            document_id=None,
            scope_evidence_id=scope_evidence_id,
            reason_code=reason_code,
            record_hash="a" * 64,
        )


@pytest.mark.parametrize(
    ("document_type", "publisher_role", "binding_role"),
    [
        ("summary_prospectus", PublisherRole.POLICY_OPERATOR, "subject_product"),
        ("summary_prospectus", PublisherRole.INDEX_PROVIDER, "subject_product"),
        ("index_methodology", PublisherRole.EXCHANGE, "subject_index"),
        ("policy_base", PublisherRole.EXCHANGE, "subject_policy"),
        ("index_methodology", PublisherRole.ISSUER, "subject_index"),
        ("policy_base", PublisherRole.ISSUER, "subject_policy"),
        ("official_update", PublisherRole.INDEX_PROVIDER, "subject_product"),
        ("official_update", PublisherRole.ISSUER, "subject_index"),
        ("official_update", PublisherRole.ASSET_MANAGER, "subject_policy"),
    ],
)
def test_direct_admission_rejects_known_wrong_publisher_authority(
    document_type: str,
    publisher_role: PublisherRole,
    binding_role: str,
) -> None:
    decision = admit_document(
        candidate(
            "wrong-authority",
            document_type=document_type,
            publisher_role=publisher_role,
            binding_role=binding_role,
        ),
        cutoff_date=date(2026, 8, 24),
    )

    assert decision.accepted is False
    assert decision.coverage_status is CoverageStatus.PUBLISHER_NOT_APPROVED


@pytest.mark.parametrize(
    ("required_role", "document_type", "binding_role"),
    [
        (DocumentRole.PRODUCT_SUMMARY, "summary_prospectus", "subject_index"),
        (DocumentRole.PRODUCT_FULL, "full_prospectus", "subject_policy"),
        (DocumentRole.INDEX_METHODOLOGY, "index_methodology", "subject_product"),
        (DocumentRole.POLICY_BASE, "policy_base", "subject_index"),
    ],
)
def test_incompatible_binding_role_fails_closed_for_admission_and_selection(
    required_role: DocumentRole,
    document_type: str,
    binding_role: str,
) -> None:
    document = candidate(
        "wrong-binding",
        document_type=document_type,
        binding_role=binding_role,
        claim_types={
            "investment_strategy",
            "risk_factor",
            "index_methodology",
            "selection_rules",
            "rebalancing",
            "legal_structure",
        },
    )

    direct = admit_document(document, cutoff_date=date(2026, 8, 24))
    selected = select_canonical_document(
        (document,),
        required_role=required_role,
        cutoff_date=date(2026, 8, 24),
    )

    assert direct.coverage_status is CoverageStatus.AMBIGUOUS_ENTITY_BINDING
    assert selected.coverage_status is CoverageStatus.AMBIGUOUS_ENTITY_BINDING


@pytest.mark.parametrize(
    ("binding_role", "publisher_role"),
    [
        ("subject_product", PublisherRole.REGULATOR_DISCLOSURE),
        ("subject_index", PublisherRole.INDEX_PROVIDER),
        ("subject_policy", PublisherRole.POLICY_AUTHORITY),
    ],
)
def test_official_update_admits_every_approved_binding_context(
    binding_role: str,
    publisher_role: PublisherRole,
) -> None:
    document = candidate(
        f"update-{binding_role}",
        document_type="official_update",
        publisher_role=publisher_role,
        binding_role=binding_role,
        claim_types={"official_update"},
    )

    direct = admit_document(document, cutoff_date=date(2026, 8, 24))
    selected = select_canonical_document(
        (document,),
        required_role=DocumentRole.OFFICIAL_UPDATE,
        cutoff_date=date(2026, 8, 24),
    )

    assert direct.accepted
    assert selected.document_id == document.document_id
