"""Concise-first selection of official document claim sections."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import unicodedata

from .chunking import ExtractedSection, classify_section
from .models import SectionType


@dataclass(frozen=True, slots=True)
class SectionSelectionResult:
    selected_sections: tuple[ExtractedSection, ...]
    excluded_section_keys: tuple[str, ...]
    missing_section_types: frozenset[SectionType]
    reason_codes: tuple[str, ...]


def select_canonical_claim_sections(
    sections: tuple[ExtractedSection, ...],
    *,
    requested_section_types: frozenset[SectionType],
) -> SectionSelectionResult:
    """Prefer concise sections and use full text only for missing claim types."""

    ordered = tuple(sorted(sections, key=_source_key))
    classified = tuple(
        (section, classify_section(section, requested_section_types=requested_section_types))
        for section in ordered
    )
    selected: list[ExtractedSection] = []
    selected_ids: set[int] = set()
    seen_text_hashes: set[str] = set()
    missing: set[SectionType] = set()

    for section_type in sorted(requested_section_types, key=lambda value: value.value):
        matching = tuple(
            section
            for section, classified_type in classified
            if classified_type is section_type
        )
        concise = tuple(section for section in matching if _is_concise(section))
        candidates = concise or matching
        if not candidates:
            missing.add(section_type)
            continue
        for section in candidates:
            text_hash = hashlib.sha256(section.exact_text.encode()).hexdigest()
            if text_hash in seen_text_hashes:
                continue
            seen_text_hashes.add(text_hash)
            selected.append(section)
            selected_ids.add(id(section))

    excluded = tuple(
        _section_key(section) for section in ordered if id(section) not in selected_ids
    )
    return SectionSelectionResult(
        selected_sections=tuple(selected),
        excluded_section_keys=excluded,
        missing_section_types=frozenset(missing),
        reason_codes=tuple(
            f"missing_section:{section_type.value}"
            for section_type in sorted(missing, key=lambda value: value.value)
        ),
    )


def _is_concise(section: ExtractedSection) -> bool:
    headings = {
        " ".join(unicodedata.normalize("NFKC", heading).split()).casefold()
        for heading in section.heading_path
    }
    return bool(headings & {"요약정보", "간이투자설명서"})


def _source_key(section: ExtractedSection) -> tuple[object, ...]:
    return (
        section.character_start,
        section.character_end,
        section.page_start if section.page_start is not None else 0,
        section.heading_path,
        section.exact_text,
    )


def _section_key(section: ExtractedSection) -> str:
    payload = json.dumps(
        {
            "heading_path": section.heading_path,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "character_start": section.character_start,
            "character_end": section.character_end,
            "text_hash": hashlib.sha256(section.exact_text.encode()).hexdigest(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
