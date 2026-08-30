from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from io import BytesIO
import json
from urllib.parse import parse_qs, urlparse

import pytest

from financial_agent.documents import (
    CoverageStatus,
    DocumentCandidate,
    DocumentRole,
    DocumentSourceTarget,
    PublisherRole,
    SourceAuditStatus,
    SourceAuthorityTier,
    admit_document,
)
from financial_agent.ingestion.document_sources import DocumentDiscoveryContext
from financial_agent.ingestion.document_sources.dart import DartDocumentSourceAdapter


_CUTOFF = date(2026, 8, 24)
_API_KEY = "SYNTHETIC-DART-SECRET"


def _target(
    *,
    product_family: str = "domestic_etf",
    canonical_name: str = "한빛 성장 ETF",
    identifiers: tuple[tuple[str, str], ...] = (("DART_CORP_CODE", "00123456"),),
) -> DocumentSourceTarget:
    return DocumentSourceTarget(
        dataset_version="2026-08-24",
        entity_id="product-1",
        entity_type="product",
        canonical_name=canonical_name,
        product_family=product_family,
        required_role=DocumentRole.PRODUCT_SUMMARY,
        binding_role="subject_product",
        identifiers=identifiers,
        cutoff_date=_CUTOFF,
    )


def _publisher_target(
    *,
    canonical_name: str = "한빛 성장 ETF",
    identifiers: tuple[tuple[str, str], ...] = (
        ("DART_PUBLISHER_CORP_CODE", "00123456"),
        ("DART_PUBLISHER_NAME", "한빛자산운용"),
    ),
) -> DocumentSourceTarget:
    return _target(canonical_name=canonical_name, identifiers=identifiers)


def _context(api_key: str | None = _API_KEY) -> DocumentDiscoveryContext:
    return DocumentDiscoveryContext(
        cutoff_date=_CUTOFF,
        dart_api_key=api_key,
        sec_user_agent=None,
        locator_registry_path=None,
    )


def _filing(
    receipt_no: str,
    receipt_date: str,
    *,
    report_name: str = "투자설명서(집합투자증권)",
    corp_name: str = "한빛 성장 ETF",
    rm: str = "",
) -> dict[str, str]:
    return {
        "corp_code": "00123456",
        "corp_name": corp_name,
        "stock_code": "123456",
        "corp_cls": "Y",
        "report_nm": report_name,
        "rcept_no": receipt_no,
        "flr_nm": "한빛자산운용",
        "rcept_dt": receipt_date,
        "rm": rm,
    }


def _nonprospectus_filings(start: int, count: int) -> list[dict[str, str]]:
    return [
        _filing(
            f"20260801{ordinal:06d}",
            "20260801",
            report_name="자산운용보고서",
        )
        for ordinal in range(start, start + count)
    ]


def _list_response(
    filings: list[dict[str, str]],
    *,
    page_no: int = 1,
    total_page: int = 1,
    total_count: int | None = None,
    page_count: int = 100,
) -> dict[str, object]:
    return {
        "status": "000",
        "message": "정상",
        "page_no": page_no,
        "page_count": page_count,
        "total_count": len(filings) if total_count is None else total_count,
        "total_page": total_page,
        "list": filings,
    }


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
            raise AssertionError("original document body must not be read")
        return super().read(size)


class _SyntheticOpener:
    def __init__(
        self,
        list_pages: dict[int, object],
        *,
        error: Exception | None = None,
        redirect_location: str | None = None,
    ) -> None:
        self.list_pages = list_pages
        self.error = error
        self.redirect_location = redirect_location
        self.calls: list[str] = []
        self.requests: list[tuple[str, str, dict[str, str], float]] = []
        self.responses: list[_Response] = []

    def open_no_redirect(
        self,
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Response:
        self.calls.append(url)
        self.requests.append((url, method, dict(headers), timeout))
        if self.error is not None:
            raise self.error
        if self.redirect_location is not None and len(self.calls) == 1:
            response = _Response(
                b"redirect body must not be read",
                status=302,
                location=self.redirect_location,
                fail_if_read=True,
            )
            self.responses.append(response)
            return response
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if "/list" in parsed.path:
            page = int(query.get("page_no", ["1"])[0])
            payload = self.list_pages[page]
            encoded = (
                payload
                if isinstance(payload, bytes)
                else json.dumps(payload).encode()
            )
            response = _Response(encoded)
            self.responses.append(response)
            return response
        if parsed.path.endswith("/document.xml"):
            response = _Response(
                b"PK\x03\x04synthetic-original-body",
                fail_if_read=True,
            )
            self.responses.append(response)
            return response
        raise AssertionError(f"unexpected synthetic URL path: {parsed.path}")


def _adapter(
    filings: list[dict[str, str]],
    *,
    page_no: int = 1,
    total_page: int = 1,
) -> tuple[DartDocumentSourceAdapter, _SyntheticOpener]:
    opener = _SyntheticOpener(
        {page_no: _list_response(filings, page_no=page_no, total_page=total_page)},
    )
    return DartDocumentSourceAdapter(opener), opener


def test_dart_selects_latest_effective_collective_investment_prospectus() -> None:
    filings = [
        _filing("20260810000100", "20260810", rm="정"),
        _filing(
            "20260820000123",
            "20260820",
            report_name="[기재정정] 투자설명서(집합투자증권)",
        ),
    ]
    adapter, opener = _adapter(filings)

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert [item.accession_or_receipt_id for item in result.candidates] == [
        "20260820000123"
    ]
    candidate = result.candidates[0]
    assert candidate.authority_tier is SourceAuthorityTier.TIER_1_REGULATORY
    assert candidate.publisher_role is PublisherRole.REGULATOR_DISCLOSURE
    assert candidate.source_locator == (
        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260820000123"
    )
    assert candidate.discovery_locator == (
        "https://opendart.fss.or.kr/api/document.xml"
    )
    assert candidate.document_type == "full_prospectus"
    assert candidate.target_entity_id == "product-1"
    assert candidate.effective_from is None
    assert len(opener.calls) == 1


def test_dart_discovery_never_requests_or_reads_original_document_body() -> None:
    adapter, opener = _adapter([_filing("20260820000123", "20260820")])

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert all("/document.xml" not in url for url in opener.calls)
    assert len(opener.responses) == 1
    assert opener.responses[0].read_sizes == [2 * 1024 * 1024 + 1]


def test_unknown_dart_effectiveness_cannot_pass_document_admission() -> None:
    adapter, _ = _adapter([_filing("20260820000123", "20260820")])
    discovered = adapter.discover(_target(), _context()).candidates[0]
    candidate = DocumentCandidate(
        document_id=discovered.document_id,
        document_type=discovered.document_type,
        document_version=discovered.document_version,
        source_id="dart",
        publisher_role=discovered.publisher_role,
        jurisdiction=discovered.jurisdiction,
        original_language=discovered.original_language,
        published_at=discovered.published_at,
        available_at=discovered.available_at,
        effective_from=discovered.effective_from,
        effective_to=discovered.effective_to,
        bound_entity_ids=("product-1",),
        binding_role="subject_product",
        claim_types=frozenset({"investment_strategy", "risk_factor"}),
        content_checksum="a" * 64,
        extraction_method="synthetic",
        exact_text_available=True,
        source_locator=discovered.source_locator,
    )

    decision = admit_document(candidate, cutoff_date=_CUTOFF)

    assert not decision.accepted
    assert decision.coverage_status is CoverageStatus.VERSION_UNKNOWN
    assert decision.reason_code == "effective_version_not_verified"


def test_dart_resolves_complete_correction_chain_to_current_submission() -> None:
    filings = [
        _filing("20260801000001", "20260801", rm="정"),
        _filing(
            "20260805000001",
            "20260805",
            report_name="[기재정정] 투자설명서(집합투자증권)",
            rm="정",
        ),
        _filing(
            "20260810000001",
            "20260810",
            report_name="[정정명령부과] 투자설명서(집합투자증권)",
        ),
        _filing(
            "20260811000001",
            "20260811",
            report_name="[정정제출요구] 투자설명서(집합투자증권)",
        ),
        _filing(
            "20260815000001",
            "20260815",
            report_name="[첨부정정] 투자설명서(집합투자증권)",
            rm="정",
        ),
        _filing(
            "20260820000123",
            "20260820",
            report_name="[첨부추가] 투자설명서(집합투자증권)",
        ),
    ]
    adapter, _ = _adapter(filings)

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert [item.accession_or_receipt_id for item in result.candidates] == [
        "20260820000123"
    ]


@pytest.mark.parametrize("marker", ("정정명령부과", "정정제출요구"))
def test_dart_rejects_unresolved_correction_order_or_request(marker: str) -> None:
    adapter, _ = _adapter(
        [
            _filing("20260801000001", "20260801", rm="정"),
            _filing(
                "20260820000123",
                "20260820",
                report_name=f"[{marker}] 투자설명서(집합투자증권)",
            ),
        ]
    )

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.VERSION_UNKNOWN
    assert result.reason_code == "dart_correction_state_unresolved"
    assert result.candidates == ()


def test_dart_rejects_withdrawn_current_correction() -> None:
    adapter, _ = _adapter(
        [
            _filing("20260801000001", "20260801", rm="정"),
            _filing(
                "20260820000123",
                "20260820",
                report_name="[첨부정정] 투자설명서(집합투자증권)",
                rm="철",
            ),
        ]
    )

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.VERSION_UNKNOWN
    assert result.reason_code == "dart_correction_state_unresolved"
    assert result.candidates == ()


@pytest.mark.parametrize("api_key", (None, "", "   "))
def test_dart_missing_api_key_is_per_target_credentials_missing(
    api_key: str | None,
) -> None:
    opener = _SyntheticOpener({})

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context(api_key))

    assert result.status is SourceAuditStatus.CREDENTIALS_MISSING
    assert result.reason_code == "dart_api_key_missing"
    assert result.candidates == ()
    assert result.attempted_source is not None
    assert result.attempted_source.source_code == "DART"
    assert result.attempted_source.source_locator is None
    assert result.attempted_source.discovery_locator is None
    assert opener.calls == []


def test_dart_absent_corp_code_fails_before_network() -> None:
    opener = _SyntheticOpener({})

    result = DartDocumentSourceAdapter(opener).discover(
        _target(identifiers=(("ISIN", "KR7000000000"),)),
        _context(),
    )

    assert result.status is SourceAuditStatus.IDENTIFIER_MISSING
    assert result.reason_code == "dart_corp_code_missing"
    assert opener.calls == []


def test_dart_two_product_corp_codes_are_ambiguous_before_network() -> None:
    opener = _SyntheticOpener({})

    result = DartDocumentSourceAdapter(opener).discover(
        _target(
            identifiers=(
                ("DART_CORP_CODE", "00123456"),
                ("DART_CORP_CODE", "00654321"),
            )
        ),
        _context(),
    )

    assert result.status is SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
    assert result.reason_code == "dart_corp_code_ambiguous"
    assert opener.calls == []


@pytest.mark.parametrize(
    "identifiers",
    (
        (
            ("DART_PUBLISHER_CORP_CODE", "00123456"),
            ("DART_PUBLISHER_CORP_CODE", "00654321"),
            ("DART_PUBLISHER_NAME", "한빛자산운용"),
        ),
        (("DART_PUBLISHER_CORP_CODE", "00123456"),),
    ),
)
def test_dart_ambiguous_publisher_binding_fails_before_network(
    identifiers: tuple[tuple[str, str], ...],
) -> None:
    opener = _SyntheticOpener({})

    result = DartDocumentSourceAdapter(opener).discover(
        _target(identifiers=identifiers),
        _context(),
    )

    assert result.status is SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
    assert result.reason_code == "dart_publisher_binding_ambiguous"
    assert opener.calls == []


def test_dart_rejects_mixed_product_and_publisher_binding_modes_before_network() -> None:
    opener = _SyntheticOpener({})
    target = _target(
        identifiers=(
            ("DART_CORP_CODE", "00123456"),
            ("DART_PUBLISHER_CORP_CODE", "00654321"),
            ("DART_PUBLISHER_NAME", "한빛자산운용"),
        )
    )

    result = DartDocumentSourceAdapter(opener).discover(target, _context())

    assert result.status is SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
    assert result.reason_code == "dart_binding_mode_ambiguous"
    assert opener.calls == []


def test_dart_rejects_a_response_for_another_exact_corp_code() -> None:
    filing = _filing("20260820000123", "20260820")
    filing["corp_code"] = "00999999"
    adapter, _ = _adapter([filing])

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
    assert result.reason_code == "dart_corp_code_response_mismatch"
    assert result.candidates == ()


def test_dart_uses_explicit_approved_publisher_binding_and_report_product() -> None:
    adapter, _ = _adapter(
        [
            _filing(
                "20260820000123",
                "20260820",
                corp_name="한빛자산운용",
                report_name=(
                    "투자설명서(집합투자증권) [한빛\n성장   ETF]"
                ),
            )
        ]
    )

    result = adapter.discover(_publisher_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert result.candidates[0].accession_or_receipt_id == "20260820000123"


def test_dart_publisher_binding_rejects_ambiguous_report_product_metadata() -> None:
    adapter, _ = _adapter(
        [
            _filing(
                "20260820000123",
                "20260820",
                corp_name="한빛자산운용",
                report_name=(
                    "투자설명서(집합투자증권) "
                    "[한빛 성장 ETF] [다른 ETF]"
                ),
            )
        ]
    )

    result = adapter.discover(_publisher_target(), _context())

    assert result.status is SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
    assert result.reason_code == "dart_product_metadata_ambiguous"
    assert result.candidates == ()


def test_dart_ignores_unparseable_other_product_when_exact_product_exists() -> None:
    adapter, _ = _adapter(
        [
            _filing(
                "20260820000123",
                "20260820",
                corp_name="한빛자산운용",
                report_name="투자설명서(집합투자증권) [한빛 성장 ETF]",
            ),
            _filing(
                "20260819000123",
                "20260819",
                corp_name="한빛자산운용",
                report_name="투자설명서(집합투자증권)",
            ),
        ]
    )

    result = adapter.discover(_publisher_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert [item.accession_or_receipt_id for item in result.candidates] == [
        "20260820000123"
    ]


def test_dart_product_identity_allows_whitespace_presence_only_difference() -> None:
    target_name = "삼성 KODEX 모멘텀PLUS증권상장지수투자신탁[주식]"
    adapter, _ = _adapter(
        [
            _filing(
                "20260805000047",
                "20260805",
                corp_name="한빛자산운용",
                report_name=(
                    "투자설명서(집합투자증권)"
                    "(삼성KODEX모멘텀PLUS증권상장지수투자신탁[주식])"
                ),
            )
        ]
    )

    result = adapter.discover(
        _publisher_target(canonical_name=target_name),
        _context(),
    )

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert result.candidates[0].accession_or_receipt_id == "20260805000047"


def test_dart_publisher_binding_requires_exact_approved_publisher_name() -> None:
    adapter, _ = _adapter(
        [
            _filing(
                "20260820000123",
                "20260820",
                corp_name="다른자산운용",
                report_name="투자설명서(집합투자증권) [한빛 성장 ETF]",
            )
        ]
    )

    result = adapter.discover(_publisher_target(), _context())

    assert result.status is SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
    assert result.reason_code == "dart_publisher_name_mismatch"


def test_dart_requires_secondary_whitespace_only_exact_product_name() -> None:
    adapter, _ = _adapter(
        [
            _filing(
                "20260820000123",
                "20260820",
                corp_name="한빛 성장 ETF 2호",
            )
        ]
    )

    result = adapter.discover(_target(canonical_name="한빛   성장 ETF"), _context())

    assert result.status is SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
    assert result.reason_code == "dart_product_name_mismatch"
    assert result.candidates == ()


def test_dart_accepts_whitespace_only_exact_product_name() -> None:
    adapter, _ = _adapter(
        [
            _filing(
                "20260820000123",
                "20260820",
                corp_name="한빛\n성장   ETF",
            )
        ]
    )

    result = adapter.discover(_target(canonical_name="한빛 성장 ETF"), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE


def test_dart_searches_project_window_then_previous_window_until_match() -> None:
    filing = _filing("20260205000123", "20260205")

    class WindowedOpener:
        def __init__(self) -> None:
            self.windows: list[tuple[str, str]] = []

        def open_no_redirect(
            self,
            url: str,
            *,
            method: str,
            headers: Mapping[str, str],
            timeout: float,
        ) -> _Response:
            del method, headers, timeout
            query = parse_qs(urlparse(url).query)
            window = (query["bgn_de"][0], query["end_de"][0])
            self.windows.append(window)
            if window == ("20260224", "20260824"):
                return _Response(
                    json.dumps(
                        {"status": "013", "message": "조회된 데이타가 없습니다."}
                    ).encode()
                )
            if window == ("20250823", "20260223"):
                return _Response(json.dumps(_list_response([filing])).encode())
            raise AssertionError(f"unexpected search window: {window}")

    opener = WindowedOpener()
    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert [item.accession_or_receipt_id for item in result.candidates] == [
        "20260205000123"
    ]
    assert opener.windows == [
        ("20260224", "20260824"),
        ("20250823", "20260223"),
    ]


def test_dart_reports_only_post_cutoff_prospectuses() -> None:
    adapter, opener = _adapter([_filing("20260825000123", "20260825")])

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.AFTER_CUTOFF_ONLY
    assert result.reason_code == "dart_after_cutoff_only"
    assert result.candidates == ()
    assert len(opener.calls) == 1


def test_dart_ignores_non_prospectus_filings() -> None:
    adapter, opener = _adapter(
        [
            _filing(
                "20260820000123",
                "20260820",
                report_name="자산운용보고서",
            )
        ]
    )

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.DOCUMENT_NOT_FOUND
    assert result.reason_code == "dart_prospectus_not_found"
    assert opener.calls


def test_dart_follows_list_pagination_and_uses_bounded_fund_search() -> None:
    opener = _SyntheticOpener(
        {
            1: _list_response(
                _nonprospectus_filings(1, 100),
                page_no=1,
                total_page=2,
                total_count=101,
            ),
            2: _list_response(
                [_filing("20260820000123", "20260820")],
                page_no=2,
                total_page=2,
                total_count=101,
            ),
        }
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    list_calls = [url for url in opener.calls if "/list.json" in url]
    assert len(list_calls) == 2
    first_query = parse_qs(urlparse(list_calls[0]).query)
    assert first_query["corp_code"] == ["00123456"]
    assert first_query["bgn_de"] == ["20260224"]
    assert first_query["end_de"] == ["20260824"]
    assert first_query["pblntf_ty"] == ["G"]
    assert first_query["page_count"] == ["100"]
    assert [parse_qs(urlparse(url).query)["page_no"] for url in list_calls] == [
        ["1"],
        ["2"],
    ]


def test_dart_rejects_inconsistent_pagination_metadata() -> None:
    opener = _SyntheticOpener(
        {
            1: _list_response(
                _nonprospectus_filings(1, 100),
                page_no=1,
                total_page=2,
                total_count=101,
            ),
            2: _list_response(
                [_filing("20260820000123", "20260820")],
                page_no=2,
                total_page=1,
                total_count=101,
            ),
        }
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "dart_response_malformed"


def test_dart_allows_013_only_on_initial_no_result_request() -> None:
    initial = _SyntheticOpener({1: {"status": "013", "message": "no data"}})

    initial_result = DartDocumentSourceAdapter(initial).discover(
        _target(),
        _context(),
    )

    assert initial_result.status is SourceAuditStatus.DOCUMENT_NOT_FOUND
    continuation = _SyntheticOpener(
        {
            1: _list_response(
                _nonprospectus_filings(1, 100),
                page_no=1,
                total_page=2,
                total_count=101,
            ),
            2: {"status": "013", "message": "premature end"},
        }
    )

    continuation_result = DartDocumentSourceAdapter(continuation).discover(
        _target(),
        _context(),
    )

    assert continuation_result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert continuation_result.reason_code == "dart_response_malformed"


@pytest.mark.parametrize(
    "payload",
    (
        _list_response(
            [_filing("20260820000123", "20260820")],
            page_count=99,
        ),
        _list_response(
            _nonprospectus_filings(1, 100),
            total_count=200,
            total_page=1,
        ),
        _list_response(
            _nonprospectus_filings(1, 99),
            total_count=101,
            total_page=2,
        ),
    ),
)
def test_dart_rejects_impossible_pagination_counters(payload: object) -> None:
    opener = _SyntheticOpener({1: payload})

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "dart_response_malformed"


def test_dart_accepts_exactly_100_complete_pages() -> None:
    pages = {
        page: _list_response(
            (
                _nonprospectus_filings((page - 1) * 100 + 1, 100)
                if page < 100
                else [_filing("20260820000123", "20260820")]
            ),
            page_no=page,
            total_page=100,
            total_count=9901,
        )
        for page in range(1, 101)
    }
    opener = _SyntheticOpener(pages)

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert len(opener.calls) == 100


def test_dart_refuses_101_pages_before_requesting_page_two() -> None:
    opener = _SyntheticOpener(
        {
            1: _list_response(
                _nonprospectus_filings(1, 100),
                total_page=101,
                total_count=10001,
            )
        }
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "dart_response_malformed"
    assert len(opener.calls) == 1


def test_dart_open_api_error_status_is_stable_and_secret_safe() -> None:
    opener = _SyntheticOpener(
        {1: {"status": "020", "message": f"limit for {_API_KEY}"}}
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.RATE_LIMITED
    assert result.reason_code == "dart_rate_limited"
    assert _API_KEY not in repr(result)


@pytest.mark.parametrize(
    "payload",
    (
        b"not-json",
        {"status": "000", "total_page": "one", "list": []},
        _list_response(
            [
                {
                    "corp_code": "00123456",
                    "corp_name": "한빛 성장 ETF",
                    "report_nm": "투자설명서(집합투자증권)",
                    "rcept_no": "not-a-receipt",
                    "rcept_dt": "20260820",
                }
            ]
        ),
    ),
)
def test_dart_malformed_schema_fails_closed(payload: object) -> None:
    opener = _SyntheticOpener({1: payload})

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "dart_response_malformed"
    assert result.candidates == ()


@pytest.mark.parametrize(
    "location",
    (
        "https://evil.example.invalid/steal",
        "http://opendart.fss.or.kr/api/list-redirect.json",
        "https://opendart.fss.or.kr:444/api/list-redirect.json",
        "https://opendart.fss.or.kr/api/document.xml",
    ),
)
def test_dart_denies_unsafe_redirect_before_target_request(location: str) -> None:
    opener = _SyntheticOpener(
        {1: _list_response([_filing("20260820000123", "20260820")])},
        redirect_location=location,
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_DENIED
    assert result.reason_code == "dart_redirect_location_denied"
    assert result.candidates == ()
    assert len(opener.calls) == 1
    assert location not in opener.calls


def test_dart_follows_explicit_same_host_https_redirect() -> None:
    location = "https://opendart.fss.or.kr/api/list.json?page_no=1"
    opener = _SyntheticOpener(
        {1: _list_response([_filing("20260820000123", "20260820")])},
        redirect_location=location,
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert len(opener.calls) == 2
    assert opener.calls[1] == location
    assert opener.responses[0].read_sizes == []


def test_dart_uses_the_shared_explicit_get_opener_contract() -> None:
    opener = _SyntheticOpener(
        {1: _list_response([_filing("20260820000123", "20260820")])}
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert opener.requests
    assert all(method == "GET" for _, method, _, _ in opener.requests)
    assert all(
        headers == {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        for _, _, headers, _ in opener.requests
    )


def test_dart_never_calls_an_opener_without_no_redirect_boundary() -> None:
    class AutoFollowingOpener:
        def __init__(self) -> None:
            self.called = False

        def __call__(self, url: str, *, timeout: float) -> _Response:
            del url, timeout
            self.called = True
            raise AssertionError("auto-following opener must never be called")

    opener = AutoFollowingOpener()

    with pytest.raises(TypeError, match="open_no_redirect"):
        DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert not opener.called


def test_dart_never_exposes_api_key_from_upstream_exception() -> None:
    opener = _SyntheticOpener(
        {},
        error=RuntimeError(f"crtfc_key={_API_KEY}"),
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "dart_access_method_unverified"
    assert _API_KEY not in repr(result)
    assert _API_KEY not in str(result)


@pytest.mark.parametrize("product_family", ("domestic_etf", "public_fund"))
def test_dart_supports_only_domestic_fund_product_targets(
    product_family: str,
) -> None:
    adapter, _ = _adapter([])

    assert adapter.supports(_target(product_family=product_family))


def test_dart_rejects_other_product_families() -> None:
    adapter, _ = _adapter([])

    assert not adapter.supports(_target(product_family="overseas_etf"))
