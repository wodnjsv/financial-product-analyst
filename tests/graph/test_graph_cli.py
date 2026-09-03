from __future__ import annotations

import json
from pathlib import Path

import pytest

from financial_agent.graph.cli import GraphBuildError, build_graph_snapshot
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
    expected_names = {"data.nq", "evidence.nq", "manifest.json", "report.json"}
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
