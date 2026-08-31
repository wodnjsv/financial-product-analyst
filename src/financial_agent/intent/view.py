"""Pinned, bounded request projections for intent resolution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.contracts.request import RequestContext
from financial_agent.graph.contract import (
    APPROVED_RDF_TYPES,
    GRAPH_CONTRACT_RELATIVE_PATHS,
)

from .candidates import (
    MAX_ENTITY_CANDIDATES,
    MAX_ENTITY_CANDIDATES_PER_MENTION,
    MAX_ENTITY_MENTIONS,
    EntityCandidate,
    SemanticCandidate,
    SemanticCandidateSet,
)
from .catalog import SemanticCatalogSnapshot
from .literals import LiteralCandidate
from .normalization import NormalizedRequest
from .resolution import ContractFileHash, ResolverBuildManifest


NORMALIZER_VERSION = "intent-normalizer-v1"
CANDIDATE_POLICY_VERSION = "intent-candidate-v1"
RESOLVER_SCHEMA_VERSION = "1.0"
PROMPT_VERSION = "intent-resolver-ko-v1"
ADAPTER_VERSION = "clova-chat-v3-structured-v1"

MAX_CANDIDATES_PER_MENTION = 5
MAX_SEMANTIC_CANDIDATES = 80

_VERSION_FIELDS = {
    "normalizer_version": NORMALIZER_VERSION,
    "candidate_policy_version": CANDIDATE_POLICY_VERSION,
    "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
    "prompt_version": PROMPT_VERSION,
    "adapter_version": ADAPTER_VERSION,
}
_SEMANTIC_MATCH_PRIORITY = {
    "canonical_id": 0,
    "direct_alias": 1,
    "group_alias": 2,
    "ambiguous_alias": 3,
    "trigram": 4,
}
_ENTITY_MATCH_PRIORITY = {
    "exact_identifier": 0,
    "exact_name": 1,
    "exact_alias": 2,
    "trigram": 3,
}


class ResolverInvariantError(RuntimeError):
    """A resolver input violates a fail-closed runtime invariant."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ActiveDatasetPin(ContractModel):
    dataset_version: Identifier
    manifest_hash: Sha256Hex


class ResolverViewSemanticCandidate(ContractModel):
    semantic_id: Identifier
    match_kind: str = Field(min_length=1)
    score: int = Field(ge=0, le=1_000_000)


class ResolverViewSemanticCandidateGroup(ContractModel):
    mention_id: Identifier
    items: tuple[ResolverViewSemanticCandidate, ...] = Field(
        max_length=MAX_CANDIDATES_PER_MENTION
    )


class ResolverViewConcept(ContractModel):
    concept_id: Identifier
    kind: str = Field(min_length=1)
    definition_ko: str = Field(min_length=1)
    value_kind: str = Field(min_length=1)
    allowed_product_families: tuple[Identifier, ...]
    allowed_ontology_types: tuple[Identifier, ...]
    required_qualifiers: tuple[Identifier, ...]
    allowed_operators: tuple[Identifier, ...]
    missingness_sensitive: bool
    normalization_rule: str = Field(min_length=1)


class ResolverViewRelationDefinition(ContractModel):
    relation_id: Identifier
    definition_ko: str = Field(min_length=1)
    subject_ontology_types: tuple[Identifier, ...]
    object_ontology_types: tuple[Identifier, ...]
    required_qualifiers: tuple[Identifier, ...]


class ResolverViewLiteralCandidate(ContractModel):
    literal_id: Identifier
    segment_id: Identifier
    kind: str = Field(min_length=1)
    original_text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    canonical_value: str = Field(min_length=1)
    currency: str | None = None


class ResolverViewEntityCandidate(ContractModel):
    entity_id: Identifier
    canonical_name: str = Field(min_length=1)
    ontology_type_ids: tuple[Identifier, ...] = Field(min_length=1)
    product_family: Identifier | None = None
    match_kind: str = Field(min_length=1)
    score: int = Field(ge=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_ontology_types(self) -> "ResolverViewEntityCandidate":
        if (
            self.ontology_type_ids != tuple(sorted(set(self.ontology_type_ids)))
            or not set(self.ontology_type_ids) <= APPROVED_RDF_TYPES
        ):
            raise ValueError("ontology type IDs must be unique, sorted, and approved")
        return self


class ResolverViewEntityCandidateGroup(ContractModel):
    mention_id: Identifier
    items: tuple[ResolverViewEntityCandidate, ...] = Field(
        max_length=MAX_ENTITY_CANDIDATES_PER_MENTION
    )


class ResolverView(ContractModel):
    build_manifest: ResolverBuildManifest
    active_dataset_pin: ActiveDatasetPin
    product_family_ids: tuple[Identifier, ...]
    action_ids: tuple[Identifier, ...]
    semantic_candidates: tuple[ResolverViewSemanticCandidateGroup, ...]
    concept_definitions: tuple[ResolverViewConcept, ...]
    relation_definitions: tuple[ResolverViewRelationDefinition, ...]
    literal_candidates: tuple[ResolverViewLiteralCandidate, ...]
    entity_candidates: tuple[ResolverViewEntityCandidateGroup, ...]

    @model_validator(mode="after")
    def validate_entity_candidate_bounds(self) -> "ResolverView":
        if (
            len(self.entity_candidates) > MAX_ENTITY_MENTIONS
            or sum(len(group.items) for group in self.entity_candidates)
            > MAX_ENTITY_CANDIDATES
        ):
            raise ValueError("RESOLVER_VIEW_LIMIT_EXCEEDED")
        return self


def build_manifest(
    snapshot: SemanticCatalogSnapshot, versions: Mapping[str, str]
) -> ResolverBuildManifest:
    """Build a provenance manifest from a compiled catalog and fixed code versions."""
    if (
        dict(versions) != _VERSION_FIELDS
        or tuple(sorted(snapshot.ontology_hashes))
        != tuple(sorted(GRAPH_CONTRACT_RELATIVE_PATHS))
    ):
        raise ResolverInvariantError("CATALOG_VERSION_MISMATCH")
    return ResolverBuildManifest(
        catalog_version=snapshot.catalog_version,
        catalog_hash=snapshot.catalog_hash,
        ontology_hashes=tuple(
            ContractFileHash(relative_path=path, sha256=digest)
            for path, digest in sorted(snapshot.ontology_hashes.items())
        ),
        overlay_version=snapshot.overlay_version,
        overlay_hash=snapshot.overlay_hash,
        **_VERSION_FIELDS,
    )


def build_resolver_view(
    context: RequestContext,
    normalized: NormalizedRequest,
    literals: Sequence[LiteralCandidate],
    semantic_candidates: SemanticCandidateSet,
    entity_candidates: Mapping[str, Sequence[EntityCandidate]],
    manifest: ResolverBuildManifest,
    active_dataset_pin: ActiveDatasetPin,
    catalog: SemanticCatalogSnapshot,
) -> ResolverView:
    """Build the model-safe projection of one dataset-pinned resolver request."""
    validate_resolver_pins(catalog, context, normalized, manifest, active_dataset_pin)
    selected_semantic = _select_semantic_candidates(semantic_candidates)
    semantic_ids = {item.semantic_id for items in selected_semantic.values() for item in items}
    return ResolverView(
        build_manifest=manifest,
        active_dataset_pin=active_dataset_pin,
        product_family_ids=tuple(sorted(item.value for item in ProductFamily)),
        action_ids=tuple(sorted(item.value for item in IntentType)),
        semantic_candidates=tuple(
            ResolverViewSemanticCandidateGroup(
                mention_id=mention_id,
                items=tuple(
                    ResolverViewSemanticCandidate(
                        semantic_id=item.semantic_id,
                        match_kind=item.match_kind,
                        score=item.score,
                    )
                    for item in sorted(items, key=lambda item: item.semantic_id)
                ),
            )
            for mention_id, items in sorted(selected_semantic.items())
        ),
        concept_definitions=tuple(
            _concept_projection(concept)
            for concept_id, concept in sorted(catalog.concepts_by_id.items())
            if concept_id in semantic_ids and concept.kind != "relation"
        ),
        relation_definitions=tuple(
            _relation_projection(concept)
            for concept_id, concept in sorted(catalog.concepts_by_id.items())
            if concept_id in semantic_ids and concept.kind == "relation"
        ),
        literal_candidates=tuple(
            _literal_projection(item)
            for item in sorted(literals, key=lambda item: item.literal_id)
        ),
        entity_candidates=_entity_candidate_groups(entity_candidates),
    )


def validate_resolver_pins(
    catalog: SemanticCatalogSnapshot,
    context: RequestContext,
    normalized: NormalizedRequest,
    manifest: ResolverBuildManifest,
    active_dataset_pin: ActiveDatasetPin,
) -> None:
    """Fail closed when runtime inputs do not share one resolver build pin."""
    catalog_hashes = tuple(
        ContractFileHash(relative_path=path, sha256=digest)
        for path, digest in sorted(catalog.ontology_hashes.items())
    )
    if (
        normalized.context != context
        or not active_dataset_pin.dataset_version
        or not active_dataset_pin.manifest_hash
        or active_dataset_pin.dataset_version != context.dataset_version
        or manifest.catalog_version != catalog.catalog_version
        or manifest.catalog_hash != catalog.catalog_hash
        or manifest.overlay_version != catalog.overlay_version
        or manifest.overlay_hash != catalog.overlay_hash
        or manifest.ontology_hashes != catalog_hashes
        or manifest.schema_version != RESOLVER_SCHEMA_VERSION
        or any(
            getattr(manifest, field_name) != expected
            for field_name, expected in _VERSION_FIELDS.items()
        )
    ):
        raise ResolverInvariantError("CATALOG_VERSION_MISMATCH")


def _select_semantic_candidates(
    candidates: SemanticCandidateSet,
) -> dict[str, tuple[SemanticCandidate, ...]]:
    exact_by_mention: dict[str, list[SemanticCandidate]] = {}
    fuzzy: list[SemanticCandidate] = []
    candidates_by_mention: dict[str, list[SemanticCandidate]] = {}
    for group in candidates.by_mention:
        candidates_by_mention.setdefault(group.mention.mention_id, []).extend(group.items)
    for mention_id, items in candidates_by_mention.items():
        best = _best_semantic_by_id(items)
        exact = [item for item in best if item.match_kind != "trigram"]
        if len(exact) > MAX_CANDIDATES_PER_MENTION:
            raise ResolverInvariantError("RESOLVER_VIEW_LIMIT_EXCEEDED")
        exact_by_mention[mention_id] = exact
        fuzzy.extend(item for item in best if item.match_kind == "trigram")

    exact_total = sum(len(items) for items in exact_by_mention.values())
    if exact_total > MAX_SEMANTIC_CANDIDATES:
        raise ResolverInvariantError("RESOLVER_VIEW_LIMIT_EXCEEDED")

    remaining_by_mention = {
        mention_id: MAX_CANDIDATES_PER_MENTION - len(items)
        for mention_id, items in exact_by_mention.items()
    }
    total = exact_total
    for item in sorted(
        fuzzy,
        key=lambda item: (-item.score, item.mention_id, item.semantic_id, item.source_id),
    ):
        if total == MAX_SEMANTIC_CANDIDATES or remaining_by_mention[item.mention_id] == 0:
            continue
        exact_by_mention[item.mention_id].append(item)
        remaining_by_mention[item.mention_id] -= 1
        total += 1
    return {key: tuple(value) for key, value in exact_by_mention.items() if value}


def _best_semantic_by_id(items: Sequence[SemanticCandidate]) -> list[SemanticCandidate]:
    selected: dict[str, SemanticCandidate] = {}
    for item in items:
        previous = selected.get(item.semantic_id)
        if previous is None or _semantic_key(item) < _semantic_key(previous):
            selected[item.semantic_id] = item
    return list(selected.values())


def _semantic_key(item: SemanticCandidate) -> tuple[int, int, str, str]:
    return (
        _SEMANTIC_MATCH_PRIORITY[item.match_kind],
        -item.score,
        item.semantic_id,
        item.source_id,
    )


def _concept_projection(concept: object) -> ResolverViewConcept:
    return ResolverViewConcept(
        concept_id=concept.id,
        kind=concept.kind,
        definition_ko=concept.definition_ko,
        value_kind=concept.value_kind,
        allowed_product_families=tuple(sorted(concept.allowed_product_families)),
        allowed_ontology_types=tuple(sorted(concept.allowed_ontology_types)),
        required_qualifiers=tuple(sorted(concept.required_qualifiers)),
        allowed_operators=tuple(sorted(concept.allowed_operators)),
        missingness_sensitive=concept.missingness_sensitive,
        normalization_rule=concept.normalization_rule,
    )


def _relation_projection(concept: object) -> ResolverViewRelationDefinition:
    return ResolverViewRelationDefinition(
        relation_id=concept.id,
        definition_ko=concept.definition_ko,
        subject_ontology_types=tuple(sorted(concept.subject_ontology_types)),
        object_ontology_types=tuple(sorted(concept.object_ontology_types)),
        required_qualifiers=tuple(sorted(concept.required_qualifiers)),
    )


def _literal_projection(item: LiteralCandidate) -> ResolverViewLiteralCandidate:
    return ResolverViewLiteralCandidate(
        literal_id=item.literal_id,
        segment_id=item.segment_id,
        kind=item.kind,
        original_text=item.original_text,
        start_char=item.start_char,
        end_char=item.end_char,
        canonical_value=item.canonical_value,
        currency=item.currency,
    )


def _entity_candidate_groups(
    candidates_by_mention: Mapping[str, Sequence[EntityCandidate]],
) -> tuple[ResolverViewEntityCandidateGroup, ...]:
    groups: list[ResolverViewEntityCandidateGroup] = []
    for mention_id, candidates in sorted(candidates_by_mention.items()):
        selected = _select_entity_candidates(candidates)
        if selected:
            groups.append(
                ResolverViewEntityCandidateGroup(
                    mention_id=mention_id,
                    items=tuple(
                        ResolverViewEntityCandidate(
                            entity_id=item.entity_id,
                            canonical_name=item.canonical_name,
                            ontology_type_ids=item.ontology_type_ids,
                            product_family=item.product_family,
                            match_kind=item.match_kind,
                            score=item.score,
                        )
                        for item in sorted(selected, key=lambda item: item.entity_id)
                    ),
                )
            )
    return tuple(groups)


def _select_entity_candidates(
    candidates: Sequence[EntityCandidate],
) -> tuple[EntityCandidate, ...]:
    selected: dict[str, EntityCandidate] = {}
    for item in candidates:
        previous = selected.get(item.entity_id)
        if previous is None or _entity_key(item) < _entity_key(previous):
            selected[item.entity_id] = item
    exact = [item for item in selected.values() if item.match_kind != "trigram"]
    if len(exact) > MAX_ENTITY_CANDIDATES_PER_MENTION:
        raise ResolverInvariantError("RESOLVER_VIEW_LIMIT_EXCEEDED")
    fuzzy = [item for item in selected.values() if item.match_kind == "trigram"]
    return tuple(
        sorted(exact, key=_entity_key)
        + sorted(fuzzy, key=_entity_key)[
            : MAX_ENTITY_CANDIDATES_PER_MENTION - len(exact)
        ]
    )


def _entity_key(item: EntityCandidate) -> tuple[int, int, str, str]:
    return (
        _ENTITY_MATCH_PRIORITY[item.match_kind],
        -item.score,
        item.entity_id,
        item.source_id,
    )
