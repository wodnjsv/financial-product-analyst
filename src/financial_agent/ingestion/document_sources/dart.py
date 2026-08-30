"""Fail-closed OpenDART discovery for domestic fund prospectuses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
import json
import re
from typing import BinaryIO
from urllib.parse import urlencode, urlparse
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo

from financial_agent.documents import (
    DocumentRole,
    DocumentSourceCandidate,
    DocumentSourceTarget,
    PublisherRole,
    SourceAuditStatus,
    SourceAuthorityTier,
)

from .base import (
    DocumentDiscoveryContext,
    SourceAdapterResult,
    classify_access_error,
    sanitize_public_locator,
)


_LIST_ENDPOINT = "https://opendart.fss.or.kr/api/list.json"
_DOCUMENT_ENDPOINT = "https://opendart.fss.or.kr/api/document.xml"
_VIEWER_ENDPOINT = "https://dart.fss.or.kr/dsaf001/main.do"
_DART_HOST = "opendart.fss.or.kr"
_SEOUL = ZoneInfo("Asia/Seoul")
_CORP_CODE = re.compile(r"^[0-9]{8}$")
_RECEIPT_NO = re.compile(r"^[0-9]{14}$")
_RECEIPT_DATE = re.compile(r"^[0-9]{8}$")
_CORRECTION_PREFIX = re.compile(r"^(?:\[(?:기재)?정정\]\s*)+")
_MAX_LIST_PAGES = 100
_PAGE_COUNT = 100
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class _Filing:
    corp_name: str
    report_name: str
    receipt_no: str
    receipt_date: date
    document_type: str
    report_identity: str


class _DartResponseError(Exception):
    def __init__(self, status: SourceAuditStatus, reason_code: str) -> None:
        self.status = status
        self.reason_code = reason_code
        super().__init__(reason_code)


class _DartMalformedResponse(Exception):
    pass


class _DartMalformedDocument(Exception):
    pass


class DartDocumentSourceAdapter:
    """Discover exact regulator-filed prospectuses without entity inference."""

    source_code = "DART"

    def __init__(self, opener: object) -> None:
        self._opener = opener

    def supports(self, target: DocumentSourceTarget) -> bool:
        return (
            target.entity_type == "product"
            and target.product_family in {"domestic_etf", "public_fund"}
            and target.required_role
            in {DocumentRole.PRODUCT_SUMMARY, DocumentRole.PRODUCT_FULL}
            and target.binding_role == "subject_product"
        )

    def discover(
        self,
        target: DocumentSourceTarget,
        context: DocumentDiscoveryContext,
    ) -> SourceAdapterResult:
        api_key = context.dart_api_key
        if api_key is None or not api_key.strip():
            return _unavailable(
                SourceAuditStatus.CREDENTIALS_MISSING,
                "dart_api_key_missing",
            )

        corp_codes = tuple(
            value
            for scheme, value in target.identifiers
            if scheme == "DART_CORP_CODE"
        )
        if not corp_codes:
            return _unavailable(
                SourceAuditStatus.IDENTIFIER_MISSING,
                "dart_corp_code_missing",
            )
        if len(corp_codes) != 1:
            return _unavailable(
                SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
                "dart_corp_code_ambiguous",
            )
        corp_code = corp_codes[0]
        if _CORP_CODE.fullmatch(corp_code) is None:
            return _unavailable(
                SourceAuditStatus.IDENTIFIER_MISSING,
                "dart_corp_code_invalid",
            )
        if context.cutoff_date != target.cutoff_date:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "dart_cutoff_mismatch",
            )

        try:
            filings = self._list_filings(
                api_key=api_key,
                corp_code=corp_code,
                cutoff_date=context.cutoff_date,
            )
            selected = _select_current_filings(
                filings,
                target_name=target.canonical_name,
                cutoff_date=context.cutoff_date,
            )
            for filing in selected:
                self._preflight_document(api_key, filing.receipt_no)
        except _DartResponseError as error:
            return _unavailable(error.status, error.reason_code)
        except _DartMalformedResponse:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "dart_response_malformed",
            )
        except _DartMalformedDocument:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "dart_document_malformed",
            )
        except Exception as error:
            status = classify_access_error(error)
            return _unavailable(status, f"dart_{status.value}")

        candidates = tuple(_candidate(filing) for filing in selected)
        return SourceAdapterResult(
            status=SourceAuditStatus.ELIGIBLE,
            reason_code=None,
            candidates=candidates,
        )

    def _list_filings(
        self,
        *,
        api_key: str,
        corp_code: str,
        cutoff_date: date,
    ) -> tuple[_Filing, ...]:
        filings: list[_Filing] = []
        page_number = 1
        expected_total_pages: int | None = None
        while True:
            url = _url(
                _LIST_ENDPOINT,
                crtfc_key=api_key,
                corp_code=corp_code,
                bgn_de="19000101",
                end_de=cutoff_date.strftime("%Y%m%d"),
                pblntf_ty="G",
                page_no=str(page_number),
                page_count=str(_PAGE_COUNT),
            )
            payload = self._read(url, _MAX_JSON_BYTES)
            page = _decode_list_page(
                payload,
                expected_page=page_number,
                expected_corp_code=corp_code,
            )
            if page is None:
                return ()
            page_filings, total_pages = page
            if total_pages > _MAX_LIST_PAGES:
                raise _DartMalformedResponse
            if expected_total_pages is None:
                expected_total_pages = total_pages
            elif total_pages != expected_total_pages:
                raise _DartMalformedResponse
            filings.extend(page_filings)
            if page_number >= total_pages:
                return tuple(filings)
            page_number += 1

    def _preflight_document(self, api_key: str, receipt_no: str) -> None:
        url = _url(
            _DOCUMENT_ENDPOINT,
            crtfc_key=api_key,
            rcept_no=receipt_no,
        )
        payload = self._read(url, _MAX_DOCUMENT_BYTES)
        try:
            with ZipFile(BytesIO(payload)) as archive:
                names = archive.namelist()
        except (BadZipFile, OSError, ValueError) as error:
            _raise_for_document_error(payload)
            raise _DartMalformedDocument from error
        if not names or not any(name.lower().endswith(".xml") for name in names):
            raise _DartMalformedDocument

    def _read(self, url: str, limit: int) -> bytes:
        response = _open(self._opener, url)
        try:
            final_url = response.geturl() if hasattr(response, "geturl") else url
            if urlparse(final_url).hostname != _DART_HOST:
                raise _DartResponseError(
                    SourceAuditStatus.ACCESS_DENIED,
                    "dart_redirect_host_denied",
                )
            payload = response.read(limit + 1)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if not isinstance(payload, bytes) or len(payload) > limit:
            raise _DartMalformedResponse
        return payload


def _open(opener: object, url: str) -> BinaryIO:
    if callable(opener):
        return opener(url, timeout=_REQUEST_TIMEOUT_SECONDS)  # type: ignore[no-any-return]
    open_method = getattr(opener, "open", None)
    if not callable(open_method):
        raise TypeError("DART opener must be callable or provide open()")
    return open_method(url, timeout=_REQUEST_TIMEOUT_SECONDS)  # type: ignore[no-any-return]


def _decode_list_page(
    payload: bytes,
    *,
    expected_page: int,
    expected_corp_code: str,
) -> tuple[tuple[_Filing, ...], int] | None:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _DartMalformedResponse from error
    if not isinstance(decoded, dict):
        raise _DartMalformedResponse

    status = decoded.get("status")
    if status == "013":
        return None
    if status != "000":
        _raise_for_dart_status(status)

    page_number = decoded.get("page_no")
    total_pages = decoded.get("total_page")
    items = decoded.get("list")
    if (
        not _is_int(page_number)
        or page_number != expected_page
        or not _is_int(total_pages)
        or total_pages < 1
        or not isinstance(items, list)
    ):
        raise _DartMalformedResponse
    return (
        tuple(
            _parse_filing(item, expected_corp_code=expected_corp_code)
            for item in items
        ),
        total_pages,
    )


def _raise_for_dart_status(status: object) -> None:
    if not isinstance(status, str):
        raise _DartMalformedResponse
    if status == "020":
        raise _DartResponseError(
            SourceAuditStatus.RATE_LIMITED,
            "dart_rate_limited",
        )
    if status in {"010", "011", "012"}:
        raise _DartResponseError(
            SourceAuditStatus.ACCESS_DENIED,
            "dart_access_denied",
        )
    if status == "014":
        raise _DartResponseError(
            SourceAuditStatus.DOCUMENT_NOT_FOUND,
            "dart_document_not_found",
        )
    raise _DartResponseError(
        SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
        "dart_error_status",
    )


def _parse_filing(item: object, *, expected_corp_code: str) -> _Filing:
    if not isinstance(item, dict):
        raise _DartMalformedResponse
    corp_code = item.get("corp_code")
    corp_name = item.get("corp_name")
    report_name = item.get("report_nm")
    receipt_no = item.get("rcept_no")
    receipt_date_text = item.get("rcept_dt")
    if not all(
        isinstance(value, str) and bool(value.strip())
        for value in (
            corp_code,
            corp_name,
            report_name,
            receipt_no,
            receipt_date_text,
        )
    ):
        raise _DartMalformedResponse
    assert isinstance(corp_code, str)
    assert isinstance(corp_name, str)
    assert isinstance(report_name, str)
    assert isinstance(receipt_no, str)
    assert isinstance(receipt_date_text, str)
    if corp_code != expected_corp_code:
        raise _DartResponseError(
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "dart_corp_code_response_mismatch",
        )
    if (
        _RECEIPT_NO.fullmatch(receipt_no) is None
        or _RECEIPT_DATE.fullmatch(receipt_date_text) is None
    ):
        raise _DartMalformedResponse
    try:
        receipt_date = datetime.strptime(receipt_date_text, "%Y%m%d").date()
    except ValueError as error:
        raise _DartMalformedResponse from error
    document_type = _document_type(report_name)
    return _Filing(
        corp_name=corp_name,
        report_name=report_name,
        receipt_no=receipt_no,
        receipt_date=receipt_date,
        document_type=document_type,
        report_identity=_report_identity(report_name),
    )


def _select_current_filings(
    filings: tuple[_Filing, ...],
    *,
    target_name: str,
    cutoff_date: date,
) -> tuple[_Filing, ...]:
    prospectuses = tuple(filing for filing in filings if filing.document_type)
    exact = tuple(
        filing
        for filing in prospectuses
        if _normalize_whitespace(filing.corp_name)
        == _normalize_whitespace(target_name)
    )
    if not exact:
        if prospectuses:
            raise _DartResponseError(
                SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
                "dart_product_name_mismatch",
            )
        raise _DartResponseError(
            SourceAuditStatus.DOCUMENT_NOT_FOUND,
            "dart_prospectus_not_found",
        )

    eligible = tuple(
        filing for filing in exact if filing.receipt_date <= cutoff_date
    )
    if not eligible:
        raise _DartResponseError(
            SourceAuditStatus.AFTER_CUTOFF_ONLY,
            "dart_after_cutoff_only",
        )

    current: dict[tuple[str, str], _Filing] = {}
    for filing in eligible:
        key = (filing.document_type, filing.report_identity)
        previous = current.get(key)
        if previous is None or (
            filing.receipt_date,
            filing.receipt_no,
        ) > (previous.receipt_date, previous.receipt_no):
            current[key] = filing
    return tuple(
        sorted(
            current.values(),
            key=lambda filing: (filing.document_type, filing.receipt_no),
        )
    )


def _candidate(filing: _Filing) -> DocumentSourceCandidate:
    published_at = datetime.combine(
        filing.receipt_date,
        datetime.min.time(),
        tzinfo=_SEOUL,
    )
    source_locator = sanitize_public_locator(
        f"{_VIEWER_ENDPOINT}?rcpNo={filing.receipt_no}",
        allowed_hosts=frozenset({"dart.fss.or.kr"}),
    )
    discovery_locator = sanitize_public_locator(
        _DOCUMENT_ENDPOINT,
        allowed_hosts=frozenset({_DART_HOST}),
    )
    return DocumentSourceCandidate(
        document_id=f"dart-rcept:{filing.receipt_no}",
        source_code="DART",
        authority_tier=SourceAuthorityTier.TIER_1_REGULATORY,
        publisher_code="FSS_DART",
        publisher_role=PublisherRole.REGULATOR_DISCLOSURE,
        document_type=filing.document_type,
        document_version=filing.receipt_no,
        source_locator=source_locator,
        discovery_locator=discovery_locator,
        jurisdiction="KR",
        original_language="ko",
        published_at=published_at,
        available_at=published_at,
        effective_from=filing.receipt_date,
        effective_to=None,
        media_type="application/zip",
        accession_or_receipt_id=filing.receipt_no,
    )


def _document_type(report_name: str) -> str:
    normalized = _report_identity(report_name)
    if "투자설명서" not in normalized or "집합투자증권" not in normalized:
        return ""
    if "간이투자설명서" in normalized:
        return "summary_prospectus"
    return "full_prospectus"


def _raise_for_document_error(payload: bytes) -> None:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return
    if not isinstance(decoded, dict):
        return
    status = decoded.get("status")
    if status != "000":
        _raise_for_dart_status(status)


def _report_identity(report_name: str) -> str:
    return _normalize_whitespace(_CORRECTION_PREFIX.sub("", report_name))


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _url(endpoint: str, **parameters: str) -> str:
    return f"{endpoint}?{urlencode(parameters)}"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _unavailable(
    status: SourceAuditStatus,
    reason_code: str,
) -> SourceAdapterResult:
    return SourceAdapterResult(status=status, reason_code=reason_code, candidates=())
