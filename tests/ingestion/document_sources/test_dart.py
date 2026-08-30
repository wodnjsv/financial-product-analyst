from __future__ import annotations

from datetime import date
from io import BytesIO
import json
from urllib.parse import parse_qs, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from financial_agent.documents import (
    DocumentRole,
    DocumentSourceTarget,
    PublisherRole,
    SourceAuditStatus,
    SourceAuthorityTier,
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
        "rm": "",
    }


def _list_response(
    filings: list[dict[str, str]],
    *,
    page_no: int = 1,
    total_page: int = 1,
) -> dict[str, object]:
    return {
        "status": "000",
        "message": "정상",
        "page_no": page_no,
        "page_count": 100,
        "total_count": len(filings),
        "total_page": total_page,
        "list": filings,
    }


def _document_zip() -> bytes:
    payload = BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        archive.writestr("20260820000123.xml", "<DOCUMENT />")
    return payload.getvalue()


class _Response(BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)

    def geturl(self) -> str:
        return "https://opendart.fss.or.kr/api/list.json"


class _SyntheticOpener:
    def __init__(
        self,
        list_pages: dict[int, object],
        *,
        documents: dict[str, bytes] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.list_pages = list_pages
        self.documents = documents or {}
        self.error = error
        self.calls: list[str] = []

    def __call__(self, url: str, *, timeout: float) -> _Response:
        del timeout
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("/list.json"):
            page = int(query["page_no"][0])
            payload = self.list_pages[page]
            encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            return _Response(encoded)
        if parsed.path.endswith("/document.xml"):
            receipt_no = query["rcept_no"][0]
            return _Response(self.documents.get(receipt_no, _document_zip()))
        raise AssertionError(f"unexpected synthetic URL path: {parsed.path}")


def _adapter(
    filings: list[dict[str, str]],
    *,
    page_no: int = 1,
    total_page: int = 1,
    documents: dict[str, bytes] | None = None,
) -> tuple[DartDocumentSourceAdapter, _SyntheticOpener]:
    opener = _SyntheticOpener(
        {page_no: _list_response(filings, page_no=page_no, total_page=total_page)},
        documents=documents,
    )
    return DartDocumentSourceAdapter(opener), opener


def test_dart_selects_latest_effective_collective_investment_prospectus() -> None:
    filings = [
        _filing("20260810000100", "20260810"),
        _filing(
            "20260820000123",
            "20260820",
            report_name="[정정] 투자설명서(집합투자증권)",
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
    assert len(opener.calls) == 2


@pytest.mark.parametrize("api_key", (None, "", "   "))
def test_dart_missing_api_key_is_per_target_credentials_missing(
    api_key: str | None,
) -> None:
    opener = _SyntheticOpener({})

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context(api_key))

    assert result.status is SourceAuditStatus.CREDENTIALS_MISSING
    assert result.reason_code == "dart_api_key_missing"
    assert result.candidates == ()
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


def test_dart_two_publisher_corp_codes_are_ambiguous_before_network() -> None:
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


def test_dart_rejects_a_response_for_another_exact_corp_code() -> None:
    filing = _filing("20260820000123", "20260820")
    filing["corp_code"] = "00999999"
    adapter, _ = _adapter([filing])

    result = adapter.discover(_target(), _context())

    assert result.status is SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
    assert result.reason_code == "dart_corp_code_response_mismatch"
    assert result.candidates == ()


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
    assert len(opener.calls) == 1


def test_dart_follows_list_pagination_and_uses_bounded_fund_search() -> None:
    opener = _SyntheticOpener(
        {
            1: _list_response([], page_no=1, total_page=2),
            2: _list_response(
                [_filing("20260820000123", "20260820")],
                page_no=2,
                total_page=2,
            ),
        }
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    list_calls = [url for url in opener.calls if "/list.json" in url]
    assert len(list_calls) == 2
    first_query = parse_qs(urlparse(list_calls[0]).query)
    assert first_query["corp_code"] == ["00123456"]
    assert first_query["bgn_de"] == ["19000101"]
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
            1: _list_response([], page_no=1, total_page=2),
            2: _list_response([], page_no=2, total_page=1),
        }
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "dart_response_malformed"


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


def test_dart_malformed_original_file_zip_fails_closed() -> None:
    opener = _SyntheticOpener(
        {1: _list_response([_filing("20260820000123", "20260820")])},
        documents={"20260820000123": b"not-a-zip"},
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    assert result.reason_code == "dart_document_malformed"
    assert result.candidates == ()


def test_dart_original_file_api_error_status_is_classified() -> None:
    opener = _SyntheticOpener(
        {1: _list_response([_filing("20260820000123", "20260820")])},
        documents={
            "20260820000123": json.dumps(
                {"status": "020", "message": f"limit for {_API_KEY}"}
            ).encode()
        },
    )

    result = DartDocumentSourceAdapter(opener).discover(_target(), _context())

    assert result.status is SourceAuditStatus.RATE_LIMITED
    assert result.reason_code == "dart_rate_limited"
    assert _API_KEY not in repr(result)


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
