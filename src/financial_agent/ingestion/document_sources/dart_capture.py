"""Capture a full prospectus attached to an already-bound DART filing."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
import unicodedata
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request

from financial_agent.documents import DocumentSourceCandidate
from financial_agent.ingestion.official import (
    OfficialObjectManifest,
    capture_http_object,
)
from financial_agent.ingestion.sources import SourceVerificationError

from .base import NoRedirectHttpOpener


_DART_HOST = "dart.fss.or.kr"
_RECEIPT_NO = re.compile(r"^[0-9]{14}$")
_DCM_NO = re.compile(r"node1\['dcmNo'\]\s*=\s*\"([0-9]+)\"\s*;")
_HTML_LIMIT_BYTES = 4 * 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class DartCapturedProspectus:
    manifest: OfficialObjectManifest
    attachment_locator: str

    @property
    def object_name(self) -> str:
        return self.manifest.object_name

    @property
    def object_key(self) -> str:
        return self.manifest.object_key

    @property
    def media_type(self) -> str:
        return self.manifest.media_type

    @property
    def size_bytes(self) -> int:
        return self.manifest.size_bytes

    @property
    def sha256(self) -> str:
        return self.manifest.sha256


class _DownloadTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_row = False
        self._text: list[str] = []
        self._hrefs: list[str] = []
        self.rows: list[tuple[str, tuple[str, ...]]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "tr":
            self._in_row = True
            self._text = []
            self._hrefs = []
        elif tag == "a" and self._in_row:
            href = dict(attrs).get("href")
            if href:
                self._hrefs.append(href)

    def handle_data(self, data: str) -> None:
        if self._in_row:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._in_row:
            text = " ".join(" ".join(self._text).split())
            self.rows.append((text, tuple(self._hrefs)))
            self._in_row = False


class _CaptureOpener:
    def __init__(self, opener: NoRedirectHttpOpener) -> None:
        self._opener = opener

    def open(self, request: object) -> object:
        if not isinstance(request, Request):
            raise TypeError("DART capture request must be a urllib Request")
        response = _open(
            self._opener,
            request.full_url,
            headers=dict(request.header_items()),
        )
        if _status(response) != 200:
            response.close()
            raise _error(
                "DART_PROSPECTUS_DOWNLOAD_FAILED",
                "DART prospectus download did not return success",
            )
        return response


def _error(code: str, message: str) -> SourceVerificationError:
    return SourceVerificationError(code, message)


def capture_dart_full_prospectus(
    opener: NoRedirectHttpOpener,
    *,
    candidate: DocumentSourceCandidate,
    canonical_name: str,
    destination: Path,
    maximum_bytes: int,
) -> DartCapturedProspectus:
    """Resolve and atomically capture one official full-prospectus PDF."""

    receipt_no = _validate_candidate(candidate)
    if not canonical_name.strip():
        raise ValueError("canonical_name must not be blank")
    if destination.exists():
        raise _error(
            "DART_PROSPECTUS_TARGET_EXISTS",
            "DART prospectus capture target already exists",
        )

    viewer_url = (
        f"https://{_DART_HOST}/dsaf001/main.do?rcpNo={receipt_no}"
    )
    viewer_html = _read_html(opener, viewer_url)
    dcm_numbers = set(_DCM_NO.findall(viewer_html))
    if len(dcm_numbers) != 1:
        raise _error(
            "DART_PROSPECTUS_DOCUMENT_ID_AMBIGUOUS",
            "DART filing document identity is missing or ambiguous",
        )
    dcm_no = next(iter(dcm_numbers))
    download_page_url = (
        f"https://{_DART_HOST}/pdf/download/main.do"
        f"?rcp_no={receipt_no}&dcm_no={dcm_no}"
    )
    download_html = _read_html(opener, download_page_url)
    attachment_name, attachment_url = _select_attachment(
        download_html,
        receipt_no=receipt_no,
        canonical_name=canonical_name,
        base_url=download_page_url,
    )

    request = Request(
        attachment_url,
        headers={
            "Accept": "application/pdf",
            "Accept-Encoding": "identity",
            "Referer": download_page_url,
            "User-Agent": "financial-product-agent-document-capture/1.0",
        },
        method="GET",
    )
    object_manifest = capture_http_object(
        _CaptureOpener(opener),
        request=request,
        destination=destination,
        object_name=attachment_name,
        object_key=f"documents/dart/{receipt_no}/full-prospectus.pdf",
        expected_media_type="application/pdf",
        maximum_bytes=maximum_bytes,
    )
    try:
        with destination.open("rb") as captured:
            if captured.read(5) != b"%PDF-":
                raise _error(
                    "DART_PROSPECTUS_PDF_INVALID",
                    "DART prospectus attachment is not a PDF",
                )
    except SourceVerificationError:
        destination.unlink(missing_ok=True)
        raise
    except OSError:
        destination.unlink(missing_ok=True)
        raise _error(
            "DART_PROSPECTUS_PDF_INVALID",
            "DART prospectus attachment could not be verified",
        ) from None
    return DartCapturedProspectus(
        manifest=object_manifest,
        attachment_locator=attachment_url,
    )


def _validate_candidate(candidate: DocumentSourceCandidate) -> str:
    receipt_no = candidate.accession_or_receipt_id
    if (
        candidate.source_code != "DART"
        or candidate.document_type != "full_prospectus"
        or receipt_no is None
        or _RECEIPT_NO.fullmatch(receipt_no) is None
    ):
        raise _error(
            "DART_PROSPECTUS_CANDIDATE_INVALID",
            "DART full-prospectus candidate is invalid",
        )
    return receipt_no


def _read_html(opener: NoRedirectHttpOpener, url: str) -> str:
    response = _open(
        opener,
        url,
        headers={"Accept": "text/html", "Accept-Encoding": "identity"},
    )
    try:
        if _status(response) != 200:
            raise _error(
                "DART_PROSPECTUS_DISCOVERY_FAILED",
                "DART prospectus discovery did not return success",
            )
        content_type = _header(response, "Content-Type")
        if (content_type or "").split(";", 1)[0].strip().lower() != "text/html":
            raise _error(
                "DART_PROSPECTUS_DISCOVERY_FAILED",
                "DART prospectus discovery did not return HTML",
            )
        payload = response.read(_HTML_LIMIT_BYTES + 1)
        if len(payload) > _HTML_LIMIT_BYTES:
            raise _error(
                "DART_PROSPECTUS_DISCOVERY_FAILED",
                "DART prospectus discovery response is too large",
            )
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        raise _error(
            "DART_PROSPECTUS_DISCOVERY_FAILED",
            "DART prospectus discovery response is not UTF-8",
        ) from None
    finally:
        response.close()


def _select_attachment(
    payload: str,
    *,
    receipt_no: str,
    canonical_name: str,
    base_url: str,
) -> tuple[str, str]:
    parser = _DownloadTableParser()
    parser.feed(payload)
    target_identity = _identity(canonical_name)
    matches: list[tuple[str, str]] = []
    for row_text, hrefs in parser.rows:
        if (
            "투자설명서" not in row_text
            or "간이투자설명서" in row_text
            or target_identity not in _identity(row_text)
        ):
            continue
        for href in hrefs:
            url = urljoin(base_url, href)
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            if (
                parsed.scheme == "https"
                and parsed.hostname == _DART_HOST
                and parsed.port in {None, 443}
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
                and parsed.path == "/pdf/download/file.do"
                and query.get("rcp_no") == [receipt_no]
            ):
                matches.append((row_text, url))
    if not matches:
        raise _error(
            "DART_PROSPECTUS_ATTACHMENT_NOT_FOUND",
            "bound DART full-prospectus attachment was not found",
        )
    if len(matches) != 1:
        raise _error(
            "DART_PROSPECTUS_ATTACHMENT_AMBIGUOUS",
            "bound DART full-prospectus attachment is ambiguous",
        )
    return matches[0]


def _identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _open(
    opener: NoRedirectHttpOpener,
    url: str,
    *,
    headers: dict[str, str],
) -> object:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _DART_HOST
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise _error(
            "DART_PROSPECTUS_LOCATOR_INVALID",
            "DART prospectus locator is invalid",
        )
    response = opener.open_no_redirect(
        url,
        method="GET",
        headers=headers,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    return response


def _status(response: object) -> int:
    status = getattr(response, "status", None)
    if not isinstance(status, int) or isinstance(status, bool):
        raise _error(
            "DART_PROSPECTUS_RESPONSE_INVALID",
            "DART prospectus response status is invalid",
        )
    return status


def _header(response: object, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    getter = getattr(headers, "get", None)
    value = getter(name) if callable(getter) else None
    return value if isinstance(value, str) else None
