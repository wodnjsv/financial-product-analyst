from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
import tempfile

import pytest

from financial_agent.ingestion.official.authority import (
    validate_official_enrichment_scope,
)
from financial_agent.ingestion.official_pipeline import (
    OrganizerInputs,
    _coverage_statuses,
    _organizer_rows_for_official,
    _prepare_official_sources,
    _snapshot_official_inputs,
    load_official_manifests,
)
from financial_agent.ingestion.pipeline import (
    SOURCE_SPECS,
    _preflight_sources,
    _snapshot_source_inputs,
)
from financial_agent.ingestion.sources import sha256_path


RUN_CURRENT_SEC = os.getenv("RUN_CURRENT_SEC_TESTS") == "1"
ORGANIZER_ROOT = os.getenv("FINANCIAL_AGENT_CURRENT_ORGANIZER_ROOT")
SEC_CAPTURE_ROOT = os.getenv("FINANCIAL_AGENT_CURRENT_SEC_CAPTURE_ROOT")

_EXPECTED_OBJECT_HASHES = {
    "SEC_NPORT_2026Q2": (
        "077cc836a978a593b29012219395fbe9c303d5e930f5be3b5f4353c3b02296fc"
    ),
    "SEC_SERIES_CLASS_20260601": (
        "9fdb6d24157bbec44244366dfddebe2300404ab591da479cf537db884078af6a"
    ),
}


@pytest.fixture(scope="session", autouse=True)
def _require_explicit_current_sec_configuration() -> None:
    if RUN_CURRENT_SEC and (
        ORGANIZER_ROOT is None or SEC_CAPTURE_ROOT is None
    ):
        pytest.fail("CURRENT_SEC_CONFIGURATION_MISSING", pytrace=False)


def _organizer_inputs(root: Path) -> OrganizerInputs:
    data_paths = {
        code: root / spec.data_file_name for code, spec in SOURCE_SPECS.items()
    }
    schema_paths = {
        code: root / spec.schema_file_name for code, spec in SOURCE_SPECS.items()
    }
    return OrganizerInputs(
        data_paths=data_paths,
        schema_paths=schema_paths,
        data_sha256={
            code: sha256_path(path) for code, path in data_paths.items()
        },
        schema_sha256={
            code: sha256_path(path) for code, path in schema_paths.items()
        },
    )


@pytest.mark.organizer_data
@pytest.mark.skipif(
    not RUN_CURRENT_SEC,
    reason="explicit current-SEC gate is disabled",
)
def test_current_organizer_exact_sec_binding_sample_is_bounded() -> None:
    organizer_inputs = _organizer_inputs(Path(ORGANIZER_ROOT or ""))
    capture_root = Path(SEC_CAPTURE_ROOT or "")
    manifests = load_official_manifests(capture_root / "manifests")
    assert {manifest.source_code for manifest in manifests} == set(
        _EXPECTED_OBJECT_HASHES
    )
    assert all(
        manifest.cutoff_date.isoformat() == "2026-08-24"
        for manifest in manifests
    )
    assert {
        manifest.source_code: manifest.objects[0].sha256
        for manifest in manifests
    } == _EXPECTED_OBJECT_HASHES

    with _snapshot_source_inputs(
        organizer_inputs.data_paths,
        organizer_inputs.schema_paths,
    ) as (data_paths, schema_paths):
        preflight = _preflight_sources(
            data_paths=data_paths,
            schema_paths=schema_paths,
            data_sha256=organizer_inputs.data_sha256,
            schema_sha256=organizer_inputs.schema_sha256,
        )
        organizer_rows = _organizer_rows_for_official(
            data_paths,
            {manifest.source_code for manifest in manifests},
        )
        assert len(organizer_rows["PREF02N001"]) == 6_037
        with _snapshot_official_inputs(
            manifests,
            capture_root / "objects",
        ) as verified_paths:
            with tempfile.TemporaryDirectory(
                prefix="financial-agent-current-sec-gate-"
            ) as scratch:
                prepared = _prepare_official_sources(
                    manifests,
                    verified_paths,
                    organizer_rows,
                    preflight.contexts,
                    preflight.identity_index,
                    Path(scratch),
                    nport_matched_product_sample_size=10,
                )
                source = next(
                    item
                    for item in prepared
                    if item.source_code == "SEC_NPORT_2026Q2"
                )
                coverage: Counter[str] = Counter()
                source_records = 0
                relations = 0
                for factory in source.row_factories:
                    for row in factory():
                        validate_official_enrichment_scope(
                            source.source_code,
                            row,
                        )
                        coverage.update(_coverage_statuses(row))
                        source_records += len(
                            row.records_by_table["evidence.source_record"]
                        )
                        relations += len(
                            row.records_by_table[
                                "relation.relation_record"
                            ]
                        )

    assert sum(coverage.values()) == 10
    assert set(coverage) <= {"COVERED", "PARTIALLY_COVERED"}
    assert source_records == 10
    assert relations > 10
