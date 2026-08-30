"""Deterministic text-layer PDF extraction and section assembly."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import re
from pathlib import Path
from typing import Mapping

import pdfplumber

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
        "주요투자 위험",
        "집합투자기구의 투자목적",
        "집합투자기구의 투자전략",
        "집합투자기구의 투자위험",
    }
)
_BOUNDARY_HEADINGS = frozenset(
    {
        "분류",
        "투자비용",
        "투자실적",
        "운용전문인력",
        "투자자 유의사항",
        "투자결정시 유의사항 안내",
        "매입 방법",
        "환매 방법",
        "수수료",
        "보수 및 수수료",
        "과세",
        "재무제표",
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


def read_pdf_layout(pdf_path: Path) -> tuple[PdfPageLayout, ...]:
    """Read stable line and table geometry from one text-layer PDF."""

    try:
        payload = pdf_path.read_bytes()
        with pdfplumber.open(BytesIO(payload)) as document:
            if not document.pages:
                raise PdfExtractionError("PDF_OPEN_FAILED", "PDF has no pages")
            pages = tuple(
                _page_layout(page, page_number)
                for page_number, page in enumerate(document.pages, start=1)
            )
    except PdfExtractionError:
        raise
    except Exception as error:
        raise PdfExtractionError("PDF_OPEN_FAILED", type(error).__name__) from None
    return pages


def extract_pdf_sections(
    pdf_path: Path,
    *,
    extraction_version: str,
) -> ExtractedPdfDocument:
    """Extract one PDF from immutable bytes without an OCR fallback."""

    try:
        payload = pdf_path.read_bytes()
    except OSError as error:
        raise PdfExtractionError("PDF_OPEN_FAILED", type(error).__name__) from None
    source_checksum = hashlib.sha256(payload).hexdigest()
    try:
        with pdfplumber.open(BytesIO(payload)) as document:
            if not document.pages:
                raise PdfExtractionError("PDF_OPEN_FAILED", "PDF has no pages")
            pages = tuple(
                _page_layout(page, page_number)
                for page_number, page in enumerate(document.pages, start=1)
            )
    except PdfExtractionError:
        raise
    except Exception as error:
        raise PdfExtractionError("PDF_OPEN_FAILED", type(error).__name__) from None
    return assemble_pdf_sections(
        pages,
        source_checksum=source_checksum,
        extraction_version=extraction_version,
    )


def _page_layout(page: object, page_number: int) -> PdfPageLayout:
    extract_lines = getattr(page, "extract_text_lines")
    raw_lines = extract_lines(return_chars=True, strip=True) or []
    lines = tuple(_text_line(value) for value in raw_lines if value.get("text", "").strip())
    find_tables = getattr(page, "find_tables")
    rows: list[PdfTableRow] = []
    for table in sorted(find_tables(), key=lambda item: item.bbox):
        extracted = table.extract()
        for row_geometry, values in zip(table.rows, extracted, strict=True):
            cells = tuple(_clean_cell(value) for value in values)
            if not any(value for value in cells):
                continue
            _, top, _, bottom = row_geometry.bbox
            rows.append(PdfTableRow(cells, float(top), float(bottom)))
    return PdfPageLayout(page_number, lines, tuple(rows))


def _text_line(raw: Mapping[str, object]) -> PdfTextLine:
    characters = raw.get("chars")
    if not isinstance(characters, list) or not characters:
        raise PdfExtractionError("PDF_LINE_GEOMETRY_INVALID")
    sizes = [float(character["size"]) for character in characters]
    font_names = [str(character.get("fontname", "")).casefold() for character in characters]
    return PdfTextLine(
        text=" ".join(str(raw["text"]).split()),
        top=float(raw["top"]),
        dominant_size=max(sizes),
        emphasized=any(
            marker in font_name
            for font_name in font_names
            for marker in ("bold", "demi", "semibold")
        ),
    )


def _clean_cell(value: str | None) -> str | None:
    if value is None:
        return None
    lines = tuple(" ".join(line.split()) for line in value.splitlines() if line.strip())
    return "\n".join(lines) or None


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
        page_items = _page_text_items(page)
        for line_index, text in enumerate(page_items):
            if line_index:
                parts.append("\n")
                cursor += 1
            start = cursor
            parts.append(text)
            cursor += len(text)
            spans.append(_LineSpan(page.page_number, text, start, cursor))
    return "".join(parts), tuple(spans)


def _page_text_items(page: PdfPageLayout) -> tuple[str, ...]:
    table_ranges = tuple((row.top, row.bottom) for row in page.table_rows)
    items: list[tuple[float, int, int, str]] = []
    for ordinal, line in enumerate(page.lines):
        if any(top <= line.top <= bottom for top, bottom in table_ranges):
            continue
        items.append((line.top, 0, ordinal, " ".join(line.text.split())))
    for row_ordinal, row in enumerate(page.table_rows):
        for cell_ordinal, cell in enumerate(row.cells):
            if cell:
                items.append(
                    (
                        row.top,
                        1,
                        row_ordinal * 10_000 + cell_ordinal * 100,
                        " ".join(cell.split()),
                    )
                )
    return tuple(item[3] for item in sorted(items))


def _sections(
    canonical_text: str, spans: tuple[_LineSpan, ...]
) -> tuple[ExtractedSection, ...]:
    toc_pages = _table_of_contents_pages(spans)
    root_path: tuple[str, ...] = ()
    current: _OpenSection | None = None
    current_has_body = False
    sections: list[ExtractedSection] = []
    for span in spans:
        if span.page_number in toc_pages:
            continue
        heading = _normalized_heading(span.text)
        if re.match(r"^제\s*\d+\s*부(?:[.]|\s|$)", heading):
            if current is not None:
                _close_section(canonical_text, spans, current, span.start, sections)
                current = None
                current_has_body = False
            root_path = ()
            continue
        if heading in _SUMMARY_HEADINGS:
            if current is not None:
                _close_section(canonical_text, spans, current, span.start, sections)
                current = None
                current_has_body = False
            root_path = (heading,)
            continue
        if _is_boundary_heading(heading):
            if current is not None:
                _close_section(canonical_text, spans, current, span.start, sections)
                current = None
                current_has_body = False
            continue
        if heading not in _CLAIM_HEADINGS:
            if current is not None:
                if current_has_body and _is_outline_marker(heading):
                    _close_section(canonical_text, spans, current, span.start, sections)
                    current = None
                    current_has_body = False
                elif not _is_outline_marker(heading):
                    current_has_body = True
            continue
        if current is not None:
            _close_section(canonical_text, spans, current, span.start, sections)
        current = _OpenSection(
            heading_path=(*root_path, heading),
            page_start=span.page_number,
            character_start=_next_content_start(canonical_text, span.end),
        )
        current_has_body = False
    if current is not None:
        _close_section(canonical_text, spans, current, len(canonical_text), sections)
    return tuple(sections)


def _normalized_heading(text: str) -> str:
    normalized = " ".join(text.split()).strip()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1].strip()
    return normalized


def _is_boundary_heading(heading: str) -> bool:
    if heading in _BOUNDARY_HEADINGS:
        return True
    return re.fullmatch(r"투자비용\s*\d*", heading) is not None


def _is_outline_marker(heading: str) -> bool:
    return (
        re.fullmatch(r"(?:\(\d+\)|\d+[.)]|[가-힣][.)]|[①-⑳])", heading)
        is not None
    )


def _table_of_contents_pages(spans: tuple[_LineSpan, ...]) -> frozenset[int]:
    first_by_page: dict[int, str] = {}
    for span in spans:
        first_by_page.setdefault(span.page_number, _normalized_heading(span.text))

    toc_pages: set[int] = set()
    in_toc = False
    for page_number, first_heading in first_by_page.items():
        if first_heading.replace(" ", "") == "목차":
            in_toc = True
        elif in_toc and first_heading in {
            "투자결정시 유의사항 안내",
            "요약정보",
            "간이투자설명서",
        }:
            in_toc = False
        if in_toc:
            toc_pages.add(page_number)
    return frozenset(toc_pages)


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
