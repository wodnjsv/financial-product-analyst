"""Deterministic literal extraction from normalized request segments."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
from typing import Literal

from .normalization import NormalizedRequest, NormalizedSegment


_NUMERIC = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_MONEY_RE = re.compile(rf"(?<![\d,.])(?P<number>{_NUMERIC})(?P<unit>만원|원)")
_PERCENTAGE_RE = re.compile(rf"(?<![\d,.])(?P<number>{_NUMERIC})%")
_ISO_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?!\d)"
)
_KOREAN_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일"
)
_PERIOD_RE = re.compile(r"(?<!\d)(?P<number>\d+)(?P<unit>년|개월)")
_RANK_RE = re.compile(r"(?<!\d)(?P<number>\d+)위")
_RESULT_LIMIT_RE = re.compile(r"(?<!\d)(?P<number>\d+)개")
_NATIVE_NUMBER_VALUES = {
    "한": "1",
    "하나": "1",
    "두": "2",
    "둘": "2",
    "세": "3",
    "셋": "3",
    "네": "4",
    "넷": "4",
    "다섯": "5",
    "여섯": "6",
    "일곱": "7",
    "여덟": "8",
    "아홉": "9",
    "열": "10",
}
_NATIVE_NUMBER_ALTERNATION = "|".join(
    sorted(_NATIVE_NUMBER_VALUES, key=len, reverse=True)
)
_NATIVE_RESULT_LIMIT_RE = re.compile(
    rf"(?<![가-힣])(?P<number>{_NATIVE_NUMBER_ALTERNATION})\s*"
    r"(?:개|종목|상품(?!군)|자리)"
)
_NUMBER_RE = re.compile(rf"(?<![\d,.])(?P<number>{_NUMERIC})(?![\d,.])")
_CURRENCY_RE = re.compile(r"(?<![A-Za-z])(KRW|USD)(?![A-Za-z])|원화|달러")
_SORT_DIRECTION_RE = re.compile(r"오름차순|내림차순|높은|낮은")

_CURRENCY_VALUES = {"KRW": "KRW", "원화": "KRW", "USD": "USD", "달러": "USD"}
_SORT_VALUES = {"오름차순": "asc", "내림차순": "desc", "높은": "desc", "낮은": "asc"}


@dataclass(frozen=True, slots=True)
class LiteralCandidate:
    literal_id: str
    segment_id: str
    kind: str
    original_text: str
    start_char: int
    end_char: int
    canonical_value: str
    currency: str | None = None

    @property
    def value_kind(self) -> Literal["string", "integer", "decimal", "date"]:
        return {
            "currency": "string",
            "date": "date",
            "money": "decimal",
            "number": "decimal",
            "percentage": "decimal",
            "period": "string",
            "rank_position": "integer",
            "result_limit": "integer",
            "sort_direction": "string",
        }[self.kind]  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class _LiteralMatch:
    start: int
    end: int
    kind: str
    canonical_value: str
    currency: str | None = None


def _decimal_string(value: str) -> str:
    decimal_value = Decimal(value.replace(",", ""))
    rendered = format(decimal_value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _date_string(year: str, month: str, day: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _matches(segment: NormalizedSegment) -> list[_LiteralMatch]:
    text = segment.normalized_text
    matches: list[_LiteralMatch] = []

    for pattern in (_ISO_DATE_RE, _KOREAN_DATE_RE):
        for match in pattern.finditer(text):
            canonical_value = _date_string(
                match.group("year"), match.group("month"), match.group("day")
            )
            if canonical_value is not None:
                matches.append(
                    _LiteralMatch(match.start(), match.end(), "date", canonical_value)
                )

    for match in _MONEY_RE.finditer(text):
        multiplier = (
            Decimal("10000") if match.group("unit") == "만원" else Decimal("1")
        )
        canonical_value = _decimal_string(
            str(Decimal(match.group("number").replace(",", "")) * multiplier)
        )
        matches.append(
            _LiteralMatch(match.start(), match.end(), "money", canonical_value, "KRW")
        )

    for match in _PERCENTAGE_RE.finditer(text):
        matches.append(
            _LiteralMatch(
                match.start(),
                match.end(),
                "percentage",
                _decimal_string(match.group("number")),
            )
        )

    for match in _PERIOD_RE.finditer(text):
        unit = match.group("unit")
        canonical_value = f"P{match.group('number')}{'Y' if unit == '년' else 'M'}"
        matches.append(
            _LiteralMatch(match.start(), match.end(), "period", canonical_value)
        )

    for pattern, kind in (
        (_RANK_RE, "rank_position"),
        (_RESULT_LIMIT_RE, "result_limit"),
    ):
        for match in pattern.finditer(text):
            matches.append(
                _LiteralMatch(
                    match.start(),
                    match.end(),
                    kind,
                    _decimal_string(match.group("number")),
                )
            )

    for match in _NATIVE_RESULT_LIMIT_RE.finditer(text):
        matches.append(
            _LiteralMatch(
                match.start(),
                match.end(),
                "result_limit",
                _NATIVE_NUMBER_VALUES[match.group("number")],
            )
        )

    for match in _CURRENCY_RE.finditer(text):
        value = _CURRENCY_VALUES[match.group()]
        matches.append(
            _LiteralMatch(match.start(), match.end(), "currency", value, value)
        )

    for match in _SORT_DIRECTION_RE.finditer(text):
        matches.append(
            _LiteralMatch(
                match.start(), match.end(), "sort_direction", _SORT_VALUES[match.group()]
            )
        )

    for match in _NUMBER_RE.finditer(text):
        matches.append(
            _LiteralMatch(
                match.start(),
                match.end(),
                "number",
                _decimal_string(match.group("number")),
            )
        )

    return matches


def extract_literals(request: NormalizedRequest) -> tuple[LiteralCandidate, ...]:
    """Return non-overlapping literal candidates in original source order."""

    candidates: list[LiteralCandidate] = []
    for segment in request.segments:
        selected: list[_LiteralMatch] = []
        for match in sorted(_matches(segment), key=lambda item: (item.start, -item.end)):
            if any(
                match.start < selected_match.end and match.end > selected_match.start
                for selected_match in selected
            ):
                continue
            selected.append(match)

        for match in sorted(selected, key=lambda item: (item.start, item.end, item.kind)):
            original_start, original_end = segment.to_original_span(match.start, match.end)
            candidates.append(
                LiteralCandidate(
                    literal_id=(
                        f"lit-{segment.segment_id}-{original_start}-{original_end}-{match.kind}"
                    ),
                    segment_id=segment.segment_id,
                    kind=match.kind,
                    original_text=segment.original_text[original_start:original_end],
                    start_char=original_start,
                    end_char=original_end,
                    canonical_value=match.canonical_value,
                    currency=match.currency,
                )
            )
    return tuple(candidates)
