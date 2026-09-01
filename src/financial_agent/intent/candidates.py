"""Bounded deterministic semantic and entity candidate contracts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.graph.contract import APPROVED_RDF_TYPES

from .catalog import SemanticCatalogSnapshot
from .normalization import NormalizedRequest, NormalizedSegment


MATCH_PRIORITY = {
    "canonical_id": 0,
    "direct_alias": 1,
    "group_alias": 2,
    "ambiguous_alias": 3,
    "trigram": 4,
}
SEMANTIC_CANDIDATE_POLICY_VERSION = "semantic-candidates-v1-trigram-0.50"
TRIGRAM_THRESHOLD_SCORE = 500_000
MAX_CANDIDATES_PER_MENTION = 5
MAX_SEMANTIC_CANDIDATES = 80
MAX_ENTITY_CANDIDATES_PER_MENTION = 5
MAX_ENTITY_MENTIONS = 16
MAX_ENTITY_CANDIDATES = (
    MAX_ENTITY_MENTIONS * MAX_ENTITY_CANDIDATES_PER_MENTION
)

SemanticMatchKind = Literal[
    "canonical_id", "direct_alias", "group_alias", "ambiguous_alias", "trigram"
]
EntityMatchKind = Literal[
    "exact_identifier", "exact_name", "exact_alias", "trigram"
]


class Mention(ContractModel):
    """A source-preserving text span offered to candidate generators."""

    mention_id: Identifier
    segment_id: Identifier
    text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_span(self) -> "Mention":
        if self.end_char <= self.start_char:
            raise ValueError("mention end_char must be after start_char")
        return self


class SemanticCandidate(ContractModel):
    mention_id: Identifier
    semantic_id: Identifier
    match_kind: SemanticMatchKind
    score: int = Field(ge=0, le=1_000_000)
    source_id: str = Field(min_length=1)


class SemanticCandidateGroup(ContractModel):
    mention: Mention
    items: tuple[SemanticCandidate, ...] = Field(max_length=MAX_CANDIDATES_PER_MENTION)

    @model_validator(mode="after")
    def validate_mention_identity(self) -> "SemanticCandidateGroup":
        if any(item.mention_id != self.mention.mention_id for item in self.items):
            raise ValueError("semantic candidate mention IDs must match their group")
        return self


class SemanticCandidateSet(ContractModel):
    candidate_policy_version: Identifier
    by_mention: tuple[SemanticCandidateGroup, ...]

    @property
    def total_count(self) -> int:
        return sum(len(group.items) for group in self.by_mention)


class EntityCandidate(ContractModel):
    entity_id: Identifier
    canonical_name: str = Field(min_length=1)
    ontology_type_ids: tuple[Identifier, ...] = Field(min_length=1)
    product_family: str | None = None
    match_kind: EntityMatchKind
    score: int = Field(ge=0, le=1_000_000)
    source_id: Identifier

    @model_validator(mode="after")
    def validate_ontology_types(self) -> "EntityCandidate":
        if (
            self.ontology_type_ids != tuple(sorted(set(self.ontology_type_ids)))
            or not set(self.ontology_type_ids) <= APPROVED_RDF_TYPES
        ):
            raise ValueError("ontology type IDs must be unique, sorted, and approved")
        return self


@dataclass(frozen=True, slots=True)
class _CandidateRecord:
    candidate: SemanticCandidate
    registration_order: int

    @property
    def sort_key(self) -> tuple[int, int, int, str, str]:
        return (
            MATCH_PRIORITY[self.candidate.match_kind],
            -self.candidate.score,
            self.registration_order,
            self.candidate.semantic_id,
            self.candidate.source_id,
        )


def generate_semantic_candidates(
    normalized: NormalizedRequest,
    catalog: SemanticCatalogSnapshot,
) -> SemanticCandidateSet:
    """Generate immutable semantic hints without resolving an intent or entity."""

    candidates: dict[str, tuple[Mention, list[_CandidateRecord]]] = {}
    registration_order = 0

    def add(
        mention: Mention,
        semantic_id: str,
        match_kind: SemanticMatchKind,
        score: int,
        source_id: str,
    ) -> None:
        nonlocal registration_order
        entry = candidates.setdefault(mention.mention_id, (mention, []))
        entry[1].append(
            _CandidateRecord(
                SemanticCandidate(
                    mention_id=mention.mention_id,
                    semantic_id=semantic_id,
                    match_kind=match_kind,
                    score=score,
                    source_id=source_id,
                ),
                registration_order,
            )
        )
        registration_order += 1

    for segment in normalized.segments:
        for mention in _exact_mentions(segment, catalog):
            for semantic_id, match_kind, source_id in _exact_matches(mention, catalog):
                add(mention, semantic_id, match_kind, 1_000_000, source_id)

        for mention in _fuzzy_mentions(segment):
            for semantic_id, score, source_id in _trigram_matches(mention, catalog):
                if score >= TRIGRAM_THRESHOLD_SCORE:
                    add(mention, semantic_id, "trigram", score, source_id)

    groups = [
        (mention, _best_per_semantic(records))
        for mention, records in (
            candidates[key]
            for key in sorted(
                candidates,
                key=lambda mention_id: _mention_sort_key(candidates[mention_id][0], normalized),
            )
        )
    ]
    selected = _select_bounded(groups)
    return SemanticCandidateSet(
        candidate_policy_version=SEMANTIC_CANDIDATE_POLICY_VERSION,
        by_mention=tuple(
            SemanticCandidateGroup(
                mention=mention,
                items=tuple(record.candidate for record in records),
            )
            for mention, records in selected
            if records
        ),
    )


def _mention_sort_key(
    mention: Mention, normalized: NormalizedRequest
) -> tuple[int, int, int, str]:
    segment_positions = {
        segment.segment_id: position for position, segment in enumerate(normalized.segments)
    }
    return (
        segment_positions[mention.segment_id],
        mention.start_char,
        mention.end_char,
        mention.mention_id,
    )


def _exact_mentions(
    segment: NormalizedSegment, catalog: SemanticCatalogSnapshot
) -> tuple[Mention, ...]:
    surfaces = set(catalog.alias_candidates) | _semantic_ids(catalog)
    spans: set[tuple[int, int]] = set()
    text = segment.normalized_text
    for surface in surfaces:
        start = text.lower().find(surface.lower())
        while surface and start >= 0:
            spans.add((start, start + len(surface)))
            start = text.lower().find(surface.lower(), start + 1)
    return tuple(_mention_from_span(segment, start, end) for start, end in sorted(spans))


def _exact_matches(
    mention: Mention, catalog: SemanticCatalogSnapshot
) -> Iterable[tuple[str, SemanticMatchKind, str]]:
    normalized_text = mention.normalized_text.lower()
    for semantic_id in sorted(_semantic_ids(catalog)):
        if normalized_text == semantic_id.lower():
            yield semantic_id, "canonical_id", f"canonical:{semantic_id}"
    for alias_text in sorted(catalog.alias_candidates):
        if normalized_text != alias_text.lower():
            continue
        match_kind = {
            "direct": "direct_alias",
            "group": "group_alias",
            "ambiguous": "ambiguous_alias",
        }[catalog.alias_kinds[alias_text]]
        for semantic_id in catalog.alias_candidates[alias_text]:
            yield (
                semantic_id,
                match_kind,
                f"overlay:{alias_text}",
            )


def _fuzzy_mentions(segment: NormalizedSegment) -> tuple[Mention, ...]:
    spans = {(0, len(segment.normalized_text))}
    start = 0
    for part in segment.normalized_text.split(" "):
        end = start + len(part)
        if part:
            spans.add((start, end))
        start = end + 1
    return tuple(_mention_from_span(segment, start, end) for start, end in sorted(spans))


def _trigram_matches(
    mention: Mention, catalog: SemanticCatalogSnapshot
) -> Iterable[tuple[str, int, str]]:
    for alias_text in sorted(catalog.alias_candidates):
        score = _trigram_jaccard_score(mention.normalized_text, alias_text)
        if score == 0:
            continue
        for semantic_id in catalog.alias_candidates[alias_text]:
            yield (
                semantic_id,
                score,
                f"overlay:{alias_text}",
            )


def _trigram_jaccard_score(left: str, right: str) -> int:
    left_trigrams = _code_point_trigrams(left.lower())
    right_trigrams = _code_point_trigrams(right.lower())
    union = left_trigrams | right_trigrams
    if not union:
        return 0
    return len(left_trigrams & right_trigrams) * 1_000_000 // len(union)


def _code_point_trigrams(value: str) -> frozenset[str]:
    return frozenset(value[index : index + 3] for index in range(len(value) - 2))


def _mention_from_span(segment: NormalizedSegment, start: int, end: int) -> Mention:
    original_start, original_end = segment.to_original_span(start, end)
    return Mention(
        mention_id=f"mention-{segment.segment_id}-{original_start}-{original_end}",
        segment_id=segment.segment_id,
        text=segment.original_text[original_start:original_end],
        normalized_text=segment.normalized_text[start:end],
        start_char=original_start,
        end_char=original_end,
    )


def _semantic_ids(catalog: SemanticCatalogSnapshot) -> set[str]:
    return (
        set(catalog.concepts_by_id)
        | set(catalog.product_family_ids)
        | set(catalog.action_ids)
        | set(catalog.entity_type_ids)
    )


def _best_per_semantic(records: list[_CandidateRecord]) -> list[_CandidateRecord]:
    best: dict[str, _CandidateRecord] = {}
    for record in records:
        existing = best.get(record.candidate.semantic_id)
        if existing is None or record.sort_key < existing.sort_key:
            best[record.candidate.semantic_id] = record
    return sorted(best.values(), key=lambda record: record.sort_key)


def _select_bounded(
    groups: list[tuple[Mention, list[_CandidateRecord]]]
) -> list[tuple[Mention, list[_CandidateRecord]]]:
    selected: list[list[_CandidateRecord]] = [[] for _ in groups]
    total = 0
    for priority_range in (range(0, MATCH_PRIORITY["trigram"]), range(MATCH_PRIORITY["trigram"], 5)):
        for group_index, (_, records) in enumerate(groups):
            for record in records:
                if MATCH_PRIORITY[record.candidate.match_kind] not in priority_range:
                    continue
                if len(selected[group_index]) >= MAX_CANDIDATES_PER_MENTION:
                    continue
                if total >= MAX_SEMANTIC_CANDIDATES:
                    break
                selected[group_index].append(record)
                total += 1
    return [
        (mention, sorted(records, key=lambda record: record.sort_key))
        for (mention, _), records in zip(groups, selected, strict=True)
    ]
