from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

import pytest

from financial_agent.graph.contract import (
    GRAPH_CONTRACT_RELATIVE_PATHS,
    EntityProjection,
    EvidenceProjection,
    GraphArtifacts,
    GraphProjectionBatch,
    RelationProjection,
    SourceProjection,
)
from financial_agent.graph.exporter import build_graph_artifacts
from financial_agent.graph.manifest import (
    EXPORTER_VERSION,
    GraphComponentManifest,
    build_graph_manifest,
)
from financial_agent.graph.validator import GraphValidationResult


def _inputs() -> tuple[GraphProjectionBatch, GraphArtifacts]:
    dataset_version = "dataset-2026-08-24"
    cutoff_date = date(2026, 8, 24)
    batch = GraphProjectionBatch(
        dataset_version=dataset_version,
        cutoff_date=cutoff_date,
        entities=(
            EntityProjection(dataset_version, "product", ("FinancialProduct",)),
            EntityProjection(
                dataset_version,
                "manager",
                ("AssetManager", "Organization"),
            ),
        ),
        sources=(SourceProjection(dataset_version, "source", "manager"),),
        evidences=(
            EvidenceProjection(
                dataset_version,
                "evidence",
                "source",
                cutoff_date,
                None,
                None,
                None,
                None,
                "eligible",
            ),
        ),
        relations=(
            RelationProjection(
                dataset_version,
                "managed",
                "product",
                "managedBy",
                "manager",
                None,
                None,
                ("evidence",),
            ),
        ),
    )
    return batch, build_graph_artifacts(batch)


def _contract_paths(project_root: Path) -> tuple[Path, ...]:
    paths = tuple(project_root / relative for relative in GRAPH_CONTRACT_RELATIVE_PATHS)
    for index, path in enumerate(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"contract-{index}\n".encode())
    return paths


def _contract_hashes(project_root: Path, paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        path.resolve().relative_to(project_root.resolve()).as_posix(): sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths
    }


def _validation(
    *,
    project_root: Path,
    contract_paths: tuple[Path, ...],
    artifacts: GraphArtifacts,
    report: bytes = b"<urn:report> <urn:status> \"ok\" .\n",
    cutoff_date: str = "2026-08-24",
) -> GraphValidationResult:
    return GraphValidationResult(
        conforms=True,
        report_text="Conforms: True\n",
        report_ntriples=report,
        report_hash=sha256(report).hexdigest(),
        validated_data_hash=sha256(artifacts.data_nquads).hexdigest(),
        validated_evidence_hash=sha256(artifacts.evidence_nquads).hexdigest(),
        validated_cutoff_date=cutoff_date,
        contract_hashes=_contract_hashes(project_root, contract_paths),
    )


def test_manifest_uses_sorted_canonical_json_and_exact_contract_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    contract_paths = _contract_paths(tmp_path)
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    validation = _validation(
        project_root=tmp_path,
        contract_paths=contract_paths,
        artifacts=artifacts,
    )

    manifest = build_graph_manifest(
        batch=batch,
        artifacts=artifacts,
        ontology_paths=tuple(reversed(contract_paths)),
        validation=validation,
    )

    expected = {
        "cutoff_date": "2026-08-24",
        "data_nquads_hash": sha256(artifacts.data_nquads).hexdigest(),
        "dataset_version": "dataset-2026-08-24",
        "entity_type_counts": {
            "AssetManager": 1,
            "FinancialProduct": 1,
            "Organization": 1,
        },
        "evidence_nquads_hash": sha256(artifacts.evidence_nquads).hexdigest(),
        "exporter_version": EXPORTER_VERSION,
        "ontology_hashes": dict(sorted(validation.contract_hashes.items())),
        "predicate_counts": {"managedBy": 1},
        "schema_version": "1",
        "validation_report_hash": validation.report_hash,
    }
    expected_bytes = json.dumps(
        expected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert manifest.canonical_bytes() == expected_bytes
    assert manifest.component_manifest_hash() == sha256(expected_bytes).hexdigest()
    assert tuple(manifest.ontology_hashes) == tuple(sorted(GRAPH_CONTRACT_RELATIVE_PATHS))

    reversed_manifest = build_graph_manifest(
        batch=batch,
        artifacts=replace(
            artifacts,
            entity_type_counts=MappingProxyType(
                {
                    "Organization": 1,
                    "FinancialProduct": 1,
                    "AssetManager": 1,
                }
            ),
            predicate_counts=MappingProxyType({"managedBy": 1}),
        ),
        ontology_paths=contract_paths,
        validation=validation,
    )
    assert reversed_manifest.canonical_bytes() == expected_bytes


@pytest.mark.parametrize("mutation", ("ontology", "data", "evidence", "report"))
def test_manifest_hash_changes_when_any_hashed_input_changes(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    contract_paths = _contract_paths(tmp_path)
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    original_validation = _validation(
        project_root=tmp_path,
        contract_paths=contract_paths,
        artifacts=artifacts,
    )
    original = build_graph_manifest(
        batch=batch,
        artifacts=artifacts,
        ontology_paths=contract_paths,
        validation=original_validation,
    )

    report = original_validation.report_ntriples
    if mutation == "ontology":
        contract_paths[0].write_bytes(b"changed ontology\n")
    elif mutation == "data":
        batch = replace(
            batch,
            relations=(replace(batch.relations[0], valid_from=date(2026, 8, 1)),),
        )
        artifacts = build_graph_artifacts(batch)
    elif mutation == "evidence":
        batch = replace(
            batch,
            evidences=(replace(batch.evidences[0], evidence_id="evidence-changed"),),
            relations=(
                replace(batch.relations[0], evidence_ids=("evidence-changed",)),
            ),
        )
        artifacts = build_graph_artifacts(batch)
    else:
        report += b"# changed\n"
    validation = _validation(
        project_root=tmp_path,
        contract_paths=contract_paths,
        artifacts=artifacts,
        report=report,
    )

    changed = build_graph_manifest(
        batch=batch,
        artifacts=artifacts,
        ontology_paths=contract_paths,
        validation=validation,
    )
    assert changed.component_manifest_hash() != original.component_manifest_hash()


def test_manifest_rejects_failed_validation(tmp_path: Path, monkeypatch) -> None:
    contract_paths = _contract_paths(tmp_path)
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    validation = replace(
        _validation(
            project_root=tmp_path,
            contract_paths=contract_paths,
            artifacts=artifacts,
        ),
        conforms=False,
    )

    with pytest.raises(ValueError, match="validation"):
        build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=contract_paths,
            validation=validation,
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing", "contract path set"),
        ("extra", "contract path set"),
        ("substituted", "contract path set"),
        ("duplicate", "duplicate ontology path"),
    ],
)
def test_manifest_requires_the_exact_seven_contract_paths(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
    match: str,
) -> None:
    contract_paths = list(_contract_paths(tmp_path))
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    validation = _validation(
        project_root=tmp_path,
        contract_paths=tuple(contract_paths),
        artifacts=artifacts,
    )
    if mutation == "missing":
        contract_paths.pop()
    elif mutation == "extra":
        extra = tmp_path / "ontology" / "extra.ttl"
        extra.write_bytes(b"extra\n")
        contract_paths.append(extra)
    elif mutation == "substituted":
        substitute = tmp_path / "ontology" / "substitute.ttl"
        substitute.write_bytes(b"substitute\n")
        contract_paths[0] = substitute
    else:
        contract_paths.append(contract_paths[0])

    with pytest.raises(ValueError, match=match):
        build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=tuple(contract_paths),
            validation=validation,
        )


@pytest.mark.parametrize("artifact", ("data", "evidence"))
def test_manifest_rejects_validation_from_different_artifacts(
    tmp_path: Path,
    monkeypatch,
    artifact: str,
) -> None:
    contract_paths = _contract_paths(tmp_path)
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    validated_artifacts = (
        replace(artifacts, data_nquads=artifacts.data_nquads + b"different\n")
        if artifact == "data"
        else replace(
            artifacts,
            evidence_nquads=artifacts.evidence_nquads + b"different\n",
        )
    )
    validation = _validation(
        project_root=tmp_path,
        contract_paths=contract_paths,
        artifacts=validated_artifacts,
    )

    with pytest.raises(ValueError, match=f"validated {artifact}"):
        build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=contract_paths,
            validation=validation,
        )


def test_manifest_rejects_validation_from_a_different_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    contract_paths = _contract_paths(tmp_path)
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    validation = _validation(
        project_root=tmp_path,
        contract_paths=contract_paths,
        artifacts=artifacts,
    )
    contract_paths[0].write_bytes(b"contract changed after validation\n")

    with pytest.raises(ValueError, match="validated contract"):
        build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=contract_paths,
            validation=validation,
        )


def test_manifest_rejects_validation_at_a_different_cutoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    contract_paths = _contract_paths(tmp_path)
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    validation = _validation(
        project_root=tmp_path,
        contract_paths=contract_paths,
        artifacts=artifacts,
        cutoff_date="2026-08-23",
    )

    with pytest.raises(ValueError, match="validated cutoff"):
        build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=contract_paths,
            validation=validation,
        )


def test_manifest_rejects_artifacts_from_a_different_projection_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    contract_paths = _contract_paths(tmp_path)
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    validation = _validation(
        project_root=tmp_path,
        contract_paths=contract_paths,
        artifacts=artifacts,
    )

    with pytest.raises(ValueError, match="projection batch"):
        build_graph_manifest(
            batch=replace(batch, dataset_version="different-version"),
            artifacts=artifacts,
            ontology_paths=contract_paths,
            validation=validation,
        )


def test_manifest_rejects_fabricated_artifact_counts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    contract_paths = _contract_paths(tmp_path)
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", tmp_path)
    batch, artifacts = _inputs()
    artifacts = replace(
        artifacts,
        entity_type_counts=MappingProxyType({"Fabricated": 999}),
    )
    validation = _validation(
        project_root=tmp_path,
        contract_paths=contract_paths,
        artifacts=artifacts,
    )

    with pytest.raises(ValueError, match="projection batch"):
        build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=contract_paths,
            validation=validation,
        )


def test_manifest_rejects_ontology_paths_outside_the_repository(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    contract_paths = _contract_paths(project_root)
    outside = tmp_path / "outside.ttl"
    outside.write_bytes(b"outside\n")
    monkeypatch.setattr("financial_agent.graph.manifest._PROJECT_ROOT", project_root)
    batch, artifacts = _inputs()
    validation = _validation(
        project_root=project_root,
        contract_paths=contract_paths,
        artifacts=artifacts,
    )

    with pytest.raises(ValueError, match="repository"):
        build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=(*contract_paths[1:], outside),
            validation=validation,
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
