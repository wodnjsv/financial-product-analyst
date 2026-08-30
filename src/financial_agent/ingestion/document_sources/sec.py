"""Fail-closed SEC EDGAR discovery for overseas ETF prospectuses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import json
import re
from typing import BinaryIO
from urllib.parse import urlparse
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
    SourceAdapterResult,
    classify_access_error,
    sanitize_public_locator,
)


_SUBMISSIONS_ROOT = "https://data.sec.gov/submissions"
_ARCHIVES_ROOT = "https://www.sec.gov/Archives/edgar/data"
_SEOUL = ZoneInfo("Asia/Seoul")
_CIK = re.compile(r"^[0-9]{1,10}$")
_SERIES_ID = re.compile(r"^S[0-9]{9}$")
_CLASS_ID = re.compile(r"^C[0-9]{9}$")
_ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
_PRIMARY_DOCUMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_USER_AGENT = re.compile(
    r"^\S(?:.*\S)?\s+[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$"
)
_TAG_TEMPLATE = r"<{tag}>\s*([^<\r\n]+)"
_DISCOVERY_FORMS = frozenset({"497K", "497", "485BPOS", "N-1A", "N-1A/A"})
_FULL_FORMS = frozenset({"485BPOS", "N-1A", "N-1A/A"})
_MAX_SUBMISSION_FILES = 100
_MAX_FILINGS_PER_RESPONSE = 100_000
_MAX_INDEX_ITEMS = 10_000
_MAX_SUBMISSIONS_BYTES = 8 * 1024 * 1024
_MAX_INDEX_BYTES = 2 * 1024 * 1024
_MAX_HEADER_BYTES = 512 * 1024
_REQUEST_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class _Binding:
    cik: str
    padded_cik: str
    series_id: str
    class_id: str


@dataclass(frozen=True, slots=True)
class _Filing:
    accession: str
    filing_date: date
    accepted_at: datetime
    form: str
    primary_document: str
    description: str


@dataclass(frozen=True, slots=True)
class _SubmissionFile:
    name: str
    filing_count: int


@dataclass(frozen=True, slots=True)
class _BoundFiling:
    filing: _Filing
    media_type: str


class _SecResponseError(Exception):
    def __init__(self, status: SourceAuditStatus, reason_code: str) -> None:
        self.status = status
        self.reason_code = reason_code
        super().__init__(reason_code)


class _SecMalformedResponse(Exception):
    pass


class SecDocumentSourceAdapter:
    """Discover exact SEC Series/Class-bound filing metadata."""

    source_code = "SEC"

    def __init__(self, opener: object) -> None:
        self._opener = opener

    def supports(self, target: DocumentSourceTarget) -> bool:
        return (
            target.entity_type == "product"
            and target.product_family == "overseas_etf"
            and target.required_role is DocumentRole.PRODUCT_SUMMARY
            and target.binding_role == "subject_product"
        )

    def discover(
        self,
        target: DocumentSourceTarget,
        context: DocumentDiscoveryContext,
    ) -> SourceAdapterResult:
        if not self.supports(target):
            return _unavailable(
                SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE,
                "sec_target_not_supported",
            )
        user_agent = context.sec_user_agent
        if user_agent is None or _USER_AGENT.fullmatch(user_agent.strip()) is None:
            return _unavailable(
                SourceAuditStatus.CREDENTIALS_MISSING,
                "sec_user_agent_missing",
            )
        try:
            binding = _resolve_binding(target)
        except _SecResponseError as error:
            return _unavailable(error.status, error.reason_code)
        if context.cutoff_date != target.cutoff_date:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "sec_cutoff_mismatch",
            )

        headers = {
            "User-Agent": user_agent.strip(),
            "Accept-Encoding": "identity",
        }
        attempted_source = DocumentSourceAttempt(
            source_code="SEC",
            source_locator=None,
            discovery_locator=(
                f"{_SUBMISSIONS_ROOT}/CIK{binding.padded_cik}.json"
            ),
        )
        try:
            filings = self._filings(binding=binding, headers=headers)
            selected = self._discover_bound(
                filings,
                binding=binding,
                cutoff_date=context.cutoff_date,
                headers=headers,
            )
        except _SecResponseError as error:
            return _unavailable(
                error.status,
                error.reason_code,
                attempted_source=attempted_source,
            )
        except _SecMalformedResponse:
            return _unavailable(
                SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
                "sec_response_malformed",
                attempted_source=attempted_source,
            )
        except Exception as error:
            status = classify_access_error(error)
            return _unavailable(
                status,
                f"sec_{status.value}",
                attempted_source=attempted_source,
            )

        return SourceAdapterResult(
            status=SourceAuditStatus.ELIGIBLE,
            reason_code=None,
            candidates=tuple(_candidate(item, binding=binding) for item in selected),
        )

    def _filings(
        self,
        *,
        binding: _Binding,
        headers: dict[str, str],
    ) -> tuple[_Filing, ...]:
        main_url = f"{_SUBMISSIONS_ROOT}/CIK{binding.padded_cik}.json"
        payload = self._read(main_url, _MAX_SUBMISSIONS_BYTES, headers=headers)
        filings, files = _decode_main_submissions(payload, binding=binding)
        all_filings = list(filings)
        for item in files:
            page_url = f"{_SUBMISSIONS_ROOT}/{item.name}"
            page_payload = self._read(
                page_url,
                _MAX_SUBMISSIONS_BYTES,
                headers=headers,
            )
            page_filings = _decode_filing_columns(page_payload)
            if len(page_filings) != item.filing_count:
                raise _SecMalformedResponse
            all_filings.extend(page_filings)
            if len(all_filings) > _MAX_FILINGS_PER_RESPONSE:
                raise _SecMalformedResponse
        accessions = [filing.accession for filing in all_filings]
        if len(accessions) != len(set(accessions)):
            raise _SecMalformedResponse
        return tuple(all_filings)

    def _discover_bound(
        self,
        filings: tuple[_Filing, ...],
        *,
        binding: _Binding,
        cutoff_date: date,
        headers: dict[str, str],
    ) -> tuple[_BoundFiling, ...]:
        recognized = tuple(
            filing for filing in filings if filing.form in _DISCOVERY_FORMS
        )
        cutoff_at = datetime.combine(cutoff_date, time.max, tzinfo=_SEOUL)
        eligible = tuple(
            filing
            for filing in recognized
            if filing.filing_date <= cutoff_date
            and filing.accepted_at.astimezone(_SEOUL) <= cutoff_at
        )
        if recognized and not eligible:
            raise _SecResponseError(
                SourceAuditStatus.AFTER_CUTOFF_ONLY,
                "sec_after_cutoff_only",
            )

        relevant = tuple(filing for filing in eligible if filing.form != "497")
        bound: list[_BoundFiling] = []
        for filing in relevant:
            archive_base = _archive_base(binding, filing.accession)
            index_payload = self._read(
                f"{archive_base}/index.json",
                _MAX_INDEX_BYTES,
                headers=headers,
            )
            media_type = _decode_filing_index(
                index_payload,
                archive_base=archive_base,
                filing=filing,
            )
            header_payload = self._read(
                f"{archive_base}/{filing.accession}.hdr.sgml",
                _MAX_HEADER_BYTES,
                headers=headers,
            )
            if _header_has_exact_binding(header_payload, binding=binding):
                bound.append(_BoundFiling(filing, media_type))

        selected = _select_bound(tuple(bound))
        if selected:
            return selected
        if relevant and not bound:
            raise _SecResponseError(
                SourceAuditStatus.DOCUMENT_NOT_FOUND,
                "sec_exact_series_class_not_found",
            )
        raise _SecResponseError(
            SourceAuditStatus.DOCUMENT_NOT_FOUND,
            "sec_prospectus_not_found",
        )

    def _read(
        self,
        url: str,
        limit: int,
        *,
        headers: dict[str, str],
    ) -> bytes:
        response = _open_no_redirect(
            self._opener,
            url,
            headers=headers,
        )
        try:
            status_code = _response_status(response)
        except Exception:
            response.close()
            raise
        if 300 <= status_code < 400:
            response.close()
            raise _SecResponseError(
                SourceAuditStatus.ACCESS_DENIED,
                "sec_redirect_location_denied",
            )
        if status_code != 200:
            response.close()
            raise HttpStatusError(status_code)
        try:
            payload = response.read(limit + 1)
        finally:
            response.close()
        if not isinstance(payload, bytes) or len(payload) > limit:
            raise _SecMalformedResponse
        return payload


def _open_no_redirect(
    opener: object,
    url: str,
    *,
    headers: dict[str, str],
) -> BinaryIO:
    open_method = getattr(opener, "open_no_redirect", None)
    if not callable(open_method):
        raise TypeError("SEC opener must provide open_no_redirect()")
    return open_method(  # type: ignore[no-any-return]
        url,
        headers=dict(headers),
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )


def _response_status(response: BinaryIO) -> int:
    status_code = getattr(response, "status", None)
    if not isinstance(status_code, int) or isinstance(status_code, bool):
        raise _SecMalformedResponse
    return status_code


def has_complete_sec_identity(target: DocumentSourceTarget) -> bool:
    """Return whether the target has one syntactically exact SEC identity."""

    try:
        _resolve_binding(target)
    except _SecResponseError:
        return False
    return True


def _resolve_binding(target: DocumentSourceTarget) -> _Binding:
    values = {
        scheme: tuple(
            value for item_scheme, value in target.identifiers if item_scheme == scheme
        )
        for scheme in ("SEC_CIK", "SEC_SERIES_ID", "SEC_CLASS_ID")
    }
    for scheme, reason in (
        ("SEC_CIK", "sec_cik_missing"),
        ("SEC_SERIES_ID", "sec_series_id_missing"),
        ("SEC_CLASS_ID", "sec_class_id_missing"),
    ):
        if not values[scheme]:
            raise _SecResponseError(SourceAuditStatus.IDENTIFIER_MISSING, reason)
        if len(values[scheme]) != 1:
            raise _SecResponseError(
                SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
                reason.replace("missing", "ambiguous"),
            )
    cik, series_id, class_id = (
        values["SEC_CIK"][0],
        values["SEC_SERIES_ID"][0],
        values["SEC_CLASS_ID"][0],
    )
    if (
        _CIK.fullmatch(cik) is None
        or int(cik) == 0
        or _SERIES_ID.fullmatch(series_id) is None
        or _CLASS_ID.fullmatch(class_id) is None
    ):
        raise _SecResponseError(
            SourceAuditStatus.IDENTIFIER_MISSING,
            "sec_identifier_invalid",
        )
    normalized_cik = cik.lstrip("0")
    return _Binding(
        cik=normalized_cik,
        padded_cik=normalized_cik.zfill(10),
        series_id=series_id,
        class_id=class_id,
    )


def _decode_main_submissions(
    payload: bytes,
    *,
    binding: _Binding,
) -> tuple[tuple[_Filing, ...], tuple[_SubmissionFile, ...]]:
    decoded = _decode_json(payload)
    if not isinstance(decoded, dict):
        raise _SecMalformedResponse
    cik = decoded.get("cik")
    filings = decoded.get("filings")
    if (
        not isinstance(cik, str)
        or cik.lstrip("0") != binding.cik
        or not isinstance(filings, dict)
    ):
        raise _SecMalformedResponse
    recent = filings.get("recent")
    files = filings.get("files")
    if not isinstance(recent, dict) or not isinstance(files, list):
        raise _SecMalformedResponse
    recent_filings = _parse_columns(recent)
    if len(files) > _MAX_SUBMISSION_FILES:
        raise _SecMalformedResponse
    parsed_files: list[_SubmissionFile] = []
    names: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise _SecMalformedResponse
        name = item.get("name")
        filing_count = item.get("filingCount")
        filing_from = item.get("filingFrom")
        filing_to = item.get("filingTo")
        if (
            not isinstance(name, str)
            or re.fullmatch(
                rf"CIK{binding.padded_cik}-submissions-[0-9]{{3}}\.json",
                name,
            )
            is None
            or name in names
            or not _is_int(filing_count)
            or filing_count < 0
            or filing_count > _MAX_FILINGS_PER_RESPONSE
        ):
            raise _SecMalformedResponse
        start = _parse_date(filing_from)
        end = _parse_date(filing_to)
        if end < start:
            raise _SecMalformedResponse
        names.add(name)
        parsed_files.append(_SubmissionFile(name, filing_count))
    return recent_filings, tuple(parsed_files)


def _decode_filing_columns(payload: bytes) -> tuple[_Filing, ...]:
    decoded = _decode_json(payload)
    if not isinstance(decoded, dict):
        raise _SecMalformedResponse
    return _parse_columns(decoded)


def _decode_json(payload: bytes) -> object:
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _SecMalformedResponse from error


def _parse_columns(columns: dict[object, object]) -> tuple[_Filing, ...]:
    field_names = (
        "accessionNumber",
        "filingDate",
        "acceptanceDateTime",
        "form",
        "primaryDocument",
        "primaryDocDescription",
    )
    arrays = [columns.get(field) for field in field_names]
    if not all(isinstance(values, list) for values in arrays):
        raise _SecMalformedResponse
    typed_arrays = [values for values in arrays if isinstance(values, list)]
    lengths = {len(values) for values in typed_arrays}
    if len(lengths) != 1:
        raise _SecMalformedResponse
    count = lengths.pop()
    if count > _MAX_FILINGS_PER_RESPONSE:
        raise _SecMalformedResponse
    filings: list[_Filing] = []
    for index in range(count):
        values = [array[index] for array in typed_arrays]
        if not all(isinstance(value, str) for value in values):
            raise _SecMalformedResponse
        accession, filing_date, accepted_at, form, primary, description = values
        if (
            _ACCESSION.fullmatch(accession) is None
            or _PRIMARY_DOCUMENT.fullmatch(primary) is None
            or not form.strip()
        ):
            raise _SecMalformedResponse
        filings.append(
            _Filing(
                accession=accession,
                filing_date=_parse_date(filing_date),
                accepted_at=_parse_datetime(accepted_at),
                form=form.strip().upper(),
                primary_document=primary,
                description=description.strip(),
            )
        )
    return tuple(filings)


def _parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise _SecMalformedResponse
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise _SecMalformedResponse from error
    if parsed.isoformat() != value:
        raise _SecMalformedResponse
    return parsed


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _SecMalformedResponse from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _SecMalformedResponse
    return parsed


def _decode_filing_index(
    payload: bytes,
    *,
    archive_base: str,
    filing: _Filing,
) -> str:
    decoded = _decode_json(payload)
    if not isinstance(decoded, dict):
        raise _SecMalformedResponse
    directory = decoded.get("directory")
    if not isinstance(directory, dict):
        raise _SecMalformedResponse
    name = directory.get("name")
    items = directory.get("item")
    expected_path = urlparse(archive_base).path
    if (
        not isinstance(name, str)
        or name.rstrip("/") != expected_path
        or not isinstance(items, list)
        or len(items) > _MAX_INDEX_ITEMS
    ):
        raise _SecMalformedResponse
    item_types: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise _SecMalformedResponse
        item_name = item.get("name")
        media_type = item.get("type")
        if (
            not isinstance(item_name, str)
            or _PRIMARY_DOCUMENT.fullmatch(item_name) is None
            or not isinstance(media_type, str)
            or not media_type.strip()
            or item_name in item_types
        ):
            raise _SecMalformedResponse
        item_types[item_name] = media_type.strip().lower()
    header_name = f"{filing.accession}.hdr.sgml"
    if filing.primary_document not in item_types or header_name not in item_types:
        raise _SecMalformedResponse
    primary_type = item_types[filing.primary_document]
    if primary_type not in {"text/html", "application/xhtml+xml"}:
        raise _SecResponseError(
            SourceAuditStatus.MEDIA_TYPE_UNSUPPORTED,
            "sec_primary_media_type_unsupported",
        )
    return primary_type


def _header_has_exact_binding(payload: bytes, *, binding: _Binding) -> bool:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _SecMalformedResponse from error
    if "<SERIES-AND-CLASSES-CONTRACTS-DATA>" not in text:
        raise _SecMalformedResponse
    starts = [match.start() for match in re.finditer(r"<SERIES>", text)]
    if not starts:
        raise _SecMalformedResponse
    for index, start in enumerate(starts):
        next_start = starts[index + 1] if index + 1 < len(starts) else len(text)
        explicit_end = text.find("</SERIES>", start, next_start)
        end = explicit_end if explicit_end >= 0 else next_start
        block = text[start:end]
        owner_ciks = _tag_values(block, "OWNER-CIK")
        series_ids = _tag_values(block, "SERIES-ID")
        class_ids = _tag_values(block, "CLASS-CONTRACT-ID")
        if len(owner_ciks) != 1 or len(series_ids) != 1 or not class_ids:
            raise _SecMalformedResponse
        owner_cik = owner_ciks[0]
        if _CIK.fullmatch(owner_cik) is None:
            raise _SecMalformedResponse
        if (
            owner_cik.lstrip("0") == binding.cik
            and series_ids[0] == binding.series_id
            and binding.class_id in class_ids
        ):
            return True
    return False


def _tag_values(block: str, tag: str) -> tuple[str, ...]:
    pattern = re.compile(_TAG_TEMPLATE.format(tag=re.escape(tag)), re.IGNORECASE)
    return tuple(match.group(1).strip() for match in pattern.finditer(block))


def _select_bound(filings: tuple[_BoundFiling, ...]) -> tuple[_BoundFiling, ...]:
    summaries = tuple(item for item in filings if item.filing.form == "497K")
    full = tuple(item for item in filings if item.filing.form in _FULL_FORMS)
    base = (_latest(summaries),) if summaries else ((_latest(full),) if full else ())
    return tuple(item for item in base if item is not None)


def _latest(filings: tuple[_BoundFiling, ...]) -> _BoundFiling:
    return max(
        filings,
        key=lambda item: (item.filing.accepted_at, item.filing.accession),
    )


def _archive_base(binding: _Binding, accession: str) -> str:
    return f"{_ARCHIVES_ROOT}/{binding.cik}/{accession.replace('-', '')}"


def _candidate(
    item: _BoundFiling,
    *,
    binding: _Binding,
) -> DocumentSourceCandidate:
    filing = item.filing
    archive_base = _archive_base(binding, filing.accession)
    source_locator = sanitize_public_locator(
        f"{archive_base}/{filing.primary_document}",
        allowed_hosts=frozenset({"www.sec.gov"}),
    )
    discovery_locator = sanitize_public_locator(
        f"{archive_base}/{filing.accession}-index.html",
        allowed_hosts=frozenset({"www.sec.gov"}),
    )
    document_type = (
        "summary_prospectus" if filing.form == "497K" else "full_prospectus"
    )
    return DocumentSourceCandidate(
        document_id=f"sec-accession:{filing.accession}",
        source_code="SEC",
        authority_tier=SourceAuthorityTier.TIER_1_REGULATORY,
        publisher_code="US_SEC_EDGAR",
        publisher_role=PublisherRole.REGULATOR_DISCLOSURE,
        document_type=document_type,
        document_version=filing.accession,
        source_locator=source_locator,
        discovery_locator=discovery_locator,
        jurisdiction="US",
        original_language="en",
        published_at=filing.accepted_at,
        available_at=filing.accepted_at,
        effective_from=None,
        effective_to=None,
        media_type=item.media_type,
        accession_or_receipt_id=filing.accession,
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _unavailable(
    status: SourceAuditStatus,
    reason_code: str,
    *,
    attempted_source: DocumentSourceAttempt | None = None,
) -> SourceAdapterResult:
    return SourceAdapterResult(
        status=status,
        reason_code=reason_code,
        candidates=(),
        attempted_source=attempted_source
        or DocumentSourceAttempt("SEC", None, None),
    )
