"""Exact, span-preserving semantic locks for the V2 query path."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from financial_agent.contracts.base import ContractModel, Identifier

from .candidates import (
    SemanticCandidate,
    SemanticCandidateSet,
    generate_semantic_candidates,
)
from .catalog import SemanticCatalogSnapshot
from .literals import LiteralCandidate, extract_literals
from .normalization import NormalizedRequest
from .operators import extract_operator_candidates


class ExactSemanticLock(ContractModel):
    lock_id: Identifier
    role: Literal["product_family", "field", "operator", "literal"]
    canonical_id: Identifier
    evidence_span_ids: tuple[Identifier, ...]
    source: Literal["canonical", "direct_alias", "literal"]


def build_exact_semantic_locks(
    request: NormalizedRequest,
    catalog: SemanticCatalogSnapshot,
    *,
    semantic_candidates: SemanticCandidateSet | None = None,
    literals: Sequence[LiteralCandidate] | None = None,
) -> tuple[ExactSemanticLock, ...]:
    """Build locks only from unique canonical, direct-alias, and literal evidence."""

    candidates = (
        semantic_candidates
        if semantic_candidates is not None
        else generate_semantic_candidates(request, catalog)
    )
    resolved_literals = (
        tuple(literals) if literals is not None else extract_literals(request)
    )
    operators = extract_operator_candidates(request, resolved_literals)
    locks: list[ExactSemanticLock] = []
    for group in candidates.by_mention:
        for candidate in group.items:
            role = _semantic_role(candidate, catalog)
            if role is None or candidate.match_kind not in {"canonical_id", "direct_alias"}:
                continue
            locks.append(
                ExactSemanticLock(
                    lock_id=(
                        f"lock-{role}-{group.mention.mention_id}-{candidate.semantic_id}"
                    ),
                    role=role,
                    canonical_id=candidate.semantic_id,
                    evidence_span_ids=(group.mention.mention_id,),
                    source=(
                        "canonical"
                        if candidate.match_kind == "canonical_id"
                        else "direct_alias"
                    ),
                )
            )
    locks.extend(
        ExactSemanticLock(
            lock_id=f"lock-literal-{literal.literal_id}",
            role="literal",
            canonical_id=literal.literal_id,
            evidence_span_ids=(literal.literal_id,),
            source="literal",
        )
        for literal in resolved_literals
    )
    locks.extend(
        ExactSemanticLock(
            lock_id=f"lock-operator-{candidate.operator_candidate_id}",
            role="operator",
            canonical_id=candidate.operator_id.value,
            evidence_span_ids=(candidate.evidence_span_id,),
            source="canonical",
        )
        for candidate in operators
    )
    return validate_exact_semantic_locks(locks)


def validate_exact_semantic_locks(
    locks: Iterable[ExactSemanticLock],
) -> tuple[ExactSemanticLock, ...]:
    """Reject incompatible exact meanings claimed for the same role and evidence."""

    ordered = tuple(sorted(locks, key=lambda item: item.lock_id))
    claims: dict[tuple[str, str], str] = {}
    for lock in ordered:
        if not lock.evidence_span_ids:
            raise ValueError("EXACT_LOCK_CONFLICT")
        for evidence_span_id in lock.evidence_span_ids:
            key = (lock.role, evidence_span_id)
            existing = claims.setdefault(key, lock.canonical_id)
            if existing != lock.canonical_id:
                raise ValueError("EXACT_LOCK_CONFLICT")
    return ordered


def _semantic_role(
    candidate: SemanticCandidate, catalog: SemanticCatalogSnapshot
) -> Literal["product_family", "field"] | None:
    if candidate.semantic_id in catalog.product_family_ids:
        return "product_family"
    if candidate.semantic_id in catalog.concepts_by_id:
        return "field"
    return None
