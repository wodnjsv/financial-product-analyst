from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal


ResolutionStatus = Literal["exact", "unresolved", "conflict"]


@dataclass(frozen=True, slots=True)
class IdentityCandidate:
    scheme: str
    value: str


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    status: ResolutionStatus
    entity_id: str | None
    matched_scheme: str | None
    issue_code: str | None


_SIMPLE_PATTERNS = {
    "CUSIP": re.compile(r"[A-Z0-9*@#]{9}"),
    "KRX_SHORT_ISSUE_CODE": re.compile(r"[A-Z0-9]{6}"),
    "KRX_STANDARD_ISSUE_CODE": re.compile(r"[A-Z0-9]{12}"),
    "SEC_CLASS_ID": re.compile(r"C[0-9]{9}"),
    "SEC_SERIES_ID": re.compile(r"S[0-9]{9}"),
}
_COMPOUND_SCHEME = "SEC_CIK_CLASS_TICKER"


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _valid_isin(value: str) -> bool:
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value) is None:
        return False
    expanded = "".join(str(int(character, 36)) for character in value)
    total = 0
    for index, character in enumerate(reversed(expanded)):
        number = int(character) * (2 if index % 2 else 1)
        total += number // 10 + number % 10
    return total % 10 == 0


def _normalize_candidate(
    candidate: IdentityCandidate,
) -> tuple[str, str] | None:
    scheme = _normalized_text(candidate.scheme).upper()
    value = _normalized_text(candidate.value).upper()
    if not value:
        return None
    if scheme == "ISIN":
        return (scheme, value) if _valid_isin(value) else None
    if scheme == "SEC_CIK":
        if re.fullmatch(r"[0-9]{1,10}", value) is None:
            return None
        return scheme, value.lstrip("0") or "0"
    if scheme == "SEC_NPORT_HOLDING_ID":
        parts = value.split("/", 1)
        if len(parts) != 2 or not all(parts):
            return None
        return scheme, value
    pattern = _SIMPLE_PATTERNS.get(scheme)
    if pattern is None or pattern.fullmatch(value) is None:
        return None
    return scheme, value


def _normalize_compound(
    scheme: str, values: tuple[str, ...]
) -> tuple[str, tuple[str, ...]] | None:
    normalized_scheme = _normalized_text(scheme).upper()
    if normalized_scheme != _COMPOUND_SCHEME or len(values) != 2:
        return None
    cik = _normalized_text(values[0])
    ticker = _normalized_text(values[1]).upper()
    if re.fullmatch(r"[0-9]{1,10}", cik) is None:
        return None
    if re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", ticker) is None:
        return None
    return normalized_scheme, (cik.lstrip("0") or "0", ticker)


class OfficialIdentityIndex:
    def __init__(
        self,
        *,
        exact_entries: Iterable[tuple[IdentityCandidate, str]] = (),
        compound_entries: Iterable[
            tuple[str, tuple[str, ...], str]
        ] = (),
    ) -> None:
        self._exact: dict[tuple[str, str], set[str]] = {}
        self._compound: dict[tuple[str, tuple[str, ...]], list[str]] = {}
        for candidate, entity_id in exact_entries:
            key = _normalize_candidate(candidate)
            if key is not None:
                self._exact.setdefault(key, set()).add(entity_id)
        for scheme, values, entity_id in compound_entries:
            key = _normalize_compound(scheme, values)
            if key is not None:
                self._compound.setdefault(key, []).append(entity_id)

    def resolve_product(
        self, candidates: Sequence[IdentityCandidate]
    ) -> IdentityResolution:
        matched: list[tuple[str, set[str]]] = []
        for candidate in candidates:
            key = _normalize_candidate(candidate)
            if key is not None and key in self._exact:
                matched.append((key[0], self._exact[key]))
        return self._resolution(matched)

    def resolve_compound_product(
        self, scheme: str, values: tuple[str, ...]
    ) -> IdentityResolution:
        key = _normalize_compound(scheme, values)
        if key is None or key not in self._compound:
            return self._unresolved()
        return self._resolution([(key[0], self._compound[key])])

    @staticmethod
    def _unresolved() -> IdentityResolution:
        return IdentityResolution(
            status="unresolved",
            entity_id=None,
            matched_scheme=None,
            issue_code="NO_EXACT_IDENTITY",
        )

    @classmethod
    def _resolution(
        cls, matched: Sequence[tuple[str, Collection[str]]]
    ) -> IdentityResolution:
        if not matched:
            return cls._unresolved()
        if any(len(entity_ids) != 1 for _, entity_ids in matched):
            return IdentityResolution(
                status="conflict",
                entity_id=None,
                matched_scheme=None,
                issue_code="IDENTITY_KEY_CONFLICT",
            )
        entities = {next(iter(entity_ids)) for _, entity_ids in matched}
        if len(entities) != 1:
            return IdentityResolution(
                status="conflict",
                entity_id=None,
                matched_scheme=None,
                issue_code="IDENTITY_CANDIDATE_CONFLICT",
            )
        return IdentityResolution(
            status="exact",
            entity_id=next(iter(entities)),
            matched_scheme=matched[0][0],
            issue_code=None,
        )
