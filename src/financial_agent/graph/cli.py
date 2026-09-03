"""Build a validated, deterministic Graph snapshot outside the repository."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Sequence

from sqlalchemy.ext.asyncio import create_async_engine

from financial_agent.graph.contract import (
    GRAPH_CONTRACT_RELATIVE_PATHS,
    SHACL_RELATIVE_PATHS,
)
from financial_agent.graph.exporter import build_graph_artifacts
from financial_agent.graph.manifest import build_graph_manifest
from financial_agent.graph.repository import GraphProjectionRepository
from financial_agent.graph.validator import validate_graph


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class GraphBuildError(ValueError):
    pass


async def build_graph_snapshot(
    *,
    database_url: str,
    dataset_version: str,
    output_directory: Path,
) -> dict[str, object]:
    if not isinstance(database_url, str) or not database_url.strip():
        raise GraphBuildError("database_url must not be blank")
    if not isinstance(dataset_version, str) or not dataset_version.strip():
        raise GraphBuildError("dataset_version must not be blank")
    output = _validated_output_directory(output_directory)
    output.parent.mkdir(parents=True, exist_ok=True)

    temporary = Path(
        tempfile.mkdtemp(prefix=".graph-build-", dir=output.parent)
    )
    engine = create_async_engine(database_url)
    try:
        batch = await GraphProjectionRepository(engine).load(dataset_version)
        artifacts = build_graph_artifacts(batch)
        data_path = temporary / "data.nq"
        evidence_path = temporary / "evidence.nq"
        data_path.write_bytes(artifacts.data_nquads)
        evidence_path.write_bytes(artifacts.evidence_nquads)

        contract_paths = tuple(
            _PROJECT_ROOT / relative for relative in GRAPH_CONTRACT_RELATIVE_PATHS
        )
        shape_paths = tuple(
            _PROJECT_ROOT / relative for relative in SHACL_RELATIVE_PATHS
        )
        validation = validate_graph(
            data_paths=(data_path, evidence_path),
            shape_paths=shape_paths,
            cutoff_date=batch.cutoff_date,
        )
        if not validation.conforms:
            raise GraphBuildError("graph validation did not conform")
        manifest = build_graph_manifest(
            batch=batch,
            artifacts=artifacts,
            ontology_paths=contract_paths,
            validation=validation,
        )
        report = {
            "component_manifest_hash": manifest.component_manifest_hash(),
            "conforms": True,
            "cutoff_date": batch.cutoff_date.isoformat(),
            "data_nquads_hash": manifest.data_nquads_hash,
            "dataset_version": batch.dataset_version,
            "entity_count": len(batch.entities),
            "evidence_count": len(batch.evidences),
            "evidence_nquads_hash": manifest.evidence_nquads_hash,
            "predicate_counts": dict(manifest.predicate_counts),
            "relation_count": len(batch.relations),
            "source_count": len(batch.sources),
            "validation_report_hash": manifest.validation_report_hash,
        }
        (temporary / "manifest.json").write_bytes(manifest.canonical_bytes())
        (temporary / "report.json").write_bytes(_canonical_json(report))

        if output.exists():
            output.rmdir()
        os.replace(temporary, output)
        return report
    finally:
        await engine.dispose()
        if temporary.exists():
            shutil.rmtree(temporary)


def _validated_output_directory(value: Path) -> Path:
    output = Path(value)
    if output.is_symlink():
        raise GraphBuildError("output directory must not be a symlink")
    resolved = output.resolve(strict=False)
    repository = _PROJECT_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise GraphBuildError("output directory must be outside the repository")
    if resolved.exists():
        if not resolved.is_dir():
            raise GraphBuildError("output path must be a directory")
        if any(resolved.iterdir()):
            raise GraphBuildError("output directory must be empty")
    return resolved


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args(argv)
    report = asyncio.run(
        build_graph_snapshot(
            database_url=args.database_url,
            dataset_version=args.dataset_version,
            output_directory=args.output_directory,
        )
    )
    print(_canonical_json(report).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
