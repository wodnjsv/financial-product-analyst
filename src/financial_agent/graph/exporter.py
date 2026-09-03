from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Iterable
from urllib.parse import quote
from zoneinfo import ZoneInfo

from rdflib import Literal, RDF, URIRef, XSD
from rdflib.term import Identifier

from financial_agent.graph.contract import (
    APPROVED_PREDICATES,
    APPROVED_RDF_TYPES,
    FP,
    RELATION_METRIC_PROPERTY_BY_ID,
    EvidenceProjection,
    GraphArtifacts,
    GraphProjectionBatch,
    RelationProjection,
)


Quad = tuple[Identifier, Identifier, Identifier, URIRef]
_SEOUL = ZoneInfo("Asia/Seoul")


class GraphProjectionError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _encoded_segment(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("invalid_identifier: identifiers must be non-empty and NUL-free")
    return quote(value, safe="")


def entity_iri(entity_id: str) -> URIRef:
    return URIRef(f"urn:financial-agent:entity:{_encoded_segment(entity_id)}")


def relation_iri(dataset_version: str, relation_id: str) -> URIRef:
    return URIRef(
        "urn:financial-agent:relation:"
        f"{_encoded_segment(dataset_version)}:{_encoded_segment(relation_id)}"
    )


def evidence_iri(dataset_version: str, evidence_id: str) -> URIRef:
    return URIRef(
        "urn:financial-agent:evidence:"
        f"{_encoded_segment(dataset_version)}:{_encoded_segment(evidence_id)}"
    )


def source_iri(dataset_version: str, source_id: str) -> URIRef:
    return URIRef(
        "urn:financial-agent:source:"
        f"{_encoded_segment(dataset_version)}:{_encoded_segment(source_id)}"
    )


def holding_weight_observation_iri(
    dataset_version: str,
    observation_id: str,
) -> URIRef:
    return URIRef(
        "urn:financial-agent:holding-weight:"
        f"{_encoded_segment(dataset_version)}:{_encoded_segment(observation_id)}"
    )


def _fail(code: str, detail: str) -> None:
    raise GraphProjectionError(code, detail)


def _validate_identifier(value: str, label: str) -> None:
    try:
        _encoded_segment(value)
    except ValueError as error:
        _fail("invalid_identifier", f"{label}: {error}")


def _validate_date(value: date | None, cutoff_date: date, label: str) -> None:
    if value is not None and value > cutoff_date:
        _fail("after_cutoff", f"{label} is after {cutoff_date.isoformat()}")


def _validate_datetime(
    value: datetime | None,
    cutoff_date: date,
    label: str,
) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() is None:
        _fail("invalid_datetime", f"{label} must include a timezone")
    cutoff_end = datetime.combine(cutoff_date + timedelta(days=1), time.min, _SEOUL)
    if value.astimezone(_SEOUL) >= cutoff_end:
        _fail("after_cutoff", f"{label} is after {cutoff_date.isoformat()} in Asia/Seoul")


def _validate_interval(
    valid_from: date | None,
    valid_to: date | None,
    label: str,
) -> None:
    if valid_from is not None and valid_to is not None and valid_from > valid_to:
        _fail("invalid_date_order", f"{label} valid_from is after valid_to")


def _validate_unique_ids(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            _fail("duplicate_id", f"{label}: {value}")
        seen.add(value)


def _validate_relation(
    relation: RelationProjection,
    *,
    batch: GraphProjectionBatch,
    entity_ids: frozenset[str],
    evidence_ids: frozenset[str],
) -> None:
    if relation.predicate_id not in APPROVED_PREDICATES:
        _fail("unknown_predicate", relation.predicate_id)
    if relation.subject_id not in entity_ids:
        _fail("missing_entity", relation.subject_id)
    if relation.object_id not in entity_ids:
        _fail("missing_entity", relation.object_id)
    if not relation.evidence_ids or not set(relation.evidence_ids) <= evidence_ids:
        _fail("missing_evidence", relation.relation_id)

    _validate_date(relation.valid_from, batch.cutoff_date, f"{relation.relation_id}.valid_from")
    _validate_date(relation.valid_to, batch.cutoff_date, f"{relation.relation_id}.valid_to")
    _validate_interval(relation.valid_from, relation.valid_to, relation.relation_id)

    if relation.predicate_id == "holdsSecurity" and not relation.metrics:
        _fail("missing_holding_weight", relation.relation_id)
    if relation.metrics and relation.predicate_id != "holdsSecurity":
        _fail("invalid_metric_relation", relation.relation_id)

    for evidence_id in relation.evidence_ids:
        _validate_identifier(evidence_id, "relation.evidence_id")
    metric_dates: set[date] = set()
    for metric in relation.metrics:
        if metric.relation_id != relation.relation_id:
            _fail("relation_metric_mismatch", metric.metric_id)
        if metric.metric_id not in RELATION_METRIC_PROPERTY_BY_ID:
            _fail("unknown_metric", metric.metric_id)
        if not isinstance(metric.numeric_value, Decimal) or not metric.numeric_value.is_finite():
            _fail("invalid_metric_value", metric.metric_id)
        if metric.numeric_value < Decimal("0") or metric.numeric_value > Decimal("100"):
            _fail("invalid_metric_value", metric.metric_id)
        if (
            RELATION_METRIC_PROPERTY_BY_ID[metric.metric_id]
            == "holdingWeightPercentage"
            and metric.unit != "percentage_point"
        ):
            _fail("invalid_metric_unit", metric.metric_id)
        _validate_identifier(metric.observation_id, "metric.observation_id")
        _validate_identifier(metric.metric_id, "metric.metric_id")
        if metric.applicable_date is None:
            _fail("missing_metric_date", metric.observation_id)
        if metric.applicable_date in metric_dates:
            _fail("ambiguous_metric_date", relation.relation_id)
        metric_dates.add(metric.applicable_date)
        _validate_date(
            metric.applicable_date,
            batch.cutoff_date,
            f"{metric.metric_id}.applicable_date",
        )


def _validate_batch(batch: GraphProjectionBatch) -> None:
    _validate_identifier(batch.dataset_version, "batch.dataset_version")
    records = (*batch.entities, *batch.sources, *batch.evidences, *batch.relations)
    metrics = tuple(metric for relation in batch.relations for metric in relation.metrics)
    for record in (*records, *metrics):
        if record.dataset_version != batch.dataset_version:
            _fail("dataset_version_mismatch", type(record).__name__)

    _validate_unique_ids((entity.entity_id for entity in batch.entities), "entity")
    _validate_unique_ids((source.source_id for source in batch.sources), "source")
    _validate_unique_ids(
        (evidence.evidence_id for evidence in batch.evidences),
        "evidence",
    )
    _validate_unique_ids(
        (relation.relation_id for relation in batch.relations),
        "relation",
    )
    _validate_unique_ids(
        (metric.observation_id for metric in metrics),
        "holding_weight_observation",
    )

    entity_ids = frozenset(entity.entity_id for entity in batch.entities)
    source_ids = frozenset(source.source_id for source in batch.sources)
    evidence_ids = frozenset(evidence.evidence_id for evidence in batch.evidences)

    for entity in batch.entities:
        _validate_identifier(entity.entity_id, "entity.entity_id")
        if not entity.rdf_types or not set(entity.rdf_types) <= APPROVED_RDF_TYPES:
            _fail("unknown_rdf_type", entity.entity_id)

    for source in batch.sources:
        _validate_identifier(source.source_id, "source.source_id")
        _validate_identifier(source.publisher_id, "source.publisher_id")
        if source.publisher_id not in entity_ids:
            _fail("missing_entity", source.publisher_id)

    for evidence in batch.evidences:
        _validate_identifier(evidence.evidence_id, "evidence.evidence_id")
        _validate_identifier(evidence.source_id, "evidence.source_id")
        if evidence.source_id not in source_ids:
            _fail("missing_source", evidence.source_id)
        if evidence.cutoff_status != "eligible":
            _fail("ineligible_evidence", evidence.evidence_id)
        _validate_date(
            evidence.applicable_date,
            batch.cutoff_date,
            f"{evidence.evidence_id}.applicable_date",
        )
        _validate_date(
            evidence.valid_from,
            batch.cutoff_date,
            f"{evidence.evidence_id}.valid_from",
        )
        _validate_date(
            evidence.valid_to,
            batch.cutoff_date,
            f"{evidence.evidence_id}.valid_to",
        )
        _validate_interval(evidence.valid_from, evidence.valid_to, evidence.evidence_id)
        _validate_datetime(
            evidence.published_at,
            batch.cutoff_date,
            f"{evidence.evidence_id}.published_at",
        )
        _validate_datetime(
            evidence.available_at,
            batch.cutoff_date,
            f"{evidence.evidence_id}.available_at",
        )

    for relation in batch.relations:
        _validate_identifier(relation.relation_id, "relation.relation_id")
        _validate_identifier(relation.subject_id, "relation.subject_id")
        _validate_identifier(relation.object_id, "relation.object_id")
        _validate_relation(
            relation,
            batch=batch,
            entity_ids=entity_ids,
            evidence_ids=evidence_ids,
        )


def _serialize_quads(quads: Iterable[Quad]) -> bytes:
    lines = sorted(
        {
            f"{subject.n3()} {predicate.n3()} {object_.n3()} {graph.n3()} ."
            for subject, predicate, object_, graph in quads
        }
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_graph_artifacts(batch: GraphProjectionBatch) -> GraphArtifacts:
    _validate_batch(batch)

    encoded_version = _encoded_segment(batch.dataset_version)
    data_graph = URIRef(f"urn:data:financial-product:{encoded_version}")
    evidence_graph = URIRef(f"urn:evidence:financial-product:{encoded_version}")
    data_quads: list[Quad] = []
    evidence_quads: list[Quad] = []

    for entity in batch.entities:
        node = entity_iri(entity.entity_id)
        data_quads.append((node, FP.entityId, Literal(entity.entity_id), data_graph))
        data_quads.extend((node, RDF.type, FP[type_id], data_graph) for type_id in entity.rdf_types)

    for source in batch.sources:
        node = source_iri(batch.dataset_version, source.source_id)
        evidence_quads.extend(
            (
                (node, RDF.type, FP.SourceRecord, evidence_graph),
                (node, FP.sourceId, Literal(source.source_id), evidence_graph),
            )
        )

    for evidence in batch.evidences:
        node = evidence_iri(batch.dataset_version, evidence.evidence_id)
        evidence_quads.extend(
            (
                (node, RDF.type, FP.EvidenceRecord, evidence_graph),
                (node, FP.evidenceId, Literal(evidence.evidence_id), evidence_graph),
                (
                    node,
                    FP.sourceRecord,
                    source_iri(batch.dataset_version, evidence.source_id),
                    evidence_graph,
                ),
            )
        )

    for relation in batch.relations:
        subject = entity_iri(relation.subject_id)
        object_ = entity_iri(relation.object_id)
        predicate = FP[relation.predicate_id]
        assertion = relation_iri(batch.dataset_version, relation.relation_id)
        data_quads.extend(
            (
                (subject, predicate, object_, data_graph),
                (assertion, RDF.type, FP.RelationAssertion, data_graph),
                (assertion, FP.subject, subject, data_graph),
                (assertion, FP.predicate, predicate, data_graph),
                (assertion, FP.object, object_, data_graph),
                (assertion, FP.relationId, Literal(relation.relation_id), data_graph),
                (assertion, FP.datasetVersion, Literal(batch.dataset_version), data_graph),
            )
        )
        if relation.valid_from is not None:
            data_quads.append(
                (
                    assertion,
                    FP.validFrom,
                    Literal(relation.valid_from, datatype=XSD.date),
                    data_graph,
                )
            )
        if relation.valid_to is not None:
            data_quads.append(
                (assertion, FP.validTo, Literal(relation.valid_to, datatype=XSD.date), data_graph)
            )
        for metric in relation.metrics:
            observation = holding_weight_observation_iri(
                batch.dataset_version,
                metric.observation_id,
            )
            data_quads.extend(
                (
                    (
                        assertion,
                        FP.holdingWeightObservation,
                        observation,
                        data_graph,
                    ),
                    (observation, RDF.type, FP.HoldingWeightObservation, data_graph),
                    (
                        observation,
                        FP.observationId,
                        Literal(metric.observation_id),
                        data_graph,
                    ),
                    (
                        observation,
                        FP[RELATION_METRIC_PROPERTY_BY_ID[metric.metric_id]],
                        Literal(metric.numeric_value, datatype=XSD.decimal),
                        data_graph,
                    ),
                    (
                        observation,
                        FP.applicableDate,
                        Literal(metric.applicable_date, datatype=XSD.date),
                        data_graph,
                    ),
                )
            )
        evidence_quads.extend(
            (
                assertion,
                FP.supportedBy,
                evidence_iri(batch.dataset_version, evidence_id),
                evidence_graph,
            )
            for evidence_id in relation.evidence_ids
        )

    entity_type_counts = Counter(
        type_id for entity in batch.entities for type_id in entity.rdf_types
    )
    predicate_counts = Counter(relation.predicate_id for relation in batch.relations)
    return GraphArtifacts(
        data_nquads=_serialize_quads(data_quads),
        evidence_nquads=_serialize_quads(evidence_quads),
        entity_type_counts=MappingProxyType(dict(sorted(entity_type_counts.items()))),
        predicate_counts=MappingProxyType(dict(sorted(predicate_counts.items()))),
    )
