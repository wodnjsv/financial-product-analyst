from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from io import BytesIO
import json
from urllib.parse import urlparse

import pytest

from financial_agent.documents import (
    DocumentRole,
    DocumentSourceTarget,
    PublisherRole,
    SourceAuditStatus,
    SourceAuthorityTier,
)
from financial_agent.ingestion.document_sources import DocumentDiscoveryContext
from financial_agent.ingestion.document_sources.sec import SecDocumentSourceAdapter


_CUTOFF = date(2026, 8, 24)
_CIK = "1445546"
_PADDED_CIK = "0001445546"
_SERIES_ID = "S000000001"
_CLASS_ID = "C000000001"
_USER_AGENT = "Synthetic Research contact@example.invalid"
_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{_PADDED_CIK}.json"


def _target(
    *,
    identifiers: tuple[tuple[str, str], ...] = (
        ("SEC_CIK", _CIK),
        ("SEC_SERIES_ID", _SERIES_ID),
        ("SEC_CLASS_ID", _CLASS_ID),
    ),
    product_family: str = "overseas_etf",
    required_role: DocumentRole = DocumentRole.PRODUCT_SUMMARY,
) -> DocumentSourceTarget:
    return DocumentSourceTarget(
        dataset_version="2026-08-24",
        entity_id="product-1",
        entity_type="product",
        canonical_name="Synthetic Overseas ETF",
        product_family=product_family,
        required_role=required_role,
        binding_role="subject_product",
        identifiers=identifiers,
        cutoff_date=_CUTOFF,
    )


def _context(user_agent: str | None = _USER_AGENT) -> DocumentDiscoveryContext:
    return DocumentDiscoveryContext(
        cutoff_date=_CUTOFF,
        dart_api_key=None,
        sec_user_agent=user_agent,
        locator_registry_path=None,
    )


def _filing(
    accession: str = "0001445546-25-008729",
    *,
    form: str = "497K",
    filing_date: str = "2025-08-20",
    acceptance: str = "2025-08-20T16:30:00.000Z",
    primary_document: str = "synthetic-497k.htm",
    description: str = "Summary Prospectus",
) -> dict[str, str]:
    return {
        "accessionNumber": accession,
        "filingDate": filing_date,
        "acceptanceDateTime": acceptance,
        "form": form,
        "primaryDocument": primary_document,
        "primaryDocDescription": description,
    }


_FILING_FIELDS = tuple(_filing())


def _columns(filings: list[dict[str, str]]) -> dict[str, list[str]]:
    return {field: [filing[field] for filing in filings] for field in _FILING_FIELDS}


def _submissions(
    filings: list[dict[str, str]],
    *,
    files: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "cik": _PADDED_CIK,
        "filings": {
            "recent": _columns(filings),
            "files": [] if files is None else files,
        },
    }


def _archive_base(accession: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{_CIK}/"
        f"{accession.replace('-', '')}"
    )


def _index(accession: str, primary_document: str) -> dict[str, object]:
    return {
        "directory": {
            "name": urlparse(_archive_base(accession)).path,
            "item": [
                {
                    "last-modified": "2025-08-20 16:31:00",
                    "name": primary_document,
                    "type": "text/html",
                    "size": "12345",
                },
                {
                    "last-modified": "2025-08-20 16:31:00",
                    "name": f"{accession}.hdr.sgml",
                    "type": "text/plain",
                    "size": "2345",
                },
            ],
        }
    }


def _header(
    *,
    cik: str = _PADDED_CIK,
    series_id: str = _SERIES_ID,
    class_id: str = _CLASS_ID,
) -> bytes:
    return (
        "<SEC-HEADER>\n"
        "<SERIES-AND-CLASSES-CONTRACTS-DATA>\n"
        "<EXISTING-SERIES-AND-CLASSES-CONTRACTS>\n"
        "<SERIES>\n"
        f"<OWNER-CIK>{cik}\n"
        f"<SERIES-ID>{series_id}\n"
        "<CLASS-CONTRACT>\n"
        f"<CLASS-CONTRACT-ID>{class_id}\n"
        "</CLASS-CONTRACT>\n"
        "</SERIES>\n"
        "</EXISTING-SERIES-AND-CLASSES-CONTRACTS>\n"
        "</SERIES-AND-CLASSES-CONTRACTS-DATA>\n"
        "</SEC-HEADER>\n"
    ).encode()


class _Response(BytesIO):
    def __init__(
        self,
        payload: bytes,
        *,
        status: int = 200,
        location: str | None = None,
        fail_if_read: bool = False,
    ) -> None:
        super().__init__(payload)
        self.status = status
        self.headers = {} if location is None else {"Location": location}
        self.fail_if_read = fail_if_read
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self.fail_if_read:
            raise AssertionError("primary filing body must not be read")
        return super().read(size)


class _SyntheticOpener:
    def __init__(
        self,
        responses: dict[str, object],
        *,
        statuses: dict[str, int] | None = None,
        error: Exception | None = None,
        redirect_from: str | None = None,
        redirect_to: str | None = None,
    ) -> None:
        self.responses = responses
        self.statuses = {} if statuses is None else statuses
        self.error = error
        self.redirect_from = redirect_from
        self.redirect_to = redirect_to
        self.redirected = False
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.methods: list[str] = []
        self.opened_responses: list[_Response] = []

    def open_no_redirect(
        self,
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Response:
        del timeout
        self.calls.append((url, dict(headers)))
        self.methods.append(method)
        if self.error is not None:
            raise self.error
        if (
            not self.redirected
            and url == self.redirect_from
            and self.redirect_to is not None
        ):
            self.redirected = True
            response = _Response(
                b"redirect body must not be read",
                status=302,
                location=self.redirect_to,
                fail_if_read=True,
            )
            self.opened_responses.append(response)
            return response
        if url not in self.responses and url.endswith((".htm", ".html")):
            response = _Response(b"primary body", fail_if_read=True)
            self.opened_responses.append(response)
            return response
        if url not in self.responses:
            raise AssertionError(f"unexpected synthetic URL: {url}")
        payload = self.responses[url]
        encoded = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode()
        )
        response = _Response(encoded, status=self.statuses.get(url, 200))
        self.opened_responses.append(response)
        return response


def _responses(
    filings: list[dict[str, str]],
    *,
    bindings: dict[str, tuple[str, str, str]] | None = None,
    files: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    responses: dict[str, object] = {
        _SUBMISSIONS_URL: _submissions(filings, files=files)
    }
    for filing in filings:
        accession = filing["accessionNumber"]
        primary = filing["primaryDocument"]
        base = _archive_base(accession)
        responses[f"{base}/index.json"] = _index(accession, primary)
        binding = (
            (_PADDED_CIK, _SERIES_ID, _CLASS_ID)
            if bindings is None
            else bindings[accession]
        )
        responses[f"{base}/{accession}.hdr.sgml"] = _header(
            cik=binding[0], series_id=binding[1], class_id=binding[2]
        )
    return responses


def _discover(
    filings: list[dict[str, str]],
    *,
    bindings: dict[str, tuple[str, str, str]] | None = None,
) -> tuple[object, _SyntheticOpener]:
    opener = _SyntheticOpener(_responses(filings, bindings=bindings))
    result = SecDocumentSourceAdapter(opener).discover(_target(), _context())
    return result, opener


def test_sec_returns_only_497k_bound_to_exact_series_and_class() -> None:
    filing = _filing()
    result, opener = _discover([filing])

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.document_type == "summary_prospectus"
    assert candidate.accession_or_receipt_id == "0001445546-25-008729"
    assert candidate.source_locator == (
        f"{_archive_base(filing['accessionNumber'])}/synthetic-497k.htm"
    )
    assert candidate.discovery_locator.endswith(
        "/0001445546-25-008729-index.html"
    )
    assert candidate.authority_tier is SourceAuthorityTier.TIER_1_REGULATORY
    assert candidate.publisher_role is PublisherRole.REGULATOR_DISCLOSURE
    assert candidate.effective_from is None
    assert all(headers["User-Agent"] == _USER_AGENT for _, headers in opener.calls)


def test_sec_discovery_never_requests_primary_document_body() -> None:
    filing = _filing()
    result, opener = _discover([filing])

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert all(
        url != f"{_archive_base(filing['accessionNumber'])}/synthetic-497k.htm"
        for url, _ in opener.calls
    )
    assert [url.rsplit("/", 1)[-1] for url, _ in opener.calls] == [
        f"CIK{_PADDED_CIK}.json",
        "index.json",
        f"{filing['accessionNumber']}.hdr.sgml",
    ]


@pytest.mark.parametrize("user_agent", (None, "", "   ", "no-email"))
def test_sec_missing_or_invalid_user_agent_fails_before_network(
    user_agent: str | None,
) -> None:
    opener = _SyntheticOpener({})

    result = SecDocumentSourceAdapter(opener).discover(
        _target(), _context(user_agent)
    )

    assert result.status is SourceAuditStatus.CREDENTIALS_MISSING
    assert result.reason_code == "sec_user_agent_missing"
    assert result.candidates == ()
    assert result.attempted_source is not None
    assert result.attempted_source.source_code == "SEC"
    assert result.attempted_source.source_locator is None
    assert result.attempted_source.discovery_locator is None
    assert opener.calls == []


@pytest.mark.parametrize(
    ("identifiers", "status", "reason"),
    (
        (
            (("SEC_SERIES_ID", _SERIES_ID), ("SEC_CLASS_ID", _CLASS_ID)),
            SourceAuditStatus.IDENTIFIER_MISSING,
            "sec_cik_missing",
        ),
        (
            (("SEC_CIK", _CIK), ("SEC_CLASS_ID", _CLASS_ID)),
            SourceAuditStatus.IDENTIFIER_MISSING,
            "sec_series_id_missing",
        ),
        (
            (("SEC_CIK", _CIK), ("SEC_SERIES_ID", _SERIES_ID)),
            SourceAuditStatus.IDENTIFIER_MISSING,
            "sec_class_id_missing",
        ),
        (
            (
                ("SEC_CIK", _CIK),
                ("SEC_CIK", "1445547"),
                ("SEC_SERIES_ID", _SERIES_ID),
                ("SEC_CLASS_ID", _CLASS_ID),
            ),
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "sec_cik_ambiguous",
        ),
        (
            (
                ("SEC_CIK", _CIK),
                ("SEC_SERIES_ID", _SERIES_ID),
                ("SEC_SERIES_ID", "S000000002"),
                ("SEC_CLASS_ID", _CLASS_ID),
            ),
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "sec_series_id_ambiguous",
        ),
        (
            (
                ("SEC_CIK", _CIK),
                ("SEC_SERIES_ID", _SERIES_ID),
                ("SEC_CLASS_ID", _CLASS_ID),
                ("SEC_CLASS_ID", "C000000002"),
            ),
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "sec_class_id_ambiguous",
        ),
    ),
)
def test_sec_requires_one_exact_cik_series_and_class_before_network(
    identifiers: tuple[tuple[str, str], ...],
    status: SourceAuditStatus,
    reason: str,
) -> None:
    opener = _SyntheticOpener({})

    result = SecDocumentSourceAdapter(opener).discover(
        _target(identifiers=identifiers), _context()
    )

    assert result.status is status
    assert result.reason_code == reason
    assert opener.calls == []


@pytest.mark.parametrize(
    "identifiers",
    (
        (
            ("SEC_CIK", "not-cik"),
            ("SEC_SERIES_ID", _SERIES_ID),
            ("SEC_CLASS_ID", _CLASS_ID),
        ),
        (
            ("SEC_CIK", _CIK),
            ("SEC_SERIES_ID", "series-1"),
            ("SEC_CLASS_ID", _CLASS_ID),
        ),
        (
            ("SEC_CIK", _CIK),
            ("SEC_SERIES_ID", _SERIES_ID),
            ("SEC_CLASS_ID", "class-1"),
        ),
    ),
)
def test_sec_rejects_invalid_exact_identifiers_before_network(
    identifiers: tuple[tuple[str, str], ...],
) -> None:
    opener = _SyntheticOpener({})

    result = SecDocumentSourceAdapter(opener).discover(
        _target(identifiers=identifiers), _context()
    )

    assert result.status is SourceAuditStatus.IDENTIFIER_MISSING
    assert result.reason_code == "sec_identifier_invalid"
    assert opener.calls == []


def test_sec_excludes_filing_for_another_class_under_same_cik() -> None:
    filing = _filing()
    result, _ = _discover(
        [filing],
        bindings={
            filing["accessionNumber"]: (
                _PADDED_CIK,
                _SERIES_ID,
                "C000000999",
            )
        },
    )

    assert result.status is SourceAuditStatus.DOCUMENT_NOT_FOUND
    assert result.reason_code == "sec_exact_series_class_not_found"
    assert result.candidates == ()


def test_sec_filters_after_cutoff_before_opening_filing_metadata() -> None:
    filing = _filing(
        filing_date="2026-08-25",
        acceptance="2026-08-25T00:00:00.000Z",
    )
    opener = _SyntheticOpener(_responses([filing]))

    result = SecDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.AFTER_CUTOFF_ONLY
    assert result.reason_code == "sec_after_cutoff_only"
    assert [url for url, _ in opener.calls] == [_SUBMISSIONS_URL]


def test_sec_filters_post_cutoff_acceptance_before_opening_filing_metadata() -> None:
    filing = _filing(
        filing_date="2026-08-24",
        acceptance="2026-08-25T00:00:00.000Z",
    )
    opener = _SyntheticOpener(_responses([filing]))

    result = SecDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.AFTER_CUTOFF_ONLY
    assert [url for url, _ in opener.calls] == [_SUBMISSIONS_URL]


def test_sec_selects_current_497k_and_not_older_497k() -> None:
    older = _filing(
        "0001445546-25-000111",
        filing_date="2025-01-02",
        acceptance="2025-01-02T10:00:00.000Z",
        primary_document="older.htm",
    )
    current = _filing()
    result, _ = _discover([older, current])

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert [candidate.accession_or_receipt_id for candidate in result.candidates] == [
        current["accessionNumber"]
    ]


@pytest.mark.parametrize("form", ("485BPOS", "N-1A", "N-1A/A"))
def test_sec_uses_full_prospectus_only_when_no_bound_497k(form: str) -> None:
    full = _filing(
        form=form,
        primary_document="full-prospectus.htm",
        description="Prospectus",
    )
    result, _ = _discover([full])

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.document_type == "full_prospectus"
    assert candidate.effective_from is None


def test_sec_497k_prevents_full_prospectus_fallback() -> None:
    summary = _filing()
    full = _filing(
        "0001445546-25-007000",
        form="485BPOS",
        primary_document="full.htm",
        description="Prospectus",
    )
    result, _ = _discover([full, summary])

    assert [candidate.document_type for candidate in result.candidates] == [
        "summary_prospectus"
    ]


def test_sec_does_not_admit_nominal_497_supplement_from_description() -> None:
    supplement = _filing(
        form="497",
        primary_document="strategy-supplement.htm",
        description="Supplement - Principal Investment Strategy Update",
    )
    result, opener = _discover([supplement])

    assert result.status is SourceAuditStatus.DOCUMENT_NOT_FOUND
    assert result.reason_code == "sec_prospectus_not_found"
    assert result.candidates == ()
    assert [url for url, _ in opener.calls] == [_SUBMISSIONS_URL]


def test_sec_does_not_admit_administrative_497_with_claim_words() -> None:
    administrative = _filing(
        form="497",
        primary_document="administrative-supplement.htm",
        description=(
            "Supplement to Investment Strategy Materials - "
            "Distributor Contact Change"
        ),
    )
    result, opener = _discover([administrative])

    assert result.status is SourceAuditStatus.DOCUMENT_NOT_FOUND
    assert result.reason_code == "sec_prospectus_not_found"
    assert result.candidates == ()
    assert [url for url, _ in opener.calls] == [_SUBMISSIONS_URL]


def test_sec_excludes_generic_497_definitive_material() -> None:
    generic = _filing(
        form="497",
        primary_document="fee-update.htm",
        description="Definitive Materials - Fee and Distributor Update",
    )
    result, _ = _discover([generic])

    assert result.status is SourceAuditStatus.DOCUMENT_NOT_FOUND
    assert result.reason_code == "sec_prospectus_not_found"
    assert result.candidates == ()


def test_sec_follows_older_submissions_pagination() -> None:
    older_url = (
        f"https://data.sec.gov/submissions/"
        f"CIK{_PADDED_CIK}-submissions-001.json"
    )
    filing = _filing()
    files = [
        {
            "name": f"CIK{_PADDED_CIK}-submissions-001.json",
            "filingCount": 1,
            "filingFrom": "2025-08-20",
            "filingTo": "2025-08-20",
        }
    ]
    responses = _responses([], files=files)
    responses[older_url] = _columns([filing])
    responses.update(
        {
            url: payload
            for url, payload in _responses([filing]).items()
            if url != _SUBMISSIONS_URL
        }
    )
    opener = _SyntheticOpener(responses)

    result = SecDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert [url for url, _ in opener.calls][:2] == [_SUBMISSIONS_URL, older_url]


@pytest.mark.parametrize(
    "payload",
    (
        b"not-json",
        {"cik": _PADDED_CIK, "filings": {"recent": {}}},
        _submissions([_filing()]) | {"cik": "9999999999"},
    ),
)
def test_sec_malformed_submissions_json_fails_closed(payload: object) -> None:
    opener = _SyntheticOpener({_SUBMISSIONS_URL: payload})

    result = SecDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "sec_response_malformed"
    assert result.candidates == ()


def test_sec_malformed_filing_index_json_fails_closed() -> None:
    filing = _filing()
    responses = _responses([filing])
    responses[f"{_archive_base(filing['accessionNumber'])}/index.json"] = {
        "directory": {"name": "wrong", "item": []}
    }
    opener = _SyntheticOpener(responses)

    result = SecDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "sec_response_malformed"


@pytest.mark.parametrize(
    ("status_code", "expected", "reason"),
    (
        (403, SourceAuditStatus.ACCESS_DENIED, "sec_access_denied"),
        (429, SourceAuditStatus.RATE_LIMITED, "sec_rate_limited"),
    ),
)
def test_sec_maps_403_and_429_without_reading_response_body(
    status_code: int,
    expected: SourceAuditStatus,
    reason: str,
) -> None:
    opener = _SyntheticOpener(
        {_SUBMISSIONS_URL: b"secret upstream response"},
        statuses={_SUBMISSIONS_URL: status_code},
    )

    result = SecDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is expected
    assert result.reason_code == reason
    assert result.attempted_source is not None
    assert result.attempted_source.source_code == "SEC"
    assert result.attempted_source.source_locator is None
    assert result.attempted_source.discovery_locator == _SUBMISSIONS_URL
    assert opener.opened_responses[0].read_sizes == []


def test_sec_user_agent_never_appears_in_public_result_or_error() -> None:
    opener = _SyntheticOpener(
        {}, error=RuntimeError(f"blocked User-Agent={_USER_AGENT}")
    )

    result = SecDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "sec_access_method_unverified"
    assert _USER_AGENT not in repr(result)
    assert _USER_AGENT not in str(result)


@pytest.mark.parametrize(
    "location",
    (
        "https://evil.example.invalid/steal",
        "http://data.sec.gov/submissions/CIK0001445546.json",
        "https://data.sec.gov:444/submissions/CIK0001445546.json",
        f"{_archive_base('0001445546-25-008729')}/synthetic-497k.htm",
    ),
)
def test_sec_denies_unsafe_redirect_before_following(location: str) -> None:
    opener = _SyntheticOpener(
        {_SUBMISSIONS_URL: _submissions([])},
        redirect_from=_SUBMISSIONS_URL,
        redirect_to=location,
    )

    result = SecDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_DENIED
    assert result.reason_code == "sec_redirect_location_denied"
    assert [url for url, _ in opener.calls] == [_SUBMISSIONS_URL]


def _assert_metadata_redirect_denied(
    responses: dict[str, object],
    *,
    redirect_from: str,
    redirect_to: str,
) -> None:
    opener = _SyntheticOpener(
        responses,
        redirect_from=redirect_from,
        redirect_to=redirect_to,
    )

    result = SecDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_DENIED
    assert result.reason_code == "sec_redirect_location_denied"
    called_urls = [url for url, _ in opener.calls]
    assert redirect_from in called_urls
    assert redirect_to not in called_urls
    assert opener.opened_responses[-1].read_sizes == []


def test_sec_denies_cross_cik_submissions_redirect_before_target_request() -> None:
    redirected = "https://data.sec.gov/submissions/CIK0001445547.json"

    _assert_metadata_redirect_denied(
        {_SUBMISSIONS_URL: _submissions([])},
        redirect_from=_SUBMISSIONS_URL,
        redirect_to=redirected,
    )


def test_sec_denies_main_to_older_submissions_redirect_before_target_request() -> None:
    redirected = (
        f"https://data.sec.gov/submissions/CIK{_PADDED_CIK}-submissions-001.json"
    )

    _assert_metadata_redirect_denied(
        {_SUBMISSIONS_URL: _submissions([])},
        redirect_from=_SUBMISSIONS_URL,
        redirect_to=redirected,
    )


def test_sec_denies_cross_accession_index_redirect_before_target_request() -> None:
    filing = _filing()
    source = f"{_archive_base(filing['accessionNumber'])}/index.json"
    redirected = f"{_archive_base('0001445546-25-008730')}/index.json"

    _assert_metadata_redirect_denied(
        _responses([filing]),
        redirect_from=source,
        redirect_to=redirected,
    )


def test_sec_denies_index_to_header_redirect_before_target_request() -> None:
    filing = _filing()
    base = _archive_base(filing["accessionNumber"])
    source = f"{base}/index.json"
    redirected = f"{base}/{filing['accessionNumber']}.hdr.sgml"

    _assert_metadata_redirect_denied(
        _responses([filing]),
        redirect_from=source,
        redirect_to=redirected,
    )


def test_sec_denies_header_to_header_redirect_before_target_request() -> None:
    filing = _filing()
    base = _archive_base(filing["accessionNumber"])
    source = f"{base}/{filing['accessionNumber']}.hdr.sgml"
    redirected = (
        f"{_archive_base('0001445546-25-008730')}/"
        "0001445546-25-008730.hdr.sgml"
    )

    _assert_metadata_redirect_denied(
        _responses([filing]),
        redirect_from=source,
        redirect_to=redirected,
    )


def test_sec_never_calls_auto_following_opener() -> None:
    class AutoFollowingOpener:
        def __init__(self) -> None:
            self.called = False

        def __call__(self, url: str, **kwargs: object) -> _Response:
            del url, kwargs
            self.called = True
            raise AssertionError("auto-following opener must not be called")

    opener = AutoFollowingOpener()

    with pytest.raises(TypeError, match="open_no_redirect"):
        SecDocumentSourceAdapter(opener).discover(_target(), _context())

    assert not opener.called


def test_sec_uses_the_shared_explicit_get_opener_contract() -> None:
    result, opener = _discover([_filing()])

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert opener.methods
    assert set(opener.methods) == {"GET"}


def test_sec_supports_only_overseas_product_summary_targets() -> None:
    adapter = SecDocumentSourceAdapter(_SyntheticOpener({}))

    assert adapter.supports(_target())
    assert not adapter.supports(_target(required_role=DocumentRole.PRODUCT_FULL))
    assert not adapter.supports(_target(required_role=DocumentRole.OFFICIAL_UPDATE))
    assert not adapter.supports(_target(product_family="domestic_etf"))


def test_sec_product_full_discovery_is_unsupported_before_network() -> None:
    summary = _filing()
    full = _filing(
        "0001445546-25-007000",
        form="485BPOS",
        primary_document="full.htm",
        description="Prospectus",
    )
    opener = _SyntheticOpener(_responses([summary, full]))

    result = SecDocumentSourceAdapter(opener).discover(
        _target(required_role=DocumentRole.PRODUCT_FULL),
        _context(),
    )

    assert result.status is SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE
    assert result.reason_code == "sec_target_not_supported"
    assert result.candidates == ()
    assert opener.calls == []
