from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence
from warnings import catch_warnings, filterwarnings
from zoneinfo import ZoneInfo

from pyshacl import validate
from rdflib import Dataset, Graph, Literal, RDFS, URIRef, XSD
from rdflib.compare import to_canonical_graph
from rdflib.util import guess_format

from financial_agent.graph.contract import (
    APPROVED_PREDICATES,
    FP,
    TBOX_RELATIVE_PATHS,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ONTOLOGY_PATHS = tuple(_PROJECT_ROOT / relative for relative in TBOX_RELATIVE_PATHS)
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
    validated_data_hash: str
    validated_evidence_hash: str | None
    validated_cutoff_date: str
    contract_hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "contract_hashes",
            MappingProxyType(dict(sorted(self.contract_hashes.items()))),
        )


InputBytes = tuple[Path, bytes]


def _read_paths(paths: Sequence[Path]) -> tuple[InputBytes, ...]:
    return tuple((path, path.read_bytes()) for path in paths)


def _parse_inputs(inputs: Sequence[InputBytes]) -> Graph:
    graph = Graph()
    for path, payload in inputs:
        graph.parse(data=payload, format=guess_format(str(path)))
    return graph


def _validation_graphs(
    data_inputs: Sequence[InputBytes],
    cutoff_date: date,
) -> tuple[Graph, Graph]:
    union = Graph()
    explicit_types = Graph()
    for path, payload in data_inputs:
        source = Dataset()
        with catch_warnings():
            for module in (
                r"rdflib\.graph",
                r"rdflib\.plugins\.parsers\.nquads",
            ):
                filterwarnings(
                    "ignore",
                    message=(
                        r"Dataset\.default_context is deprecated, use "
                        r"Dataset\.default_graph instead\."
                    ),
                    category=DeprecationWarning,
                    module=module,
                )
            filterwarnings(
                "ignore",
                message=r"ConjunctiveGraph is deprecated, use Dataset instead\.",
                category=DeprecationWarning,
                module=r"rdflib\.plugins\.parsers\.trig",
            )
            source.parse(data=payload, format=guess_format(str(path)))
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


def _contract_hashes(inputs: Sequence[InputBytes]) -> Mapping[str, str]:
    project_root = _PROJECT_ROOT.resolve()
    hashes: dict[str, str] = {}
    for path, payload in inputs:
        try:
            relative = path.resolve().relative_to(project_root).as_posix()
        except ValueError as error:
            raise ValueError("validation contract path must be inside the repository") from error
        if relative in hashes:
            raise ValueError(f"duplicate validation contract path: {relative}")
        hashes[relative] = sha256(payload).hexdigest()
    return MappingProxyType(dict(sorted(hashes.items())))


def _explicit_type_ontology(ontology: Graph) -> Graph:
    explicit_ontology = Graph()
    for triple in ontology:
        if triple[1] not in {RDFS.domain, RDFS.range}:
            explicit_ontology.add(triple)
    return explicit_ontology


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
    if len(data_paths) not in {1, 2}:
        raise ValueError("validation requires one data artifact and optional Evidence artifact")
    data_inputs = _read_paths(data_paths)
    shape_inputs = _read_paths(shape_paths)
    ontology_inputs = _read_paths(_ONTOLOGY_PATHS)
    data, explicit_types = _validation_graphs(data_inputs, cutoff_date)
    shapes = _parse_inputs(shape_inputs)
    ontology = _parse_inputs(ontology_inputs)
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
    domain_shape_inputs = tuple(
        item for item in shape_inputs if item[0].name == "domain.shacl.ttl"
    )
    domain_conforms, domain_report_graph, domain_report_text = validate(
        data_graph=explicit_types,
        shacl_graph=_parse_inputs(domain_shape_inputs),
        ont_graph=_explicit_type_ontology(ontology),
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
        validated_data_hash=sha256(data_inputs[0][1]).hexdigest(),
        validated_evidence_hash=(
            sha256(data_inputs[1][1]).hexdigest() if len(data_inputs) == 2 else None
        ),
        validated_cutoff_date=cutoff_date.isoformat(),
        contract_hashes=_contract_hashes((*ontology_inputs, *shape_inputs)),
    )
