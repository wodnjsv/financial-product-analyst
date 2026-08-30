"""Deterministic text-layer PDF extraction and section assembly."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from .chunking import ExtractedSection


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUMMARY_HEADINGS = frozenset({"요약정보", "간이투자설명서"})
_CLAIM_HEADINGS = frozenset(
    {
        "투자목적",
        "투자 목적",
        "투자목적 및 투자전략",
        "투자 목적 및 투자 전략",
        "투자전략",
        "투자 전략",
        "주요투자위험",
        "주요 투자위험",
        "집합투자기구의 투자목적",
        "집합투자기구의 투자전략",
        "집합투자기구의 투자위험",
    }
)


class PdfExtractionError(ValueError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        super().__init__(code if detail is None else f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class PdfTextLine:
    text: str
    top: float
    dominant_size: float
    emphasized: bool


@dataclass(frozen=True, slots=True)
class PdfTableRow:
    cells: tuple[str | None, ...]
    top: float
    bottom: float


@dataclass(frozen=True, slots=True)
class PdfPageLayout:
    page_number: int
    lines: tuple[PdfTextLine, ...]
    table_rows: tuple[PdfTableRow, ...]


@dataclass(frozen=True, slots=True)
class ExtractedPdfDocument:
    canonical_text: str
    page_count: int
    text_page_count: int
    sections: tuple[ExtractedSection, ...]
    source_checksum: str
    text_checksum: str
    extraction_method: str
    extraction_version: str
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _LineSpan:
    page_number: int
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _OpenSection:
    heading_path: tuple[str, ...]
    page_start: int
    character_start: int


def assemble_pdf_sections(
    pages: tuple[PdfPageLayout, ...],
    *,
    source_checksum: str,
    extraction_version: str,
) -> ExtractedPdfDocument:
    """Assemble validated page layouts into reproducible section spans."""

    _validate_assembly_input(
        pages,
        source_checksum=source_checksum,
        extraction_version=extraction_version,
    )
    canonical_text, spans = _canonical_text(pages)
    sections = _sections(canonical_text, spans)
    return ExtractedPdfDocument(
        canonical_text=canonical_text,
        page_count=len(pages),
        text_page_count=len(pages),
        sections=sections,
        source_checksum=source_checksum,
        text_checksum=hashlib.sha256(canonical_text.encode()).hexdigest(),
        extraction_method="pdf_text_layer",
        extraction_version=extraction_version,
        issues=(),
    )


def _validate_assembly_input(
    pages: tuple[PdfPageLayout, ...],
    *,
    source_checksum: str,
    extraction_version: str,
) -> None:
    if not isinstance(pages, tuple) or not pages:
        raise PdfExtractionError("PDF_PAGE_ORDER_INVALID")
    if _SHA256.fullmatch(source_checksum) is None:
        raise PdfExtractionError("PDF_SOURCE_CHECKSUM_INVALID")
    if not extraction_version.strip():
        raise PdfExtractionError("PDF_EXTRACTION_VERSION_INVALID")
    if tuple(page.page_number for page in pages) != tuple(range(1, len(pages) + 1)):
        raise PdfExtractionError("PDF_PAGE_ORDER_INVALID")
    for page in pages:
        if not page.lines and not any(
            cell is not None and cell.strip()
            for row in page.table_rows
            for cell in row.cells
        ):
            raise PdfExtractionError("PDF_TEXT_LAYER_MISSING")


def _canonical_text(
    pages: tuple[PdfPageLayout, ...],
) -> tuple[str, tuple[_LineSpan, ...]]:
    parts: list[str] = []
    spans: list[_LineSpan] = []
    cursor = 0
    for page_index, page in enumerate(pages):
        if page_index:
            parts.append("\n\f\n")
            cursor += 3
        for line_index, source_line in enumerate(page.lines):
            if line_index:
                parts.append("\n")
                cursor += 1
            text = " ".join(source_line.text.split())
            start = cursor
            parts.append(text)
            cursor += len(text)
            spans.append(_LineSpan(page.page_number, text, start, cursor))
    return "".join(parts), tuple(spans)


def _sections(
    canonical_text: str, spans: tuple[_LineSpan, ...]
) -> tuple[ExtractedSection, ...]:
    root_path: tuple[str, ...] = ()
    current: _OpenSection | None = None
    sections: list[ExtractedSection] = []
    for span in spans:
        heading = _normalized_heading(span.text)
        if heading in _SUMMARY_HEADINGS:
            if current is not None:
                _close_section(canonical_text, spans, current, span.start, sections)
                current = None
            root_path = (heading,)
            continue
        if heading not in _CLAIM_HEADINGS:
            continue
        if current is not None:
            _close_section(canonical_text, spans, current, span.start, sections)
        current = _OpenSection(
            heading_path=(*root_path, heading),
            page_start=span.page_number,
            character_start=_next_content_start(canonical_text, span.end),
        )
    if current is not None:
        _close_section(canonical_text, spans, current, len(canonical_text), sections)
    return tuple(sections)


def _normalized_heading(text: str) -> str:
    normalized = " ".join(text.split()).strip()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1].strip()
    return normalized


def _next_content_start(text: str, position: int) -> int:
    while position < len(text) and text[position] in "\n\f":
        position += 1
    return position


def _close_section(
    canonical_text: str,
    spans: tuple[_LineSpan, ...],
    current: _OpenSection,
    end: int,
    output: list[ExtractedSection],
) -> None:
    start = current.character_start
    while end > start and canonical_text[end - 1] in "\n\f ":
        end -= 1
    if end <= start:
        return
    exact_text = canonical_text[start:end]
    page_end = current.page_start
    for span in spans:
        if span.start < end and span.end > start:
            page_end = span.page_number
    output.append(
        ExtractedSection(
            heading_path=current.heading_path,
            exact_text=exact_text,
            page_start=current.page_start,
            page_end=page_end,
            character_start=start,
            character_end=end,
        )
    )
