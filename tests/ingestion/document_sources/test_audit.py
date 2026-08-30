from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest

from financial_agent.documents import (
    DocumentRole,
    DocumentSourceCandidate,
    DocumentSourceTarget,
    PublisherRole,
    SourceAuditStatus,
    SourceAuthorityTier,
)
from financial_agent.ingestion.document_sources import (
    DocumentDiscoveryContext,
    SourceAdapterResult,
)
from financial_agent.ingestion.document_sources.audit import (
    audit_document_sources,
    document_source_audit_passed,
)


_CUTOFF = date(2026, 8, 24)
_NOW = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
_SEC_IDENTIFIERS = (
    ("SEC_CIK", "1445546"),
    ("SEC_SERIES_ID", "S000000001"),
    ("SEC_CLASS_ID", "C000000001"),
)


def _target(
    entity_id: str,
    *,
    entity_type: str = "product",
    product_family: str | None = "domestic_etf",
    required_role: DocumentRole = DocumentRole.PRODUCT_SUMMARY,
    binding_role: str = "subject_product",
    identifiers: tuple[tuple[str, str], ...] = (("SYNTHETIC_ID", "1"),),
) -> DocumentSourceTarget:
    return DocumentSourceTarget(
        dataset_version="2026-08-24",
        entity_id=entity_id,
        entity_type=entity_type,
        canonical_name=f"Synthetic {entity_id}",
        product_family=product_family,
        required_role=required_role,
        binding_role=binding_role,
        identifiers=identifiers,
        cutoff_date=_CUTOFF,
    )


def _source_candidate(
    document_id: str,
    *,
    source_code: str = "DART",
    document_type: str = "summary_prospectus",
    publisher_role: PublisherRole = PublisherRole.REGULATOR_DISCLOSURE,
    document_version: str | None = "2026.1",
    effective_from: date | None = date(2026, 8, 1),
    jurisdiction: str = "KR",
) -> DocumentSourceCandidate:
    return DocumentSourceCandidate(
        document_id=document_id,
        source_code=source_code,
        authority_tier=(
            SourceAuthorityTier.TIER_1_REGULATORY
            if source_code in {"DART", "SEC"}
            else SourceAuthorityTier.TIER_2_CLAIM_OWNER
        ),
        publisher_code=f"{source_code}-PUBLISHER",
        publisher_role=publisher_role,
        document_type=document_type,
        document_version=document_version,
        source_locator=f"https://official.example.invalid/{document_id}.pdf",
        discovery_locator=f"https://official.example.invalid/{document_id}.pdf",
        jurisdiction=jurisdiction,
        original_language="ko" if jurisdiction == "KR" else "en",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        available_at=datetime(2026, 8, 1, tzinfo=UTC),
        effective_from=effective_from,
        effective_to=None,
        media_type="application/pdf",
        accession_or_receipt_id=document_id,
    )


def _context() -> DocumentDiscoveryContext:
    return DocumentDiscoveryContext(
        cutoff_date=_CUTOFF,
        dart_api_key="synthetic",
        sec_user_agent="Synthetic contact@example.invalid",
        locator_registry_path=None,
    )


@dataclass
class _StubAdapter:
    source_code: str
    result: SourceAdapterResult
    error: BaseException | None = None
    calls: list[DocumentSourceTarget] = field(default_factory=list)

    def supports(self, target: DocumentSourceTarget) -> bool:
        return True

    def discover(
        self,
        target: DocumentSourceTarget,
        context: DocumentDiscoveryContext,
    ) -> SourceAdapterResult:
        self.calls.append(target)
        if self.error is not None:
            raise self.error
        return self.result


def _unavailable_adapter(
    source_code: str,
    status: SourceAuditStatus = SourceAuditStatus.DOCUMENT_NOT_FOUND,
) -> _StubAdapter:
    return _StubAdapter(
        source_code,
        SourceAdapterResult(
            status=status,
            reason_code=f"{source_code.lower()}_{status.value}",
            candidates=(),
        ),
    )


def _eligible_adapter(
    source_code: str,
    *candidates: DocumentSourceCandidate,
) -> _StubAdapter:
    return _StubAdapter(
        source_code,
        SourceAdapterResult(
            status=SourceAuditStatus.ELIGIBLE,
            reason_code=None,
            candidates=tuple(candidates),
        ),
    )


def test_audit_does_not_fallback_after_tier_one_product_failure() -> None:
    dart = _unavailable_adapter("DART")
    manager = _eligible_adapter("MANAGER", _source_candidate("manager"))

    report = audit_document_sources(
        targets=(_target("domestic-etf"),),
        adapters=(dart, manager),
        context=_context(),
        generated_at=_NOW,
    )

    assert report.entries[0].status is SourceAuditStatus.DOCUMENT_NOT_FOUND
    assert report.entries[0].candidate is None
    assert dart.calls == [report.entries[0].target]
    assert manager.calls == []
    assert document_source_audit_passed(report) is False


def test_domestic_bond_is_not_applicable_without_adapter_calls() -> None:
    dart = _unavailable_adapter("DART")
    registered = _unavailable_adapter("REGISTERED")

    report = audit_document_sources(
        targets=(_target("bond", product_family="domestic_bond"),),
        adapters=(dart, registered),
        context=_context(),
        generated_at=_NOW,
    )

    assert report.entries[0].status is SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE
    assert report.entries[0].reason_code == "domestic_bond_not_in_document_scope"
    assert dart.calls == []
    assert registered.calls == []
    assert document_source_audit_passed(report) is True


def test_duplicate_index_target_is_audited_once() -> None:
    target = _target(
        "index-1",
        entity_type="index",
        product_family=None,
        required_role=DocumentRole.INDEX_METHODOLOGY,
        binding_role="subject_index",
    )
    registered = _unavailable_adapter("REGISTERED")

    report = audit_document_sources(
        targets=(target, target),
        adapters=(registered,),
        context=_context(),
        generated_at=_NOW,
    )

    assert len(report.entries) == 1
    assert registered.calls == [target]


@pytest.mark.parametrize("product_family", ("domestic_etf", "public_fund"))
def test_domestic_product_families_route_only_to_dart(
    product_family: str,
) -> None:
    dart = _unavailable_adapter("DART")
    registered = _unavailable_adapter("REGISTERED")

    audit_document_sources(
        targets=(_target(product_family, product_family=product_family),),
        adapters=(registered, dart),
        context=_context(),
        generated_at=_NOW,
    )

    assert len(dart.calls) == 1
    assert registered.calls == []


def test_overseas_summary_routes_to_sec_only_with_complete_exact_identity() -> None:
    complete = _target(
        "overseas-complete",
        product_family="overseas_etf",
        identifiers=_SEC_IDENTIFIERS,
    )
    incomplete = _target(
        "overseas-incomplete",
        product_family="overseas_etf",
        identifiers=_SEC_IDENTIFIERS[:-1],
    )
    sec = _unavailable_adapter("SEC")
    registered = _unavailable_adapter(
        "REGISTERED", SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    )

    report = audit_document_sources(
        targets=(complete, incomplete),
        adapters=(registered, sec),
        context=_context(),
        generated_at=_NOW,
    )

    assert sec.calls == [complete]
    assert registered.calls == [incomplete]
    assert report.entries[1].status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED


@pytest.mark.parametrize(
    "required_role",
    (DocumentRole.PRODUCT_FULL, DocumentRole.OFFICIAL_UPDATE),
)
def test_sec_is_never_called_for_an_unsupported_overseas_role(
    required_role: DocumentRole,
) -> None:
    sec = _unavailable_adapter("SEC")
    registered = _unavailable_adapter("REGISTERED")
    target = _target(
        f"overseas-{required_role.value}",
        product_family="overseas_etf",
        required_role=required_role,
        identifiers=_SEC_IDENTIFIERS,
    )

    report = audit_document_sources(
        targets=(target,),
        adapters=(sec, registered),
        context=_context(),
        generated_at=_NOW,
    )

    assert sec.calls == []
    if required_role is DocumentRole.OFFICIAL_UPDATE:
        assert registered.calls == [target]
    else:
        assert registered.calls == []
        assert report.entries[0].status is SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE


@pytest.mark.parametrize(
    ("entity_type", "required_role", "binding_role"),
    (
        ("index", DocumentRole.INDEX_METHODOLOGY, "subject_index"),
        ("policy", DocumentRole.POLICY_BASE, "subject_policy"),
        ("policy", DocumentRole.OFFICIAL_UPDATE, "subject_policy"),
    ),
)
def test_claim_owner_targets_route_only_to_registered_adapter(
    entity_type: str,
    required_role: DocumentRole,
    binding_role: str,
) -> None:
    registered = _unavailable_adapter("REGISTERED")
    dart = _unavailable_adapter("DART")
    target = _target(
        f"{entity_type}-{required_role.value}",
        entity_type=entity_type,
        product_family=None,
        required_role=required_role,
        binding_role=binding_role,
    )

    audit_document_sources(
        targets=(target,),
        adapters=(dart, registered),
        context=_context(),
        generated_at=_NOW,
    )

    assert registered.calls == [target]
    assert dart.calls == []


def test_unavailable_targets_remain_in_the_report() -> None:
    dart = _unavailable_adapter("DART", SourceAuditStatus.CREDENTIALS_MISSING)

    report = audit_document_sources(
        targets=(_target("a"), _target("b")),
        adapters=(dart,),
        context=_context(),
        generated_at=_NOW,
    )

    assert [entry.target.entity_id for entry in report.entries] == ["a", "b"]
    assert all(
        entry.status is SourceAuditStatus.CREDENTIALS_MISSING
        for entry in report.entries
    )


def test_adapter_exception_becomes_stable_unverified_status() -> None:
    dart = _unavailable_adapter("DART")
    dart.error = RuntimeError("api_key=must-not-escape")

    report = audit_document_sources(
        targets=(_target("domestic-etf"),),
        adapters=(dart,),
        context=_context(),
        generated_at=_NOW,
    )

    entry = report.entries[0]
    assert entry.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert entry.reason_code == "dart_access_method_unverified"
    assert "must-not-escape" not in repr(report)


def test_canonical_version_failure_is_a_stable_audit_entry() -> None:
    candidate = _source_candidate(
        "unknown-version",
        document_version=None,
        effective_from=None,
    )

    report = audit_document_sources(
        targets=(_target("domestic-etf"),),
        adapters=(_eligible_adapter("DART", candidate),),
        context=_context(),
        generated_at=_NOW,
    )

    entry = report.entries[0]
    assert entry.status is SourceAuditStatus.VERSION_UNKNOWN
    assert entry.reason_code == "effective_version_not_verified"
    assert entry.candidate is None


def test_canonical_authority_failure_is_a_stable_audit_entry() -> None:
    candidate = _source_candidate(
        "manager-copy",
        source_code="DART",
        publisher_role=PublisherRole.ASSET_MANAGER,
    )

    report = audit_document_sources(
        targets=(_target("domestic-etf"),),
        adapters=(_eligible_adapter("DART", candidate),),
        context=_context(),
        generated_at=_NOW,
    )

    entry = report.entries[0]
    assert entry.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert entry.reason_code == "publisher_role_not_approved"
    assert entry.candidate is None


def test_canonical_selection_returns_only_the_latest_role_candidate() -> None:
    older = _source_candidate(
        "older",
        source_code="REGISTERED",
        document_type="index_methodology",
        publisher_role=PublisherRole.INDEX_PROVIDER,
        effective_from=date(2026, 7, 1),
    )
    latest = _source_candidate(
        "latest",
        source_code="REGISTERED",
        document_type="index_methodology",
        publisher_role=PublisherRole.INDEX_PROVIDER,
        effective_from=date(2026, 8, 1),
    )
    target = _target(
        "index-1",
        entity_type="index",
        product_family=None,
        required_role=DocumentRole.INDEX_METHODOLOGY,
        binding_role="subject_index",
    )

    report = audit_document_sources(
        targets=(target,),
        adapters=(_eligible_adapter("REGISTERED", older, latest),),
        context=_context(),
        generated_at=_NOW,
    )

    assert report.entries[0].status is SourceAuditStatus.ELIGIBLE
    assert report.entries[0].candidate == latest
    assert document_source_audit_passed(report) is True


def test_report_is_identical_when_targets_adapters_and_candidates_are_reordered() -> None:
    target_a = _target("a")
    target_b = _target(
        "index-b",
        entity_type="index",
        product_family=None,
        required_role=DocumentRole.INDEX_METHODOLOGY,
        binding_role="subject_index",
    )
    first = _source_candidate(
        "first",
        source_code="REGISTERED",
        document_type="index_methodology",
        publisher_role=PublisherRole.INDEX_PROVIDER,
        effective_from=date(2026, 7, 1),
    )
    second = _source_candidate(
        "second",
        source_code="REGISTERED",
        document_type="index_methodology",
        publisher_role=PublisherRole.INDEX_PROVIDER,
        effective_from=date(2026, 8, 1),
    )

    report_one = audit_document_sources(
        targets=(target_b, target_a),
        adapters=(
            _eligible_adapter("REGISTERED", second, first),
            _unavailable_adapter("DART"),
        ),
        context=_context(),
        generated_at=_NOW,
    )
    report_two = audit_document_sources(
        targets=(target_a, target_b),
        adapters=(
            _unavailable_adapter("DART"),
            _eligible_adapter("REGISTERED", first, second),
        ),
        context=_context(),
        generated_at=_NOW,
    )

    assert report_one == report_two
