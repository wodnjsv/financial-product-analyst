"""Server-owned request evidence candidates with original-text provenance."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping, Sequence
from enum import Enum

from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.canonical import canonical_json_bytes

from .candidates import EntityCandidate, Mention, SemanticCandidateSet
from .catalog import PolicyCue
from .literals import LiteralCandidate
from .normalization import NormalizedRequest


MAX_SURFACE_TOKEN_CODE_POINTS = 32


class EvidenceSourceKind(str, Enum):
    SEMANTIC = "semantic"
    LITERAL = "literal"
    REFERENCE = "reference"
    ENTITY = "entity"
    POLICY = "policy"
    SURFACE = "surface"


class EvidenceCandidate(ContractModel):
    evidence_id: Identifier
    segment_id: Identifier
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    text: str = Field(min_length=1)
    source_kinds: tuple[EvidenceSourceKind, ...]
    offered_semantic_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_coordinates(self) -> "EvidenceCandidate":
        if self.end_char <= self.start_char:
            raise ValueError("evidence end_char must be after start_char")
        return self


class _EvidenceBuilder:
    def __init__(self) -> None:
        self._records: dict[
            tuple[str, int, int, str], tuple[set[EvidenceSourceKind], set[str]]
        ] = {}

    def add(
        self,
        *,
        segment_id: str,
        start_char: int,
        end_char: int,
        text: str,
        source_kind: EvidenceSourceKind,
        offered_semantic_ids: Sequence[str] = (),
    ) -> None:
        if not text or end_char <= start_char:
            return
        key = (segment_id, start_char, end_char, text)
        source_kinds, semantic_ids = self._records.setdefault(key, (set(), set()))
        source_kinds.add(source_kind)
        semantic_ids.update(offered_semantic_ids)

    def occupied_spans(self) -> Mapping[str, tuple[tuple[int, int], ...]]:
        by_segment: dict[str, list[tuple[int, int]]] = {}
        for segment_id, start_char, end_char, _ in self._records:
            by_segment.setdefault(segment_id, []).append((start_char, end_char))
        return {
            segment_id: tuple(_merged_spans(spans))
            for segment_id, spans in by_segment.items()
        }

    def build(
        self, normalized: NormalizedRequest
    ) -> tuple[EvidenceCandidate, ...]:
        segment_ordinals = {
            segment.segment_id: ordinal
            for ordinal, segment in enumerate(normalized.segments)
        }
        return tuple(
            EvidenceCandidate(
                evidence_id=_evidence_id(segment_id, start_char, end_char, text),
                segment_id=segment_id,
                start_char=start_char,
                end_char=end_char,
                text=text,
                source_kinds=tuple(sorted(source_kinds, key=lambda item: item.value)),
                offered_semantic_ids=tuple(sorted(semantic_ids)),
            )
            for (segment_id, start_char, end_char, text), (
                source_kinds,
                semantic_ids,
            ) in sorted(
                self._records.items(),
                key=lambda item: (
                    segment_ordinals[item[0][0]],
                    item[0][1],
                    item[0][2],
                    item[0][3],
                ),
            )
        )


def build_evidence_candidates(
    *,
    normalized: NormalizedRequest,
    literals: Sequence[LiteralCandidate],
    semantic_candidates: SemanticCandidateSet,
    entity_candidates: Mapping[str, Sequence[EntityCandidate]],
    policy_cues: Sequence[PolicyCue],
) -> tuple[EvidenceCandidate, ...]:
    """Merge bounded source spans into deterministic request-scoped evidence."""
    builder = _EvidenceBuilder()
    mentions = {
        group.mention.mention_id: group.mention
        for group in semantic_candidates.by_mention
    }

    for group in semantic_candidates.by_mention:
        _add_mention(
            builder,
            group.mention,
            EvidenceSourceKind.SEMANTIC,
            tuple(item.semantic_id for item in group.items),
        )
    for literal in literals:
        builder.add(
            segment_id=literal.segment_id,
            start_char=literal.start_char,
            end_char=literal.end_char,
            text=literal.original_text,
            source_kind=EvidenceSourceKind.LITERAL,
        )
    for reference in normalized.reference_candidates:
        builder.add(
            segment_id=reference.segment_id,
            start_char=reference.start_char,
            end_char=reference.end_char,
            text=reference.text,
            source_kind=EvidenceSourceKind.REFERENCE,
        )
    for mention_id, candidates in entity_candidates.items():
        if candidates and (mention := mentions.get(mention_id)) is not None:
            _add_mention(builder, mention, EvidenceSourceKind.ENTITY)
    _add_named_entity_evidence(builder, normalized, entity_candidates, mentions)
    _add_policy_evidence(builder, normalized, policy_cues)
    _add_surface_evidence(builder, normalized)
    return builder.build(normalized)


def _add_mention(
    builder: _EvidenceBuilder,
    mention: Mention,
    source_kind: EvidenceSourceKind,
    offered_semantic_ids: Sequence[str] = (),
) -> None:
    builder.add(
        segment_id=mention.segment_id,
        start_char=mention.start_char,
        end_char=mention.end_char,
        text=mention.text,
        source_kind=source_kind,
        offered_semantic_ids=offered_semantic_ids,
    )


def _add_named_entity_evidence(
    builder: _EvidenceBuilder,
    normalized: NormalizedRequest,
    entity_candidates: Mapping[str, Sequence[EntityCandidate]],
    semantic_mentions: Mapping[str, Mention],
) -> None:
    segments = {segment.segment_id: segment for segment in normalized.segments}
    for mention in normalized.context.named_entities:
        if (
            not entity_candidates.get(mention.mention_id)
            or mention.mention_id in semantic_mentions
        ):
            continue
        segment = segments[mention.segment_id]
        start_char = segment.original_text.find(mention.text)
        if start_char >= 0:
            builder.add(
                segment_id=mention.segment_id,
                start_char=start_char,
                end_char=start_char + len(mention.text),
                text=mention.text,
                source_kind=EvidenceSourceKind.ENTITY,
            )


def _add_policy_evidence(
    builder: _EvidenceBuilder,
    normalized: NormalizedRequest,
    policy_cues: Sequence[PolicyCue],
) -> None:
    for segment in normalized.segments:
        for cue in policy_cues:
            start = segment.normalized_text.find(cue.surface)
            while start >= 0:
                end = start + len(cue.surface)
                original_start, original_end = segment.to_original_span(start, end)
                builder.add(
                    segment_id=segment.segment_id,
                    start_char=original_start,
                    end_char=original_end,
                    text=segment.original_text[original_start:original_end],
                    source_kind=EvidenceSourceKind.POLICY,
                    offered_semantic_ids=(cue.semantic_tag,),
                )
                start = segment.normalized_text.find(cue.surface, start + 1)


def _add_surface_evidence(
    builder: _EvidenceBuilder, normalized: NormalizedRequest
) -> None:
    occupied = builder.occupied_spans()
    for segment in normalized.segments:
        for start_char, end_char in _uncovered_token_spans(
            segment.original_text, occupied.get(segment.segment_id, ())
        ):
            builder.add(
                segment_id=segment.segment_id,
                start_char=start_char,
                end_char=end_char,
                text=segment.original_text[start_char:end_char],
                source_kind=EvidenceSourceKind.SURFACE,
            )


def _uncovered_token_spans(
    text: str, occupied: Sequence[tuple[int, int]]
) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if _is_token_boundary(text[index]):
            index += 1
            continue
        token_start = index
        while index < len(text) and not _is_token_boundary(text[index]):
            index += 1
        token_end = index
        for uncovered_start, uncovered_end in _subtract_spans(
            (token_start, token_end), occupied
        ):
            for chunk_start in range(
                uncovered_start, uncovered_end, MAX_SURFACE_TOKEN_CODE_POINTS
            ):
                spans.append(
                    (
                        chunk_start,
                        min(chunk_start + MAX_SURFACE_TOKEN_CODE_POINTS, uncovered_end),
                    )
                )
    return tuple(spans)


def _is_token_boundary(character: str) -> bool:
    return character.isspace() or unicodedata.category(character).startswith("P")


def _subtract_spans(
    span: tuple[int, int], occupied: Sequence[tuple[int, int]]
) -> tuple[tuple[int, int], ...]:
    start, end = span
    remaining: list[tuple[int, int]] = []
    cursor = start
    for occupied_start, occupied_end in occupied:
        if occupied_end <= cursor:
            continue
        if occupied_start >= end:
            break
        if occupied_start > cursor:
            remaining.append((cursor, min(occupied_start, end)))
        cursor = max(cursor, occupied_end)
        if cursor >= end:
            break
    if cursor < end:
        remaining.append((cursor, end))
    return tuple(remaining)


def _merged_spans(spans: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _evidence_id(segment_id: str, start_char: int, end_char: int, text: str) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "segment_id": segment_id,
                "start_char": start_char,
                "end_char": end_char,
                "text": text,
            }
        )
    ).hexdigest()
    return f"evidence-{digest}"
