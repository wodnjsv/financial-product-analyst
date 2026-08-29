"""Deterministic selection and bounded assembly of evidence-ready text chunks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Protocol

from .models import CoverageStatus, DocumentChunkDraft, SectionType


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


@dataclass(frozen=True, slots=True)
class WhitespaceTokenCounter:
    """Small deterministic counter for tests and tokenizer-independent callers."""

    def count(self, text: str) -> int:
        return len(text.split())


@dataclass(frozen=True, slots=True)
class ExtractedSection:
    heading_path: tuple[str, ...]
    exact_text: str
    page_start: int | None
    page_end: int | None
    character_start: int
    character_end: int


@dataclass(frozen=True, slots=True)
class DocumentChunkContext:
    dataset_version: str
    document_id: str
    canonical_entity_name: str
    document_type: str
    original_language: str


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    chunks: tuple[DocumentChunkDraft, ...]
    coverage_status: CoverageStatus
    reason_code: str | None
    observed_chunk_count: int


_DISALLOWED_HEADINGS = (
    "fee",
    "expense",
    "distribution",
    "redemption",
    "tax",
    "accounting",
    "legal notice",
    "legal disclaimer",
    "holdings",
    "portfolio holding",
    "historical performance",
    "financial statement",
    "market commentary",
    "fee policy",
    "distribution_redemption",
    "taxation",
    "accounting policy",
    "general legal notice",
    "full holdings table",
    "historical performance table",
    "운용보수",
    "수수료",
    "분배",
    "환매",
    "과세",
    "회계",
    "법적 고지",
    "보유종목",
    "성과",
    "재무제표",
    "시장전망",
    "운용자 코멘터리",
)

_SECTION_RULES: tuple[tuple[SectionType, tuple[str, ...]], ...] = (
    (SectionType.REBALANCING, ("rebalancing", "reconstitution", "리밸런싱", "정기변경")),
    (SectionType.RISK_FACTOR, ("principal risk", "risk factor", "investment risk", "투자위험", "위험요인")),
    (SectionType.INVESTMENT_STRATEGY, ("principal investment strateg", "investment strategy", "투자전략")),
    (SectionType.INVESTMENT_OBJECTIVE, ("investment objective", "investment goal", "투자목적")),
    (SectionType.INDEX_METHODOLOGY, ("index methodology", "methodology", "지수 방법론", "지수산출방법")),
    (SectionType.THEME_DEFINITION, ("theme definition", "investment theme", "테마 정의", "테마")),
    (SectionType.SELECTION_RULES, ("selection rule", "eligibility rule", "constituent selection", "편입 기준", "종목선정")),
    (SectionType.LEGAL_STRUCTURE, ("legal structure", "fund structure", "법적 구조", "펀드 구조")),
    (SectionType.OFFICIAL_UPDATE, ("official update", "official notice", "공식 변경", "공시사항")),
    (SectionType.CHANGE_HISTORY, ("change history", "amendment history", "변경 이력", "개정 이력")),
    (SectionType.CURRENCY_HEDGE, ("currency hedge", "fx hedge", "환헤지", "통화헤지")),
    (SectionType.DERIVATIVES_LEVERAGE, ("derivative", "leverage", "파생상품", "레버리지")),
    (SectionType.GOVERNANCE, ("governance", "거버넌스")),
)

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[A-Za-z][.)])\s+")


def classify_section(section: ExtractedSection) -> SectionType | None:
    """Return an approved claim section type, otherwise fail closed."""

    heading = " > ".join(section.heading_path).casefold()
    if any(pattern in heading for pattern in _DISALLOWED_HEADINGS):
        return None
    for section_type, patterns in _SECTION_RULES:
        if any(pattern in heading for pattern in patterns):
            return section_type
    return None


def chunk_document_sections(
    context: DocumentChunkContext,
    sections: tuple[ExtractedSection, ...],
    *,
    counter: TokenCounter,
    target_min: int = 300,
    target_max: int = 800,
    overlap: int = 75,
    soft_limit: int = 20,
) -> ChunkingResult:
    """Chunk approved sections without changing their evidence text or locators."""

    _validate_budget(target_min, target_max, overlap, soft_limit)
    candidates: list[tuple[ExtractedSection, SectionType, int, int]] = []
    seen_paragraph_hashes: set[str] = set()
    for section in sorted(sections, key=_section_key):
        section_type = classify_section(section)
        if section_type is None or not section.exact_text.strip():
            continue
        candidates.extend(
            _section_candidates(
                section,
                section_type,
                counter=counter,
                target_max=target_max,
                overlap=overlap,
                seen_paragraph_hashes=seen_paragraph_hashes,
            )
        )

    chunks: list[DocumentChunkDraft] = []
    seen_chunk_hashes: set[str] = set()
    section_chunk_counts: dict[tuple[int, int, tuple[str, ...], str], int] = {}
    for section, section_type, start, end in candidates:
        exact_text = section.exact_text[start:end]
        content_hash = _sha256(exact_text)
        if content_hash in seen_chunk_hashes:
            continue
        seen_chunk_hashes.add(content_hash)
        section_key = _section_key(section)
        section_chunk_counts[section_key] = section_chunk_counts.get(section_key, 0) + 1
        ordinal = len(chunks) + 1
        chunks.append(
            _draft(
                context=context,
                section=section,
                section_type=section_type,
                ordinal=ordinal,
                start=start,
                end=end,
                exact_text=exact_text,
                content_hash=content_hash,
            )
        )

    observed_chunk_count = len(chunks)
    if not chunks:
        return ChunkingResult(
            chunks=(),
            coverage_status=CoverageStatus.SECTION_MISSING,
            reason_code="approved_section_not_found",
            observed_chunk_count=0,
        )
    if observed_chunk_count > soft_limit or any(
        count > soft_limit for count in section_chunk_counts.values()
    ):
        return ChunkingResult(
            chunks=tuple(chunks),
            coverage_status=CoverageStatus.REVIEW_REQUIRED_CHUNK_BUDGET,
            reason_code="soft_chunk_limit_exceeded",
            observed_chunk_count=observed_chunk_count,
        )
    return ChunkingResult(
        chunks=tuple(chunks),
        coverage_status=CoverageStatus.INDEXED,
        reason_code=None,
        observed_chunk_count=observed_chunk_count,
    )


def _validate_budget(
    target_min: int, target_max: int, overlap: int, soft_limit: int
) -> None:
    if target_min < 0 or target_max <= 0 or target_min > target_max:
        raise ValueError("chunk token targets must satisfy 0 <= target_min <= target_max")
    if overlap < 0 or soft_limit < 0:
        raise ValueError("overlap and soft_limit must be non-negative")


def _section_key(section: ExtractedSection) -> tuple[int, int, tuple[str, ...], str]:
    return (
        section.character_start,
        section.character_end,
        tuple(part.casefold() for part in section.heading_path),
        section.exact_text,
    )


def _section_candidates(
    section: ExtractedSection,
    section_type: SectionType,
    *,
    counter: TokenCounter,
    target_max: int,
    overlap: int,
    seen_paragraph_hashes: set[str],
) -> list[tuple[ExtractedSection, SectionType, int, int]]:
    groups: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] = []
    for start, end in _semantic_ranges(section.exact_text):
        paragraph = section.exact_text[start:end]
        paragraph_hash = _sha256(paragraph.strip())
        if paragraph_hash in seen_paragraph_hashes:
            if current:
                groups.append(current)
                current = []
            continue
        seen_paragraph_hashes.add(paragraph_hash)
        current.append((start, end))
    if current:
        groups.append(current)

    candidates: list[tuple[ExtractedSection, SectionType, int, int]] = []
    for group in groups:
        for start, end in _bounded_ranges(
            section.exact_text,
            group,
            counter=counter,
            target_max=target_max,
            overlap=overlap,
        ):
            candidates.append((section, section_type, start, end))
    return candidates


def _semantic_ranges(text: str) -> tuple[tuple[int, int], ...]:
    starts = [0]
    offset = 0
    after_blank_line = False
    for line in text.splitlines(keepends=True):
        if line.strip() == "":
            after_blank_line = True
        elif offset and (after_blank_line or _BULLET.match(line)):
            starts.append(offset)
            after_blank_line = False
        else:
            after_blank_line = False
        offset += len(line)
    return tuple(
        (start, end)
        for start, end in zip(starts, (*starts[1:], len(text)), strict=True)
        if text[start:end].strip()
    )


def _bounded_ranges(
    text: str,
    units: list[tuple[int, int]],
    *,
    counter: TokenCounter,
    target_max: int,
    overlap: int,
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    current: list[tuple[int, int]] = []
    for unit in units:
        proposed = [*current, unit]
        if current and _count_range(text, proposed, counter) > target_max:
            ranges.append((current[0][0], current[-1][1]))
            current = _overlap_units(text, current, counter, overlap)
            current.append(unit)
            while len(current) > 1 and _count_range(text, current, counter) > target_max:
                current.pop(0)
        else:
            current = proposed
    if current:
        ranges.append((current[0][0], current[-1][1]))
    return ranges


def _overlap_units(
    text: str,
    units: list[tuple[int, int]],
    counter: TokenCounter,
    overlap: int,
) -> list[tuple[int, int]]:
    if overlap == 0:
        return []
    selected: list[tuple[int, int]] = []
    for unit in reversed(units):
        selected.insert(0, unit)
        if _count_range(text, selected, counter) >= overlap:
            break
    return selected


def _count_range(
    text: str, units: list[tuple[int, int]], counter: TokenCounter
) -> int:
    return counter.count(text[units[0][0] : units[-1][1]])


def _draft(
    *,
    context: DocumentChunkContext,
    section: ExtractedSection,
    section_type: SectionType,
    ordinal: int,
    start: int,
    end: int,
    exact_text: str,
    content_hash: str,
) -> DocumentChunkDraft:
    section_path = " > ".join(section.heading_path)
    character_start = section.character_start + start
    character_end = section.character_start + end
    chunk_id = _sha256(
        "\x1f".join(
            (
                context.document_id,
                section_type.value,
                section_path,
                str(character_start),
                str(character_end),
                content_hash,
            )
        )
    )
    embedding_text = "\n".join(
        (
            context.canonical_entity_name,
            context.document_type,
            section_path,
            exact_text,
        )
    )
    normalized_search_text = " ".join(exact_text.split())
    record_hash = _sha256(
        json.dumps(
            {
                "chunk_id": chunk_id,
                "content_hash": content_hash,
                "dataset_version": context.dataset_version,
                "document_id": context.document_id,
                "ordinal": ordinal,
                "section_type": section_type.value,
                "section_path": section_path,
                "character_start": character_start,
                "character_end": character_end,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return DocumentChunkDraft(
        dataset_version=context.dataset_version,
        chunk_id=chunk_id,
        document_id=context.document_id,
        ordinal=ordinal,
        page_start=section.page_start,
        page_end=section.page_end,
        section_type=section_type,
        section_path=section_path,
        character_start=character_start,
        character_end=character_end,
        exact_text=exact_text,
        normalized_search_text=normalized_search_text,
        embedding_text=embedding_text,
        content_hash=content_hash,
        record_hash=record_hash,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
