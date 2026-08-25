from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from types import MappingProxyType

from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.models import (
    CanonicalIdentity,
    IdentifierCandidate,
    IdentityResolution,
)


_ALLOWED_ROLES = frozenset(
    {
        "Bond",
        "DomesticETF",
        "DomesticETN",
        "FundShareClass",
        "OverseasETF",
        "OverseasETN",
    }
)
_GLOBAL_SCHEMES = frozenset({"ISIN", "LIPPER"})
_OWNER_PRIORITY = {
    "PREF01N001": 0,
    "PRFD01N001": 1,
    "PREF02N001": 2,
    "PRBD01N001": 3,
}
_SCHEME_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_MISSING_IDENTIFIER_VALUES = frozenset({"", "NULL"})
_PUBLIC_FUND_KSD_SENTINELS = frozenset({"KR0000000000", "000000000000"})


class AuthoritativeIdentityValidationError(RuntimeError):
    def __init__(self, issue_counts: Mapping[str, int]) -> None:
        normalized = dict(sorted(issue_counts.items()))
        self.issue_counts = normalized
        self.code = (
            next(iter(normalized))
            if len(normalized) == 1
            else "IDENTITY_CANDIDATE_VALIDATION_FAILED"
        )
        super().__init__(self.code)


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


def _normalized_lookup(scheme: str, value: str) -> tuple[str, str] | None:
    normalized_scheme = _normalized_text(scheme).upper()
    normalized_value = _normalized_text(value).upper()
    if (
        _SCHEME_PATTERN.fullmatch(normalized_scheme) is None
        or not normalized_value
    ):
        return None
    if normalized_scheme == "ISIN" and not _valid_isin(normalized_value):
        return None
    return normalized_scheme, normalized_value


def _source_value(row: Mapping[str, object], column: str) -> str:
    raw = row.get(column)
    if raw is None:
        return ""
    return _normalized_text(str(raw))


def collect_organizer_identifier_candidates(
    source_code: str,
    rows: Iterable[Mapping[str, object]],
) -> tuple[IdentifierCandidate, ...]:
    normalized_source = _normalized_text(source_code).upper()
    candidates: list[IdentifierCandidate] = []
    issues: Counter[str] = Counter()

    for row_number, row in enumerate(rows, start=2):
        row_candidates: list[IdentifierCandidate] = []

        def append(
            natural_key: str,
            entity_role: str,
            scheme: str,
            value: str,
        ) -> None:
            normalized_value = _normalized_text(value).upper()
            if normalized_value in _MISSING_IDENTIFIER_VALUES:
                return
            candidate = IdentifierCandidate(
                source_code=normalized_source,
                row_number=row_number,
                natural_key=_normalized_text(natural_key),
                entity_role=entity_role,
                scheme=scheme,
                value=normalized_value,
            )
            if candidate not in row_candidates:
                row_candidates.append(candidate)

        if normalized_source == "PRBD01N001":
            natural_key = _source_value(row, "pd_no")
            if natural_key and natural_key.upper() != "NULL":
                append(natural_key, "Bond", "PRBD_PD_NO", natural_key)

        elif normalized_source in {"PREF01N001", "PREF02N001"}:
            natural_key = _source_value(row, "pd_itm_no")
            group = _source_value(row, "pd_grp_no").upper()
            role_prefix = (
                "Domestic"
                if normalized_source == "PREF01N001"
                else "Overseas"
            )
            role = f"{role_prefix}{group}" if group in {"ETF", "ETN"} else ""
            if natural_key and natural_key.upper() != "NULL" and role:
                local_scheme = (
                    "PREF01_PD_ITM_NO"
                    if normalized_source == "PREF01N001"
                    else "PREF02_PD_ITM_NO"
                )
                append(natural_key, role, local_scheme, natural_key)
                normalized_natural_key = natural_key.upper()
                if normalized_source == "PREF01N001" and _valid_isin(
                    normalized_natural_key
                ):
                    append(natural_key, role, "ISIN", normalized_natural_key)

                explicit_isin = _source_value(row, "pd_isin_cd").upper()
                if explicit_isin not in _MISSING_IDENTIFIER_VALUES:
                    if (
                        normalized_source == "PREF01N001"
                        and _valid_isin(normalized_natural_key)
                        and explicit_isin != normalized_natural_key
                    ):
                        issues["IDENTITY_EXPLICIT_ISIN_MISMATCH"] += 1
                    append(natural_key, role, "ISIN", explicit_isin)

                if normalized_source == "PREF02N001":
                    lipper = _source_value(row, "pd_lipper_id")
                    append(natural_key, role, "LIPPER", lipper)

        elif normalized_source == "PRFD01N001":
            natural_key = _source_value(row, "itm_no")
            if natural_key and natural_key.upper() != "NULL":
                append(
                    natural_key,
                    "FundShareClass",
                    "PRFD_ITM_NO",
                    natural_key,
                )
                ksd_identifier = _source_value(row, "ksd_itm_no").upper()
                if (
                    ksd_identifier not in _MISSING_IDENTIFIER_VALUES
                    and ksd_identifier not in _PUBLIC_FUND_KSD_SENTINELS
                ):
                    append(
                        natural_key,
                        "FundShareClass",
                        "KSD_PRODUCT",
                        ksd_identifier,
                    )
                    if _valid_isin(ksd_identifier):
                        append(
                            natural_key,
                            "FundShareClass",
                            "ISIN",
                            ksd_identifier,
                        )

        candidates.extend(row_candidates)

    if issues:
        raise AuthoritativeIdentityValidationError(issues)
    return tuple(candidates)


def _normalized_candidate(
    candidate: IdentifierCandidate,
    issues: Counter[str],
) -> IdentifierCandidate | None:
    source_code = _normalized_text(candidate.source_code).upper()
    natural_key = _normalized_text(candidate.natural_key)
    entity_role = _normalized_text(candidate.entity_role)
    scheme = _normalized_text(candidate.scheme).upper()
    value = _normalized_text(candidate.value).upper()

    valid = True
    if not source_code:
        issues["IDENTITY_SOURCE_BLANK"] += 1
        valid = False
    if candidate.row_number < 1:
        issues["IDENTITY_ROW_NUMBER_INVALID"] += 1
        valid = False
    if not natural_key:
        issues["IDENTITY_NATURAL_KEY_BLANK"] += 1
        valid = False
    if entity_role not in _ALLOWED_ROLES:
        issues["IDENTITY_ROLE_INVALID"] += 1
        valid = False
    if _SCHEME_PATTERN.fullmatch(scheme) is None:
        issues["IDENTITY_SCHEME_INVALID"] += 1
        valid = False
    if not value:
        issues["IDENTITY_VALUE_BLANK"] += 1
        valid = False
    elif scheme == "ISIN" and not _valid_isin(value):
        issues["IDENTITY_ISIN_INVALID"] += 1
        valid = False
    if not valid:
        return None
    return IdentifierCandidate(
        source_code=source_code,
        row_number=candidate.row_number,
        natural_key=natural_key,
        entity_role=entity_role,
        scheme=scheme,
        value=value,
    )


class _UnionFind:
    def __init__(self, nodes: Iterable[tuple[str, str]]) -> None:
        self._parent = {node: node for node in nodes}

    def find(self, node: tuple[str, str]) -> tuple[str, str]:
        parent = self._parent[node]
        if parent != node:
            self._parent[node] = self.find(parent)
        return self._parent[node]

    def union(self, nodes: Iterable[tuple[str, str]]) -> None:
        roots = sorted({self.find(node) for node in nodes})
        if len(roots) < 2:
            return
        owner = roots[0]
        for root in roots[1:]:
            self._parent[root] = owner


def _compatible_overlap(roles: frozenset[str]) -> bool:
    return roles == frozenset({"DomesticETF", "FundShareClass"})


def _owner_sort_key(node: tuple[str, str]) -> tuple[int, str, str]:
    return (
        _OWNER_PRIORITY.get(node[0], len(_OWNER_PRIORITY)),
        node[0],
        node[1],
    )


class AuthoritativeIdentityIndex:
    __slots__ = ("_identities", "_resolutions")

    def __init__(
        self,
        *,
        identities: tuple[CanonicalIdentity, ...],
        resolutions: Mapping[tuple[str, str], IdentityResolution],
    ) -> None:
        self._identities = identities
        self._resolutions = MappingProxyType(dict(resolutions))

    @property
    def identities(self) -> tuple[CanonicalIdentity, ...]:
        return self._identities

    def resolve(self, scheme: str, value: str) -> IdentityResolution:
        key = _normalized_lookup(scheme, value)
        if key is None:
            return IdentityResolution(
                status="NOT_FOUND",
                canonical_identity=None,
            )
        return self._resolutions.get(
            key,
            IdentityResolution(
                status="NOT_FOUND",
                canonical_identity=None,
            ),
        )


def build_authoritative_identity_index(
    candidates: Iterable[IdentifierCandidate],
) -> AuthoritativeIdentityIndex:
    issues: Counter[str] = Counter()
    normalized = tuple(
        candidate
        for candidate in (
            _normalized_candidate(item, issues) for item in candidates
        )
        if candidate is not None
    )
    if issues:
        raise AuthoritativeIdentityValidationError(issues)

    node_roles: dict[tuple[str, str], set[str]] = defaultdict(set)
    key_nodes: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for candidate in normalized:
        node = (candidate.source_code, candidate.natural_key)
        node_roles[node].add(candidate.entity_role)
        key_nodes[(candidate.scheme, candidate.value)].add(node)

    role_conflict_count = sum(
        1 for roles in node_roles.values() if len(roles) != 1
    )
    if role_conflict_count:
        raise AuthoritativeIdentityValidationError(
            {"IDENTITY_ROLE_CONFLICT": role_conflict_count}
        )

    union_find = _UnionFind(node_roles)
    ambiguous_global_keys: set[tuple[str, str]] = set()
    for key in sorted(key_nodes):
        if key[0] not in _GLOBAL_SCHEMES:
            continue
        nodes = key_nodes[key]
        roots = {union_find.find(node) for node in nodes}
        if len(roots) < 2:
            continue
        roles = frozenset(
            role
            for node in nodes
            for role in node_roles[node]
        )
        if _compatible_overlap(roles) and len(nodes) == 2:
            union_find.union(nodes)
        else:
            ambiguous_global_keys.add(key)

    component_nodes: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for node in node_roles:
        component_nodes[union_find.find(node)].add(node)

    identity_by_node: dict[tuple[str, str], CanonicalIdentity] = {}
    identities: list[CanonicalIdentity] = []
    for nodes in component_nodes.values():
        roles = frozenset(
            role for node in nodes for role in node_roles[node]
        )
        domestic_etf_nodes = sorted(
            (
                node
                for node in nodes
                if "DomesticETF" in node_roles[node]
            ),
            key=_owner_sort_key,
        )
        owner = (
            domestic_etf_nodes[0]
            if _compatible_overlap(roles) and domestic_etf_nodes
            else min(nodes, key=_owner_sort_key)
        )
        identity = CanonicalIdentity(
            entity_id=stable_id("product", owner[0], owner[1]),
            owner_source_code=owner[0],
            owner_natural_key=owner[1],
            roles=roles,
        )
        identities.append(identity)
        for node in nodes:
            identity_by_node[node] = identity

    resolutions: dict[tuple[str, str], IdentityResolution] = {}
    for key, nodes in key_nodes.items():
        resolved_identities = {
            identity_by_node[node]
            for node in nodes
        }
        if key in ambiguous_global_keys or len(resolved_identities) != 1:
            resolutions[key] = IdentityResolution(
                status="AMBIGUOUS",
                canonical_identity=None,
            )
        else:
            resolutions[key] = IdentityResolution(
                status="MATCHED",
                canonical_identity=next(iter(resolved_identities)),
            )

    return AuthoritativeIdentityIndex(
        identities=tuple(
            sorted(
                identities,
                key=lambda item: (
                    item.owner_source_code,
                    item.owner_natural_key,
                    item.entity_id,
                ),
            )
        ),
        resolutions=resolutions,
    )
