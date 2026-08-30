from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from hashlib import sha256
from types import MappingProxyType

import pytest

from financial_agent.graph.contract import GraphArtifacts, GraphProjectionBatch
from financial_agent.graph.manifest import (
    EXPORTER_VERSION,
    GraphComponentManifest,
    build_graph_manifest,
)
from financial_agent.graph.validator import GraphValidationResult


def _validation(report: bytes = b"<urn:report> <urn:status> \"ok\" .\n") -> GraphValidationResult:
    return GraphValidationResult(
        conforms=True,
        report_text="Conforms: True\n",
        report_ntriples=report,
        report_hash=sha256(report).hexdigest(),
    )


def _inputs() -> tuple[GraphProjectionBatch, GraphArtifacts]:
    return (
        GraphProjectionBatch(
            dataset_version="dataset-2026-08-24",
            cutoff_date=date(2026, 8, 24),
            entities=(),
            sources=(),
            evidences=(),
            relations=(),
        ),
        GraphArtifacts(
            data_nquads=b"<urn:a> <urn:p> <urn:b> <urn:data> .\n",
            evidence_nquads=b"<urn:e> <urn:p> <urn:s> <urn:evidence> .\n",
            entity_type_counts=MappingProxyType({"Security": 1, "ETF": 2}),
            predicate_counts=MappingProxyType({"holdsSecurity": 2, "listedOn": 1}),
        ),
    )


def test_manifest_uses_sorted_canonical_json_and_repo_relative_ontology_keys(
    tmp_path, monkeypatch
) -> None:
    ontology = tmp_path / "ontology"
    ontology.mkdir()
    common = ontology / "common.ttl"
    etf = ontology / "etf_kr.ttl"
    common.write_bytes(b"common ontology\n")
    etf.write_bytes(b"etf ontology\n")
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()

    manifest = build_graph_manifest(
        batch=batch,
        artifacts=artifacts,
        ontology_paths=(etf, common),
        validation=_validation(),
    )

    expected = {
        "cutoff_date": "2026-08-24",
        "data_nquads_hash": sha256(artifacts.data_nquads).hexdigest(),
        "dataset_version": "dataset-2026-08-24",
        "entity_type_counts": {"ETF": 2, "Security": 1},
        "evidence_nquads_hash": sha256(artifacts.evidence_nquads).hexdigest(),
        "exporter_version": EXPORTER_VERSION,
        "ontology_hashes": {
            "ontology/common.ttl": sha256(common.read_bytes()).hexdigest(),
            "ontology/etf_kr.ttl": sha256(etf.read_bytes()).hexdigest(),
        },
        "predicate_counts": {"holdsSecurity": 2, "listedOn": 1},
        "schema_version": "1",
        "validation_report_hash": _validation().report_hash,
    }
    expected_bytes = json.dumps(
        expected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert manifest.canonical_bytes() == expected_bytes
    assert manifest.component_manifest_hash() == sha256(expected_bytes).hexdigest()
    assert all(not key.startswith("/") for key in manifest.ontology_hashes)

    reversed_manifest = build_graph_manifest(
        batch=batch,
        artifacts=replace(
            artifacts,
            entity_type_counts=MappingProxyType({"ETF": 2, "Security": 1}),
            predicate_counts=MappingProxyType({"listedOn": 1, "holdsSecurity": 2}),
        ),
        ontology_paths=(common, etf),
        validation=_validation(),
    )
    assert reversed_manifest.canonical_bytes() == expected_bytes
    assert reversed_manifest.component_manifest_hash() == manifest.component_manifest_hash()


@pytest.mark.parametrize(
    "mutation",
    ("ontology", "data", "evidence", "report"),
)
def test_manifest_hash_changes_when_any_hashed_input_changes(
    tmp_path, monkeypatch, mutation: str
) -> None:
    ontology = tmp_path / "ontology"
    ontology.mkdir()
    common = ontology / "common.ttl"
    common.write_bytes(b"ontology-v1\n")
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    validation = _validation()
    original = build_graph_manifest(
        batch=batch,
        artifacts=artifacts,
        ontology_paths=(common,),
        validation=validation,
    )

    if mutation == "ontology":
        common.write_bytes(b"ontology-v2\n")
    elif mutation == "data":
        artifacts = replace(artifacts, data_nquads=artifacts.data_nquads + b"# changed\n")
    elif mutation == "evidence":
        artifacts = replace(
            artifacts,
            evidence_nquads=artifacts.evidence_nquads + b"# changed\n",
        )
    else:
        validation = _validation(validation.report_ntriples + b"# changed\n")

    changed = build_graph_manifest(
        batch=batch,
        artifacts=artifacts,
        ontology_paths=(common,),
        validation=validation,
    )
    assert changed.component_manifest_hash() != original.component_manifest_hash()


def test_manifest_rejects_failed_validation(tmp_path, monkeypatch) -> None:
    ontology = tmp_path / "ontology"
    ontology.mkdir()
    common = ontology / "common.ttl"
    common.write_bytes(b"ontology\n")
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    validation = replace(_validation(), conforms=False)

    with pytest.raises(ValueError, match="validation"):
        build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=(common,),
            validation=validation,
        )


def test_manifest_rejects_ontology_paths_outside_the_repository(
    tmp_path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside.ttl"
    outside.write_bytes(b"outside\n")
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", project_root)
    batch, artifacts = _inputs()

    with pytest.raises(ValueError, match="repository"):
        build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=(outside,),
            validation=_validation(),
        )


def test_manifest_rejects_a_duplicate_resolved_path_before_hashing(
    tmp_path, monkeypatch
) -> None:
    ontology = tmp_path / "ontology"
    ontology.mkdir()
    common = ontology / "common.ttl"
    common.write_bytes(b"ontology\n")
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        type(common),
        "read_bytes",
        lambda _path: pytest.fail("duplicate paths must be rejected before hashing"),
    )
    batch, artifacts = _inputs()

    with pytest.raises(ValueError, match="duplicate ontology path"):
        build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=(common, common),
            validation=_validation(),
        )


def test_manifest_defensively_freezes_caller_owned_mappings() -> None:
    ontology_hashes = {"ontology/common.ttl": "a" * 64}
    entity_type_counts = {"ETF": 1}
    predicate_counts = {"holdsSecurity": 1}
    manifest = GraphComponentManifest(
        schema_version="1",
        dataset_version="dataset-2026-08-24",
        cutoff_date="2026-08-24",
        exporter_version=EXPORTER_VERSION,
        ontology_hashes=ontology_hashes,
        data_nquads_hash="b" * 64,
        evidence_nquads_hash="c" * 64,
        validation_report_hash="d" * 64,
        entity_type_counts=entity_type_counts,
        predicate_counts=predicate_counts,
    )
    original_bytes = manifest.canonical_bytes()
    original_hash = manifest.component_manifest_hash()

    ontology_hashes["ontology/common.ttl"] = "e" * 64
    entity_type_counts["ETF"] = 99
    predicate_counts["holdsSecurity"] = 99

    assert manifest.canonical_bytes() == original_bytes
    assert manifest.component_manifest_hash() == original_hash
    with pytest.raises(TypeError):
        manifest.ontology_hashes["ontology/extra.ttl"] = "f" * 64  # type: ignore[index]
