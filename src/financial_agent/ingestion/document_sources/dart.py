"""Fail-closed OpenDART discovery for domestic fund prospectuses."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import re
from typing import BinaryIO
import unicodedata
from urllib.parse import urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

from financial_agent.documents import (
    DocumentRole,
    DocumentSourceCandidate,
    DocumentSourceAttempt,
    DocumentSourceTarget,
    PublisherRole,
    SourceAuditStatus,
    SourceAuthorityTier,
)

from .base import (
    DocumentDiscoveryContext,
    HttpStatusError,
    NoRedirectHttpOpener,
    SourceAdapterResult,
    classify_access_error,
    sanitize_public_locator,
)


_LIST_ENDPOINT = "https://opendart.fss.or.kr/api/list.json"
_VIEWER_ENDPOINT = "https://dart.fss.or.kr/dsaf001/main.do"
_DART_HOST = "opendart.fss.or.kr"
_SEOUL = ZoneInfo("Asia/Seoul")
_CORP_CODE = re.compile(r"^[0-9]{8}$")
_RECEIPT_NO = re.compile(r"^[0-9]{14}$")
_RECEIPT_DATE = re.compile(r"^[0-9]{8}$")
_CORRECTION_MARKER = re.compile(
    r"^\[(정정|기재정정|첨부정정|첨부추가|정정명령부과|정정제출요구)\]\s*"
)
_UNRESOLVED_MARKERS = frozenset({"정정명령부과", "정정제출요구"})
_PUBLISHER_PRODUCT_PREFIX = re.compile(
    r"^(?:간이)?투자설명서\(집합투자증권(?:-[^)]+)?\)\s*"
)
_MAX_LIST_PAGES = 100
_PAGE_COUNT = 100
_MAX_JSON_BYTES = 2 * 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 15.0
_MAX_REDIRECTS = 3
_SEARCH_WINDOW_MONTHS = 6
_MAX_SEARCH_WINDOWS = 60


@dataclass(frozen=True, slots=True)
class _Binding:
    mode: str
    corp_code: str
    publisher_name: str | None


@dataclass(frozen=True, slots=True)
class _Filing:
    corp_name: str
    receipt_no: str
    receipt_date: date
    document_type: str
    report_identity: str
    product_name: str | None
    correction_state: str


@dataclass(frozen=True, slots=True)
class _ListPage:
    filings: tuple[_Filing, ...]
    total_count: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class DartRejectedFiling:
    receipt_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class DartPublisherDiscoveryResult:
    target_results: tuple[tuple[str, SourceAdapterResult], ...]
    resolved_product_names: tuple[tuple[str, str], ...]
    rejected_filings: tuple[DartRejectedFiling, ...]


class _DartResponseError(Exception):
    def __init__(self, status: SourceAuditStatus, reason_code: str) -> None:
        self.status = status
        self.reason_code = reason_code
        super().__init__(reason_code)


class _DartMalformedResponse(Exception):
    pass


class DartDocumentSourceAdapter:
    """Discover exact regulator-filed prospectuses without entity inference."""

    source_code = "DART"

    def __init__(self, opener: NoRedirectHttpOpener) -> None:
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

        try:
            binding = _resolve_binding(target)
        except _DartResponseError as error:
            return _unavailable(error.status, error.reason_code)
        if context.cutoff_date != target.cutoff_date:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "dart_cutoff_mismatch",
            )

        try:
            selected = self._search_current_filings(
                api_key=api_key,
                binding=binding,
                target_name=target.canonical_name,
                cutoff_date=context.cutoff_date,
            )
        except _DartResponseError as error:
            return _unavailable(error.status, error.reason_code)
        except _DartMalformedResponse:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "dart_response_malformed",
            )
        except Exception as error:
            status = classify_access_error(error)
            return _unavailable(status, f"dart_{status.value}")

        candidates = tuple(
            _candidate(filing, target_entity_id=target.entity_id)
            for filing in selected
        )
        return SourceAdapterResult(
            status=SourceAuditStatus.ELIGIBLE,
            reason_code=None,
            candidates=candidates,
        )

    def discover_publisher_targets(
        self,
        *,
        corp_code: str,
        publisher_name: str,
        targets: tuple[tuple[str, str, str], ...],
        target_member_names: Mapping[str, tuple[str, ...]] | None = None,
        context: DocumentDiscoveryContext,
    ) -> DartPublisherDiscoveryResult:
        """Fetch each publisher filing page once and select exact targets."""

        if not targets or len({item[0] for item in targets}) != len(targets):
            raise ValueError("publisher targets must be nonempty and unique")
        member_names = dict(target_member_names or {})
        target_keys = {item[0] for item in targets}
        if not set(member_names) <= target_keys or any(
            len(names) < 2
            or any(not name.strip() for name in names)
            for names in member_names.values()
        ):
            raise ValueError("publisher target member names are invalid")
        _validate_corp_code(corp_code)
        binding = _Binding("publisher", corp_code, publisher_name)
        if context.dart_api_key is None or not context.dart_api_key.strip():
            unavailable = _unavailable(
                SourceAuditStatus.CREDENTIALS_MISSING,
                "dart_api_key_missing",
            )
            return DartPublisherDiscoveryResult(
                target_results=tuple(
                    (target_key, unavailable) for target_key, _, _ in targets
                ),
                resolved_product_names=(),
                rejected_filings=(),
            )

        unresolved = {target_key for target_key, _, _ in targets}
        results: dict[str, SourceAdapterResult] = {}
        resolved_product_names: dict[str, str] = {}
        filings: list[_Filing] = []
        window_end = context.cutoff_date
        try:
            for _ in range(_MAX_SEARCH_WINDOWS):
                window_start = _subtract_months(window_end, _SEARCH_WINDOW_MONTHS)
                filings.extend(
                    self._list_filings(
                        api_key=context.dart_api_key,
                        binding=binding,
                        begin_date=window_start,
                        end_date=window_end,
                    )
                )
                for target_key, target_name, target_entity_id in targets:
                    if target_key not in unresolved:
                        continue
                    try:
                        selected = _select_current_filings(
                            tuple(filings),
                            binding=binding,
                            target_name=target_name,
                            member_names=member_names.get(target_key, ()),
                            cutoff_date=context.cutoff_date,
                        )
                    except _DartResponseError as error:
                        if error.reason_code in {
                            "dart_product_metadata_ambiguous",
                            "dart_product_name_mismatch",
                            "dart_prospectus_not_found",
                        }:
                            continue
                        results[target_key] = _unavailable(
                            error.status, error.reason_code
                        )
                        unresolved.remove(target_key)
                        continue
                    results[target_key] = SourceAdapterResult(
                        status=SourceAuditStatus.ELIGIBLE,
                        reason_code=None,
                        candidates=tuple(
                            _candidate(
                                filing,
                                target_entity_id=target_entity_id,
                            )
                            for filing in selected
                        ),
                    )
                    selected_names = {
                        filing.product_name
                        for filing in selected
                        if filing.product_name is not None
                    }
                    if len(selected_names) != 1:
                        raise _DartMalformedResponse
                    resolved_product_names[target_key] = next(
                        iter(selected_names)
                    )
                    unresolved.remove(target_key)
                if not unresolved:
                    break
                window_end = window_start - timedelta(days=1)
        except _DartResponseError as error:
            for target_key in unresolved:
                results[target_key] = _unavailable(error.status, error.reason_code)
        except _DartMalformedResponse:
            for target_key in unresolved:
                results[target_key] = _unavailable(
                    SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                    "dart_response_malformed",
                )
        except Exception as error:
            status = classify_access_error(error)
            for target_key in unresolved:
                results[target_key] = _unavailable(
                    status, f"dart_{status.value}"
                )

        for target_key, target_name, _ in targets:
            if target_key in results:
                continue
            try:
                _select_current_filings(
                    tuple(filings),
                    binding=binding,
                    target_name=target_name,
                    member_names=member_names.get(target_key, ()),
                    cutoff_date=context.cutoff_date,
                )
            except _DartResponseError as error:
                results[target_key] = _unavailable(error.status, error.reason_code)
            else:
                raise RuntimeError("resolved publisher target was not recorded")
        target_results = tuple(
            (target_key, results[target_key]) for target_key, _, _ in targets
        )
        selected_receipts = {
            candidate.accession_or_receipt_id
            for _, result in target_results
            for candidate in result.candidates
        }
        organizer_names = {
            _normalize_product_identity(target_name) for _, target_name, _ in targets
        }
        rejected_filings = tuple(
            sorted(
                {
                    DartRejectedFiling(
                        receipt_id=filing.receipt_no,
                        reason_code=(
                            "dart_version_not_selected"
                            if _normalize_product_identity(filing.product_name or "")
                            in organizer_names
                            else "dart_filing_not_in_organizer_inventory"
                        ),
                    )
                    for filing in filings
                    if filing.document_type
                    and filing.receipt_no not in selected_receipts
                },
                key=lambda item: (item.receipt_id, item.reason_code),
            )
        )
        return DartPublisherDiscoveryResult(
            target_results=target_results,
            resolved_product_names=tuple(sorted(resolved_product_names.items())),
            rejected_filings=rejected_filings,
        )

    def _search_current_filings(
        self,
        *,
        api_key: str,
        binding: _Binding,
        target_name: str,
        cutoff_date: date,
    ) -> tuple[_Filing, ...]:
        window_end = cutoff_date
        saw_prospectus = False
        for _ in range(_MAX_SEARCH_WINDOWS):
            window_start = _subtract_months(window_end, _SEARCH_WINDOW_MONTHS)
            filings = self._list_filings(
                api_key=api_key,
                binding=binding,
                begin_date=window_start,
                end_date=window_end,
            )
            saw_prospectus = saw_prospectus or any(
                filing.document_type for filing in filings
            )
            try:
                return _select_current_filings(
                    filings,
                    binding=binding,
                    target_name=target_name,
                    cutoff_date=cutoff_date,
                )
            except _DartResponseError as error:
                if error.reason_code not in {
                    "dart_product_name_mismatch",
                    "dart_prospectus_not_found",
                }:
                    raise
            window_end = window_start - timedelta(days=1)
        raise _DartResponseError(
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING
            if saw_prospectus
            else SourceAuditStatus.DOCUMENT_NOT_FOUND,
            "dart_product_name_mismatch"
            if saw_prospectus
            else "dart_prospectus_not_found",
        )

    def _list_filings(
        self,
        *,
        api_key: str,
        binding: _Binding,
        begin_date: date,
        end_date: date,
    ) -> tuple[_Filing, ...]:
        filings: list[_Filing] = []
        page_number = 1
        expected_total_pages: int | None = None
        expected_total_count: int | None = None
        while True:
            url = _url(
                _LIST_ENDPOINT,
                crtfc_key=api_key,
                corp_code=binding.corp_code,
                bgn_de=begin_date.strftime("%Y%m%d"),
                end_de=end_date.strftime("%Y%m%d"),
                pblntf_ty="G",
                page_no=str(page_number),
                page_count=str(_PAGE_COUNT),
            )
            payload = self._read(url, _MAX_JSON_BYTES)
            page = _decode_list_page(
                payload,
                expected_page=page_number,
                binding=binding,
            )
            if page is None:
                return ()
            if page.total_pages > _MAX_LIST_PAGES:
                raise _DartMalformedResponse
            if expected_total_pages is None:
                expected_total_pages = page.total_pages
                expected_total_count = page.total_count
            elif (
                page.total_pages != expected_total_pages
                or page.total_count != expected_total_count
            ):
                raise _DartMalformedResponse
            filings.extend(page.filings)
            if page_number >= page.total_pages:
                if len(filings) != page.total_count:
                    raise _DartMalformedResponse
                return tuple(filings)
            page_number += 1

    def _read(self, url: str, limit: int) -> bytes:
        current_url = url
        for redirect_count in range(_MAX_REDIRECTS + 1):
            response = _open_no_redirect(self._opener, current_url)
            try:
                status_code = _response_status(response)
            except Exception:
                response.close()
                raise
            if 300 <= status_code < 400:
                try:
                    location = _response_location(response)
                finally:
                    response.close()
                if redirect_count >= _MAX_REDIRECTS:
                    raise _DartResponseError(
                        SourceAuditStatus.ACCESS_DENIED,
                        "dart_redirect_limit_exceeded",
                    )
                redirected_url = urljoin(current_url, location)
                if not _is_approved_dart_url(redirected_url):
                    raise _DartResponseError(
                        SourceAuditStatus.ACCESS_DENIED,
                        "dart_redirect_location_denied",
                    )
                current_url = redirected_url
                continue
            if status_code != 200:
                response.close()
                raise HttpStatusError(status_code)
            try:
                payload = response.read(limit + 1)
            finally:
                response.close()
            if not isinstance(payload, bytes) or len(payload) > limit:
                raise _DartMalformedResponse
            return payload
        raise _DartResponseError(
            SourceAuditStatus.ACCESS_DENIED,
            "dart_redirect_limit_exceeded",
        )


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _open_no_redirect(opener: NoRedirectHttpOpener, url: str) -> BinaryIO:
    open_method = getattr(opener, "open_no_redirect", None)
    if not callable(open_method):
        raise TypeError("DART opener must provide open_no_redirect()")
    return open_method(  # type: ignore[no-any-return]
        url,
        method="GET",
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )


def _response_status(response: BinaryIO) -> int:
    status_code = getattr(response, "status", None)
    if not isinstance(status_code, int) or isinstance(status_code, bool):
        raise _DartMalformedResponse
    return status_code


def _response_location(response: BinaryIO) -> str:
    headers = getattr(response, "headers", None)
    location = headers.get("Location") if headers is not None else None
    if not isinstance(location, str) or not location.strip():
        raise _DartMalformedResponse
    return location


def _is_approved_dart_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == _DART_HOST
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and parsed.path == "/api/list.json"
    )


def _resolve_binding(target: DocumentSourceTarget) -> _Binding:
    product_codes = tuple(
        value
        for scheme, value in target.identifiers
        if scheme == "DART_CORP_CODE"
    )
    publisher_codes = tuple(
        value
        for scheme, value in target.identifiers
        if scheme == "DART_PUBLISHER_CORP_CODE"
    )
    publisher_names = tuple(
        value
        for scheme, value in target.identifiers
        if scheme == "DART_PUBLISHER_NAME"
    )
    if product_codes and (publisher_codes or publisher_names):
        raise _DartResponseError(
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "dart_binding_mode_ambiguous",
        )
    if product_codes:
        if len(product_codes) != 1:
            raise _DartResponseError(
                SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
                "dart_corp_code_ambiguous",
            )
        corp_code = product_codes[0]
        _validate_corp_code(corp_code)
        return _Binding("product", corp_code, None)
    if publisher_codes:
        if len(publisher_codes) != 1 or len(publisher_names) != 1:
            raise _DartResponseError(
                SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
                "dart_publisher_binding_ambiguous",
            )
        corp_code = publisher_codes[0]
        _validate_corp_code(corp_code)
        return _Binding("publisher", corp_code, publisher_names[0])
    raise _DartResponseError(
        SourceAuditStatus.IDENTIFIER_MISSING,
        "dart_corp_code_missing",
    )


def _validate_corp_code(corp_code: str) -> None:
    if _CORP_CODE.fullmatch(corp_code) is None:
        raise _DartResponseError(
            SourceAuditStatus.IDENTIFIER_MISSING,
            "dart_corp_code_invalid",
        )


def _decode_list_page(
    payload: bytes,
    *,
    expected_page: int,
    binding: _Binding,
) -> _ListPage | None:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _DartMalformedResponse from error
    if not isinstance(decoded, dict):
        raise _DartMalformedResponse

    status = decoded.get("status")
    if status == "013":
        if expected_page != 1:
            raise _DartMalformedResponse
        return None
    if status != "000":
        _raise_for_dart_status(status)

    page_number = decoded.get("page_no")
    page_count = decoded.get("page_count")
    total_count = decoded.get("total_count")
    total_pages = decoded.get("total_page")
    items = decoded.get("list")
    if (
        not _is_int(page_number)
        or page_number != expected_page
        or not _is_int(page_count)
        or page_count != _PAGE_COUNT
        or not _is_int(total_count)
        or total_count < 1
        or not _is_int(total_pages)
        or total_pages < 1
        or not isinstance(items, list)
    ):
        raise _DartMalformedResponse
    calculated_pages = (total_count + page_count - 1) // page_count
    expected_items = (
        page_count
        if expected_page < total_pages
        else total_count - page_count * (expected_page - 1)
    )
    if (
        total_pages != calculated_pages
        or expected_page > total_pages
        or expected_items < 1
        or len(items) != expected_items
    ):
        raise _DartMalformedResponse
    return _ListPage(
        filings=tuple(_parse_filing(item, binding=binding) for item in items),
        total_count=total_count,
        total_pages=total_pages,
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


def _parse_filing(item: object, *, binding: _Binding) -> _Filing:
    if not isinstance(item, dict):
        raise _DartMalformedResponse
    corp_code = item.get("corp_code")
    corp_name = item.get("corp_name")
    report_name = item.get("report_nm")
    receipt_no = item.get("rcept_no")
    receipt_date_text = item.get("rcept_dt")
    rm = item.get("rm")
    if not all(
        isinstance(value, str) and bool(value.strip())
        for value in (
            corp_code,
            corp_name,
            report_name,
            receipt_no,
            receipt_date_text,
        )
    ) or not isinstance(rm, str):
        raise _DartMalformedResponse
    assert isinstance(corp_code, str)
    assert isinstance(corp_name, str)
    assert isinstance(report_name, str)
    assert isinstance(receipt_no, str)
    assert isinstance(receipt_date_text, str)
    if corp_code != binding.corp_code:
        raise _DartResponseError(
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "dart_corp_code_response_mismatch",
        )
    if (
        binding.mode == "publisher"
        and _normalize_whitespace(corp_name)
        != _normalize_whitespace(binding.publisher_name or "")
    ):
        raise _DartResponseError(
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "dart_publisher_name_mismatch",
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
    report_identity, markers = _report_metadata(report_name)
    document_type = _document_type(report_identity)
    product_name = (
        _publisher_product_name(report_identity)
        if binding.mode == "publisher" and document_type
        else None
    )
    correction_state = "current"
    if "철" in rm:
        correction_state = "withdrawn"
    elif any(marker in _UNRESOLVED_MARKERS for marker in markers):
        correction_state = "unresolved"
    elif not markers and "정" in rm:
        correction_state = "superseded"
    return _Filing(
        corp_name=corp_name,
        receipt_no=receipt_no,
        receipt_date=receipt_date,
        document_type=document_type,
        report_identity=report_identity,
        product_name=product_name,
        correction_state=correction_state,
    )


def _select_current_filings(
    filings: tuple[_Filing, ...],
    *,
    binding: _Binding,
    target_name: str,
    member_names: tuple[str, ...] = (),
    cutoff_date: date,
) -> tuple[_Filing, ...]:
    prospectuses = tuple(filing for filing in filings if filing.document_type)
    exact = tuple(
        filing
        for filing in prospectuses
        if _normalize_product_identity(
            filing.corp_name
            if binding.mode == "product"
            else filing.product_name or ""
        )
        == _normalize_product_identity(target_name)
    )
    if not exact and binding.mode == "publisher" and member_names:
        matched_names = {
            _normalize_product_identity(filing.product_name or "")
            for filing in prospectuses
            if filing.product_name is not None
            and _matches_all_share_classes(filing.product_name, member_names)
        }
        if len(matched_names) > 1:
            raise _DartResponseError(
                SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
                "dart_product_metadata_ambiguous",
            )
        if matched_names:
            selected_name = next(iter(matched_names))
            exact = tuple(
                filing
                for filing in prospectuses
                if _normalize_product_identity(filing.product_name or "")
                == selected_name
            )
    if not exact:
        if binding.mode == "publisher" and any(
            filing.product_name is None for filing in prospectuses
        ):
            raise _DartResponseError(
                SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
                "dart_product_metadata_ambiguous",
            )
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
    current_filings = tuple(
        filing
        for filing in current.values()
        if filing.correction_state == "current"
    )
    if not current_filings:
        raise _DartResponseError(
            SourceAuditStatus.VERSION_UNKNOWN,
            "dart_correction_state_unresolved",
        )
    return tuple(
        sorted(
            current_filings,
            key=lambda filing: (filing.document_type, filing.receipt_no),
        )
    )


def _matches_all_share_classes(
    official_fund_name: str,
    member_names: tuple[str, ...],
) -> bool:
    official = _normalize_product_identity(official_fund_name)
    if not official:
        return False
    suffixes: list[str] = []
    for member_name in member_names:
        member = _normalize_product_identity(member_name)
        if not member.startswith(official):
            return False
        suffixes.append(member[len(official) :])
    return any(suffixes) and all(_is_explicit_share_class_suffix(value) for value in suffixes)


def _is_explicit_share_class_suffix(value: str) -> bool:
    if not value or len(value) > 32:
        return False
    normalized = value.upper()
    if any(
        token in normalized
        for token in ("투자신탁", "증권", "주식", "채권", "펀드", "호")
    ):
        return False
    if any(token in normalized for token in ("클래스", "CLASS", "종류")):
        return True
    stripped = normalized.strip("_-()")
    return re.fullmatch(r"[A-Z][A-Z0-9-]*(?:\([^()]+\))?", stripped) is not None


def _candidate(
    filing: _Filing,
    *,
    target_entity_id: str,
) -> DocumentSourceCandidate:
    published_at = datetime.combine(
        filing.receipt_date,
        datetime.min.time(),
        tzinfo=_SEOUL,
    )
    source_locator = sanitize_public_locator(
        f"{_VIEWER_ENDPOINT}?rcpNo={filing.receipt_no}",
        allowed_hosts=frozenset({"dart.fss.or.kr"}),
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
        discovery_locator=source_locator,
        jurisdiction="KR",
        original_language="ko",
        published_at=published_at,
        available_at=published_at,
        effective_from=None,
        effective_to=None,
        media_type=None,
        accession_or_receipt_id=filing.receipt_no,
        target_entity_id=target_entity_id,
    )


def _document_type(report_name: str) -> str:
    normalized = _normalize_whitespace(report_name)
    if "투자설명서" not in normalized or "집합투자증권" not in normalized:
        return ""
    if "간이투자설명서" in normalized:
        return "summary_prospectus"
    return "full_prospectus"


def _report_metadata(report_name: str) -> tuple[str, tuple[str, ...]]:
    remaining = report_name
    markers: list[str] = []
    while match := _CORRECTION_MARKER.match(remaining):
        markers.append(match.group(1))
        remaining = remaining[match.end() :]
    return _normalize_whitespace(remaining), tuple(markers)


def _publisher_product_name(report_identity: str) -> str | None:
    match = _PUBLISHER_PRODUCT_PREFIX.match(report_identity)
    if match is None:
        return None
    product_name = _single_balanced_wrapper(report_identity[match.end() :].strip())
    if product_name is None:
        return None
    return _normalize_whitespace(product_name)


def _single_balanced_wrapper(value: str) -> str | None:
    if len(value) < 3 or value[0] not in {"(", "["}:
        return None
    pairs = {"(": ")", "[": "]"}
    closing = frozenset(pairs.values())
    stack: list[str] = []
    for index, character in enumerate(value):
        if character in pairs:
            stack.append(pairs[character])
        elif character in closing:
            if not stack or stack.pop() != character:
                return None
            if not stack and index != len(value) - 1:
                return None
    if stack:
        return None
    product_name = value[1:-1]
    return product_name if product_name.strip() else None


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _normalize_product_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(str.maketrans({"[": "(", "]": ")"}))
    return "".join(normalized.split())


def _url(endpoint: str, **parameters: str) -> str:
    return f"{endpoint}?{urlencode(parameters)}"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _unavailable(
    status: SourceAuditStatus,
    reason_code: str,
) -> SourceAdapterResult:
    return SourceAdapterResult(
        status=status,
        reason_code=reason_code,
        candidates=(),
        attempted_source=DocumentSourceAttempt("DART", None, None),
    )
