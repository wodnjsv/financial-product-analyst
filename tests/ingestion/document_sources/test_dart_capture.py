from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

import pytest

from financial_agent.documents import (
    DocumentSourceCandidate,
    PublisherRole,
    SourceAuthorityTier,
)
from financial_agent.ingestion.document_sources.dart_capture import (
    capture_dart_full_prospectus,
)
from financial_agent.ingestion.sources import SourceVerificationError


_SEOUL = timezone(timedelta(hours=9))
_RECEIPT = "20260805000047"
_PRODUCT_NAME = "삼성 KODEX 모멘텀PLUS증권상장지수투자신탁[주식]"
_PDF = b"%PDF-1.4\nsynthetic full prospectus\n%%EOF\n"


class _Response(BytesIO):
    def __init__(
        self,
        payload: bytes,
        *,
        content_type: str,
        status: int = 200,
    ) -> None:
        super().__init__(payload)
        self.status = status
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
        }


class _SyntheticOpener:
    def __init__(self, responses: Mapping[str, _Response]) -> None:
        self.responses = dict(responses)
        self.requests: list[tuple[str, dict[str, str]]] = []

    def open_no_redirect(
        self,
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Response:
        del method, timeout
        self.requests.append((url, dict(headers)))
        response = self.responses.get(urlparse(url).path)
        if response is None:
            raise AssertionError(f"unexpected synthetic path: {urlparse(url).path}")
        return response


def _candidate() -> DocumentSourceCandidate:
    published = datetime(2026, 8, 5, tzinfo=_SEOUL)
    return DocumentSourceCandidate(
        document_id=f"dart-rcept:{_RECEIPT}",
        source_code="DART",
        authority_tier=SourceAuthorityTier.TIER_1_REGULATORY,
        publisher_code="FSS_DART",
        publisher_role=PublisherRole.REGULATOR_DISCLOSURE,
        document_type="full_prospectus",
        document_version=_RECEIPT,
        source_locator=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={_RECEIPT}",
        discovery_locator=(
            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={_RECEIPT}"
        ),
        jurisdiction="KR",
        original_language="ko",
        published_at=published,
        available_at=published,
        effective_from=date(2026, 8, 5),
        effective_to=None,
        media_type="application/pdf",
        accession_or_receipt_id=_RECEIPT,
        target_entity_id="domestic-etf:KR7244620001",
    )


def _viewer_html() -> bytes:
    return b"""
    <html><script>
    node1['dcmNo'] = "11509553";
    node1['dcmNo'] = "11509553";
    </script></html>
    """


def _download_html(*rows: str) -> bytes:
    return ("<html><table>" + "".join(rows) + "</table></html>").encode()


def _row(filename: str, href: str) -> str:
    return (
        f'<tr><td class="tL">{filename}</td>'
        f'<td><a class="btnFile" href="{href}"></a></td></tr>'
    )


def _opener(*attachment_rows: str, pdf: bytes = _PDF) -> _SyntheticOpener:
    generated = _row(
        "[삼성자산운용][정정]투자설명서(집합투자증권)(2026.08.05).pdf",
        f"/pdf/download/pdf.do?rcp_no={_RECEIPT}&dcm_no=11509553",
    )
    return _SyntheticOpener(
        {
            "/dsaf001/main.do": _Response(
                _viewer_html(), content_type="text/html"
            ),
            "/pdf/download/main.do": _Response(
                _download_html(generated, *attachment_rows),
                content_type="text/html",
            ),
            "/pdf/download/file.do": _Response(
                pdf,
                content_type="application/pdf",
            ),
        }
    )


def _matching_attachment() -> str:
    return _row(
        (
            "투자설명서(개편)_삼성kodex모멘텀plus증권상장지수"
            "투자신탁(주식)_reviewed.pdf"
        ),
        (
            f"/pdf/download/file.do?rcp_no={_RECEIPT}"
            "&dcm_id=10611&dcm_seq=949&fl_nm=reviewed.pdf"
        ),
    )


def test_capture_selects_bound_full_attachment_not_generated_report(
    tmp_path: Path,
) -> None:
    opener = _opener(_matching_attachment())
    destination = tmp_path / "prospectus.pdf"

    captured = capture_dart_full_prospectus(
        opener,
        candidate=_candidate(),
        canonical_name=_PRODUCT_NAME,
        destination=destination,
        maximum_bytes=1024,
    )

    assert destination.read_bytes() == _PDF
    assert captured.object_name.endswith("_reviewed.pdf")
    assert captured.object_key == (
        f"documents/dart/{_RECEIPT}/full-prospectus.pdf"
    )
    assert captured.media_type == "application/pdf"
    assert captured.size_bytes == len(_PDF)
    assert captured.sha256 == hashlib.sha256(_PDF).hexdigest()
    assert captured.attachment_locator == opener.requests[-1][0]
    assert urlparse(opener.requests[-1][0]).path == "/pdf/download/file.do"
    assert opener.requests[-1][1]["Referer"].endswith(
        f"rcp_no={_RECEIPT}&dcm_no=11509553"
    )
    request_headers = {
        name.lower(): value for name, value in opener.requests[-1][1].items()
    }
    assert request_headers["user-agent"] == (
        "financial-product-agent-document-capture/1.0"
    )


def test_capture_accepts_exact_etf_name_before_abbreviated_legal_suffix(
    tmp_path: Path,
) -> None:
    opener = _opener(
        _row(
            (
                "(44a5)kbrise200totalreturn증권상장지수(주식)"
                "투자설명서-260129.pdf"
            ),
            (
                f"/pdf/download/file.do?rcp_no={_RECEIPT}"
                "&dcm_id=10611&dcm_seq=249&fl_nm=rise.pdf"
            ),
        )
    )

    captured = capture_dart_full_prospectus(
        opener,
        candidate=_candidate(),
        canonical_name=(
            "KB RISE 200 Total Return증권상장지수투자신탁(주식)"
        ),
        destination=tmp_path / "prospectus.pdf",
        maximum_bytes=1024,
    )

    assert captured.object_name.startswith("(44a5)kbrise200totalreturn")


def test_capture_rejects_attachment_for_a_different_product(
    tmp_path: Path,
) -> None:
    opener = _opener(
        _row(
            "투자설명서_다른상품증권상장지수투자신탁(주식).pdf",
            f"/pdf/download/file.do?rcp_no={_RECEIPT}&fl_nm=other.pdf",
        )
    )

    with pytest.raises(SourceVerificationError) as caught:
        capture_dart_full_prospectus(
            opener,
            candidate=_candidate(),
            canonical_name=_PRODUCT_NAME,
            destination=tmp_path / "prospectus.pdf",
            maximum_bytes=1024,
        )

    assert caught.value.code == "DART_PROSPECTUS_ATTACHMENT_NOT_FOUND"
    assert not (tmp_path / "prospectus.pdf").exists()


def test_capture_rejects_non_pdf_bytes_without_leaving_an_object(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "prospectus.pdf"

    with pytest.raises(SourceVerificationError) as caught:
        capture_dart_full_prospectus(
            _opener(_matching_attachment(), pdf=b"not a PDF"),
            candidate=_candidate(),
            canonical_name=_PRODUCT_NAME,
            destination=destination,
            maximum_bytes=1024,
        )

    assert caught.value.code == "DART_PROSPECTUS_PDF_INVALID"
    assert not destination.exists()
