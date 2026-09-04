from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

import pytest

from financial_agent.graph import cli
from financial_agent.graph.cli import GraphBuildError, build_graph_snapshot
from financial_agent.graph.contract import GRAPH_CONTRACT_RELATIVE_PATHS
from financial_agent.graph.jena import JenaReleaseResult
from financial_agent.graph.repository import GraphProjectionRepository
from tests.graph.test_graph_exporter import valid_batch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = "postgresql+psycopg://graph-build.invalid/graph"


@pytest.mark.asyncio
@pytest.mark.parametrize("dataset_version", ["", "   "])
async def test_build_rejects_missing_dataset_version(
    tmp_path: Path, dataset_version: str
) -> None:
    with pytest.raises(GraphBuildError, match="dataset_version"):
        await build_graph_snapshot(
            database_url=DATABASE_URL,
            dataset_version=dataset_version,
            output_directory=tmp_path / "graph",
        )


@pytest.mark.asyncio
async def test_build_rejects_output_inside_repository() -> None:
    output = PROJECT_ROOT / "tmp" / "forbidden-graph-build"

    with pytest.raises(GraphBuildError, match="outside the repository"):
        await build_graph_snapshot(
            database_url=DATABASE_URL,
            dataset_version="dataset-v1",
            output_directory=output,
        )


@pytest.mark.asyncio
async def test_build_rejects_symlink_and_nonempty_output(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    symlink = tmp_path / "symlink"
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(GraphBuildError, match="symlink"):
        await build_graph_snapshot(
            database_url=DATABASE_URL,
            dataset_version="dataset-v1",
            output_directory=symlink,
        )

    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "existing.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(GraphBuildError, match="empty"):
        await build_graph_snapshot(
            database_url=DATABASE_URL,
            dataset_version="dataset-v1",
            output_directory=nonempty,
        )
    assert (nonempty / "existing.txt").read_text("utf-8") == "keep"


@pytest.mark.asyncio
async def test_build_is_deterministic_and_report_contains_only_aggregates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    batch = valid_batch()

    async def load(_repository, dataset_version: str):
        assert dataset_version == batch.dataset_version
        return batch

    monkeypatch.setattr(GraphProjectionRepository, "load", load)
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    first = await build_graph_snapshot(
        database_url=DATABASE_URL,
        dataset_version=batch.dataset_version,
        output_directory=first_output,
    )
    second = await build_graph_snapshot(
        database_url=DATABASE_URL,
        dataset_version=batch.dataset_version,
        output_directory=second_output,
    )

    assert first == second
    expected_names = {
        "data.nq",
        "evidence.nq",
        "expected-bindings.json",
        "manifest.json",
        "preflight.json",
        "report.json",
        "validation.nt",
    }
    assert {path.name for path in first_output.iterdir()} == expected_names
    for name in expected_names:
        assert (first_output / name).read_bytes() == (second_output / name).read_bytes()

    report = json.loads((first_output / "report.json").read_text("utf-8"))
    assert report == first
    assert report["entity_count"] == len(batch.entities)
    assert report["relation_count"] == len(batch.relations)
    assert report["evidence_count"] == len(batch.evidences)
    assert report["source_count"] == len(batch.sources)
    serialized = json.dumps(report, ensure_ascii=False)
    for forbidden in ("product/상품", "source/1", "relation/보유", "27.40"):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_build_leaves_no_partial_output_when_projection_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fail(_repository, _dataset_version: str):
        raise RuntimeError("synthetic projection failure")

    monkeypatch.setattr(GraphProjectionRepository, "load", fail)
    output = tmp_path / "failed"

    with pytest.raises(RuntimeError, match="synthetic projection failure"):
        await build_graph_snapshot(
            database_url=DATABASE_URL,
            dataset_version="dataset-v1",
            output_directory=output,
        )

    assert not output.exists()
    assert not tuple(tmp_path.glob(".graph-build-*"))


@pytest.mark.asyncio
async def test_release_build_persists_jena_report_but_not_telemetry_in_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catches release builds falling back to full-data pySHACL."""
    batch = valid_batch()
    elapsed_values = iter((7.5, 99.0))

    async def load(_repository, _dataset_version: str):
        return batch

    def validate_with_jena(**kwargs):
        data_hash = sha256(kwargs["data_path"].read_bytes()).hexdigest()
        evidence_hash = sha256(kwargs["evidence_path"].read_bytes()).hexdigest()
        contracts = {
            relative: sha256((PROJECT_ROOT / relative).read_bytes()).hexdigest()
            for relative in GRAPH_CONTRACT_RELATIVE_PATHS
        }
        report = b'{"conforms":true,"schema_version":"1"}'
        elapsed = next(elapsed_values)
        return JenaReleaseResult(
            conforms=True,
            report_bytes=report,
            report_hash=sha256(report).hexdigest(),
            telemetry_bytes=(f'{{"elapsed_seconds":{elapsed}}}').encode("utf-8"),
            validated_data_hash=data_hash,
            validated_evidence_hash=evidence_hash,
            validated_cutoff_date=batch.cutoff_date.isoformat(),
            contract_hashes=MappingProxyType(contracts),
        )

    monkeypatch.setattr(GraphProjectionRepository, "load", load)
    monkeypatch.setattr(cli, "run_jena_release_validation", validate_with_jena)
    jena_home = tmp_path / "jena"
    fuseki_home = tmp_path / "fuseki"
    jena_home.mkdir()
    fuseki_home.mkdir()
    output = tmp_path / "release"
    second_output = tmp_path / "release-second"

    report = await build_graph_snapshot(
        database_url=DATABASE_URL,
        dataset_version=batch.dataset_version,
        output_directory=output,
        jena_home=jena_home,
        fuseki_home=fuseki_home,
    )
    second_report = await build_graph_snapshot(
        database_url=DATABASE_URL,
        dataset_version=batch.dataset_version,
        output_directory=second_output,
        jena_home=jena_home,
        fuseki_home=fuseki_home,
    )

    assert (output / "validation.json").read_bytes().startswith(b'{"conforms"')
    assert (output / "telemetry.json").read_bytes() == b'{"elapsed_seconds":7.5}'
    assert report["validation_backend"] == "jena"
    assert b"elapsed_seconds" not in (output / "manifest.json").read_bytes()
    assert (second_output / "telemetry.json").read_bytes() == b'{"elapsed_seconds":99.0}'
    assert (output / "manifest.json").read_bytes() == (
        second_output / "manifest.json"
    ).read_bytes()
    assert report["component_manifest_hash"] == second_report["component_manifest_hash"]


@pytest.mark.asyncio
async def test_release_build_leaves_no_partial_output_when_jena_rejects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    batch = valid_batch()

    async def load(_repository, _dataset_version: str):
        return batch

    def reject_with_jena(**kwargs):
        report = b'{"conforms":false,"schema_version":"1"}'
        return JenaReleaseResult(
            conforms=False,
            report_bytes=report,
            report_hash=sha256(report).hexdigest(),
            telemetry_bytes=b'{"elapsed_seconds":1.0}',
            validated_data_hash=sha256(kwargs["data_path"].read_bytes()).hexdigest(),
            validated_evidence_hash=sha256(
                kwargs["evidence_path"].read_bytes()
            ).hexdigest(),
            validated_cutoff_date=batch.cutoff_date.isoformat(),
            contract_hashes=MappingProxyType({}),
        )

    monkeypatch.setattr(GraphProjectionRepository, "load", load)
    monkeypatch.setattr(cli, "run_jena_release_validation", reject_with_jena)
    jena_home = tmp_path / "jena"
    fuseki_home = tmp_path / "fuseki"
    jena_home.mkdir()
    fuseki_home.mkdir()
    output = tmp_path / "release-rejected"

    with pytest.raises(GraphBuildError, match="did not conform"):
        await build_graph_snapshot(
            database_url=DATABASE_URL,
            dataset_version=batch.dataset_version,
            output_directory=output,
            jena_home=jena_home,
            fuseki_home=fuseki_home,
        )

    assert not output.exists()
    assert not tuple(tmp_path.glob(".graph-build-*"))


@pytest.mark.asyncio
async def test_build_stops_before_export_when_preflight_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catches malformed projection data reaching RDF export or SHACL."""
    batch = valid_batch()

    async def load(_repository, _dataset_version: str):
        return batch

    def reject(_batch):
        return type(
            "FailedPreflight",
            (),
            {
                "conforms": False,
                "report_bytes": b'{"conforms":false}',
                "report_hash": "a" * 64,
                "violation_codes": ("MISSING_EVIDENCE",),
            },
        )()

    def unexpected_export(_batch):
        pytest.fail("RDF export must not run after preflight failure")

    monkeypatch.setattr(GraphProjectionRepository, "load", load)
    monkeypatch.setattr(cli, "validate_projection_batch", reject)
    monkeypatch.setattr(cli, "build_graph_artifacts", unexpected_export)
    output = tmp_path / "failed-preflight"

    with pytest.raises(GraphBuildError, match="MISSING_EVIDENCE"):
        await build_graph_snapshot(
            database_url=DATABASE_URL,
            dataset_version=batch.dataset_version,
            output_directory=output,
        )

    assert not output.exists()
