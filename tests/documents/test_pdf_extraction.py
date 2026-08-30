from __future__ import annotations

import hashlib

import pytest

from financial_agent.documents.pdf_extraction import (
    PdfExtractionError,
    PdfPageLayout,
    PdfTextLine,
    assemble_pdf_sections,
)


def line(
    text: str,
    *,
    top: float,
    size: float = 10.0,
    emphasized: bool = False,
) -> PdfTextLine:
    return PdfTextLine(
        text=text,
        top=top,
        dominant_size=size,
        emphasized=emphasized,
    )


def test_assembled_section_round_trips_to_canonical_document_text() -> None:
    pages = (
        PdfPageLayout(
            page_number=1,
            lines=(
                line("[요약정보]", top=10.0, size=16.0, emphasized=True),
                line(
                    "투자목적 및 투자전략",
                    top=30.0,
                    size=12.0,
                    emphasized=True,
                ),
                line("KOSPI200을 추종합니다.", top=50.0),
            ),
            table_rows=(),
        ),
    )

    result = assemble_pdf_sections(
        pages,
        source_checksum="a" * 64,
        extraction_version="pdfplumber-layout-v1",
    )

    assert result.page_count == 1
    assert result.text_page_count == 1
    assert result.text_checksum == hashlib.sha256(
        result.canonical_text.encode()
    ).hexdigest()
    assert len(result.sections) == 1
    section = result.sections[0]
    assert section.heading_path == ("요약정보", "투자목적 및 투자전략")
    assert section.exact_text == "KOSPI200을 추종합니다."
    assert result.canonical_text[
        section.character_start : section.character_end
    ] == section.exact_text
    assert (section.page_start, section.page_end) == (1, 1)


def test_assembly_is_deterministic_for_identical_layout() -> None:
    pages = (
        PdfPageLayout(
            page_number=1,
            lines=(
                line("투자목적", top=10.0, emphasized=True),
                line("동일한 원문입니다.", top=20.0),
            ),
            table_rows=(),
        ),
    )

    first = assemble_pdf_sections(
        pages,
        source_checksum="b" * 64,
        extraction_version="pdfplumber-layout-v1",
    )
    second = assemble_pdf_sections(
        pages,
        source_checksum="b" * 64,
        extraction_version="pdfplumber-layout-v1",
    )

    assert first == second


@pytest.mark.parametrize("source_checksum", ("", "not-a-sha256", "A" * 64))
def test_assembly_rejects_invalid_source_checksum(source_checksum: str) -> None:
    pages = (
        PdfPageLayout(
            page_number=1,
            lines=(line("투자목적", top=10.0, emphasized=True),),
            table_rows=(),
        ),
    )

    with pytest.raises(PdfExtractionError, match="PDF_SOURCE_CHECKSUM_INVALID"):
        assemble_pdf_sections(
            pages,
            source_checksum=source_checksum,
            extraction_version="pdfplumber-layout-v1",
        )


def test_assembly_rejects_noncontiguous_pages() -> None:
    pages = (
        PdfPageLayout(1, (line("first", top=1.0),), ()),
        PdfPageLayout(3, (line("third", top=1.0),), ()),
    )

    with pytest.raises(PdfExtractionError, match="PDF_PAGE_ORDER_INVALID"):
        assemble_pdf_sections(
            pages,
            source_checksum="c" * 64,
            extraction_version="pdfplumber-layout-v1",
        )


def test_assembly_rejects_blank_extraction_version() -> None:
    pages = (
        PdfPageLayout(
            page_number=1,
            lines=(line("투자목적", top=10.0, emphasized=True),),
            table_rows=(),
        ),
    )

    with pytest.raises(PdfExtractionError, match="PDF_EXTRACTION_VERSION_INVALID"):
        assemble_pdf_sections(
            pages,
            source_checksum="e" * 64,
            extraction_version=" ",
        )


def test_assembly_rejects_a_page_without_usable_text() -> None:
    pages = (PdfPageLayout(page_number=1, lines=(), table_rows=()),)

    with pytest.raises(PdfExtractionError, match="PDF_TEXT_LAYER_MISSING"):
        assemble_pdf_sections(
            pages,
            source_checksum="d" * 64,
            extraction_version="pdfplumber-layout-v1",
        )
