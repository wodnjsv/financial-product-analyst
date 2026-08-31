"""Versioned semantic query concepts and Korean NLU aliases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from rdflib import Graph, Namespace, OWL, RDF, RDFS, URIRef

from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.graph.contract import (
    APPROVED_PREDICATES,
    FP,
    GRAPH_CONTRACT_RELATIVE_PATHS,
    SHACL_RELATIVE_PATHS,
    TBOX_RELATIVE_PATHS,
)


_CATALOG_PATH = Path("config/intent/semantic-query-catalog.v1.json")
_OVERLAY_PATH = Path("config/intent/korean-nlu-overlay.v1.json")
_CONCEPT_KINDS = Literal["attribute", "metric", "relation", "document_topic"]
_ALIAS_KINDS = Literal["direct", "ambiguous", "group"]
_SH = Namespace("http://www.w3.org/ns/shacl#")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SemanticConcept(_StrictModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    kind: _CONCEPT_KINDS
    definition_ko: str = Field(min_length=1)
    value_kind: str = Field(min_length=1)
    allowed_product_families: tuple[str, ...]
    allowed_ontology_types: tuple[str, ...]
    subject_ontology_types: tuple[str, ...] = ()
    object_ontology_types: tuple[str, ...] = ()
    required_qualifiers: tuple[str, ...]
    allowed_operators: tuple[str, ...]
    missingness_sensitive: bool
    normalization_rule: str = Field(min_length=1)
    authority_reference: str = Field(min_length=1)


class _CatalogPayload(_StrictModel):
    catalog_version: str = Field(min_length=1)
    product_family_ids: tuple[str, ...]
    action_ids: tuple[str, ...]
    entity_type_references: tuple[str, ...]
    concepts: tuple[SemanticConcept, ...]


class KoreanNluEntry(_StrictModel):
    semantic_id: str = Field(min_length=1)
    preferred_label: str = Field(min_length=1)
    aliases: tuple[str, ...]
    alias_kind: _ALIAS_KINDS
    negative_semantic_ids: tuple[str, ...]


class _OverlayPayload(_StrictModel):
    overlay_version: str = Field(min_length=1)
    entries: tuple[KoreanNluEntry, ...]


@dataclass(frozen=True, slots=True)
class SemanticCatalogSnapshot:
    catalog_version: str
    catalog_hash: str
    overlay_version: str
    overlay_hash: str
    product_family_ids: tuple[str, ...]
    action_ids: tuple[str, ...]
    entity_type_ids: tuple[str, ...]
    concepts_by_id: Mapping[str, SemanticConcept]
    alias_candidates: Mapping[str, tuple[str, ...]]
    alias_kinds: Mapping[str, str]
    ontology_hashes: Mapping[str, str]
    class_ancestor_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "concepts_by_id",
            "alias_candidates",
            "alias_kinds",
            "ontology_hashes",
            "class_ancestor_ids",
        ):
            value = getattr(self, field_name)
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(sorted(value.items()))),
            )


def load_catalog(project_root: Path) -> SemanticCatalogSnapshot:
    """Load only the production catalog, overlay, and graph-contract inputs."""
    root = project_root.resolve()
    return compile_catalog(
        (root / _CATALOG_PATH).read_bytes(),
        (root / _OVERLAY_PATH).read_bytes(),
        ontology_paths=tuple(root / path for path in TBOX_RELATIVE_PATHS),
        shacl_paths=tuple(root / path for path in SHACL_RELATIVE_PATHS),
    )


def compile_catalog(
    catalog_payload: bytes,
    overlay_payload: bytes,
    *,
    ontology_paths: tuple[Path, ...],
    shacl_paths: tuple[Path, ...],
) -> SemanticCatalogSnapshot:
    """Strictly compile catalog inputs against the frozen runtime and graph contracts."""
    try:
        catalog = _CatalogPayload.model_validate_json(catalog_payload)
        overlay = _OverlayPayload.model_validate_json(overlay_payload)
    except ValidationError as error:
        raise ValueError("invalid semantic catalog payload") from error

    _validate_runtime_axes(catalog)
    concepts_by_id = _index_concepts(catalog.concepts)
    ontology_hashes = _contract_hashes(ontology_paths, shacl_paths)
    tbox_graph = _parse_graph(ontology_paths)
    ontology_types = _tbox_classes(tbox_graph)
    _validate_ontology_references(catalog, concepts_by_id, ontology_types)
    _validate_relations(concepts_by_id, tbox_graph, shacl_paths)
    alias_candidates, alias_kinds = _index_overlay(
        overlay.entries,
        allowed_semantic_ids=(
            set(concepts_by_id)
            | set(catalog.product_family_ids)
            | set(catalog.action_ids)
            | set(catalog.entity_type_references)
        ),
    )
    return SemanticCatalogSnapshot(
        catalog_version=catalog.catalog_version,
        catalog_hash=_canonical_hash(_canonical_catalog_payload(catalog)),
        overlay_version=overlay.overlay_version,
        overlay_hash=_canonical_hash(_canonical_overlay_payload(overlay)),
        product_family_ids=tuple(sorted(catalog.product_family_ids)),
        action_ids=tuple(sorted(catalog.action_ids)),
        entity_type_ids=tuple(sorted(catalog.entity_type_references)),
        concepts_by_id=concepts_by_id,
        alias_candidates=alias_candidates,
        alias_kinds=alias_kinds,
        ontology_hashes=ontology_hashes,
        class_ancestor_ids=_class_ancestor_ids(tbox_graph),
    )


def _validate_runtime_axes(catalog: _CatalogPayload) -> None:
    expected_families = {item.value for item in ProductFamily}
    expected_actions = {item.value for item in IntentType}
    if set(catalog.product_family_ids) != expected_families or len(catalog.product_family_ids) != len(expected_families):
        raise ValueError("product family IDs must exactly match ProductFamily")
    if set(catalog.action_ids) != expected_actions or len(catalog.action_ids) != len(expected_actions):
        raise ValueError("action IDs must exactly match IntentType")


def _index_concepts(concepts: tuple[SemanticConcept, ...]) -> Mapping[str, SemanticConcept]:
    indexed = {concept.id: concept for concept in concepts}
    if len(indexed) != len(concepts):
        raise ValueError("concept IDs must be unique")
    for concept in concepts:
        if len(set(concept.allowed_product_families)) != len(concept.allowed_product_families):
            raise ValueError(f"duplicate product family in concept: {concept.id}")
        if not set(concept.allowed_product_families) <= {item.value for item in ProductFamily}:
            raise ValueError(f"unknown product family in concept: {concept.id}")
        if not concept.allowed_product_families:
            raise ValueError(f"concept requires an allowed product family: {concept.id}")
        if len(set(concept.allowed_ontology_types)) != len(concept.allowed_ontology_types):
            raise ValueError(f"duplicate ontology type in concept: {concept.id}")
        if not concept.allowed_ontology_types:
            raise ValueError(f"concept requires an allowed ontology type: {concept.id}")
    return MappingProxyType(dict(sorted(indexed.items())))


def _contract_hashes(
    ontology_paths: tuple[Path, ...], shacl_paths: tuple[Path, ...]
) -> Mapping[str, str]:
    resolved: dict[str, Path] = {}
    for paths, expected_paths in (
        (ontology_paths, TBOX_RELATIVE_PATHS),
        (shacl_paths, SHACL_RELATIVE_PATHS),
    ):
        actual = {_contract_relative_path(path): path for path in paths}
        if set(actual) != set(expected_paths):
            raise ValueError("ontology contract path set mismatch")
        if len(actual) != len(paths):
            raise ValueError("duplicate ontology contract path")
        resolved.update(actual)
    if tuple(sorted(resolved)) != tuple(sorted(GRAPH_CONTRACT_RELATIVE_PATHS)):
        raise ValueError("graph contract paths must exactly match")
    return MappingProxyType(
        {
            relative_path: hashlib.sha256(path.read_bytes()).hexdigest()
            for relative_path, path in sorted(resolved.items())
        }
    )


def _contract_relative_path(path: Path) -> str:
    resolved = path.resolve()
    for relative_path in GRAPH_CONTRACT_RELATIVE_PATHS:
        relative_parts = Path(relative_path).parts
        if resolved.parts[-len(relative_parts) :] == relative_parts:
            return relative_path
    raise ValueError("ontology path is outside the graph contract")


def _tbox_classes(graph: Graph) -> set[str]:
    return {
        str(subject).removeprefix(str(FP))
        for subject in graph.subjects(RDF.type, OWL.Class)
        if str(subject).startswith(str(FP))
    }


def _class_ancestor_ids(graph: Graph) -> Mapping[str, tuple[str, ...]]:
    """Return pinned transitive TBox ancestry without request-time graph work."""
    class_ids = _tbox_classes(graph)
    direct_parents = {
        class_id: {
            _class_id(parent)
            for parent in graph.objects(FP[class_id], RDFS.subClassOf)
            if str(parent).startswith(str(FP))
        }
        for class_id in class_ids
    }
    closure: dict[str, tuple[str, ...]] = {}
    for class_id in class_ids:
        ancestors: set[str] = set()
        pending = list(direct_parents[class_id])
        while pending:
            parent = pending.pop()
            if parent in ancestors:
                continue
            ancestors.add(parent)
            pending.extend(direct_parents.get(parent, ()))
        closure[class_id] = tuple(sorted(ancestors))
    return MappingProxyType(dict(sorted(closure.items())))


def _validate_ontology_references(
    catalog: _CatalogPayload,
    concepts_by_id: Mapping[str, SemanticConcept],
    ontology_types: set[str],
) -> None:
    if len(set(catalog.entity_type_references)) != len(catalog.entity_type_references):
        raise ValueError("entity type references must be unique")
    if not set(catalog.entity_type_references) <= ontology_types:
        raise ValueError("catalog entity type does not exist in the TBox")
    for concept in concepts_by_id.values():
        if not set(concept.allowed_ontology_types) <= set(catalog.entity_type_references):
            raise ValueError(f"concept type reference is not cataloged: {concept.id}")


def _validate_relations(
    concepts_by_id: Mapping[str, SemanticConcept],
    tbox_graph: Graph,
    shacl_paths: tuple[Path, ...],
) -> None:
    relation_ids = {
        concept.id for concept in concepts_by_id.values() if concept.kind == "relation"
    }
    if relation_ids != APPROVED_PREDICATES:
        raise ValueError("relation concepts must exactly match approved predicates")
    if not all(
        (FP[relation_id], RDF.type, OWL.ObjectProperty) in tbox_graph
        for relation_id in relation_ids
    ):
        raise ValueError("relation concept is not an approved TBox predicate")
    shacl_constraints = _shacl_relation_constraints(_parse_graph(shacl_paths), relation_ids)
    for relation_id in relation_ids:
        concept = concepts_by_id[relation_id]
        if concept.authority_reference != f"ontology:predicate:{relation_id}":
            raise ValueError("relation authority reference does not match TBox predicate")
        tbox_subject_types = _property_classes(tbox_graph, relation_id, RDFS.domain)
        tbox_object_types = _property_classes(tbox_graph, relation_id, RDFS.range)
        shacl_subject_types, shacl_object_types = shacl_constraints[relation_id]
        if (tbox_subject_types, tbox_object_types) != (
            shacl_subject_types,
            shacl_object_types,
        ):
            raise ValueError("relation SHACL endpoint constraints must match the TBox")
        if set(concept.allowed_ontology_types) != (
            tbox_subject_types | tbox_object_types
        ):
            raise ValueError("relation ontology types must exactly match TBox endpoints")
        if set(concept.subject_ontology_types) != tbox_subject_types:
            raise ValueError("relation subject ontology types must match TBox endpoints")
        if set(concept.object_ontology_types) != tbox_object_types:
            raise ValueError("relation object ontology types must match TBox endpoints")


def _parse_graph(paths: tuple[Path, ...]) -> Graph:
    graph = Graph()
    for path in paths:
        graph.parse(path, format="turtle")
    return graph


def _property_classes(graph: Graph, property_id: str, predicate: URIRef) -> set[str]:
    node = graph.value(FP[property_id], predicate)
    if node is None:
        raise ValueError("relation endpoint constraint is missing from the TBox")
    if graph.value(node, OWL.unionOf) is not None:
        classes = {_class_id(item) for item in graph.items(graph.value(node, OWL.unionOf))}
    else:
        classes = {_class_id(node)}
    if not classes:
        raise ValueError("relation endpoint constraint is empty")
    return classes


def _shacl_relation_constraints(
    graph: Graph, relation_ids: set[str]
) -> Mapping[str, tuple[set[str], set[str]]]:
    constraints: dict[str, tuple[set[str], set[str]]] = {}
    for relation_id in relation_ids:
        matching_shapes = [
            shape
            for shape in graph.subjects(RDF.type, _SH.NodeShape)
            if any(
                str(FP[relation_id]) in str(graph.value(target, _SH.select))
                for target in graph.objects(shape, _SH.target)
            )
        ]
        if len(matching_shapes) != 1:
            raise ValueError("relation must have one SHACL endpoint constraint shape")
        subject_types, object_types = _shacl_shape_endpoint_types(graph, matching_shapes[0])
        constraints[relation_id] = (subject_types, object_types)
    return MappingProxyType(dict(sorted(constraints.items())))


def _shacl_shape_endpoint_types(graph: Graph, shape: object) -> tuple[set[str], set[str]]:
    endpoints: dict[URIRef, set[str]] = {}
    for property_shape in graph.objects(shape, _SH.property):
        path = graph.value(property_shape, _SH.path)
        if path not in {FP.subject, FP.object}:
            continue
        endpoints[path] = _shacl_property_classes(graph, property_shape)
    if set(endpoints) != {FP.subject, FP.object}:
        raise ValueError("relation SHACL shape must constrain subject and object")
    return endpoints[FP.subject], endpoints[FP.object]


def _shacl_property_classes(graph: Graph, property_shape: object) -> set[str]:
    direct = graph.value(property_shape, _SH["class"])
    if direct is not None:
        return {_class_id(direct)}
    alternatives = graph.value(property_shape, _SH["or"])
    if alternatives is None:
        raise ValueError("relation SHACL endpoint has no class constraint")
    classes = {
        _class_id(class_node)
        for alternative in graph.items(alternatives)
        if (class_node := graph.value(alternative, _SH["class"])) is not None
    }
    if not classes:
        raise ValueError("relation SHACL endpoint has no class alternatives")
    return classes


def _class_id(node: object) -> str:
    value = str(node)
    if not value.startswith(str(FP)):
        raise ValueError("relation endpoint must reference a financial ontology class")
    return value.removeprefix(str(FP))


def _index_overlay(
    entries: tuple[KoreanNluEntry, ...], *, allowed_semantic_ids: set[str]
) -> tuple[Mapping[str, tuple[str, ...]], Mapping[str, str]]:
    semantic_ids = [entry.semantic_id for entry in entries]
    if len(set(semantic_ids)) != len(semantic_ids):
        raise ValueError("overlay semantic IDs must be unique")
    if not set(semantic_ids) <= allowed_semantic_ids:
        raise ValueError("overlay semantic ID is not cataloged")
    preferred_labels = [entry.preferred_label for entry in entries]
    if len(set(preferred_labels)) != len(preferred_labels):
        raise ValueError("overlay preferred labels must be unique")
    labels: dict[str, set[str]] = {}
    kinds: dict[str, set[str]] = {}
    for entry in entries:
        if not set(entry.negative_semantic_ids) <= allowed_semantic_ids:
            raise ValueError("overlay negative semantic ID is not cataloged")
        if entry.semantic_id in entry.negative_semantic_ids:
            raise ValueError("overlay entry cannot negate itself")
        for label in entry.aliases:
            labels.setdefault(label, set()).add(entry.semantic_id)
            kinds.setdefault(label, set()).add(entry.alias_kind)
    candidates: dict[str, tuple[str, ...]] = {}
    alias_kinds: dict[str, str] = {}
    for label, semantic_id_set in labels.items():
        label_kinds = kinds[label]
        if len(label_kinds) != 1:
            raise ValueError("alias kinds must agree for a shared alias")
        alias_kind = next(iter(label_kinds))
        if alias_kind == "direct" and len(semantic_id_set) != 1:
            raise ValueError("direct alias must have exactly one semantic ID")
        if alias_kind == "ambiguous" and len(semantic_id_set) < 2:
            raise ValueError("ambiguous alias must have at least two semantic IDs")
        candidates[label] = tuple(sorted(semantic_id_set))
        alias_kinds[label] = alias_kind
    return MappingProxyType(dict(sorted(candidates.items()))), MappingProxyType(
        dict(sorted(alias_kinds.items()))
    )


def _canonical_catalog_payload(catalog: _CatalogPayload) -> dict[str, object]:
    return {
        "catalog_version": catalog.catalog_version,
        "product_family_ids": sorted(catalog.product_family_ids),
        "action_ids": sorted(catalog.action_ids),
        "entity_type_references": sorted(catalog.entity_type_references),
        "concepts": [
            {
                **concept.model_dump(mode="json"),
                "allowed_product_families": sorted(concept.allowed_product_families),
                "allowed_ontology_types": sorted(concept.allowed_ontology_types),
                "subject_ontology_types": sorted(concept.subject_ontology_types),
                "object_ontology_types": sorted(concept.object_ontology_types),
                "required_qualifiers": sorted(concept.required_qualifiers),
                "allowed_operators": sorted(concept.allowed_operators),
            }
            for concept in sorted(catalog.concepts, key=lambda item: item.id)
        ],
    }


def _canonical_overlay_payload(overlay: _OverlayPayload) -> dict[str, object]:
    return {
        "overlay_version": overlay.overlay_version,
        "entries": [
            {
                **entry.model_dump(mode="json"),
                "aliases": sorted(entry.aliases),
                "negative_semantic_ids": sorted(entry.negative_semantic_ids),
            }
            for entry in sorted(
                overlay.entries,
                key=lambda item: (item.semantic_id, item.preferred_label),
            )
        ],
    }


def _canonical_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
