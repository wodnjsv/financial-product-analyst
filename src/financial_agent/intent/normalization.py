"""Deterministic request normalization with original code-point provenance."""

from dataclasses import dataclass
import unicodedata

from financial_agent.contracts.request import RequestContext


MAX_QUESTION_CODE_POINTS = 4_096
MAX_SEGMENTS = 16

_REFERENCE_SURFACES = (
    "그 상품들",
    "위 상품들",
    "이 상품",
    "그 상품",
    "해당 상품",
    "전자",
    "후자",
    "나머지",
    "각각",
)


class RequestNormalizationError(ValueError):
    """A request cannot enter deterministic intent normalization."""


@dataclass(frozen=True, slots=True)
class NormalizedSegment:
    segment_id: str
    original_text: str
    normalized_text: str
    origin_spans: tuple[tuple[int, int], ...]

    def to_original_span(self, start: int, end: int) -> tuple[int, int]:
        if not 0 <= start < end <= len(self.origin_spans):
            raise ValueError("normalized span is out of range")
        return self.origin_spans[start][0], self.origin_spans[end - 1][1]

    def find_normalized(self, text: str) -> tuple[int, int]:
        start = self.normalized_text.find(text)
        if not text or start < 0:
            raise ValueError("normalized text was not found")
        return start, start + len(text)


@dataclass(frozen=True, slots=True)
class ReferenceCandidate:
    reference_id: str
    segment_id: str
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class NormalizedRequest:
    context: RequestContext
    segments: tuple[NormalizedSegment, ...]
    reference_candidates: tuple[ReferenceCandidate, ...]


def normalize_segment(segment_id: str, text: str) -> NormalizedSegment:
    """Apply per-code-point NFKC and whitespace collapse without losing origins."""

    normalized_characters: list[str] = []
    origin_spans: list[tuple[int, int]] = []
    whitespace_start: int | None = None
    whitespace_end: int | None = None

    def flush_whitespace() -> None:
        nonlocal whitespace_start, whitespace_end
        if whitespace_start is not None and whitespace_end is not None:
            normalized_characters.append(" ")
            origin_spans.append((whitespace_start, whitespace_end))
        whitespace_start = None
        whitespace_end = None

    for index, character in enumerate(text):
        for normalized_character in unicodedata.normalize("NFKC", character):
            if normalized_character.isspace():
                if whitespace_start is None:
                    whitespace_start = index
                whitespace_end = index + 1
                continue
            flush_whitespace()
            normalized_characters.append(normalized_character)
            origin_spans.append((index, index + 1))
    flush_whitespace()

    return NormalizedSegment(
        segment_id=segment_id,
        original_text=text,
        normalized_text="".join(normalized_characters),
        origin_spans=tuple(origin_spans),
    )


def normalize_request(context: RequestContext) -> NormalizedRequest:
    """Normalize bounded request segments and mark explicit reference surfaces."""

    if len(context.question) > MAX_QUESTION_CODE_POINTS:
        raise RequestNormalizationError(
            "REQUEST_CONTRACT_INVALID: question exceeds 4096 code points"
        )
    if len(context.segments) > MAX_SEGMENTS:
        raise RequestNormalizationError(
            "REQUEST_CONTRACT_INVALID: request exceeds 16 segments"
        )

    segments = tuple(
        normalize_segment(segment.segment_id, segment.text)
        for segment in context.segments
    )
    candidates: list[ReferenceCandidate] = []
    for segment in segments:
        occupied: list[tuple[int, int]] = []
        for surface in _REFERENCE_SURFACES:
            start = segment.normalized_text.find(surface)
            while start >= 0:
                end = start + len(surface)
                if not any(
                    start < occupied_end and end > occupied_start
                    for occupied_start, occupied_end in occupied
                ):
                    original_start, original_end = segment.to_original_span(start, end)
                    candidates.append(
                        ReferenceCandidate(
                            reference_id=(
                                f"ref-{segment.segment_id}-{original_start}-{original_end}"
                            ),
                            segment_id=segment.segment_id,
                            text=segment.original_text[original_start:original_end],
                            start_char=original_start,
                            end_char=original_end,
                        )
                    )
                    occupied.append((start, end))
                start = segment.normalized_text.find(surface, start + 1)

    segment_order = {segment.segment_id: index for index, segment in enumerate(segments)}
    candidates.sort(
        key=lambda candidate: (
            segment_order[candidate.segment_id],
            candidate.start_char,
            candidate.end_char,
        )
    )
    return NormalizedRequest(
        context=context,
        segments=segments,
        reference_candidates=tuple(candidates),
    )
