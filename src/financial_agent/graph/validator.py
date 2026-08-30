from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Sequence
from warnings import catch_warnings, simplefilter

from pyshacl import validate
from rdflib import Dataset, Graph, Literal, URIRef, XSD
from rdflib.compare import to_canonical_graph
from rdflib.util import guess_format


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ONTOLOGY_PATHS = tuple(
    _PROJECT_ROOT / "ontology" / name
    for name in ("common.ttl", "bond_kr.ttl", "etf_kr.ttl", "etf_gl.ttl", "fund_pub.ttl")
)
_VALIDATION_CONTEXT = URIRef("urn:validation:financial-product:context")
_CUTOFF_DATE = URIRef("urn:validation:financial-product#cutoffDate")


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


def _validation_union(data_paths: Sequence[Path], cutoff_date: date) -> Graph:
    union = Graph()
    for path in data_paths:
        source = Dataset()
        with catch_warnings():
            simplefilter("ignore", DeprecationWarning)
            source.parse(path, format=guess_format(str(path)))
        for subject, predicate, object_, _ in source.quads((None, None, None, None)):
            union.add((subject, predicate, object_))
    union.add((_VALIDATION_CONTEXT, _CUTOFF_DATE, Literal(cutoff_date, datatype=XSD.date)))
    return union


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
    data = _validation_union(data_paths, cutoff_date)
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
    report_ntriples = _canonical_ntriples(report_graph)
    return GraphValidationResult(
        conforms=conforms,
        report_text=report_text.replace("\r\n", "\n").replace("\r", "\n"),
        report_ntriples=report_ntriples,
        report_hash=sha256(report_ntriples).hexdigest(),
    )
