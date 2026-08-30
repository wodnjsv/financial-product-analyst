from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from financial_agent.graph.contract import (
    GRAPH_CONTRACT_RELATIVE_PATHS,
    GraphArtifacts,
    GraphProjectionBatch,
)
from financial_agent.graph.exporter import build_graph_artifacts
from financial_agent.graph.validator import GraphValidationResult


EXPORTER_VERSION = "1"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class GraphComponentManifest:
    schema_version: str
    dataset_version: str
    cutoff_date: str
    exporter_version: str
    ontology_hashes: Mapping[str, str]
    data_nquads_hash: str
    evidence_nquads_hash: str
    validation_report_hash: str
    entity_type_counts: Mapping[str, int]
    predicate_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        for field_name in (
            "ontology_hashes",
            "entity_type_counts",
            "predicate_counts",
        ):
            values = getattr(self, field_name)
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(sorted(values.items()))),
            )

    def canonical_bytes(self) -> bytes:
        payload = {
            "schema_version": self.schema_version,
            "dataset_version": self.dataset_version,
            "cutoff_date": self.cutoff_date,
            "exporter_version": self.exporter_version,
            "ontology_hashes": dict(self.ontology_hashes),
            "data_nquads_hash": self.data_nquads_hash,
            "evidence_nquads_hash": self.evidence_nquads_hash,
            "validation_report_hash": self.validation_report_hash,
            "entity_type_counts": dict(self.entity_type_counts),
            "predicate_counts": dict(self.predicate_counts),
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def component_manifest_hash(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def _ontology_hashes(paths: Sequence[Path]) -> Mapping[str, str]:
    project_root = _PROJECT_ROOT.resolve()
    resolved_paths: dict[str, Path] = {}
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(project_root).as_posix()
        except ValueError as error:
            raise ValueError("ontology path must be inside the repository") from error
        if relative in resolved_paths:
            raise ValueError(f"duplicate ontology path: {relative}")
        resolved_paths[relative] = resolved
    expected_paths = frozenset(GRAPH_CONTRACT_RELATIVE_PATHS)
    actual_paths = frozenset(resolved_paths)
    if actual_paths != expected_paths:
        missing = ",".join(sorted(expected_paths - actual_paths)) or "none"
        extra = ",".join(sorted(actual_paths - expected_paths)) or "none"
        raise ValueError(f"contract path set mismatch: missing={missing}; extra={extra}")
    hashes = {
        relative: sha256(resolved.read_bytes()).hexdigest()
        for relative, resolved in resolved_paths.items()
    }
    return MappingProxyType(dict(sorted(hashes.items())))


def build_graph_manifest(
    *,
    batch: GraphProjectionBatch,
    artifacts: GraphArtifacts,
    ontology_paths: Sequence[Path],
    validation: GraphValidationResult,
) -> GraphComponentManifest:
    if not validation.conforms:
        raise ValueError("graph validation must conform before manifest generation")
    ontology_hashes = _ontology_hashes(ontology_paths)
    data_nquads_hash = sha256(artifacts.data_nquads).hexdigest()
    evidence_nquads_hash = sha256(artifacts.evidence_nquads).hexdigest()
    if validation.validated_data_hash != data_nquads_hash:
        raise ValueError("validated data artifact does not match manifest input")
    if validation.validated_evidence_hash != evidence_nquads_hash:
        raise ValueError("validated evidence artifact does not match manifest input")
    if dict(validation.contract_hashes) != dict(ontology_hashes):
        raise ValueError("validated contract does not match manifest input")
    if validation.validated_cutoff_date != batch.cutoff_date.isoformat():
        raise ValueError("validated cutoff does not match manifest input")
    validation_report_hash = sha256(validation.report_ntriples).hexdigest()
    if validation.report_hash != validation_report_hash:
        raise ValueError("validation report hash does not match report bytes")
    try:
        expected_artifacts = build_graph_artifacts(batch)
    except ValueError as error:
        raise ValueError("graph artifacts do not match the projection batch") from error
    if expected_artifacts != artifacts:
        raise ValueError("graph artifacts do not match the projection batch")
    return GraphComponentManifest(
        schema_version="1",
        dataset_version=batch.dataset_version,
        cutoff_date=batch.cutoff_date.isoformat(),
        exporter_version=EXPORTER_VERSION,
        ontology_hashes=ontology_hashes,
        data_nquads_hash=data_nquads_hash,
        evidence_nquads_hash=evidence_nquads_hash,
        validation_report_hash=validation_report_hash,
        entity_type_counts=MappingProxyType(
            dict(sorted(artifacts.entity_type_counts.items()))
        ),
        predicate_counts=MappingProxyType(
            dict(sorted(artifacts.predicate_counts.items()))
        ),
    )
