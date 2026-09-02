"""Deterministic semantic operator candidates from normalized Korean clauses."""

from __future__ import annotations

from dataclasses import dataclass
import re

from financial_agent.contracts.base import ContractModel, Identifier

from .literals import LiteralCandidate
from .normalization import NormalizedRequest, NormalizedSegment
from .query_contract_registry import EXPECTED_OPERATOR_DEFINITIONS, OperatorArity
from .query_contracts import QueryOperatorId, SemanticValueKind


_COMPARISON_CUES = {
    "이하": QueryOperatorId.LTE,
    "미만": QueryOperatorId.LT,
    "이상": QueryOperatorId.GTE,
    "초과": QueryOperatorId.GT,
}
_COMPARISON_RE = re.compile(
    r"(?P<cue>이하|미만|이상|초과)(?P<negation>\s*(?:이|가)?\s*아닌)?"
)
_EXCLUSION_RE = re.compile(r"제외")
_RANGE_RE = re.compile(r"(?P<cue>사이|부터\s*.*?까지)")
_HARD_CLAUSE_BOUNDARY_RE = re.compile(r"[;.!?]|그리고|및|또는|하지만")
_COMMA_RE = re.compile(r",")


class OperatorCandidate(ContractModel):
    operator_candidate_id: Identifier
    operator_id: QueryOperatorId
    arity: OperatorArity
    evidence_span_id: Identifier
    compatible_value_candidate_ids: tuple[Identifier, ...]


@dataclass(frozen=True, slots=True)
class _LocatedLiteral:
    literal: LiteralCandidate
    normalized_start: int
    normalized_end: int


def extract_operator_candidates(
    request: NormalizedRequest,
    literals: tuple[LiteralCandidate, ...],
) -> tuple[OperatorCandidate, ...]:
    """Return semantic operators whose values are bounded to their source clause."""

    candidates: list[tuple[int, int, OperatorCandidate]] = []
    for segment_index, segment in enumerate(request.segments):
        located = _located_literals(segment, literals)
        candidates.extend(
            (segment_index, start, candidate)
            for start, candidate in _range_candidates(segment, located)
        )
        candidates.extend(
            (segment_index, start, candidate)
            for start, candidate in _comparison_candidates(segment, located)
        )
        candidates.extend(
            (segment_index, start, candidate)
            for start, candidate in _exclusion_candidates(segment, located)
        )
    return tuple(candidate for _, _, candidate in sorted(candidates, key=lambda item: item[:2]))


def _located_literals(
    segment: NormalizedSegment, literals: tuple[LiteralCandidate, ...]
) -> tuple[_LocatedLiteral, ...]:
    located: list[_LocatedLiteral] = []
    for literal in literals:
        if literal.segment_id != segment.segment_id:
            continue
        for index, origin_span in enumerate(segment.origin_spans):
            if origin_span[0] != literal.start_char:
                continue
            end = index
            while (
                end < len(segment.origin_spans)
                and segment.origin_spans[end][1] < literal.end_char
            ):
                end += 1
            located.append(_LocatedLiteral(literal, index, end + 1))
            break
    return tuple(located)


def _comparison_candidates(
    segment: NormalizedSegment, literals: tuple[_LocatedLiteral, ...]
) -> tuple[tuple[int, OperatorCandidate], ...]:
    candidates: list[tuple[int, OperatorCandidate]] = []
    for match in _COMPARISON_RE.finditer(segment.normalized_text):
        operator_id = _COMPARISON_CUES[match.group("cue")]
        if match.group("negation"):
            operator_id = {
                QueryOperatorId.LTE: QueryOperatorId.GT,
                QueryOperatorId.LT: QueryOperatorId.GTE,
                QueryOperatorId.GTE: QueryOperatorId.LT,
                QueryOperatorId.GT: QueryOperatorId.LTE,
            }[operator_id]
        values = _compatible_values(
            operator_id,
            _nearest_preceding_literals(
                literals,
                match.start(),
                clause_start=_clause_start(segment.normalized_text, match.start()),
                count=1,
            ),
        )
        if len(values) != 1:
            continue
        candidates.append(
            (
                match.start(),
                _candidate(
                    segment,
                    match.start(),
                    match.end(),
                    operator_id,
                    _operator_arity(operator_id),
                    values,
                ),
            )
        )
    return tuple(candidates)


def _range_candidates(
    segment: NormalizedSegment, literals: tuple[_LocatedLiteral, ...]
) -> tuple[tuple[int, OperatorCandidate], ...]:
    candidates: list[tuple[int, OperatorCandidate]] = []
    for match in _RANGE_RE.finditer(segment.normalized_text):
        clause_start = _clause_start(segment.normalized_text, match.start())
        if match.group("cue") == "사이":
            values = _nearest_preceding_literals(
                literals, match.start(), clause_start=clause_start, count=2
            )
        else:
            lower = _nearest_preceding_literals(
                literals, match.start(), clause_start=clause_start, count=1
            )
            upper = tuple(
                item.literal
                for item in literals
                if match.start() <= item.normalized_start < match.end()
            )[:1]
            values = lower + upper
        values = _compatible_values(QueryOperatorId.BETWEEN, values)
        if len(values) != 2:
            continue
        candidates.append(
            (
                match.start(),
                _candidate(
                    segment,
                    match.start(),
                    match.end(),
                    QueryOperatorId.BETWEEN,
                    _operator_arity(QueryOperatorId.BETWEEN),
                    values,
                ),
            )
        )
    return tuple(candidates)


def _exclusion_candidates(
    segment: NormalizedSegment, literals: tuple[_LocatedLiteral, ...]
) -> tuple[tuple[int, OperatorCandidate], ...]:
    candidates: list[tuple[int, OperatorCandidate]] = []
    for match in _EXCLUSION_RE.finditer(segment.normalized_text):
        clause_start = _clause_start(
            segment.normalized_text, match.start(), include_comma=False
        )
        values = _compatible_values(QueryOperatorId.NEQ, tuple(
            item.literal
            for item in literals
            if clause_start <= item.normalized_start < match.start()
        ))
        if not values:
            continue
        operator_id = QueryOperatorId.NEQ if len(values) == 1 else QueryOperatorId.NOT_IN
        candidates.append(
            (
                match.start(),
                _candidate(
                    segment,
                    match.start(),
                    match.end(),
                    operator_id,
                    _operator_arity(operator_id),
                    values,
                ),
            )
        )
    return tuple(candidates)


def _nearest_preceding_literals(
    literals: tuple[_LocatedLiteral, ...], end: int, *, clause_start: int, count: int
) -> tuple[LiteralCandidate, ...]:
    return tuple(
        item.literal
        for item in sorted(
            (
                item
                for item in literals
                if clause_start <= item.normalized_start and item.normalized_end <= end
            ),
            key=lambda item: item.normalized_end,
            reverse=True,
        )[:count][::-1]
    )


def _clause_start(text: str, operator_start: int, *, include_comma: bool = True) -> int:
    patterns = (_HARD_CLAUSE_BOUNDARY_RE, _COMPARISON_RE, _EXCLUSION_RE) + (
        (_COMMA_RE,) if include_comma else ()
    )
    boundaries = [
        match.end()
        for pattern in patterns
        for match in pattern.finditer(text[:operator_start])
    ]
    return max(boundaries, default=0)


def _compatible_values(
    operator_id: QueryOperatorId, values: tuple[LiteralCandidate, ...]
) -> tuple[LiteralCandidate, ...]:
    allowed_value_kinds = EXPECTED_OPERATOR_DEFINITIONS[operator_id.value][1]
    return tuple(
        value
        for value in values
        if SemanticValueKind(value.value_kind) in allowed_value_kinds
    )


def _operator_arity(operator_id: QueryOperatorId) -> OperatorArity:
    return EXPECTED_OPERATOR_DEFINITIONS[operator_id.value][0]


def _candidate(
    segment: NormalizedSegment,
    start: int,
    end: int,
    operator_id: QueryOperatorId,
    arity: OperatorArity,
    values: tuple[LiteralCandidate, ...],
) -> OperatorCandidate:
    original_start, original_end = segment.to_original_span(start, end)
    evidence_span_id = f"operator-{segment.segment_id}-{original_start}-{original_end}"
    return OperatorCandidate(
        operator_candidate_id=(
            f"op-{segment.segment_id}-{original_start}-{original_end}-{operator_id.value}"
        ),
        operator_id=operator_id,
        arity=arity,
        evidence_span_id=evidence_span_id,
        compatible_value_candidate_ids=tuple(item.literal_id for item in values),
    )
