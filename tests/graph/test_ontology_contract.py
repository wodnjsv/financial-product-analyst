from __future__ import annotations

import json
from pathlib import Path

from rdflib import Graph, OWL, RDF, RDFS, URIRef, XSD

from financial_agent.graph.contract import APPROVED_PREDICATES, FP, ONTOLOGY_IRI


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TBOX_PATHS = tuple(
    PROJECT_ROOT / "ontology" / name
    for name in ("common.ttl", "bond_kr.ttl", "etf_kr.ttl", "etf_gl.ttl", "fund_pub.ttl")
)
EXPECTED_PROPERTY_TYPES = {
    "managedBy": ("FinancialProduct", "AssetManager"),
    "issuedBy": (("FinancialProduct", "Security"), "Issuer"),
    "tracksIndex": (("ETF", "PublicFund"), "Index"),
    "holdsSecurity": (("ETF", "PublicFund"), "Security"),
    "containsSecurity": ("Index", "Security"),
    "securityOfCompany": ("EquitySecurity", "Company"),
    "controlsCompany": ("Company", "Company"),
    "listedOn": ("Security", "Market"),
    "classifiedAsIndustry": (("Company", "Security"), "Industry"),
    "associatedWithTheme": (("FinancialProduct", "Index", "Company"), "Theme"),
    "hasShareClass": ("RepresentativeFund", "FundShareClass"),
    "documentedBy": (("FinancialProduct", "Organization", "PolicyProgram"), "OfficialDocument"),
    "hasRiskFactor": ("FinancialProduct", "RiskFactor"),
}


def question_predicates() -> frozenset[str]:
    catalog = json.loads(
        (PROJECT_ROOT / "tests/gold/core_questions.json").read_text("utf-8")
    )
    return frozenset(
        relation["predicate"]
        for case in catalog["cases"]
        for relation in case["requirements"]["relations"]
    )


def _tbox() -> Graph:
    graph = Graph()
    for path in TBOX_PATHS:
        graph.parse(path, format="turtle")
    return graph


def _classes_in_union(graph: Graph, node: URIRef) -> frozenset[str]:
    members = graph.value(node, OWL.unionOf)
    if members is None:
        return frozenset()
    return frozenset(str(item).removeprefix(f"{ONTOLOGY_IRI}#") for item in graph.items(members))


def _property_classes(graph: Graph, property_id: str, predicate: URIRef) -> frozenset[str]:
    node = graph.value(FP[property_id], predicate)
    assert node is not None
    if node == FP[property_id]:
        return frozenset({property_id})
    if graph.value(node, OWL.unionOf) is not None:
        return _classes_in_union(graph, node)
    return frozenset({str(node).removeprefix(f"{ONTOLOGY_IRI}#")})


def test_tbox_parses_and_matches_question_predicates() -> None:
    graph = _tbox()
    domain_properties = frozenset(
        str(subject).removeprefix(f"{ONTOLOGY_IRI}#")
        for subject in graph.subjects(RDF.type, FP.DomainPredicate)
        if str(subject).startswith(f"{ONTOLOGY_IRI}#")
    )

    assert domain_properties == APPROVED_PREDICATES
    assert question_predicates() <= APPROVED_PREDICATES
    assert APPROVED_PREDICATES - question_predicates() == {"containsSecurity"}


def test_domain_predicates_have_the_approved_domain_and_range() -> None:
    graph = _tbox()

    for property_id, (expected_domain, expected_range) in EXPECTED_PROPERTY_TYPES.items():
        expected_domain_set = frozenset(
            (expected_domain,) if isinstance(expected_domain, str) else expected_domain
        )
        expected_range_set = frozenset(
            (expected_range,) if isinstance(expected_range, str) else expected_range
        )
        assert _property_classes(graph, property_id, RDFS.domain) == expected_domain_set
        assert _property_classes(graph, property_id, RDFS.range) == expected_range_set


def test_declared_classes_resolve_and_grade_classes_are_distinct() -> None:
    graph = _tbox()
    classes = frozenset(
        subject
        for subject in graph.subjects(RDF.type, OWL.Class)
        if str(subject).startswith(f"{ONTOLOGY_IRI}#")
    )

    for property_id, (domain, range_) in EXPECTED_PROPERTY_TYPES.items():
        for class_id in (*((domain,) if isinstance(domain, str) else domain), *((range_,) if isinstance(range_, str) else range_)):
            assert FP[class_id] in classes, property_id

    assert FP.ProductRiskGrade in classes
    assert FP.CreditGrade in classes
    assert FP.ProductRiskGrade != FP.CreditGrade

    class_references = set()
    for predicate in (RDFS.subClassOf, OWL.disjointWith, RDFS.domain, RDFS.range):
        for target in graph.objects(predicate=predicate):
            if isinstance(target, URIRef) and str(target).startswith(f"{ONTOLOGY_IRI}#"):
                class_references.add(target)
            elif graph.value(target, OWL.unionOf) is not None:
                class_references.update(
                    item
                    for item in graph.items(graph.value(target, OWL.unionOf))
                    if isinstance(item, URIRef)
                    and str(item).startswith(f"{ONTOLOGY_IRI}#")
                )

    assert class_references <= classes


def test_common_tbox_owns_the_single_ontology_declaration() -> None:
    declarations = frozenset(_tbox().subjects(RDF.type, OWL.Ontology))
    assert declarations == {URIRef(ONTOLOGY_IRI)}

    common_declarations = frozenset(
        Graph().parse(TBOX_PATHS[0], format="turtle").subjects(RDF.type, OWL.Ontology)
    )
    assert common_declarations == {URIRef(ONTOLOGY_IRI)}

    for path in TBOX_PATHS[1:]:
        declarations = tuple(
            Graph().parse(path, format="turtle").subjects(RDF.type, OWL.Ontology)
        )
        assert not declarations, path.name


def test_exported_identifier_metadata_properties_are_typed_literals() -> None:
    """Catches removal of explicit IDs that read queries bind without parsing opaque IRIs."""
    graph = _tbox()

    for property_ in (FP.entityId, FP.evidenceId, FP.sourceId):
        assert (property_, RDF.type, OWL.DatatypeProperty) in graph
        assert (property_, RDFS.range, XSD.string) in graph

    assert (FP.evidenceId, RDFS.domain, FP.EvidenceRecord) in graph
    assert (FP.sourceId, RDFS.domain, FP.SourceRecord) in graph
