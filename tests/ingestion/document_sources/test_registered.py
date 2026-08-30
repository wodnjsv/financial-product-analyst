from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime
from io import BytesIO
import json
from pathlib import Path
from typing import Any

import pytest

from financial_agent.documents import (
    DocumentRole,
    DocumentSourceAuditEntry,
    DocumentSourceAuditReport,
    DocumentSourceTarget,
    PublisherRole,
    SourceAuditStatus,
    SourceAuthorityTier,
    validate_document_source_report,
)
from financial_agent.ingestion.document_sources import DocumentDiscoveryContext
from financial_agent.ingestion.document_sources.registered import (
    RegisteredDocumentSourceAdapter,
)


_ROOT = Path(__file__).resolve().parents[3]
_AUTHORITY_REGISTRY = _ROOT / "config" / "official-document-authorities.json"
_LOCATOR_REGISTRY = _ROOT / "tests" / "fixtures" / "document_source_locators.json"
_CUTOFF = date(2026, 8, 24)
_TIER_2 = "tier_2_claim_owner"
_TIER_3 = "tier_3_exchange_association"
_PERMITTED_MATRIX = (
    (
        _TIER_2,
        "index_provider",
        DocumentRole.INDEX_METHODOLOGY,
        "subject_index",
        "index",
    ),
    (_TIER_2, "index_provider", DocumentRole.OFFICIAL_UPDATE, "subject_index", "index"),
    (_TIER_2, "policy_authority", DocumentRole.POLICY_BASE, "subject_policy", "product"),
    (
        _TIER_2,
        "policy_authority",
        DocumentRole.OFFICIAL_UPDATE,
        "subject_policy",
        "product",
    ),
    (
        _TIER_2,
        "policy_operator",
        DocumentRole.POLICY_BASE,
        "subject_policy",
        "institution",
    ),
    (
        _TIER_2,
        "policy_operator",
        DocumentRole.OFFICIAL_UPDATE,
        "subject_policy",
        "institution",
    ),
    (_TIER_3, "exchange", DocumentRole.OFFICIAL_UPDATE, "subject_product", "product"),
    (
        _TIER_3,
        "industry_association",
        DocumentRole.OFFICIAL_UPDATE,
        "subject_product",
        "product",
    ),
)
_FORBIDDEN_CROSS_BINDINGS = (
    (_TIER_2, "index_provider", "subject_product", "product"),
    (_TIER_2, "policy_operator", "subject_index", "index"),
    (_TIER_3, "exchange", "subject_index", "index"),
    (_TIER_3, "industry_association", "subject_policy", "institution"),
)


def _target(
    *,
    entity_id: str = "index-1",
    entity_type: str = "index",
    required_role: DocumentRole = DocumentRole.INDEX_METHODOLOGY,
    binding_role: str = "subject_index",
) -> DocumentSourceTarget:
    return DocumentSourceTarget(
        dataset_version="2026-08-24",
        entity_id=entity_id,
        entity_type=entity_type,
        canonical_name="Synthetic Index",
        product_family=None,
        required_role=required_role,
        binding_role=binding_role,
        identifiers=(("SYNTHETIC_INDEX_ID", "INDEX-1"),),
        cutoff_date=_CUTOFF,
    )


def _context(
    locator_registry_path: Path | None = _LOCATOR_REGISTRY,
) -> DocumentDiscoveryContext:
    return DocumentDiscoveryContext(
        cutoff_date=_CUTOFF,
        dart_api_key=None,
        sec_user_agent=None,
        locator_registry_path=locator_registry_path,
    )


class _Response(BytesIO):
    def __init__(
        self,
        payload: bytes = b"%",
        *,
        status: int = 206,
        content_type: str = "application/pdf",
        content_length: str | None = "1",
        location: str | None = None,
        fail_if_read: bool = False,
    ) -> None:
        super().__init__(payload)
        self.status = status
        self.headers: dict[str, str] = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = content_length
        if location is not None:
            self.headers["Location"] = location
        self.fail_if_read = fail_if_read
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self.fail_if_read:
            raise AssertionError("redirect or document body must not be read")
        return super().read(size)


class _SyntheticOpener:
    def __init__(self, responses: list[_Response] | None = None) -> None:
        self.responses = list(responses or [_Response()])
        self.calls: list[tuple[str, str, dict[str, str], float]] = []

    def open_no_redirect(
        self,
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Response:
        self.calls.append((url, method, dict(headers), timeout))
        if not self.responses:
            raise AssertionError("unexpected preflight request")
        return self.responses.pop(0)


def _payload(path: Path = _LOCATOR_REGISTRY) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_registry(tmp_path: Path, payload: dict[str, Any]) -> Path:
    destination = tmp_path / "reviewed-locators.json"
    destination.write_text(json.dumps(payload), encoding="utf-8")
    return destination


def _mutated_locator_registry(tmp_path: Path, **changes: object) -> Path:
    payload = _payload()
    payload["locators"][0].update(changes)
    return _write_registry(tmp_path, payload)


def _matrix_registries(
    tmp_path: Path,
    *,
    authority_tier: str,
    publisher_role: str,
    required_role: DocumentRole,
    binding_role: str,
    entity_type: str,
) -> tuple[Path, Path]:
    source_code = f"SYNTHETIC_{publisher_role.upper()}"
    host = f"{publisher_role.replace('_', '-')}.example.invalid"
    authority_path = tmp_path / "authorities.json"
    authority_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "authorities": [
                    {
                        "source_code": source_code,
                        "authority_tier": authority_tier,
                        "publisher_role": publisher_role,
                        "jurisdiction": "ZZ",
                        "allowed_hosts": [host],
                        "allowed_document_roles": [required_role.value],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    locator = _payload()["locators"][0]
    locator.update(
        entity_id=f"{entity_type}-1",
        entity_type=entity_type,
        required_role=required_role.value,
        binding_role=binding_role,
        document_id=f"document-{publisher_role}-{required_role.value}",
        source_code=source_code,
        authority_tier=authority_tier,
        publisher_code=source_code,
        publisher_role=publisher_role,
        source_locator=f"https://{host}/document.pdf",
        discovery_locator=f"https://{host}/documents",
        document_type=required_role.value,
    )
    return authority_path, _write_registry(
        tmp_path, {"schema_version": "1.0", "locators": [locator]}
    )


def _adapter(
    opener: _SyntheticOpener | None = None,
) -> tuple[RegisteredDocumentSourceAdapter, _SyntheticOpener]:
    actual_opener = opener or _SyntheticOpener()
    adapter = RegisteredDocumentSourceAdapter(actual_opener, _AUTHORITY_REGISTRY)
    return adapter, actual_opener


def test_adapter_exposes_immutable_context_from_reviewed_authority_registry() -> None:
    adapter, _ = _adapter()

    assert adapter.reviewed_authorities.authorities == (
        adapter.reviewed_authorities.authority_for("SYNTHETIC_INDEX_PROVIDER"),
    )
    authority = adapter.reviewed_authorities.authorities[0]
    assert authority.source_code == "SYNTHETIC_INDEX_PROVIDER"
    assert authority.publisher_code == "SYNTHETIC_INDEX_PROVIDER"
    assert authority.authority_tier is SourceAuthorityTier.TIER_2_CLAIM_OWNER
    assert authority.publisher_role is PublisherRole.INDEX_PROVIDER
    assert authority.jurisdiction == "ZZ"
    assert authority.allowed_hosts == frozenset({"index.example.invalid"})
    assert authority.terms_review_required is False
    assert authority.allowed_document_roles == frozenset(
        {DocumentRole.INDEX_METHODOLOGY, DocumentRole.OFFICIAL_UPDATE}
    )
    snapshot = adapter.reviewed_context(_context())
    locator = snapshot.locator_for("index-1", DocumentRole.INDEX_METHODOLOGY)
    assert locator is not None
    assert snapshot.locator_is_reviewed(locator)
    assert locator.document_id == "document-index-1-methodology"
    assert locator.source_locator == (
        "https://index.example.invalid/methodology.pdf"
    )


@pytest.mark.parametrize(
    ("status", "content_length"),
    ((200, None), (206, "1")),
)
def test_registered_locator_uses_only_bounded_ranged_get(
    status: int,
    content_length: str | None,
) -> None:
    adapter, opener = _adapter(
        _SyntheticOpener(
            [_Response(status=status, content_length=content_length)]
        )
    )

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert result.reason_code is None
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.source_code == "SYNTHETIC_INDEX_PROVIDER"
    assert candidate.authority_tier is SourceAuthorityTier.TIER_2_CLAIM_OWNER
    assert candidate.publisher_role is PublisherRole.INDEX_PROVIDER
    assert candidate.source_locator == "https://index.example.invalid/methodology.pdf"
    assert candidate.media_type == "application/pdf"
    assert opener.calls == [
        (
            "https://index.example.invalid/methodology.pdf",
            "GET",
            {"Accept-Encoding": "identity", "Range": "bytes=0-0"},
            15.0,
        )
    ]
    response = opener.responses
    assert response == []


def test_preflight_reads_at_most_one_byte_and_never_retains_a_body() -> None:
    response = _Response(b"%PDF synthetic body that must remain unread")
    opener = _SyntheticOpener([response])
    adapter, _ = _adapter(opener)

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert response.read_sizes == [1]
    assert response.closed
    assert not hasattr(result.candidates[0], "body")


def test_cutoff_day_fractional_timestamp_passes_canonical_report_validation(
    tmp_path: Path,
) -> None:
    timestamp = "2026-08-24T23:59:59.500000+09:00"
    path = _mutated_locator_registry(
        tmp_path,
        published_at=timestamp,
        available_at=timestamp,
    )
    adapter, _ = _adapter()
    target = _target()

    result = adapter.discover(target, _context(path))
    assert result.status is SourceAuditStatus.ELIGIBLE
    report = DocumentSourceAuditReport(
        schema_version="1.0",
        generated_at=datetime(2026, 8, 24, 12, tzinfo=UTC),
        cutoff_date=_CUTOFF,
        dataset_version=target.dataset_version,
        entries=(
            DocumentSourceAuditEntry(
                target=target,
                status=result.status,
                reason_code=result.reason_code,
                candidate=result.candidates[0],
            ),
        ),
    )

    assert validate_document_source_report(report)


@pytest.mark.parametrize(
    (
        "authority_tier",
        "publisher_role",
        "required_role",
        "binding_role",
        "entity_type",
    ),
    _PERMITTED_MATRIX,
)
def test_permitted_tier_publisher_role_binding_matrix(
    tmp_path: Path,
    authority_tier: str,
    publisher_role: str,
    required_role: DocumentRole,
    binding_role: str,
    entity_type: str,
) -> None:
    authority_path, locator_path = _matrix_registries(
        tmp_path,
        authority_tier=authority_tier,
        publisher_role=publisher_role,
        required_role=required_role,
        binding_role=binding_role,
        entity_type=entity_type,
    )
    opener = _SyntheticOpener()
    adapter = RegisteredDocumentSourceAdapter(opener, authority_path)
    target = _target(
        entity_id=f"{entity_type}-1",
        entity_type=entity_type,
        required_role=required_role,
        binding_role=binding_role,
    )

    result = adapter.discover(target, _context(locator_path))

    assert result.status is SourceAuditStatus.ELIGIBLE
    candidate = result.candidates[0]
    assert candidate.authority_tier.value == authority_tier
    assert candidate.publisher_role.value == publisher_role
    assert len(opener.calls) == 1


@pytest.mark.parametrize(
    ("authority_tier", "publisher_role", "binding_role", "entity_type"),
    _FORBIDDEN_CROSS_BINDINGS,
)
def test_forbidden_cross_binding_matrix_is_rejected_before_access(
    tmp_path: Path,
    authority_tier: str,
    publisher_role: str,
    binding_role: str,
    entity_type: str,
) -> None:
    authority_path, locator_path = _matrix_registries(
        tmp_path,
        authority_tier=authority_tier,
        publisher_role=publisher_role,
        required_role=DocumentRole.OFFICIAL_UPDATE,
        binding_role=binding_role,
        entity_type=entity_type,
    )
    opener = _SyntheticOpener()
    adapter = RegisteredDocumentSourceAdapter(opener, authority_path)
    target = _target(
        entity_id=f"{entity_type}-1",
        entity_type=entity_type,
        required_role=DocumentRole.OFFICIAL_UPDATE,
        binding_role=binding_role,
    )

    result = adapter.discover(target, _context(locator_path))

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "registered_publisher_role_not_approved"
    assert opener.calls == []


def test_missing_reviewed_locator_is_access_method_unverified() -> None:
    adapter, opener = _adapter()

    result = adapter.discover(_target(entity_id="index-missing"), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "registered_locator_missing"
    assert result.candidates == ()
    assert opener.calls == []


def test_missing_locator_registry_is_access_method_unverified() -> None:
    adapter, opener = _adapter()

    result = adapter.discover(_target(), _context(None))

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "registered_locator_registry_missing"
    assert opener.calls == []


@pytest.mark.parametrize(
    ("changes", "expected_status", "expected_reason"),
    (
        (
            {"source_locator": "https://unknown.example.invalid/methodology.pdf"},
            SourceAuditStatus.ACCESS_DENIED,
            "registered_locator_host_not_allowed",
        ),
        (
            {"authority_tier": "tier_3_exchange_association"},
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_authority_tier_mismatch",
        ),
        (
            {"publisher_role": "exchange"},
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_publisher_role_mismatch",
        ),
        (
            {"jurisdiction": "YY"},
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_jurisdiction_mismatch",
        ),
        (
            {"source_code": "UNKNOWN_OFFICIAL_SOURCE"},
            SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
            "registered_source_code_unknown",
        ),
    ),
)
def test_locator_must_match_registered_authority_exactly(
    tmp_path: Path,
    changes: dict[str, object],
    expected_status: SourceAuditStatus,
    expected_reason: str,
) -> None:
    path = _mutated_locator_registry(tmp_path, **changes)
    adapter, opener = _adapter()

    result = adapter.discover(_target(), _context(path))

    assert result.status is expected_status
    assert result.reason_code == expected_reason
    assert opener.calls == []


def test_product_locator_cannot_satisfy_an_index_role(tmp_path: Path) -> None:
    path = _mutated_locator_registry(
        tmp_path,
        entity_type="product",
        binding_role="subject_product",
    )
    adapter, opener = _adapter()

    result = adapter.discover(_target(), _context(path))

    assert result.status is SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
    assert result.reason_code == "registered_entity_binding_mismatch"
    assert opener.calls == []


@pytest.mark.parametrize("field", ("source_locator", "discovery_locator"))
def test_locator_rejects_secret_query_parameters(
    tmp_path: Path, field: str
) -> None:
    path = _mutated_locator_registry(
        tmp_path,
        **{field: "https://index.example.invalid/methodology.pdf?api_key=secret"},
    )
    adapter, opener = _adapter()

    result = adapter.discover(_target(), _context(path))

    assert result.status is SourceAuditStatus.ACCESS_DENIED
    assert result.reason_code == "registered_locator_unsafe"
    assert opener.calls == []


def test_duplicate_entity_role_keys_are_rejected_before_access(tmp_path: Path) -> None:
    payload = _payload()
    payload["locators"].append(deepcopy(payload["locators"][0]))
    path = _write_registry(tmp_path, payload)
    adapter, opener = _adapter()

    result = adapter.discover(_target(), _context(path))

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "registered_locator_registry_invalid"
    assert opener.calls == []


def test_malformed_locator_fields_are_rejected_before_access(tmp_path: Path) -> None:
    path = _mutated_locator_registry(tmp_path, document_version="")
    adapter, opener = _adapter()

    result = adapter.discover(_target(), _context(path))

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "registered_locator_registry_invalid"
    assert opener.calls == []


@pytest.mark.parametrize("field", ("published_at", "available_at"))
def test_post_cutoff_timestamps_are_ineligible(tmp_path: Path, field: str) -> None:
    path = _mutated_locator_registry(
        tmp_path, **{field: "2026-08-25T00:00:00+09:00"}
    )
    adapter, opener = _adapter()

    result = adapter.discover(_target(), _context(path))

    assert result.status is SourceAuditStatus.AFTER_CUTOFF_ONLY
    assert result.reason_code == "registered_after_cutoff_only"
    assert opener.calls == []


@pytest.mark.parametrize(
    ("declared", "actual"),
    (
        ("application/pdf", "text/html; charset=utf-8"),
        ("text/html", "application/pdf"),
    ),
)
def test_response_content_type_must_match_reviewed_media_type(
    tmp_path: Path, declared: str, actual: str
) -> None:
    path = _mutated_locator_registry(tmp_path, media_type=declared)
    opener = _SyntheticOpener([_Response(content_type=actual)])
    adapter, _ = _adapter(opener)

    result = adapter.discover(_target(), _context(path))

    assert result.status is SourceAuditStatus.MEDIA_TYPE_UNSUPPORTED
    assert result.reason_code == "registered_media_type_mismatch"


def test_external_redirect_is_rejected_before_redirect_target_access() -> None:
    redirect = _Response(
        b"redirect body",
        status=302,
        location="https://outside.example.invalid/methodology.pdf",
        fail_if_read=True,
    )
    opener = _SyntheticOpener([redirect])
    adapter, _ = _adapter(opener)

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_DENIED
    assert result.reason_code == "registered_redirect_host_not_allowed"
    assert [call[0] for call in opener.calls] == [
        "https://index.example.invalid/methodology.pdf"
    ]
    assert redirect.read_sizes == []
    assert redirect.closed


def test_same_authority_redirect_is_validated_then_preflighted() -> None:
    redirect = _Response(
        b"redirect body",
        status=302,
        location="/canonical-methodology.pdf",
        fail_if_read=True,
    )
    final = _Response()
    opener = _SyntheticOpener([redirect, final])
    adapter, _ = _adapter(opener)

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert [call[0] for call in opener.calls] == [
        "https://index.example.invalid/methodology.pdf",
        "https://index.example.invalid/canonical-methodology.pdf",
    ]
    assert redirect.read_sizes == []
    assert final.read_sizes == [1]


@pytest.mark.parametrize("content_length", ("0", "-1", "not-a-number"))
def test_nonzero_content_length_is_required_when_supplied(
    content_length: str,
) -> None:
    opener = _SyntheticOpener([_Response(content_length=content_length)])
    adapter, _ = _adapter(opener)

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "registered_content_length_invalid"


def test_terms_flag_returns_review_required_without_accepting_or_opening(
    tmp_path: Path,
) -> None:
    authority_payload = _payload(_AUTHORITY_REGISTRY)
    authority_payload["authorities"][0]["terms_review_required"] = True
    authority_path = tmp_path / "authorities.json"
    authority_path.write_text(json.dumps(authority_payload), encoding="utf-8")
    opener = _SyntheticOpener()
    adapter = RegisteredDocumentSourceAdapter(opener, authority_path)

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.TERMS_REVIEW_REQUIRED
    assert result.reason_code == "registered_terms_review_required"
    assert result.attempted_source is not None
    assert result.attempted_source.source_code == "SYNTHETIC_INDEX_PROVIDER"
    assert (
        result.attempted_source.source_locator
        == "https://index.example.invalid/methodology.pdf"
    )
    assert (
        result.attempted_source.discovery_locator
        == "https://index.example.invalid/documents"
    )
    assert opener.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("authority_tier", "tier_1_regulatory"),
        ("publisher_role", "asset_manager"),
    ),
)
def test_tracked_authority_registry_rejects_unapproved_tier_or_role(
    tmp_path: Path, field: str, value: str
) -> None:
    payload = _payload(_AUTHORITY_REGISTRY)
    payload["authorities"][0][field] = value
    authority_path = tmp_path / "authorities.json"
    authority_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=field):
        RegisteredDocumentSourceAdapter(_SyntheticOpener(), authority_path)


def test_tracked_authority_registry_contains_rules_but_no_target_locators() -> None:
    payload = _payload(_AUTHORITY_REGISTRY)

    assert set(payload) == {"schema_version", "authorities"}
    assert payload["schema_version"] == "1.0"
    assert payload["authorities"]
    forbidden = {
        "entity_id",
        "required_role",
        "source_locator",
        "discovery_locator",
        "document_id",
    }
    assert all(forbidden.isdisjoint(authority) for authority in payload["authorities"])
