from __future__ import annotations

from rdflib import Literal, URIRef

from financial_agent.graph.contract import APPROVED_PREDICATES, FP
from financial_agent.graph.exporter import _encoded_segment


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
