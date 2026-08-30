from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from financial_agent.documents.pdf_extraction import (
    PdfExtractionError,
    PdfPageLayout,
    PdfTableRow,
    PdfTextLine,
    assemble_pdf_sections,
    extract_pdf_sections,
    read_pdf_layout,
)
from tests.fixtures.synthetic_pdf import write_synthetic_prospectus


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


def synthetic_prospectus(path: Path) -> Path:
    return write_synthetic_prospectus(path)


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


def test_adapter_reads_real_page_lines_and_table_rows(tmp_path: Path) -> None:
    pdf_path = synthetic_prospectus(tmp_path / "synthetic-prospectus.pdf")

    pages = read_pdf_layout(pdf_path)

    assert tuple(page.page_number for page in pages) == (1, 2)
    assert any(
        "투자목적 및 투자전략" in (cell or "")
        for row in pages[0].table_rows
        for cell in row.cells
    )
    assert any(
        "추적오차 발생위험" in (cell or "")
        for row in pages[1].table_rows
        for cell in row.cells
    )


def test_adapter_extracts_claim_sections_from_real_pdf(tmp_path: Path) -> None:
    pdf_path = synthetic_prospectus(tmp_path / "synthetic-prospectus.pdf")

    result = extract_pdf_sections(
        pdf_path,
        extraction_version="pdfplumber-layout-v1",
    )

    assert result.page_count == 2
    assert result.text_page_count == 2
    assert result.source_checksum == hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert {section.heading_path[-1] for section in result.sections} >= {
        "투자목적 및 투자전략",
        "주요투자위험",
    }
    assert any(
        "KOSPI200 지수의 변동률을 추종합니다." == section.exact_text
        for section in result.sections
    )
    assert any(
        "추적오차 발생위험" in section.exact_text
        and "지수와 수익률이 다를 수 있습니다." in section.exact_text
        for section in result.sections
    )


def test_adapter_rejects_non_pdf_bytes(tmp_path: Path) -> None:
    invalid = tmp_path / "not-a.pdf"
    invalid.write_bytes(b"not a PDF")

    with pytest.raises(PdfExtractionError, match="PDF_OPEN_FAILED"):
        extract_pdf_sections(
            invalid,
            extraction_version="pdfplumber-layout-v1",
        )


def test_table_cell_heading_is_kept_as_one_canonical_item() -> None:
    pages = (
        PdfPageLayout(
            page_number=1,
            lines=(line("요약정보", top=10.0),),
            table_rows=(
                PdfTableRow(
                    cells=(
                        "투자목적\n및\n투자전략",
                        "KOSPI200 지수의 변동률을 추종합니다.",
                    ),
                    top=30.0,
                    bottom=60.0,
                ),
                PdfTableRow(
                    cells=("투자비용 1", "보수 정보"),
                    top=70.0,
                    bottom=90.0,
                ),
            ),
        ),
    )

    result = assemble_pdf_sections(
        pages,
        source_checksum="f" * 64,
        extraction_version="pdfplumber-layout-v1",
    )

    assert len(result.sections) == 1
    assert result.sections[0].heading_path[-1] == "투자목적 및 투자전략"
    assert result.sections[0].exact_text == "KOSPI200 지수의 변동률을 추종합니다."


def test_risk_table_heading_opens_one_section_with_following_rows() -> None:
    pages = (
        PdfPageLayout(
            page_number=1,
            lines=(line("요약정보", top=10.0),),
            table_rows=(
                PdfTableRow(
                    cells=(
                        "주요투자\n위험",
                        "1",
                        "상장폐지위험",
                        "상장폐지로 손실이 발생할 수 있습니다.",
                    ),
                    top=30.0,
                    bottom=60.0,
                ),
                PdfTableRow(
                    cells=(
                        "추적오차\n발생위험",
                        "지수와 수익률이 다를 수 있습니다.",
                    ),
                    top=60.0,
                    bottom=90.0,
                ),
            ),
        ),
    )

    result = assemble_pdf_sections(
        pages,
        source_checksum="1" * 64,
        extraction_version="pdfplumber-layout-v1",
    )

    assert len(result.sections) == 1
    section = result.sections[0]
    assert section.heading_path[-1] == "주요투자 위험"
    assert "상장폐지위험" in section.exact_text
    assert "추적오차 발생위험" in section.exact_text


def test_table_of_contents_pages_do_not_create_claim_sections() -> None:
    pages = (
        PdfPageLayout(
            1,
            (
                line("목 차", top=10.0),
                line("요약정보", top=20.0),
                line("집합투자기구의 투자목적", top=30.0),
            ),
            (),
        ),
        PdfPageLayout(
            2,
            (
                line("집합투자기구의 투자전략", top=10.0),
                line("집합투자기구의 투자위험", top=20.0),
            ),
            (),
        ),
        PdfPageLayout(
            3,
            (
                line("투자결정시 유의사항 안내", top=10.0),
                line("본문입니다.", top=20.0),
            ),
            (),
        ),
        PdfPageLayout(
            4,
            (
                line("요약정보", top=10.0),
                line("투자목적", top=20.0),
                line("실제 투자목적입니다.", top=30.0),
            ),
            (),
        ),
    )

    result = assemble_pdf_sections(
        pages,
        source_checksum="2" * 64,
        extraction_version="pdfplumber-layout-v1",
    )

    assert len(result.sections) == 1
    assert result.sections[0].page_start == 4
    assert result.sections[0].exact_text == "실제 투자목적입니다."


def test_numbered_sibling_closes_full_prospectus_claim_section() -> None:
    pages = (
        PdfPageLayout(
            1,
            (
                line("투자 전략", top=10.0),
                line("1)", top=20.0),
                line("KOSPI200 지수를 추종합니다.", top=30.0),
                line("(2)", top=40.0),
                line("지수 산정 방법", top=50.0),
            ),
            (),
        ),
    )

    result = assemble_pdf_sections(
        pages,
        source_checksum="3" * 64,
        extraction_version="pdfplumber-layout-v1",
    )

    assert len(result.sections) == 1
    assert result.sections[0].exact_text == "1)\nKOSPI200 지수를 추종합니다."


def test_top_level_part_clears_summary_heading_context() -> None:
    pages = (
        PdfPageLayout(
            1,
            (
                line("요약정보", top=10.0),
                line("투자목적", top=20.0),
                line("요약 목적입니다.", top=30.0),
            ),
            (),
        ),
        PdfPageLayout(
            2,
            (
                line("제2부. 집합투자기구에 관한 사항", top=10.0),
                line("투자 전략", top=20.0),
                line("상세 전략입니다.", top=30.0),
            ),
            (),
        ),
    )

    result = assemble_pdf_sections(
        pages,
        source_checksum="4" * 64,
        extraction_version="pdfplumber-layout-v1",
    )

    assert tuple(section.heading_path for section in result.sections) == (
        ("요약정보", "투자목적"),
        ("투자 전략",),
    )
