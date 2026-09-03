from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from warnings import catch_warnings, filterwarnings

import pytest
from rdflib import Dataset, Literal, RDF, URIRef, XSD

from financial_agent.graph.contract import (
    FP,
    EntityProjection,
    EvidenceProjection,
    GraphProjectionBatch,
    RelationMetricProjection,
    RelationProjection,
    SourceProjection,
)
from financial_agent.graph.exporter import (
    GraphProjectionError,
    build_graph_artifacts,
    entity_iri,
    evidence_iri,
    holding_weight_observation_iri,
    relation_iri,
    source_iri,
)
from financial_agent.graph.validator import validate_graph


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHAPE_PATHS = (
    PROJECT_ROOT / "ontology" / "shapes" / "common.shacl.ttl",
    PROJECT_ROOT / "ontology" / "shapes" / "domain.shacl.ttl",
)
VERSION = "2026-08-24/v1"
CUTOFF = date(2026, 8, 24)
SEOUL = timezone(timedelta(hours=9))


def valid_batch() -> GraphProjectionBatch:
    metric = RelationMetricProjection(
        dataset_version=VERSION,
        observation_id="weight/2026-08-24",
        relation_id="relation/보유",
        metric_id="krx_etf_holding_weight_pct",
        numeric_value=Decimal("27.40"),
        unit="percentage_point",
        applicable_date=CUTOFF,
    )
    return GraphProjectionBatch(
        dataset_version=VERSION,
        cutoff_date=CUTOFF,
        entities=(
            EntityProjection(VERSION, "product/상품", ("ETF", "DomesticETF")),
            EntityProjection(VERSION, "security/1", ("Security",)),
            EntityProjection(VERSION, "publisher/1", ("Organization",)),
            EntityProjection(VERSION, "publisher/2", ("Organization",)),
        ),
        sources=(
            SourceProjection(VERSION, "source/1", "publisher/1"),
            SourceProjection(VERSION, "source/2", "publisher/2"),
        ),
        evidences=(
            EvidenceProjection(
                VERSION,
                "evidence/1",
                "source/1",
                CUTOFF,
                date(2026, 8, 1),
                CUTOFF,
                datetime(2026, 8, 24, 23, 59, 59, tzinfo=SEOUL),
                datetime(2026, 8, 24, 14, 59, 59, tzinfo=timezone.utc),
                "eligible",
            ),
            EvidenceProjection(
                VERSION,
                "evidence/2",
                "source/2",
                date(2026, 8, 23),
                None,
                None,
                None,
                None,
                "eligible",
            ),
        ),
        relations=(
            RelationProjection(
                dataset_version=VERSION,
                relation_id="relation/보유",
                subject_id="product/상품",
                predicate_id="holdsSecurity",
                object_id="security/1",
                valid_from=date(2026, 8, 1),
                valid_to=CUTOFF,
                evidence_ids=("evidence/1", "evidence/2"),
                metrics=(metric,),
            ),
        ),
    )


def _dataset(*payloads: bytes) -> Dataset:
    dataset = Dataset()
    with catch_warnings():
        for module in (r"rdflib\.graph", r"rdflib\.plugins\.parsers\.nquads"):
            filterwarnings(
                "ignore",
                message=(
                    r"Dataset\.default_context is deprecated, use "
                    r"Dataset\.default_graph instead\."
                ),
                category=DeprecationWarning,
                module=module,
            )
        for payload in payloads:
            dataset.parse(data=payload, format="nquads")
    return dataset


def test_export_emits_direct_edge_assertion_evidence_sources_and_metric() -> None:
    """Catches omission or misplacement of the auditable edge projection."""
    artifacts = build_graph_artifacts(valid_batch())
    dataset = _dataset(artifacts.data_nquads, artifacts.evidence_nquads)
    data_graph = dataset.graph(URIRef("urn:data:financial-product:2026-08-24%2Fv1"))
    evidence_graph = dataset.graph(
        URIRef("urn:evidence:financial-product:2026-08-24%2Fv1")
    )
    subject = entity_iri("product/상품")
    object_ = entity_iri("security/1")
    assertion = relation_iri(VERSION, "relation/보유")
    observation = holding_weight_observation_iri(VERSION, "weight/2026-08-24")
    evidence_nodes = {
        evidence_iri(VERSION, "evidence/1"),
        evidence_iri(VERSION, "evidence/2"),
    }

    assert (subject, FP.holdsSecurity, object_) in data_graph
    assert (assertion, RDF.type, FP.RelationAssertion) in data_graph
    assert (assertion, FP.subject, subject) in data_graph
    assert (assertion, FP.predicate, FP.holdsSecurity) in data_graph
    assert (assertion, FP.object, object_) in data_graph
    assert (assertion, FP.relationId, Literal("relation/보유")) in data_graph
    assert (assertion, FP.datasetVersion, Literal(VERSION)) in data_graph
    assert (assertion, FP.holdingWeightObservation, observation) in data_graph
    assert (observation, RDF.type, FP.HoldingWeightObservation) in data_graph
    assert (observation, FP.observationId, Literal("weight/2026-08-24")) in data_graph
    assert (
        observation,
        FP.holdingWeightPercentage,
        Literal(Decimal("27.40"), datatype=XSD.decimal),
    ) in data_graph
    assert (
        observation,
        FP.applicableDate,
        Literal(CUTOFF, datatype=XSD.date),
    ) in data_graph
    assert not list(data_graph.objects(assertion, FP.holdingWeightPercentage))
    assert set(evidence_graph.objects(assertion, FP.supportedBy)) == evidence_nodes
    for evidence_id, source_id in (("evidence/1", "source/1"), ("evidence/2", "source/2")):
        evidence = evidence_iri(VERSION, evidence_id)
        source = source_iri(VERSION, source_id)
        assert (evidence, RDF.type, FP.EvidenceRecord) in evidence_graph
        assert (evidence, FP.evidenceId, Literal(evidence_id)) in evidence_graph
        assert (evidence, FP.sourceRecord, source) in evidence_graph
        assert (source, RDF.type, FP.SourceRecord) in evidence_graph
        assert (source, FP.sourceId, Literal(source_id)) in evidence_graph

    assert (subject, FP.entityId, Literal("product/상품")) in data_graph
    assert (object_, FP.entityId, Literal("security/1")) in data_graph
    assert artifacts.entity_type_counts == {
        "DomesticETF": 1,
        "ETF": 1,
        "Organization": 2,
        "Security": 1,
    }
    assert artifacts.predicate_counts == {"holdsSecurity": 1}


def test_export_uses_only_the_two_exact_named_graphs_and_no_locators() -> None:
    """Catches graph-name drift or accidental disclosure of source location data."""
    artifacts = build_graph_artifacts(valid_batch())
    dataset = _dataset(artifacts.data_nquads, artifacts.evidence_nquads)

    assert {str(graph) for _, _, _, graph in dataset.quads((None, None, None, None))} == {
        "urn:data:financial-product:2026-08-24%2Fv1",
        "urn:evidence:financial-product:2026-08-24%2Fv1",
    }
    combined = artifacts.data_nquads + artifacts.evidence_nquads
    assert b"locator" not in combined.lower()
    assert b"raw_value" not in combined.lower()
    assert b"checksum" not in combined.lower()


def test_reversed_input_produces_byte_identical_sorted_lf_nquads() -> None:
    """Catches iteration-order leakage, duplicate lines, CRLFs, or missing final LF."""
    batch = valid_batch()
    reversed_relation = replace(
        batch.relations[0],
        evidence_ids=tuple(reversed(batch.relations[0].evidence_ids)),
        metrics=tuple(reversed(batch.relations[0].metrics)),
    )
    reversed_batch = replace(
        batch,
        entities=tuple(reversed(batch.entities)),
        sources=tuple(reversed(batch.sources)),
        evidences=tuple(reversed(batch.evidences)),
        relations=(reversed_relation,),
    )

    first = build_graph_artifacts(batch)
    second = build_graph_artifacts(reversed_batch)

    assert first == second
    for payload in (first.data_nquads, first.evidence_nquads):
        assert payload.endswith(b"\n")
        assert b"\r" not in payload
        lines = payload.decode("utf-8").splitlines()
        assert lines == sorted(set(lines))


def unknown_predicate(batch: GraphProjectionBatch) -> GraphProjectionBatch:
    return replace(
        batch,
        relations=(replace(batch.relations[0], predicate_id="unapprovedPredicate"),),
    )


def missing_subject(batch: GraphProjectionBatch) -> GraphProjectionBatch:
    return replace(
        batch,
        relations=(replace(batch.relations[0], subject_id="missing-subject"),),
    )


def missing_object(batch: GraphProjectionBatch) -> GraphProjectionBatch:
    return replace(
        batch,
        relations=(replace(batch.relations[0], object_id="missing-object"),),
    )


def missing_evidence(batch: GraphProjectionBatch) -> GraphProjectionBatch:
    return replace(
        batch,
        relations=(replace(batch.relations[0], evidence_ids=("missing-evidence",)),),
    )


def missing_source(batch: GraphProjectionBatch) -> GraphProjectionBatch:
    evidences = (replace(batch.evidences[0], source_id="missing-source"), *batch.evidences[1:])
    return replace(batch, evidences=evidences)


def mixed_version(batch: GraphProjectionBatch) -> GraphProjectionBatch:
    return replace(
        batch,
        entities=(
            replace(batch.entities[0], dataset_version="foreign-version"),
            *batch.entities[1:],
        ),
    )


def after_cutoff(batch: GraphProjectionBatch) -> GraphProjectionBatch:
    return replace(
        batch,
        evidences=(
            replace(batch.evidences[0], applicable_date=CUTOFF + timedelta(days=1)),
            *batch.evidences[1:],
        ),
    )


def reversed_dates(batch: GraphProjectionBatch) -> GraphProjectionBatch:
    return replace(
        batch,
        relations=(
            replace(
                batch.relations[0],
                valid_from=CUTOFF,
                valid_to=CUTOFF - timedelta(days=1),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (unknown_predicate, "unknown_predicate"),
        (missing_subject, "missing_entity"),
        (missing_object, "missing_entity"),
        (missing_evidence, "missing_evidence"),
        (missing_source, "missing_source"),
        (mixed_version, "dataset_version_mismatch"),
        (after_cutoff, "after_cutoff"),
        (reversed_dates, "invalid_date_order"),
    ],
)
def test_invalid_projection_fails_the_whole_build(mutation, code: str) -> None:
    """Catches partial export or silent omission of invalid authoritative records."""
    with pytest.raises(GraphProjectionError, match=code):
        build_graph_artifacts(mutation(valid_batch()))


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda batch: replace(
                batch,
                entities=(
                    replace(batch.entities[0], rdf_types=("UnknownClass",)),
                    *batch.entities[1:],
                ),
            ),
            "unknown_rdf_type",
        ),
        (
            lambda batch: replace(
                batch,
                evidences=(
                    replace(batch.evidences[0], cutoff_status="after_cutoff"),
                    *batch.evidences[1:],
                ),
            ),
            "ineligible_evidence",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(
                    replace(
                        batch.relations[0],
                        metrics=(
                            replace(
                                batch.relations[0].metrics[0],
                                metric_id="unknown_metric",
                            ),
                        ),
                    ),
                ),
            ),
            "unknown_metric",
        ),
    ],
)
def test_exporter_rejects_unapproved_typed_records(mutation, code: str) -> None:
    """Catches projection of vocabulary or Evidence outside the approved boundary."""
    with pytest.raises(GraphProjectionError, match=code):
        build_graph_artifacts(mutation(valid_batch()))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda batch: replace(
            batch,
            entities=(
                *batch.entities,
                replace(batch.entities[0], rdf_types=("FinancialProduct",)),
            ),
        ),
        lambda batch: replace(
            batch,
            sources=(
                *batch.sources,
                replace(batch.sources[0], publisher_id="publisher/2"),
            ),
        ),
        lambda batch: replace(
            batch,
            evidences=(
                *batch.evidences,
                replace(batch.evidences[0], source_id="source/2"),
            ),
        ),
        lambda batch: replace(
            batch,
            relations=(
                *batch.relations,
                replace(batch.relations[0], object_id="product/상품"),
            ),
        ),
    ],
    ids=["entity", "source", "evidence", "relation"],
)
def test_duplicate_projection_ids_fail_before_serialization(mutation) -> None:
    """Catches distinct records silently coalescing under one opaque IRI."""
    with pytest.raises(GraphProjectionError, match="duplicate_id"):
        build_graph_artifacts(mutation(valid_batch()))


def test_source_publisher_must_resolve_to_a_projected_entity() -> None:
    """Catches accepting an unresolved publisher identity at the Source boundary."""
    batch = valid_batch()
    batch = replace(
        batch,
        sources=(
            replace(batch.sources[0], publisher_id="publisher/missing"),
            *batch.sources[1:],
        ),
    )

    with pytest.raises(GraphProjectionError, match="missing_entity"):
        build_graph_artifacts(batch)


@pytest.mark.parametrize(
    "numeric_value",
    ["27.40", Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
    ids=["string", "nan", "positive-infinity", "negative-infinity"],
)
def test_relation_metric_requires_a_finite_decimal(numeric_value) -> None:
    """Catches RDF emission of non-decimal or non-finite relation weights."""
    batch = valid_batch()
    metric = replace(batch.relations[0].metrics[0], numeric_value=numeric_value)
    batch = replace(
        batch,
        relations=(replace(batch.relations[0], metrics=(metric,)),),
    )

    with pytest.raises(GraphProjectionError, match="invalid_metric_value"):
        build_graph_artifacts(batch)


@pytest.mark.parametrize("numeric_value", [Decimal("-0.01"), Decimal("100.01")])
def test_holding_weight_value_stays_within_percentage_point_bounds(
    numeric_value: Decimal,
) -> None:
    """Catches emitting an impossible percentage-point holding weight."""
    batch = valid_batch()
    metric = replace(batch.relations[0].metrics[0], numeric_value=numeric_value)
    batch = replace(batch, relations=(replace(batch.relations[0], metrics=(metric,)),))

    with pytest.raises(GraphProjectionError, match="invalid_metric_value"):
        build_graph_artifacts(batch)


@pytest.mark.parametrize("unit", [None, "percent", "ratio"])
def test_holding_weight_metric_requires_percentage_point_unit(unit: str | None) -> None:
    """Catches projecting a numerically valid weight with incompatible units."""
    batch = valid_batch()
    metric = replace(batch.relations[0].metrics[0], unit=unit)
    batch = replace(
        batch,
        relations=(replace(batch.relations[0], metrics=(metric,)),),
    )

    with pytest.raises(GraphProjectionError, match="invalid_metric_unit"):
        build_graph_artifacts(batch)


def test_holding_weight_requires_an_applicable_date() -> None:
    """Catches projection of a weight whose value cannot be paired with an as-of date."""
    batch = valid_batch()
    metric = replace(batch.relations[0].metrics[0], applicable_date=None)
    batch = replace(batch, relations=(replace(batch.relations[0], metrics=(metric,)),))

    with pytest.raises(GraphProjectionError, match="missing_metric_date"):
        build_graph_artifacts(batch)


def test_holding_weight_is_rejected_on_a_non_holding_relation() -> None:
    """Catches a valid numeric observation being attached to the wrong relation kind."""
    batch = valid_batch()
    batch = replace(
        batch,
        relations=(replace(batch.relations[0], predicate_id="issuedBy"),),
    )

    with pytest.raises(GraphProjectionError, match="invalid_metric_relation"):
        build_graph_artifacts(batch)


def test_holds_security_requires_at_least_one_weight_observation() -> None:
    """Catches a holdings edge that loses the weight observation required by Phase 1."""
    batch = valid_batch()
    batch = replace(batch, relations=(replace(batch.relations[0], metrics=()),))

    with pytest.raises(GraphProjectionError, match="missing_holding_weight"):
        build_graph_artifacts(batch)


def test_duplicate_holding_observation_ids_are_rejected() -> None:
    """Catches two source observations coalescing into one RDF observation node."""
    batch = valid_batch()
    duplicate = replace(
        batch.relations[0].metrics[0],
        numeric_value=Decimal("12.30"),
        applicable_date=date(2026, 8, 23),
    )
    batch = replace(
        batch,
        relations=(
            replace(
                batch.relations[0],
                metrics=(*batch.relations[0].metrics, duplicate),
            ),
        ),
    )

    with pytest.raises(GraphProjectionError, match="duplicate_id"):
        build_graph_artifacts(batch)


def test_multiple_holding_observations_keep_unambiguous_value_date_pairs() -> None:
    """Catches flattening multiple weights into independent relation-level value/date lists."""
    batch = valid_batch()
    second = replace(
        batch.relations[0].metrics[0],
        observation_id="weight/2026-08-23",
        numeric_value=Decimal("12.30"),
        applicable_date=date(2026, 8, 23),
    )
    batch = replace(
        batch,
        relations=(
            replace(
                batch.relations[0],
                metrics=(second, *batch.relations[0].metrics),
            ),
        ),
    )

    artifacts = build_graph_artifacts(batch)
    dataset = _dataset(artifacts.data_nquads)
    data_graph = dataset.graph(URIRef("urn:data:financial-product:2026-08-24%2Fv1"))
    assertion = relation_iri(VERSION, "relation/보유")
    observations = set(data_graph.objects(assertion, FP.holdingWeightObservation))

    assert observations == {
        holding_weight_observation_iri(VERSION, "weight/2026-08-23"),
        holding_weight_observation_iri(VERSION, "weight/2026-08-24"),
    }
    assert {
        (
            str(next(data_graph.objects(observation, FP.observationId))),
            str(next(data_graph.objects(observation, FP.holdingWeightPercentage))),
            str(next(data_graph.objects(observation, FP.applicableDate))),
        )
        for observation in observations
    } == {
        ("weight/2026-08-23", "12.30", "2026-08-23"),
        ("weight/2026-08-24", "27.40", "2026-08-24"),
    }


def test_holding_observations_reject_conflicting_values_on_the_same_date() -> None:
    """Catches two source observations claiming one relation/date with different weights."""
    batch = valid_batch()
    conflicting = replace(
        batch.relations[0].metrics[0],
        observation_id="weight/conflicting",
        numeric_value=Decimal("12.30"),
    )
    batch = replace(
        batch,
        relations=(
            replace(
                batch.relations[0],
                metrics=(*batch.relations[0].metrics, conflicting),
            ),
        ),
    )

    with pytest.raises(GraphProjectionError, match="ambiguous_metric_date"):
        build_graph_artifacts(batch)


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 8, 24, 23, 59, 59, 999999, tzinfo=SEOUL),
        datetime(2026, 8, 24, 14, 59, 59, 999999, tzinfo=timezone.utc),
        datetime(
            2026,
            8,
            24,
            15,
            59,
            59,
            999999,
            tzinfo=timezone(timedelta(hours=1)),
        ),
    ],
    ids=["seoul", "utc", "positive-one-offset"],
)
def test_cutoff_day_microseconds_before_seoul_midnight_are_eligible(
    timestamp: datetime,
) -> None:
    """Catches treating 23:59:59 as inclusive end instead of next midnight as exclusive."""
    batch = valid_batch()
    batch = replace(
        batch,
        evidences=(
            replace(
                batch.evidences[0],
                published_at=timestamp,
                available_at=timestamp,
            ),
            *batch.evidences[1:],
        ),
    )

    build_graph_artifacts(batch)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda batch: replace(
            batch,
            relations=(replace(batch.relations[0], valid_from=CUTOFF + timedelta(days=1)),),
        ),
        lambda batch: replace(
            batch,
            relations=(replace(batch.relations[0], valid_to=CUTOFF + timedelta(days=1)),),
        ),
        lambda batch: replace(
            batch,
            evidences=(
                replace(
                    batch.evidences[0],
                    valid_from=CUTOFF + timedelta(days=1),
                ),
                *batch.evidences[1:],
            ),
        ),
        lambda batch: replace(
            batch,
            evidences=(
                replace(
                    batch.evidences[0],
                    valid_to=CUTOFF + timedelta(days=1),
                ),
                *batch.evidences[1:],
            ),
        ),
        lambda batch: replace(
            batch,
            evidences=(
                replace(
                    batch.evidences[0],
                    published_at=datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc),
                ),
                *batch.evidences[1:],
            ),
        ),
        lambda batch: replace(
            batch,
            evidences=(
                replace(
                    batch.evidences[0],
                    available_at=datetime(2026, 8, 25, 0, 0, tzinfo=SEOUL),
                ),
                *batch.evidences[1:],
            ),
        ),
        lambda batch: replace(
            batch,
            relations=(
                replace(
                    batch.relations[0],
                    metrics=(
                        replace(
                            batch.relations[0].metrics[0],
                            applicable_date=CUTOFF + timedelta(days=1),
                        ),
                    ),
                ),
            ),
        ),
    ],
)
def test_every_temporal_field_rejects_values_after_the_seoul_cutoff(mutation) -> None:
    """Catches incomplete date coverage or UTC-date rather than Seoul-instant comparison."""
    with pytest.raises(GraphProjectionError, match="after_cutoff"):
        build_graph_artifacts(mutation(valid_batch()))


def test_naive_evidence_timestamp_is_rejected() -> None:
    """Catches accepting a timestamp whose cutoff instant cannot be determined."""
    batch = valid_batch()
    batch = replace(
        batch,
        evidences=(
            replace(batch.evidences[0], published_at=datetime(2026, 8, 24, 12, 0)),
            *batch.evidences[1:],
        ),
    )

    with pytest.raises(GraphProjectionError, match="invalid_datetime"):
        build_graph_artifacts(batch)


def test_exported_nquads_parse_and_conform_to_current_shacl(tmp_path: Path) -> None:
    """Catches syntactically valid-looking output that violates the current semantic gate."""
    artifacts = build_graph_artifacts(valid_batch())
    data_path = tmp_path / "data.nq"
    evidence_path = tmp_path / "evidence.nq"
    data_path.write_bytes(artifacts.data_nquads)
    evidence_path.write_bytes(artifacts.evidence_nquads)

    parsed = _dataset(artifacts.data_nquads, artifacts.evidence_nquads)
    result = validate_graph(
        data_paths=(data_path, evidence_path),
        shape_paths=SHAPE_PATHS,
        cutoff_date=CUTOFF,
    )

    assert sum(1 for _ in parsed.quads((None, None, None, None))) > 0
    assert result.conforms is True, result.report_text
    assert result.validated_data_hash == sha256(artifacts.data_nquads).hexdigest()
    assert result.validated_evidence_hash == sha256(artifacts.evidence_nquads).hexdigest()
    assert result.validated_cutoff_date == CUTOFF.isoformat()
    assert set(result.contract_hashes) == {
        "ontology/common.ttl",
        "ontology/bond_kr.ttl",
        "ontology/etf_kr.ttl",
        "ontology/etf_gl.ttl",
        "ontology/fund_pub.ttl",
        "ontology/shapes/common.shacl.ttl",
        "ontology/shapes/domain.shacl.ttl",
    }
