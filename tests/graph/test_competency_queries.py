from __future__ import annotations

from datetime import date
from warnings import catch_warnings, simplefilter

import pytest
from rdflib import Dataset, Literal, RDF, URIRef

from financial_agent.graph.contract import (
    APPROVED_PREDICATES,
    EntityProjection,
    EvidenceProjection,
    FP,
    GraphProjectionBatch,
    RelationProjection,
    SourceProjection,
)
from financial_agent.graph.exporter import (
    build_graph_artifacts,
    entity_iri,
    evidence_iri,
    source_iri,
)
from financial_agent.graph.queries import build_relation_query


pytestmark = pytest.mark.filterwarnings(
    "ignore:Dataset\\.default_context is deprecated, use Dataset\\.default_graph instead\\.:DeprecationWarning:rdflib\\.graph"
)


VERSION = "2026-08-24/v1"
CUTOFF = date(2026, 8, 24)
RELATIONS = (
    ("managedBy", "product/manager", "organization/manager", "relation/managed"),
    ("issuedBy", "product/issuer", "organization/issuer", "relation/issued"),
    ("tracksIndex", "product/index", "index/benchmark", "relation/tracks"),
    ("holdsSecurity", "product/holding", "security/holding", "relation/holds"),
    ("hasShareClass", "product/fund", "product/share-class", "relation/share-class"),
)


def _exported_dataset() -> Dataset:
    entity_ids = {
        entity_id
        for _, subject_id, object_id, _ in RELATIONS
        for entity_id in (subject_id, object_id)
    }
    batch = GraphProjectionBatch(
        dataset_version=VERSION,
        cutoff_date=CUTOFF,
        entities=tuple(
            EntityProjection(VERSION, entity_id, ("FinancialProduct",))
            for entity_id in sorted(entity_ids)
        )
        + (EntityProjection(VERSION, "organization/publisher", ("Organization",)),),
        sources=tuple(
            SourceProjection(VERSION, f"source/{index}", "organization/publisher")
            for index in range(1, len(RELATIONS) + 1)
        ),
        evidences=tuple(
            EvidenceProjection(
                VERSION,
                f"evidence/{index}",
                f"source/{index}",
                CUTOFF,
                None,
                None,
                None,
                None,
                "eligible",
            )
            for index in range(1, len(RELATIONS) + 1)
        ),
        relations=tuple(
            RelationProjection(
                VERSION,
                relation_id,
                subject_id,
                predicate_id,
                object_id,
                None,
                None,
                (f"evidence/{index}",),
            )
            for index, (predicate_id, subject_id, object_id, relation_id) in enumerate(
                RELATIONS, start=1
            )
        ),
    )
    artifacts = build_graph_artifacts(batch)
    dataset = Dataset()
    with catch_warnings():
        simplefilter("ignore", DeprecationWarning)
        dataset.parse(data=artifacts.data_nquads, format="nquads")
        dataset.parse(data=artifacts.evidence_nquads, format="nquads")
    return dataset


@pytest.mark.parametrize("predicate_id, subject_id, object_id, relation_id", RELATIONS)
def test_relation_query_returns_the_direct_edge_and_its_evidence(
    predicate_id: str,
    subject_id: str,
    object_id: str,
    relation_id: str,
) -> None:
    """Catches a query that returns an unbound edge or omits its evidence."""
    result = _exported_dataset().query(build_relation_query(predicate_id, VERSION))

    assert [
        {name: str(value) for name, value in row.asdict().items()}
        for row in result
    ] == [
        {
            "subject_id": subject_id,
            "predicate_id": predicate_id,
            "object_id": object_id,
            "relation_assertion_id": relation_id,
            "evidence_id": f"evidence/{RELATIONS.index((predicate_id, subject_id, object_id, relation_id)) + 1}",
            "dataset_version": VERSION,
        }
    ]


def test_relation_query_leaves_missing_validity_bounds_unbound() -> None:
    """Catches fabricated validity values for a relation without interval facts."""
    result = _exported_dataset().query(build_relation_query("managedBy", VERSION))

    assert [str(variable) for variable in result.vars] == [
        "subject_id",
        "predicate_id",
        "object_id",
        "relation_assertion_id",
        "evidence_id",
        "dataset_version",
        "valid_from",
        "valid_to",
    ]
    assert {str(variable) for variable in result.bindings[0]} == {
        "subject_id",
        "predicate_id",
        "object_id",
        "relation_assertion_id",
        "evidence_id",
        "dataset_version",
    }


def test_relation_query_requires_the_requested_assertion_dataset_version() -> None:
    """Catches accepting a foreign-version assertion in the requested data graph."""
    dataset = _exported_dataset()
    data_graph = dataset.graph(URIRef("urn:data:financial-product:2026-08-24%2Fv1"))
    evidence_graph = dataset.graph(URIRef("urn:evidence:financial-product:2026-08-24%2Fv1"))
    assertion = URIRef("urn:foreign:assertion")
    evidence = URIRef("urn:foreign:evidence")
    subject = entity_iri("product/manager")
    object_ = entity_iri("organization/manager")
    data_graph.add((subject, FP.managedBy, object_))
    data_graph.add((assertion, RDF.type, FP.RelationAssertion))
    data_graph.add((assertion, FP.subject, subject))
    data_graph.add((assertion, FP.predicate, FP.managedBy))
    data_graph.add((assertion, FP.object, object_))
    data_graph.add((assertion, FP.relationId, Literal("relation/foreign")))
    data_graph.add((assertion, FP.datasetVersion, Literal("foreign-version")))
    evidence_graph.add((assertion, FP.supportedBy, evidence))
    evidence_graph.add((evidence, RDF.type, FP.EvidenceRecord))
    evidence_graph.add((evidence, FP.evidenceId, Literal("evidence/foreign")))

    result = dataset.query(build_relation_query("managedBy", VERSION))

    assert [str(row["relation_assertion_id"]) for row in result] == ["relation/managed"]


@pytest.mark.parametrize("remove_link", (True, False))
def test_relation_query_requires_a_resolvable_evidence_source(remove_link: bool) -> None:
    """Catches evidence that dangles or points to no usable SourceRecord."""
    dataset = _exported_dataset()
    evidence_graph = dataset.graph(URIRef("urn:evidence:financial-product:2026-08-24%2Fv1"))
    evidence = evidence_iri(VERSION, "evidence/1")
    source = source_iri(VERSION, "source/1")
    if remove_link:
        evidence_graph.remove((evidence, FP.sourceRecord, None))
    else:
        evidence_graph.remove((source, RDF.type, FP.SourceRecord))
        evidence_graph.remove((source, FP.sourceId, None))

    result = dataset.query(build_relation_query("managedBy", VERSION))

    assert list(result) == []


def test_relation_query_accepts_every_approved_predicate() -> None:
    """Catches drift between the competency-query allowlist and the ontology contract."""
    queries = {
        predicate: build_relation_query(predicate, VERSION)
        for predicate in APPROVED_PREDICATES
    }

    assert set(queries) == APPROVED_PREDICATES
    assert all(
        "GRAPH <urn:data:financial-product:2026-08-24%2Fv1>" in query
        for query in queries.values()
    )
    assert all(
        "GRAPH <urn:evidence:financial-product:2026-08-24%2Fv1>" in query
        for query in queries.values()
    )


def test_relation_query_rejects_a_predicate_outside_the_ontology_contract() -> None:
    """Catches accidental exposure of unsupported graph traversal predicates."""
    with pytest.raises(ValueError, match="unknown_predicate"):
        build_relation_query("publishedBy", VERSION)
