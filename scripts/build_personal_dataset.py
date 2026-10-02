"""Build the approved personal subset from retained local source captures."""

import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from sqlalchemy.ext.asyncio import create_async_engine

from financial_agent.contracts import canonical_sha256
from financial_agent.ingestion.local_budget import (
    BudgetedWriter, StorageBudget, require_local_target,
)
from financial_agent.ingestion.models import BuildReport
from financial_agent.ingestion.official_pipeline import (
    _organizer_rows_for_official, _prepare_official_sources,
    _snapshot_official_inputs, _write_official_sources,
    compose_stage03b_manifest,
)
from financial_agent.ingestion.official_pipeline import load_official_manifests
from financial_agent.ingestion.pipeline import (
    CUTOFF_DATE, SOURCE_SPECS, _database_component_hashes, _preflight_sources,
    _snapshot_source_inputs, write_preflighted_organizer_rows,
)
from financial_agent.ingestion.sources import sha256_path


DATASET = "personal-2026-08-24-v1"


def select_krx_manifests(manifests, count=50):
    if not 1 <= count <= 50:
        raise ValueError("LOCAL_KRX_SAMPLE_LIMIT")
    krx = sorted(
        (m for m in manifests if m.source_code == "KRX_ETF_PDF"),
        key=lambda m: (hashlib.sha256(m.snapshot_id.encode()).digest(), m.snapshot_id),
    )
    if len(krx) < count:
        raise ValueError("LOCAL_KRX_SAMPLE_INSUFFICIENT")
    return tuple(m for m in manifests if m.source_code != "KRX_ETF_PDF") + tuple(krx[:count])


async def build(root: Path, url: str):
    require_local_target(url)
    output = root / "data/personal-local"
    output.mkdir(parents=True, exist_ok=True)
    budget_path = output / "budget.json"
    if budget_path.exists():
        budget = StorageBudget(**json.loads(budget_path.read_text()))
    else:
        budget = StorageBudget(shutil.disk_usage(root).free)
        budget_path.write_text(json.dumps(vars(budget), indent=2))
    workbook_roots = [p for p in root.iterdir() if p.is_dir() and (p / "prbd01n001_data.xlsx").exists()]
    if len(workbook_roots) != 1:
        raise ValueError("ORGANIZER_ROOT_AMBIGUOUS_OR_MISSING")
    source_root = workbook_roots[0]
    data = {code: source_root / spec.data_file_name for code, spec in SOURCE_SPECS.items()}
    schemas = {code: source_root / spec.schema_file_name for code, spec in SOURCE_SPECS.items()}
    capture_base = root / "data/generated/stage03b"
    capture_roots = tuple(capture_base / name for name in (
        "current-krx-holdings-capture", "current-krx-identity-capture",
        "current-ecos-capture", "current-sec-capture",
    ))
    manifests = select_krx_manifests(tuple(
        m for capture in capture_roots
        for m in load_official_manifests(capture / "manifests")
    ))
    short_codes = {m.objects[0].object_name.split("_", 1)[0]
                   for m in manifests if m.source_code == "KRX_ETF_PDF"}
    engine = create_async_engine(url.replace("postgresql://", "postgresql+psycopg://", 1),
        pool_size=2, max_overflow=0,
        connect_args={"options": "-c timezone=UTC -c role=fa_build -c statement_timeout=300000"})
    writer = BudgetedWriter(engine, budget, root)
    try:
        print({"phase": "source_preflight", **await writer.check_capacity()}, flush=True)
        with _snapshot_source_inputs(data, schemas) as (data_copy, schema_copy):
            preflight = _preflight_sources(
                data_paths=data_copy, schema_paths=schema_copy,
                data_sha256={code: sha256_path(path) for code, path in data.items()},
                schema_sha256={code: sha256_path(path) for code, path in schemas.items()},
            )
            combined = dict(compose_stage03b_manifest(preflight.manifest, manifests))
            export = root / "data/generated/local-postgres/dart-source-export"
            combined["personal_scope"] = {
                "krx_short_codes": sorted(short_codes), "nport_matched_products": 50,
                "selection": "sha256_product_or_snapshot_identity_v1", "document_limit": 100,
                "outside_sample": "unknown", "graph": "postgresql_relations_only",
                "document_export_hashes": {p.name: sha256_path(p) for p in sorted(export.glob("*.bin"))},
            }
            manifest_hash = canonical_sha256(combined)
            manifest_path = output / "manifest.json"
            manifest_text = json.dumps(combined, ensure_ascii=False, indent=2, default=str)
            if manifest_path.exists() and manifest_path.read_text() != manifest_text:
                raise RuntimeError("LOCAL_MANIFEST_CHANGED")
            manifest_path.write_text(manifest_text)
            with _snapshot_official_inputs(manifests, tuple(p / "objects" for p in capture_roots)) as verified:
                rows = dict(_organizer_rows_for_official(data_copy, {m.source_code for m in manifests}))
                rows["PREF01N001"] = tuple(row for row in rows["PREF01N001"]
                    if str(row.get("pd_ticker", "")).strip() in short_codes)
                with tempfile.TemporaryDirectory(prefix="personal-official-", dir=output) as scratch:
                    await writer.check_capacity()
                    prepared = _prepare_official_sources(manifests, verified, rows,
                        preflight.contexts, preflight.identity_index, Path(scratch),
                        nport_matched_product_sample_size=50)
                    await writer.create_building_dataset(DATASET, manifest_hash, CUTOFF_DATE)
                    print({"phase": "organizer_load"}, flush=True)
                    organizer_result = await write_preflighted_organizer_rows(writer,
                        dataset_version=DATASET, data_paths=data_copy, preflight=preflight, batch_size=1000)
                    if not organizer_result.passed:
                        raise RuntimeError("ORGANIZER_VALIDATION_FAILED")
                    (output / "organizer-checkpoint.json").write_text(json.dumps({
                        "source_counts": organizer_result.source_counts,
                        "storage": await writer.check_capacity(),
                    }, indent=2))
                    print({"phase": "official_subset_load"}, flush=True)
                    official_result = await _write_official_sources(writer, dataset_version=DATASET,
                        sources=prepared, batch_size=50)
                    report = BuildReport(dataset_version=DATASET, cutoff_date=CUTOFF_DATE,
                        dataset_manifest_hash=manifest_hash,
                        source_counts={**organizer_result.source_counts, **official_result.source_counts},
                        table_counts=await writer.table_counts(DATASET),
                        issue_counts=dict(Counter(organizer_result.issue_counts) + Counter(official_result.issue_counts)),
                        component_hashes=await _database_component_hashes(engine, DATASET),
                        passed=organizer_result.passed and official_result.passed)
                    (output / "structured-report.json").write_text(json.dumps(report.to_json_mapping(), indent=2, default=str))
                    if not report.passed:
                        raise RuntimeError("STRUCTURED_SUBSET_VALIDATION_FAILED")
                    print({"phase": "structured_complete", **await writer.check_capacity()}, flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--database-url", default="postgresql://localhost/financial_agent_local")
    args = parser.parse_args()
    asyncio.run(build(args.workspace_root.resolve(), args.database_url))
