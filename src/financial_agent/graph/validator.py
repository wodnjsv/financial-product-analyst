from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Sequence
from warnings import catch_warnings, simplefilter
from zoneinfo import ZoneInfo

from pyshacl import validate
from rdflib import Dataset, Graph, Literal, URIRef, XSD
from rdflib.compare import to_canonical_graph
from rdflib.util import guess_format

from financial_agent.graph.contract import APPROVED_PREDICATES, FP


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ONTOLOGY_PATHS = tuple(
    _PROJECT_ROOT / "ontology" / name
    for name in ("common.ttl", "bond_kr.ttl", "etf_kr.ttl", "etf_gl.ttl", "fund_pub.ttl")
)
_VALIDATION_CONTEXT = URIRef("urn:validation:financial-product:context")
_CUTOFF_DATE = URIRef("urn:validation:financial-product#cutoffDate")
_CUTOFF_END_EXCLUSIVE = URIRef("urn:validation:financial-product#cutoffEndExclusive")
_SEOUL = ZoneInfo("Asia/Seoul")
_DOMAIN_PREDICATES = frozenset(FP[predicate] for predicate in APPROVED_PREDICATES)


@dataclass(frozen=True, slots=True)
class GraphValidationResult:
    conforms: bool
    report_text: str
    report_ntriples: bytes
    report_hash: str


def _parse_paths(paths: Sequence[Path]) -> Graph:
    graph = Graph()
    for path in paths:
        graph.parse(path, format=guess_format(str(path)))
    return graph


def _validation_graphs(data_paths: Sequence[Path], cutoff_date: date) -> tuple[Graph, Graph]:
    union = Graph()
    explicit_types = Graph()
    for path in data_paths:
        source = Dataset()
        with catch_warnings():
            simplefilter("ignore", DeprecationWarning)
            source.parse(path, format=guess_format(str(path)))
        for subject, predicate, object_, _ in source.quads((None, None, None, None)):
            union.add((subject, predicate, object_))
            if predicate not in _DOMAIN_PREDICATES:
                explicit_types.add((subject, predicate, object_))
    cutoff_end = datetime.combine(cutoff_date + timedelta(days=1), time.min, _SEOUL)
    context = (
        (_VALIDATION_CONTEXT, _CUTOFF_DATE, Literal(cutoff_date, datatype=XSD.date)),
        (_VALIDATION_CONTEXT, _CUTOFF_END_EXCLUSIVE, Literal(cutoff_end, datatype=XSD.dateTime)),
    )
    for triple in context:
        union.add(triple)
        explicit_types.add(triple)
    return union, explicit_types


def _canonical_ntriples(report_graph: Graph) -> bytes:
    canonical = to_canonical_graph(report_graph)
    serialized = canonical.serialize(format="nt")
    text = serialized.decode("utf-8") if isinstance(serialized, bytes) else serialized
    return ("\n".join(sorted(line for line in text.splitlines() if line)) + "\n").encode("utf-8")


def validate_graph(
    *,
    data_paths: Sequence[Path],
    shape_paths: Sequence[Path],
    cutoff_date: date,
) -> GraphValidationResult:
    """Validate named-graph projections without modifying their source datasets."""
    data, explicit_types = _validation_graphs(data_paths, cutoff_date)
    shapes = _parse_paths(shape_paths)
    ontology = _parse_paths(_ONTOLOGY_PATHS)
    conforms, report_graph, report_text = validate(
        data_graph=data,
        shacl_graph=shapes,
        ont_graph=ontology,
        inference="rdfs",
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
        advanced=True,
    )
    domain_shape_paths = tuple(path for path in shape_paths if path.name == "domain.shacl.ttl")
    domain_conforms, domain_report_graph, domain_report_text = validate(
        data_graph=explicit_types,
        shacl_graph=_parse_paths(domain_shape_paths),
        ont_graph=ontology,
        inference="rdfs",
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
        advanced=True,
    )
    combined_report = Graph()
    combined_report += report_graph
    combined_report += domain_report_graph
    report_ntriples = _canonical_ntriples(combined_report)
    return GraphValidationResult(
        conforms=conforms and domain_conforms,
        report_text=(report_text + "\n" + domain_report_text).replace("\r\n", "\n").replace("\r", "\n"),
        report_ntriples=report_ntriples,
        report_hash=sha256(report_ntriples).hexdigest(),
    )
