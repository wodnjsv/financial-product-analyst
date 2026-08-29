"""Deterministic selection and bounded assembly of evidence-ready text chunks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Protocol
import unicodedata

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
    budget_scope_id: str
    requested_section_types: frozenset[SectionType] = frozenset()


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    chunks: tuple[DocumentChunkDraft, ...]
    coverage_status: CoverageStatus
    reason_code: str | None
    observed_chunk_count: int
    budget_scope_id: str
    dataset_version: str
    document_id: str


@dataclass(frozen=True, slots=True)
class ScopeChunkBudgetResult:
    """A scope-level budget decision that preserves document outcomes intact."""

    budget_scope_id: str
    dataset_version: str
    member_results: tuple[ChunkingResult, ...]
    observed_chunk_count: int
    over_budget: bool
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class _Unit:
    start: int
    end: int
    indivisible: bool = False


@dataclass(frozen=True, slots=True)
class _ChunkSpan:
    section: ExtractedSection
    section_type: SectionType
    start: int
    end: int
    oversized_indivisible: bool


_CONDITIONAL_SECTION_TYPES = frozenset(
    {
        SectionType.CURRENCY_HEDGE,
        SectionType.DERIVATIVES_LEVERAGE,
        SectionType.GOVERNANCE,
    }
)

_EXCLUDED_HEADINGS = frozenset(
    {
        "fees and expenses", "fees", "fee policy", "distributions and redemptions",
        "distribution and redemption", "taxation", "accounting policies",
        "accounting policy", "legal notice", "general legal notice", "legal disclaimer", "portfolio holdings",
        "full holdings table", "historical performance", "historical performance table",
        "financial statements", "market commentary", "운용 보수", "수수료", "분배 및 환매",
        "분배", "환매", "과세", "회계 정책", "회계", "법적 고지", "일반 법적 고지", "일반법적고지", "보유 종목", "보유종목",
        "성과", "재무제표", "시장 전망", "운용자 코멘터리",
    }
)

_SECTION_ALIASES: tuple[tuple[SectionType, frozenset[str]], ...] = (
    (SectionType.REBALANCING, frozenset({"rebalancing", "reconstitution", "리밸런싱", "정기 변경", "정기변경"})),
    (SectionType.RISK_FACTOR, frozenset({"principal risks", "principal risk", "risk factors", "investment risks", "투자 위험", "투자위험", "위험 요인", "위험요인"})),
    (SectionType.INVESTMENT_STRATEGY, frozenset({"principal investment strategies", "principal investment strategy", "investment strategy", "investment strategies", "투자 전략", "투자전략", "투자 목적 및 투자 전략", "투자목적 및 투자전략"})),
    (SectionType.INVESTMENT_OBJECTIVE, frozenset({"investment objective", "investment objectives", "investment goal", "투자 목적", "투자목적"})),
    (SectionType.INDEX_METHODOLOGY, frozenset({"index methodology", "index methodologies", "지수 방법론", "지수 산출 방법", "지수산출방법"})),
    (SectionType.THEME_DEFINITION, frozenset({"theme definition", "investment theme", "테마 정의"})),
    (SectionType.SELECTION_RULES, frozenset({"selection rules", "selection rule", "eligibility rules", "constituent selection", "편입 기준", "종목 선정", "종목선정"})),
    (SectionType.LEGAL_STRUCTURE, frozenset({"legal structure", "fund structure", "법적 구조", "펀드 구조"})),
    (SectionType.OFFICIAL_UPDATE, frozenset({"official update", "official notice", "공식 변경", "공시 사항", "공시사항"})),
    (SectionType.CHANGE_HISTORY, frozenset({"change history", "amendment history", "변경 이력", "개정 이력"})),
    (SectionType.CURRENCY_HEDGE, frozenset({"currency hedge", "currency hedging", "fx hedge", "fx hedging", "통화 헤지", "통화헤지", "환 헤지", "환헤지"})),
    (SectionType.DERIVATIVES_LEVERAGE, frozenset({"derivatives and leverage", "derivatives", "leverage", "파생 상품 및 레버리지", "파생상품 및 레버리지"})),
    (SectionType.GOVERNANCE, frozenset({"governance", "거버넌스"})),
)

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[A-Za-z][.)])\s+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])(?=\s)")
_WORD = re.compile(r"\S+\s*")
_APPENDIX = re.compile(r"^(?:appendix|부록)(?:$|[\s:-]|\d|[ivxlcdm])")


def classify_section(
    section: ExtractedSection,
    *,
    requested_section_types: frozenset[SectionType] = frozenset(),
) -> SectionType | None:
    """Return an explicitly approved claim section type, otherwise fail closed."""

    headings = _normalized_heading_path(section.heading_path)
    if _is_excluded_heading(headings):
        return None
    for heading in reversed(headings):
        for section_type, aliases in _SECTION_ALIASES:
            if section_type in _CONDITIONAL_SECTION_TYPES and section_type not in requested_section_types:
                continue
            if heading in aliases:
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
    if not context.budget_scope_id.strip():
        raise ValueError("budget_scope_id must not be blank")
    for section in sections:
        _validate_section(section)

    candidates: list[_ChunkSpan] = []
    seen_paragraph_hashes: set[str] = set()
    for section in sorted(sections, key=_section_key):
        section_type = classify_section(section, requested_section_types=context.requested_section_types)
        if section_type is None or not section.exact_text.strip():
            continue
        candidates.extend(_section_candidates(section, section_type, counter=counter, target_min=target_min, target_max=target_max, overlap=overlap, seen_paragraph_hashes=seen_paragraph_hashes))

    chunks: list[DocumentChunkDraft] = []
    seen_chunk_hashes: set[str] = set()
    section_chunk_counts: dict[tuple[object, ...], int] = {}
    oversized_indivisible = False
    for candidate in candidates:
        exact_text = candidate.section.exact_text[candidate.start : candidate.end]
        content_hash = _sha256(exact_text)
        if content_hash in seen_chunk_hashes:
            continue
        seen_chunk_hashes.add(content_hash)
        section_key = _section_key(candidate.section)
        section_chunk_counts[section_key] = section_chunk_counts.get(section_key, 0) + 1
        oversized_indivisible = oversized_indivisible or candidate.oversized_indivisible
        chunks.append(_draft(context=context, section=candidate.section, section_type=candidate.section_type, ordinal=len(chunks) + 1, start=candidate.start, end=candidate.end, exact_text=exact_text, content_hash=content_hash))

    if not chunks:
        return _result(context, (), CoverageStatus.SECTION_MISSING, "approved_section_not_found")
    if oversized_indivisible:
        return _result(context, tuple(chunks), CoverageStatus.REVIEW_REQUIRED_CHUNK_BUDGET, "indivisible_unit_over_target_max")
    if len(chunks) > soft_limit or any(count > soft_limit for count in section_chunk_counts.values()):
        return _result(context, tuple(chunks), CoverageStatus.REVIEW_REQUIRED_CHUNK_BUDGET, "soft_chunk_limit_exceeded")
    return _result(context, tuple(chunks), CoverageStatus.INDEXED, None)


def aggregate_chunking_results(
    results: tuple[ChunkingResult, ...], *, soft_limit: int
) -> ScopeChunkBudgetResult:
    """Apply a product/index budget to independent canonical-document results."""

    if not results:
        raise ValueError("at least one chunking result is required")
    if soft_limit < 0:
        raise ValueError("soft_limit must be non-negative")
    scope_ids = {result.budget_scope_id for result in results}
    if len(scope_ids) != 1:
        raise ValueError("chunking results must belong to one budget scope")
    budget_scope_id = next(iter(scope_ids))
    dataset_versions = {result.dataset_version for result in results}
    if len(dataset_versions) != 1:
        raise ValueError("chunking results must belong to one dataset version")
    member_ids = {(result.dataset_version, result.document_id) for result in results}
    if len(member_ids) != len(results):
        raise ValueError("duplicate document results are not allowed")
    for result in results:
        if result.observed_chunk_count != len(result.chunks):
            raise ValueError("chunking result count must match its chunks")
        if any(
            chunk.dataset_version != result.dataset_version
            or chunk.document_id != result.document_id
            for chunk in result.chunks
        ):
            raise ValueError("chunk identities must match their document result")
    chunk_ids = [
        (chunk.dataset_version, chunk.document_id, chunk.chunk_id)
        for result in results
        for chunk in result.chunks
    ]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("duplicate chunk identities are not allowed")
    members = tuple(sorted(results, key=lambda result: (result.document_id, result.budget_scope_id)))
    observed_chunk_count = sum(result.observed_chunk_count for result in members)
    return ScopeChunkBudgetResult(
        budget_scope_id=budget_scope_id,
        dataset_version=next(iter(dataset_versions)),
        member_results=members,
        observed_chunk_count=observed_chunk_count,
        over_budget=observed_chunk_count > soft_limit,
        reason_code=("soft_chunk_limit_exceeded" if observed_chunk_count > soft_limit else None),
    )


def _result(
    context: DocumentChunkContext,
    chunks: tuple[DocumentChunkDraft, ...],
    coverage_status: CoverageStatus,
    reason_code: str | None,
) -> ChunkingResult:
    return ChunkingResult(
        chunks,
        coverage_status,
        reason_code,
        len(chunks),
        context.budget_scope_id,
        context.dataset_version,
        context.document_id,
    )


def _validate_budget(target_min: int, target_max: int, overlap: int, soft_limit: int) -> None:
    if target_min < 0 or target_max <= 0 or target_min > target_max:
        raise ValueError("chunk token targets must satisfy 0 <= target_min <= target_max")
    if overlap < 0 or soft_limit < 0:
        raise ValueError("overlap and soft_limit must be non-negative")


def _validate_section(section: ExtractedSection) -> None:
    if (section.page_start is None) != (section.page_end is None):
        raise ValueError("section page range must be complete")
    if section.page_start is not None and (section.page_start < 1 or section.page_end is None or section.page_end < section.page_start):
        raise ValueError("section page range must be one-based and ordered")
    if section.character_start < 0 or section.character_end < section.character_start:
        raise ValueError("section character range must be non-negative and ordered")
    if section.character_end - section.character_start != len(section.exact_text):
        raise ValueError("section character range must match exact_text length")


def _normalized_heading_path(heading_path: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(" ".join(unicodedata.normalize("NFKC", heading).split()).casefold() for heading in heading_path)


def _is_excluded_heading(headings: tuple[str, ...]) -> bool:
    for heading in headings:
        if heading in _EXCLUDED_HEADINGS:
            return True
        if _APPENDIX.match(heading):
            return True
    return False


def _section_key(section: ExtractedSection) -> tuple[object, ...]:
    return (section.character_start, section.character_end, _normalized_heading_path(section.heading_path), section.heading_path, section.exact_text)


def _section_candidates(section: ExtractedSection, section_type: SectionType, *, counter: TokenCounter, target_min: int, target_max: int, overlap: int, seen_paragraph_hashes: set[str]) -> list[_ChunkSpan]:
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    for start, end, is_bullet in _semantic_ranges(section.exact_text):
        paragraph_hash = _sha256(section.exact_text[start:end].strip())
        if paragraph_hash in seen_paragraph_hashes:
            if current:
                groups.append(current)
                current = []
            continue
        seen_paragraph_hashes.add(paragraph_hash)
        current.extend(_split_semantic_unit(section.exact_text, start, end, is_bullet=is_bullet, counter=counter, target_max=target_max))
    if current:
        groups.append(current)

    candidates: list[_ChunkSpan] = []
    for group in groups:
        for units in _bounded_unit_groups(section.exact_text, group, counter=counter, target_min=target_min, target_max=target_max, overlap=overlap):
            candidates.append(_ChunkSpan(section, section_type, units[0].start, units[-1].end, any(unit.indivisible and _count_units(section.exact_text, [unit], counter) > target_max for unit in units)))
    return candidates


def _semantic_ranges(text: str) -> tuple[tuple[int, int, bool], ...]:
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
    return tuple((start, end, bool(_BULLET.match(text[start:end]))) for start, end in zip(starts, (*starts[1:], len(text)), strict=True) if text[start:end].strip())


def _split_semantic_unit(text: str, start: int, end: int, *, is_bullet: bool, counter: TokenCounter, target_max: int) -> list[_Unit]:
    if _count_units(text, [_Unit(start, end)], counter) <= target_max:
        return [_Unit(start, end)]
    if is_bullet:
        return [_Unit(start, end, indivisible=True)]
    units: list[_Unit] = []
    sentence_starts = [start]
    sentence_starts.extend(match.start() for match in _SENTENCE_BREAK.finditer(text, start, end))
    for sentence_start, sentence_end in zip(sentence_starts, (*sentence_starts[1:], end), strict=True):
        sentence = _Unit(sentence_start, sentence_end)
        if _count_units(text, [sentence], counter) <= target_max:
            units.append(sentence)
        else:
            units.extend(_split_at_whitespace(text, sentence, counter, target_max))
    return units


def _split_at_whitespace(text: str, unit: _Unit, counter: TokenCounter, target_max: int) -> list[_Unit]:
    words = list(_WORD.finditer(text, unit.start, unit.end))
    if not words:
        return [_Unit(unit.start, unit.end, indivisible=True)]
    units: list[_Unit] = []
    current_start = unit.start
    for word in words:
        proposed = _Unit(current_start, word.end())
        if _count_units(text, [proposed], counter) <= target_max:
            continue
        if current_start < word.start():
            units.append(_Unit(current_start, word.start()))
        current_start = word.start()
        lexical_unit = _Unit(word.start(), word.end())
        if _count_units(text, [lexical_unit], counter) > target_max:
            units.append(_Unit(word.start(), word.end(), indivisible=True))
            current_start = word.end()
    if current_start < unit.end:
        units.append(_Unit(current_start, unit.end))
    return units


def _bounded_unit_groups(text: str, units: list[_Unit], *, counter: TokenCounter, target_min: int, target_max: int, overlap: int) -> list[list[_Unit]]:
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    for unit in units:
        proposed = [*current, unit]
        if current and _count_units(text, proposed, counter) > target_max:
            groups.append(current)
            current = [unit]
        else:
            current = proposed
    if current:
        groups.append(current)
    _rebalance_terminal_group(text, groups, counter, target_min, target_max)
    return _apply_overlap(text, groups, counter, target_max, overlap)


def _rebalance_terminal_group(text: str, groups: list[list[_Unit]], counter: TokenCounter, target_min: int, target_max: int) -> None:
    if target_min == 0 or len(groups) < 2:
        return
    prior = groups[-2]
    terminal = groups[-1]
    while len(prior) > 1 and _count_units(text, terminal, counter) < target_min:
        candidate_terminal = [prior[-1], *terminal]
        candidate_prior = prior[:-1]
        if _count_units(text, candidate_terminal, counter) > target_max or _count_units(text, candidate_prior, counter) < target_min:
            break
        terminal.insert(0, prior.pop())


def _apply_overlap(text: str, groups: list[list[_Unit]], counter: TokenCounter, target_max: int, overlap: int) -> list[list[_Unit]]:
    output: list[list[_Unit]] = []
    for index, group in enumerate(groups):
        tail: list[_Unit] = []
        if index and overlap:
            for unit in reversed(groups[index - 1]):
                candidate = [unit, *tail]
                if _count_units(text, candidate, counter) > overlap:
                    break
                tail = candidate
        combined = [*tail, *group]
        while tail and _count_units(text, combined, counter) > target_max:
            tail.pop(0)
            combined = [*tail, *group]
        output.append(combined)
    return output


def _count_units(text: str, units: list[_Unit], counter: TokenCounter) -> int:
    return counter.count(text[units[0].start : units[-1].end])


def _draft(*, context: DocumentChunkContext, section: ExtractedSection, section_type: SectionType, ordinal: int, start: int, end: int, exact_text: str, content_hash: str) -> DocumentChunkDraft:
    section_path = " > ".join(section.heading_path)
    character_start = section.character_start + start
    character_end = section.character_start + end
    chunk_id = _sha256("\x1f".join((context.document_id, section_type.value, section_path, str(section.page_start), str(section.page_end), str(character_start), str(character_end), content_hash)))
    embedding_text = "\n".join((context.canonical_entity_name, context.document_type, section_path, exact_text))
    normalized_search_text = " ".join(exact_text.split())
    record_hash = _sha256(json.dumps({"dataset_version": context.dataset_version, "chunk_id": chunk_id, "document_id": context.document_id, "ordinal": ordinal, "page_start": section.page_start, "page_end": section.page_end, "section_type": section_type.value, "section_path": section_path, "character_start": character_start, "character_end": character_end, "exact_text": exact_text, "normalized_search_text": normalized_search_text, "content_hash": content_hash}, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return DocumentChunkDraft(context.dataset_version, chunk_id, context.document_id, ordinal, section.page_start, section.page_end, section_type, section_path, character_start, character_end, exact_text, normalized_search_text, embedding_text, content_hash, record_hash)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
