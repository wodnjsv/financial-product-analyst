from __future__ import annotations

import json
from rdflib import Literal, URIRef

from financial_agent.graph.contract import (
    APPROVED_PREDICATES,
    FP,
    GraphProjectionBatch,
)
from financial_agent.graph.exporter import _encoded_segment


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
    return f"""\
PREFIX fp: <{FP}>
SELECT ?subject_id ?predicate_id ?object_id ?relation_assertion_id ?evidence_id ?dataset_version ?valid_from ?valid_to
WHERE {{
  GRAPH <{data_graph}> {{
    ?subject <{predicate}> ?object .
    ?subject fp:entityId ?subject_id .
    ?object fp:entityId ?object_id .
    ?assertion a fp:RelationAssertion ;
      fp:subject ?subject ;
      fp:predicate <{predicate}> ;
      fp:object ?object ;
      fp:relationId ?relation_assertion_id ;
      fp:datasetVersion ?dataset_version .
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
"""


def build_expected_bindings(batch: GraphProjectionBatch) -> bytes:
    queries: dict[str, list[dict[str, str]]] = {
        predicate_id: [] for predicate_id in COMPETENCY_QUERY_IDS
    }
    for relation in batch.relations:
        if relation.predicate_id not in queries:
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
            "cutoff_date": batch.cutoff_date.isoformat(),
            "dataset_version": batch.dataset_version,
            "queries": queries,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
