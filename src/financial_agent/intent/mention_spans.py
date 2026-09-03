"""Bounded, source-preserving mention spans for hybrid semantic linking."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from financial_agent.contracts.base import ContractModel, Identifier

from .candidates import Mention
from .literals import LiteralCandidate
from .normalization import NormalizedRequest, NormalizedSegment, ReferenceCandidate


MAX_PHRASE_TOKENS = 4
MAX_MENTION_SPANS = 96
MENTION_SPAN_POLICY_VERSION = "meaning-neutral-spans-v1-4x96"

MentionSourceKind = Literal[
    "exact_anchor", "literal_context", "reference", "entity", "phrase"
]
_SOURCE_KIND_ORDER: tuple[MentionSourceKind, ...] = (
    "exact_anchor",
    "literal_context",
    "reference",
    "entity",
    "phrase",
)


class MentionSpanLimitError(ValueError):
    """The bounded model-facing mention set cannot preserve all source spans."""


class MentionSpanV1(ContractModel):
    mention_id: Identifier
    segment_id: Identifier
    text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    source_kinds: tuple[MentionSourceKind, ...]


class MentionSpanSetV1(ContractModel):
    policy_version: Literal["meaning-neutral-spans-v1-4x96"]
    items: tuple[MentionSpanV1, ...] = Field(max_length=MAX_MENTION_SPANS)


class _SpanBuilder:
    def __init__(self, normalized: NormalizedRequest) -> None:
        self._segments = {segment.segment_id: segment for segment in normalized.segments}
        self._records: dict[tuple[str, int, int], set[MentionSourceKind]] = {}

    def add(
        self,
        *,
        segment_id: str,
        start_char: int,
        end_char: int,
        text: str,
        source_kind: MentionSourceKind,
    ) -> None:
        segment = self._segments.get(segment_id)
        if segment is None:
            raise ValueError("mention span has an unknown segment")
        if not 0 <= start_char < end_char <= len(segment.original_text):
            raise ValueError("mention span is outside its segment")
        if segment.original_text[start_char:end_char] != text:
            raise ValueError("mention span text does not match its segment")
        self._records.setdefault((segment_id, start_char, end_char), set()).add(
            source_kind
        )

    def build(self, normalized: NormalizedRequest) -> MentionSpanSetV1:
        if len(self._records) > MAX_MENTION_SPANS:
            raise MentionSpanLimitError("MENTION_SPAN_LIMIT_EXCEEDED")
        segment_ordinals = {
            segment.segment_id: ordinal
            for ordinal, segment in enumerate(normalized.segments)
        }
        return MentionSpanSetV1(
            policy_version=MENTION_SPAN_POLICY_VERSION,
            items=tuple(
                MentionSpanV1(
                    mention_id=f"mention-{segment_id}-{start_char}-{end_char}",
                    segment_id=segment_id,
                    text=segment.original_text[start_char:end_char],
                    normalized_text=_normalized_text_for_source_range(
                        segment, start_char, end_char
                    ),
                    start_char=start_char,
                    end_char=end_char,
                    source_kinds=tuple(
                        source_kind
                        for source_kind in _SOURCE_KIND_ORDER
                        if source_kind in source_kinds
                    ),
                )
                for (segment_id, start_char, end_char), source_kinds in sorted(
                    self._records.items(),
                    key=lambda item: (
                        segment_ordinals[item[0][0]],
                        item[0][1],
                        item[0][2],
                        f"mention-{item[0][0]}-{item[0][1]}-{item[0][2]}",
                    ),
                )
                for segment in (self._segments[segment_id],)
            ),
        )


def generate_mention_spans(
    normalized: NormalizedRequest,
    exact_mentions: Sequence[Mention],
    literals: Sequence[LiteralCandidate],
    entity_mentions: Sequence[Mention],
    reference_mentions: Sequence[ReferenceCandidate],
) -> MentionSpanSetV1:
    """Return deterministic source spans without assigning semantic meaning."""

    builder = _SpanBuilder(normalized)
    for mention in exact_mentions:
        builder.add(
            segment_id=mention.segment_id,
            start_char=mention.start_char,
            end_char=mention.end_char,
            text=mention.text,
            source_kind="exact_anchor",
        )
    for literal in literals:
        builder.add(
            segment_id=literal.segment_id,
            start_char=literal.start_char,
            end_char=literal.end_char,
            text=literal.original_text,
            source_kind="literal_context",
        )
    for mention in entity_mentions:
        builder.add(
            segment_id=mention.segment_id,
            start_char=mention.start_char,
            end_char=mention.end_char,
            text=mention.text,
            source_kind="entity",
        )
    for reference in reference_mentions:
        builder.add(
            segment_id=reference.segment_id,
            start_char=reference.start_char,
            end_char=reference.end_char,
            text=reference.text,
            source_kind="reference",
        )
    for segment in normalized.segments:
        for start_char, end_char in _phrase_ranges(segment):
            builder.add(
                segment_id=segment.segment_id,
                start_char=start_char,
                end_char=end_char,
                text=segment.original_text[start_char:end_char],
                source_kind="phrase",
            )
    return builder.build(normalized)


def _normalized_text_for_source_range(
    segment: NormalizedSegment, start_char: int, end_char: int
) -> str:
    normalized_text = segment.normalized_text_for_original_span(start_char, end_char)
    if not normalized_text:
        raise ValueError("mention span has no normalized source text")
    return normalized_text


def _phrase_ranges(segment: NormalizedSegment) -> tuple[tuple[int, int], ...]:
    ranges: set[tuple[int, int]] = set()
    for token_group in _token_groups(segment.normalized_text):
        for start_index in range(len(token_group)):
            for width in range(1, min(MAX_PHRASE_TOKENS, len(token_group) - start_index) + 1):
                normalized_start = token_group[start_index][0]
                normalized_end = token_group[start_index + width - 1][1]
                ranges.add(segment.to_original_span(normalized_start, normalized_end))
                trimmed_end = _trim_korean_particle(
                    segment.normalized_text, normalized_start, normalized_end
                )
                if trimmed_end != normalized_end:
                    ranges.add(segment.to_original_span(normalized_start, trimmed_end))
    if segment.original_text:
        ranges.add((0, len(segment.original_text)))
    return tuple(sorted(ranges))


def _token_groups(text: str) -> tuple[tuple[tuple[int, int], ...], ...]:
    groups: list[tuple[tuple[int, int], ...]] = []
    current: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        if _is_punctuation(text[index]):
            if current:
                groups.append(tuple(current))
                current = []
            index += 1
            continue
        start = index
        while (
            index < len(text)
            and not text[index].isspace()
            and not _is_punctuation(text[index])
        ):
            index += 1
        current.append((start, index))
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _is_punctuation(character: str) -> bool:
    return unicodedata.category(character).startswith("P")


_KOREAN_PARTICLES = (
    "까지",
    "부터",
    "에게",
    "에서",
    "으로",
    "처럼",
    "보다",
    "는지",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "과",
    "와",
    "의",
    "에",
    "로",
    "만",
    "도",
    "랑",
)


def _trim_korean_particle(text: str, start: int, end: int) -> int:
    """Add a source range without a common trailing Korean postposition."""

    word = text[start:end]
    for particle in _KOREAN_PARTICLES:
        if len(word) > len(particle) and word.endswith(particle):
            return end - len(particle)
    return end
