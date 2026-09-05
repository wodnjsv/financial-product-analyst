from __future__ import annotations

import json
from rdflib import Literal, URIRef

from financial_agent.graph.contract import (
    APPROVED_PREDICATES,
    FP,
    GraphProjectionBatch,
)
from financial_agent.graph.exporter import _encoded_segment, relation_iri


COMPETENCY_QUERY_IDS = (
    "managedBy",
    "issuedBy",
    "tracksIndex",
    "holdsSecurity",
    "hasShareClass",
)


def _versioned_graph_iris(dataset_version: str) -> tuple[URIRef, URIRef]:
    encoded_version = _encoded_segment(dataset_version)
    return (
        URIRef(f"urn:data:financial-product:{encoded_version}"),
        URIRef(f"urn:evidence:financial-product:{encoded_version}"),
    )


def build_relation_query(
    predicate_id: str,
    dataset_version: str,
    *,
    entity_ids: tuple[str, ...] | None = None,
    relation_ids: tuple[str, ...] | None = None,
) -> str:
    """Build the evidence-bound query for one approved relation predicate."""
    if predicate_id not in APPROVED_PREDICATES:
        raise ValueError(f"unknown_predicate: {predicate_id}")
    if entity_ids is not None and (
        not entity_ids
        or len(entity_ids) != len(set(entity_ids))
        or any(not value for value in entity_ids)
    ):
        raise ValueError("entity_ids must contain unique nonblank identifiers")
    if relation_ids is not None and (
        not relation_ids
        or len(relation_ids) != len(set(relation_ids))
        or any(not value for value in relation_ids)
    ):
        raise ValueError("relation_ids must contain unique nonblank identifiers")

    data_graph, evidence_graph = _versioned_graph_iris(dataset_version)
    predicate = FP[predicate_id]
    version = Literal(dataset_version).n3()
    scope_filter = ""
    if entity_ids is not None:
        scope_values = " ".join(Literal(value).n3() for value in entity_ids)
        scope_filter = (
            f"  VALUES ?scope_id {{ {scope_values} }}\n"
            "  FILTER (?subject_id = ?scope_id || ?object_id = ?scope_id)\n"
        )
    relation_filter = ""
    if relation_ids is not None:
        relation_values = " ".join(
            relation_iri(dataset_version, value).n3() for value in relation_ids
        )
        relation_filter = f"  VALUES ?assertion {{ {relation_values} }}\n"
    return f"""\
PREFIX fp: <{FP}>
SELECT ?subject_id ?predicate_id ?object_id ?relation_assertion_id ?evidence_id ?dataset_version ?valid_from ?valid_to
WHERE {{
{relation_filter}\
  GRAPH <{data_graph}> {{
    ?assertion a fp:RelationAssertion ;
      fp:subject ?subject ;
      fp:predicate <{predicate}> ;
      fp:object ?object ;
      fp:relationId ?relation_assertion_id ;
      fp:datasetVersion ?dataset_version .
    ?subject <{predicate}> ?object .
    ?subject fp:entityId ?subject_id .
    ?object fp:entityId ?object_id .
    OPTIONAL {{ ?assertion fp:validFrom ?valid_from . }}
    OPTIONAL {{ ?assertion fp:validTo ?valid_to . }}
  }}
  GRAPH <{evidence_graph}> {{
    ?assertion fp:supportedBy ?evidence .
    ?evidence a fp:EvidenceRecord ;
      fp:evidenceId ?evidence_id ;
      fp:sourceRecord ?source .
    ?source a fp:SourceRecord ; fp:sourceId ?source_id .
  }}
  FILTER (?dataset_version = {version})
{scope_filter}\
  BIND ({Literal(predicate_id).n3()} AS ?predicate_id)
}}
ORDER BY ?relation_assertion_id ?evidence_id
"""


def build_relation_count_query(predicate_id: str, dataset_version: str) -> str:
    if predicate_id not in APPROVED_PREDICATES:
        raise ValueError(f"unknown_predicate: {predicate_id}")
    data_graph, evidence_graph = _versioned_graph_iris(dataset_version)
    predicate = FP[predicate_id]
    version = Literal(dataset_version).n3()
    return f"""\
PREFIX fp: <{FP}>
SELECT (COUNT(*) AS ?binding_count)
WHERE {{
  GRAPH <{data_graph}> {{
    ?assertion a fp:RelationAssertion ;
      fp:predicate <{predicate}> ;
      fp:datasetVersion {version} .
  }}
  GRAPH <{evidence_graph}> {{
    ?assertion fp:supportedBy ?evidence .
    ?evidence a fp:EvidenceRecord ;
      fp:evidenceId ?evidence_id ;
      fp:sourceRecord ?source .
    ?source a fp:SourceRecord ; fp:sourceId ?source_id .
  }}
}}
"""


def build_expected_bindings(
    batch: GraphProjectionBatch,
    *,
    sample_limit_per_predicate: int = 25,
) -> bytes:
    if isinstance(sample_limit_per_predicate, bool) or sample_limit_per_predicate <= 0:
        raise ValueError("sample_limit_per_predicate must be positive")
    queries: dict[str, list[dict[str, str]]] = {
        predicate_id: [] for predicate_id in COMPETENCY_QUERY_IDS
    }
    binding_counts = {predicate_id: 0 for predicate_id in COMPETENCY_QUERY_IDS}
    for relation in batch.relations:
        if relation.predicate_id not in queries:
            continue
        binding_counts[relation.predicate_id] += len(relation.evidence_ids)
        if (
            len(queries[relation.predicate_id]) + len(relation.evidence_ids)
            > sample_limit_per_predicate
        ):
            continue
        for evidence_id in relation.evidence_ids:
            row = {
                "dataset_version": batch.dataset_version,
                "evidence_id": evidence_id,
                "object_id": relation.object_id,
                "predicate_id": relation.predicate_id,
                "relation_assertion_id": relation.relation_id,
                "subject_id": relation.subject_id,
            }
            if relation.valid_from is not None:
                row["valid_from"] = relation.valid_from.isoformat()
            if relation.valid_to is not None:
                row["valid_to"] = relation.valid_to.isoformat()
            queries[relation.predicate_id].append(row)
    for rows in queries.values():
        rows.sort(key=lambda row: tuple(sorted(row.items())))
    return json.dumps(
        {
            "binding_counts": binding_counts,
            "cutoff_date": batch.cutoff_date.isoformat(),
            "dataset_version": batch.dataset_version,
            "queries": queries,
            "schema_version": "2",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
