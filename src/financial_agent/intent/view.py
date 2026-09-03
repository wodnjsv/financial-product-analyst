"""Pinned, bounded request projections for intent resolution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

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
from .axis_locks import ExactSemanticLock
from .catalog import SemanticCatalogSnapshot
from .compact_catalog import CompactSemanticCatalogV1, build_compact_semantic_catalog
from .evidence import EvidenceCandidate, build_evidence_candidates
from .literals import LiteralCandidate
from .mention_spans import MentionSpanSetV1, MentionSpanV1
from .normalization import NormalizedRequest
from .resolution import ContractFileHash, ResolverBuildManifest


NORMALIZER_VERSION = "intent-normalizer-v1"
CANDIDATE_POLICY_VERSION = "intent-candidate-v3"
RESOLVER_SCHEMA_VERSION = "2.0"
PROMPT_VERSION = "intent-resolver-ko-v5-axis-only"
ADAPTER_VERSION = "clova-chat-v3-proposal-v2"

HYBRID_RESOLVER_SCHEMA_VERSION = "3.0"
HYBRID_CANDIDATE_POLICY_VERSION = "intent-hints-v4"
HYBRID_PROMPT_VERSION = "intent-resolver-ko-v6-full-catalog"
HYBRID_ADAPTER_VERSION = "clova-chat-v3-proposal-v3"

MAX_CANDIDATES_PER_MENTION = 5
MAX_SEMANTIC_CANDIDATES = 80

_VERSION_FIELDS = {
    "normalizer_version": NORMALIZER_VERSION,
    "candidate_policy_version": CANDIDATE_POLICY_VERSION,
    "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
    "prompt_version": PROMPT_VERSION,
    "adapter_version": ADAPTER_VERSION,
}
_HYBRID_VERSION_FIELDS = {
    "normalizer_version": NORMALIZER_VERSION,
    "candidate_policy_version": HYBRID_CANDIDATE_POLICY_VERSION,
    "resolver_schema_version": HYBRID_RESOLVER_SCHEMA_VERSION,
    "prompt_version": HYBRID_PROMPT_VERSION,
    "adapter_version": HYBRID_ADAPTER_VERSION,
}
_HYBRID_OVERLAY_VERSION = "korean-nlu-overlay.v4"
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


class AxisDefinition(ContractModel):
    axis_kind: Literal["product_family", "action"]
    axis_id: Identifier
    preferred_label_ko: str = Field(min_length=1)
    definition_ko: str = Field(min_length=1)
    surface_forms: tuple[str, ...]


class ResolverViewReferenceCandidate(ContractModel):
    reference_id: Identifier
    segment_id: Identifier
    text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_coordinates(self) -> "ResolverViewReferenceCandidate":
        if self.end_char <= self.start_char:
            raise ValueError("reference end_char must be after start_char")
        return self


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
    allowed_product_families: tuple[Identifier, ...]
    subject_ontology_types: tuple[Identifier, ...]
    compatible_subject_ontology_types: tuple[Identifier, ...]
    object_ontology_types: tuple[Identifier, ...]
    required_qualifiers: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_relation_projection(self) -> "ResolverViewRelationDefinition":
        family_ids = {item.value for item in ProductFamily}
        if (
            not self.allowed_product_families
            or self.allowed_product_families
            != tuple(sorted(set(self.allowed_product_families)))
            or not set(self.allowed_product_families) <= family_ids
        ):
            raise ValueError("relation product families must be unique, sorted, and registered")
        for values in (
            self.subject_ontology_types,
            self.compatible_subject_ontology_types,
            self.object_ontology_types,
        ):
            if (
                not values
                or values != tuple(sorted(set(values)))
                or not set(values) <= APPROVED_RDF_TYPES
            ):
                raise ValueError("relation ontology types must be unique, sorted, and approved")
        if not set(self.subject_ontology_types) <= set(
            self.compatible_subject_ontology_types
        ):
            raise ValueError("relation compatible subjects must include its domain")
        return self


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
    entity_type_ids: tuple[Identifier, ...]
    semantic_candidates: tuple[ResolverViewSemanticCandidateGroup, ...]
    concept_definitions: tuple[ResolverViewConcept, ...]
    relation_definitions: tuple[ResolverViewRelationDefinition, ...]
    literal_candidates: tuple[ResolverViewLiteralCandidate, ...]
    entity_candidates: tuple[ResolverViewEntityCandidateGroup, ...]
    axis_definitions: tuple[AxisDefinition, ...]
    evidence_candidates: tuple[EvidenceCandidate, ...]
    reference_candidates: tuple[ResolverViewReferenceCandidate, ...]
    exact_semantic_locks: tuple[ExactSemanticLock, ...] = ()

    @model_validator(mode="after")
    def validate_entity_candidate_bounds(self) -> "ResolverView":
        if (
            not self.entity_type_ids
            or self.entity_type_ids != tuple(sorted(set(self.entity_type_ids)))
            or not set(self.entity_type_ids) <= APPROVED_RDF_TYPES
        ):
            raise ValueError("entity type IDs must be unique and sorted")
        if (
            len(self.entity_candidates) > MAX_ENTITY_MENTIONS
            or sum(len(group.items) for group in self.entity_candidates)
            > MAX_ENTITY_CANDIDATES
        ):
            raise ValueError("RESOLVER_VIEW_LIMIT_EXCEEDED")
        axis_pairs = tuple(
            (definition.axis_kind, definition.axis_id)
            for definition in self.axis_definitions
        )
        expected_axis_pairs = {
            ("product_family", item.value) for item in ProductFamily
        } | {("action", item.value) for item in IntentType}
        if (
            len(axis_pairs) != len(expected_axis_pairs)
            or set(axis_pairs) != expected_axis_pairs
        ):
            raise ValueError("axis definitions must exactly match runtime axes")
        return self


class ResolverViewExactLockProjection(ContractModel):
    """The minimal exact-lock evidence that V3 may show the model."""

    lock_id: Identifier
    mention_id: Identifier
    canonical_semantic_id: Identifier
    role: Literal["product_family", "field"]


class ResolverViewV3(ResolverView):
    """Shadow V3 view with full semantic selectability and bounded source spans."""

    mention_spans: MentionSpanSetV1
    compact_semantic_catalog: CompactSemanticCatalogV1
    entity_output_enabled: bool
    reference_output_enabled: bool
    exact_lock_projections: tuple[ResolverViewExactLockProjection, ...] = ()

    @model_validator(mode="after")
    def validate_exact_lock_projection_ranges(self) -> "ResolverViewV3":
        mention_ids = {item.mention_id for item in self.mention_spans.items}
        if any(
            projection.mention_id not in mention_ids
            for projection in self.exact_lock_projections
        ):
            raise ValueError("EXACT_LOCK_MENTION_MISSING")
        return self


def offered_entity_type_ids(view: ResolverView) -> tuple[str, ...]:
    """Return the exact ontology-type IDs exposed by this request view."""
    return view.entity_type_ids


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


def build_hybrid_manifest(
    snapshot: SemanticCatalogSnapshot, versions: Mapping[str, str]
) -> ResolverBuildManifest:
    """Build a V3-only manifest from the V4 model-facing overlay."""
    if (
        dict(versions) != _HYBRID_VERSION_FIELDS
        or snapshot.overlay_version != _HYBRID_OVERLAY_VERSION
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
        **_HYBRID_VERSION_FIELDS,
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
    exact_semantic_locks: Sequence[ExactSemanticLock] = (),
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
        entity_type_ids=tuple(sorted(catalog.entity_type_ids)),
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
            _relation_projection(concept, catalog)
            for concept_id, concept in sorted(catalog.concepts_by_id.items())
            if concept_id in semantic_ids and concept.kind == "relation"
        ),
        literal_candidates=tuple(
            _literal_projection(item)
            for item in sorted(literals, key=lambda item: item.literal_id)
        ),
        entity_candidates=_entity_candidate_groups(entity_candidates),
        axis_definitions=tuple(
            AxisDefinition(
                axis_kind=definition.axis_kind,
                axis_id=definition.axis_id,
                preferred_label_ko=definition.preferred_label_ko,
                definition_ko=definition.definition_ko,
                surface_forms=definition.surface_forms,
            )
            for definition in sorted(
                catalog.axis_definitions.values(),
                key=lambda definition: (definition.axis_kind, definition.axis_id),
            )
        ),
        evidence_candidates=build_evidence_candidates(
            normalized=normalized,
            literals=literals,
            semantic_candidates=semantic_candidates,
            entity_candidates=entity_candidates,
            policy_cues=catalog.policy_cues,
        ),
        reference_candidates=tuple(
            ResolverViewReferenceCandidate(
                reference_id=reference.reference_id,
                segment_id=reference.segment_id,
                text=reference.text,
                start_char=reference.start_char,
                end_char=reference.end_char,
            )
            for reference in normalized.reference_candidates
        ),
        exact_semantic_locks=tuple(exact_semantic_locks),
    )


def build_resolver_view_v3(
    context: RequestContext,
    normalized: NormalizedRequest,
    literals: Sequence[LiteralCandidate],
    semantic_candidates: SemanticCandidateSet,
    entity_candidates: Mapping[str, Sequence[EntityCandidate]],
    manifest: ResolverBuildManifest,
    active_dataset_pin: ActiveDatasetPin,
    catalog: SemanticCatalogSnapshot,
    mention_spans: MentionSpanSetV1,
    exact_semantic_locks: Sequence[ExactSemanticLock] = (),
) -> ResolverViewV3:
    """Build the non-default V3 view without narrowing its semantic catalog."""
    validate_hybrid_resolver_pins(
        catalog, context, normalized, manifest, active_dataset_pin
    )
    entity_output_enabled, reference_output_enabled = (
        _validated_hybrid_output_capabilities(context, normalized, mention_spans)
    )
    compact_catalog = build_compact_semantic_catalog(catalog)
    selected_semantic = _select_semantic_candidates(semantic_candidates)
    return ResolverViewV3(
        build_manifest=manifest,
        active_dataset_pin=active_dataset_pin,
        product_family_ids=tuple(sorted(item.value for item in ProductFamily)),
        action_ids=tuple(sorted(item.value for item in IntentType)),
        entity_type_ids=tuple(sorted(catalog.entity_type_ids)),
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
        concept_definitions=(),
        relation_definitions=(),
        literal_candidates=tuple(
            _literal_projection(item) for item in sorted(literals, key=lambda item: item.literal_id)
        ),
        entity_candidates=_entity_candidate_groups(entity_candidates),
        axis_definitions=tuple(
            AxisDefinition(
                axis_kind=definition.axis_kind,
                axis_id=definition.axis_id,
                preferred_label_ko=definition.preferred_label_ko,
                definition_ko=definition.definition_ko,
                surface_forms=definition.surface_forms,
            )
            for definition in sorted(
                catalog.axis_definitions.values(),
                key=lambda definition: (definition.axis_kind, definition.axis_id),
            )
        ),
        evidence_candidates=build_evidence_candidates(
            normalized=normalized,
            literals=literals,
            semantic_candidates=semantic_candidates,
            entity_candidates=entity_candidates,
            policy_cues=catalog.policy_cues,
        ),
        reference_candidates=tuple(
            ResolverViewReferenceCandidate(
                reference_id=reference.reference_id,
                segment_id=reference.segment_id,
                text=reference.text,
                start_char=reference.start_char,
                end_char=reference.end_char,
            )
            for reference in normalized.reference_candidates
        ),
        exact_semantic_locks=tuple(exact_semantic_locks),
        mention_spans=mention_spans,
        compact_semantic_catalog=compact_catalog,
        entity_output_enabled=entity_output_enabled,
        reference_output_enabled=reference_output_enabled,
        exact_lock_projections=_exact_lock_projections(
            exact_semantic_locks, mention_spans
        ),
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
        or manifest.schema_version != "1.0"
        or any(
            getattr(manifest, field_name) != expected
            for field_name, expected in _VERSION_FIELDS.items()
        )
    ):
        raise ResolverInvariantError("CATALOG_VERSION_MISMATCH")


def validate_hybrid_resolver_pins(
    catalog: SemanticCatalogSnapshot,
    context: RequestContext,
    normalized: NormalizedRequest,
    manifest: ResolverBuildManifest,
    active_dataset_pin: ActiveDatasetPin,
) -> None:
    """Fail closed when a V3 view is not pinned to the V4 catalog projection."""
    catalog_hashes = tuple(
        ContractFileHash(relative_path=path, sha256=digest)
        for path, digest in sorted(catalog.ontology_hashes.items())
    )
    if (
        normalized.context != context
        or not active_dataset_pin.dataset_version
        or not active_dataset_pin.manifest_hash
        or active_dataset_pin.dataset_version != context.dataset_version
        or catalog.overlay_version != _HYBRID_OVERLAY_VERSION
        or manifest.catalog_version != catalog.catalog_version
        or manifest.catalog_hash != catalog.catalog_hash
        or manifest.overlay_version != catalog.overlay_version
        or manifest.overlay_hash != catalog.overlay_hash
        or manifest.ontology_hashes != catalog_hashes
        or manifest.schema_version != "1.0"
        or any(
            getattr(manifest, field_name) != expected
            for field_name, expected in _HYBRID_VERSION_FIELDS.items()
        )
    ):
        raise ResolverInvariantError("CATALOG_VERSION_MISMATCH")


def _validated_hybrid_output_capabilities(
    context: RequestContext,
    normalized: NormalizedRequest,
    mention_spans: MentionSpanSetV1,
) -> tuple[bool, bool]:
    """Require V3 output tags to match the request's source-preserved evidence."""
    segments = {segment.segment_id: segment for segment in normalized.segments}
    expected_entity_spans: set[tuple[str, str, int, int, str, str]] = set()
    for entity in context.named_entities:
        segment = segments[entity.segment_id]
        starts = [
            start
            for start in range(len(segment.original_text) - len(entity.text) + 1)
            if entity.text and segment.original_text.startswith(entity.text, start)
        ]
        if len(starts) != 1:
            raise ResolverInvariantError("ENTITY_MENTION_RANGE_AMBIGUOUS")
        start = starts[0]
        expected_entity_spans.add(
            (
                f"mention-{entity.segment_id}-{start}-{start + len(entity.text)}",
                entity.segment_id,
                start,
                start + len(entity.text),
                entity.text,
                segment.normalized_text_for_original_span(
                    start, start + len(entity.text)
                ),
            )
        )
    expected_reference_spans = {
        (
            f"mention-{reference.segment_id}-{reference.start_char}-{reference.end_char}",
            reference.segment_id,
            reference.start_char,
            reference.end_char,
            reference.text,
            segments[reference.segment_id].normalized_text_for_original_span(
                reference.start_char, reference.end_char
            ),
        )
        for reference in normalized.reference_candidates
    }
    entity_spans = {
        _mention_span_identity(item)
        for item in mention_spans.items
        if "entity" in item.source_kinds
    }
    reference_spans = {
        _mention_span_identity(item)
        for item in mention_spans.items
        if "reference" in item.source_kinds
    }
    if (
        entity_spans != expected_entity_spans
        or reference_spans != expected_reference_spans
    ):
        raise ResolverInvariantError("MENTION_SPAN_PROVENANCE_MISMATCH")
    return bool(expected_entity_spans), bool(expected_reference_spans)


def _mention_span_identity(item: MentionSpanV1) -> tuple[str, str, int, int, str, str]:
    return (
        item.mention_id,
        item.segment_id,
        item.start_char,
        item.end_char,
        item.text,
        item.normalized_text,
    )


def validate_resolver_view_catalog(
    view: ResolverView, catalog: SemanticCatalogSnapshot
) -> None:
    """Require a restored view to retain the exact catalog type projection."""
    if view.entity_type_ids != tuple(sorted(catalog.entity_type_ids)):
        raise ResolverInvariantError("CATALOG_ENTITY_TYPE_MISMATCH")
    for relation in view.relation_definitions:
        concept = catalog.concepts_by_id.get(relation.relation_id)
        if concept is None or concept.kind != "relation":
            raise ResolverInvariantError("CATALOG_RELATION_MISMATCH")
        expected_compatible_subjects = _compatible_relation_subject_types(
            concept, catalog
        )
        if (
            relation.allowed_product_families
            != tuple(sorted(concept.allowed_product_families))
            or relation.subject_ontology_types
            != tuple(sorted(concept.subject_ontology_types))
            or relation.compatible_subject_ontology_types
            != expected_compatible_subjects
            or relation.object_ontology_types
            != tuple(sorted(concept.object_ontology_types))
        ):
            raise ResolverInvariantError("CATALOG_RELATION_MISMATCH")


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


def _exact_lock_projections(
    locks: Sequence[ExactSemanticLock], mention_spans: MentionSpanSetV1
) -> tuple[ResolverViewExactLockProjection, ...]:
    """Project only semantic exact locks whose evidence has an offered source span."""
    mention_ids = {item.mention_id for item in mention_spans.items}
    projections: list[ResolverViewExactLockProjection] = []
    for lock in sorted(locks, key=lambda item: item.lock_id):
        if lock.role not in {"product_family", "field"}:
            continue
        for mention_id in lock.evidence_span_ids:
            if mention_id not in mention_ids:
                raise ResolverInvariantError("EXACT_LOCK_MENTION_MISSING")
            projections.append(
                ResolverViewExactLockProjection(
                    lock_id=lock.lock_id,
                    mention_id=mention_id,
                    canonical_semantic_id=lock.canonical_id,
                    role=lock.role,
                )
            )
    return tuple(projections)


def model_safe_resolver_view_v3_payload(view: ResolverViewV3) -> dict[str, object]:
    """Serialize V3 without raw locks, preserving only their safe projections."""
    return view.model_dump(mode="json", exclude={"exact_semantic_locks"})


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


def _relation_projection(
    concept: object, catalog: SemanticCatalogSnapshot
) -> ResolverViewRelationDefinition:
    return ResolverViewRelationDefinition(
        relation_id=concept.id,
        definition_ko=concept.definition_ko,
        allowed_product_families=tuple(sorted(concept.allowed_product_families)),
        subject_ontology_types=tuple(sorted(concept.subject_ontology_types)),
        compatible_subject_ontology_types=_compatible_relation_subject_types(
            concept, catalog
        ),
        object_ontology_types=tuple(sorted(concept.object_ontology_types)),
        required_qualifiers=tuple(sorted(concept.required_qualifiers)),
    )


def _compatible_relation_subject_types(
    concept: object, catalog: SemanticCatalogSnapshot
) -> tuple[str, ...]:
    domain = set(concept.subject_ontology_types)
    return tuple(
        sorted(
            type_id
            for type_id in APPROVED_RDF_TYPES
            if type_id in domain
            or bool(set(catalog.class_ancestor_ids.get(type_id, ())) & domain)
        )
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
