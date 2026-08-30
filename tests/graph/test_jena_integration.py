from __future__ import annotations

import builtins
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import Mock

import pytest

from financial_agent.graph.contract import (
    EntityProjection,
    EvidenceProjection,
    GraphProjectionBatch,
    RelationMetricProjection,
    RelationProjection,
    SourceProjection,
)
from financial_agent.graph.exporter import build_graph_artifacts
from scripts.graph import verify_jena


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSION = "jena-integration-v1"
CUTOFF = date(2026, 8, 24)
RELATIONS = (
    ("managedBy", "product/etf", "organization/manager", "relation/managed"),
    ("issuedBy", "product/bond", "organization/issuer", "relation/issued"),
    ("tracksIndex", "product/etf", "index/benchmark", "relation/tracks"),
    ("holdsSecurity", "product/etf", "security/holding", "relation/holds"),
    (
        "hasShareClass",
        "product/representative-fund",
        "product/share-class",
        "relation/share-class",
    ),
)


def _require_exact_runtime() -> tuple[Path, Path]:
    if os.environ.get("RUN_JENA_INTEGRATION") != "1":
        pytest.fail(
            "Jena integration was selected but RUN_JENA_INTEGRATION is not 1. "
            "Install Apache Jena and Fuseki 6.0.0 outside the repository, then set "
            "RUN_JENA_INTEGRATION=1, JENA_HOME, and FUSEKI_HOME."
        )

    missing = [name for name in ("JENA_HOME", "FUSEKI_HOME") if not os.environ.get(name)]
    if missing:
        pytest.fail(
            "Jena integration was requested but "
            f"{', '.join(missing)} is not set. Install the official Apache Jena and "
            "Fuseki 6.0.0 archives outside the repository and export both homes."
        )

    return Path(os.environ["JENA_HOME"]), Path(os.environ["FUSEKI_HOME"])


def _synthetic_batch() -> GraphProjectionBatch:
    entities = (
        EntityProjection(VERSION, "product/etf", ("FinancialProduct", "ETF", "DomesticETF")),
        EntityProjection(VERSION, "product/bond", ("FinancialProduct", "Bond", "DomesticBond")),
        EntityProjection(
            VERSION,
            "product/representative-fund",
            ("FinancialProduct", "PublicFund", "RepresentativeFund"),
        ),
        EntityProjection(
            VERSION,
            "product/share-class",
            ("FinancialProduct", "FundShareClass"),
        ),
        EntityProjection(VERSION, "organization/manager", ("Organization", "AssetManager")),
        EntityProjection(VERSION, "organization/issuer", ("Organization", "Issuer")),
        EntityProjection(VERSION, "organization/publisher", ("Organization",)),
        EntityProjection(VERSION, "index/benchmark", ("Index",)),
        EntityProjection(VERSION, "security/holding", ("Security", "EquitySecurity")),
    )
    sources = tuple(
        SourceProjection(VERSION, f"source/{index}", "organization/publisher")
        for index in range(1, len(RELATIONS) + 1)
    )
    evidences = tuple(
        EvidenceProjection(
            VERSION,
            f"evidence/{index}",
            f"source/{index}",
            CUTOFF,
            None,
            None,
            None,
            None,
            "eligible",
        )
        for index in range(1, len(RELATIONS) + 1)
    )
    relations = tuple(
        RelationProjection(
            VERSION,
            relation_id,
            subject_id,
            predicate_id,
            object_id,
            date(2026, 8, 1),
            CUTOFF,
            (f"evidence/{index}",),
            (
                RelationMetricProjection(
                    VERSION,
                    relation_id,
                    "krx_etf_holding_weight_pct",
                    Decimal("25.00"),
                    "percentage_point",
                    CUTOFF,
                ),
            )
            if predicate_id == "holdsSecurity"
            else (),
        )
        for index, (predicate_id, subject_id, object_id, relation_id) in enumerate(
            RELATIONS, start=1
        )
    )
    return GraphProjectionBatch(VERSION, CUTOFF, entities, sources, evidences, relations)


def _expected_bindings() -> dict[str, object]:
    return {
        "cutoff_date": CUTOFF.isoformat(),
        "dataset_version": VERSION,
        "queries": {
            predicate_id: [
                {
                    "dataset_version": VERSION,
                    "evidence_id": f"evidence/{index}",
                    "object_id": object_id,
                    "predicate_id": predicate_id,
                    "relation_assertion_id": relation_id,
                    "subject_id": subject_id,
                    "valid_from": "2026-08-01",
                    "valid_to": "2026-08-24",
                }
            ]
            for index, (predicate_id, subject_id, object_id, relation_id) in enumerate(
                RELATIONS, start=1
            )
        },
    }


def _run_verifier(
    tmp_path: Path,
    *,
    environment_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    jena_home, fuseki_home = _require_exact_runtime()
    artifacts = build_graph_artifacts(_synthetic_batch())
    data_path = tmp_path / "data.nq"
    evidence_path = tmp_path / "evidence.nq"
    expected_path = tmp_path / "expected-bindings.json"
    data_path.write_bytes(artifacts.data_nquads)
    evidence_path.write_bytes(artifacts.evidence_nquads)
    expected_path.write_text(
        json.dumps(_expected_bindings(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    if environment_overrides is not None:
        environment.update(environment_overrides)

    return subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "graph" / "verify_jena.py"),
            "--jena-home",
            str(jena_home),
            "--fuseki-home",
            str(fuseki_home),
            "--data",
            str(data_path),
            "--evidence",
            str(evidence_path),
            "--expected",
            str(expected_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
        shell=False,
    )


def _summary(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return dict(
        item.split("=", 1)
        for item in result.stdout.splitlines()
        if "=" in item
    )


@pytest.mark.jena_integration
def test_verified_jena_tdb2_and_read_only_fuseki(tmp_path: Path) -> None:
    """Catches runtime drift, query mismatch, or any writable/admin surface."""
    result = _run_verifier(tmp_path)

    assert result.returncode == 0, result.stderr or result.stdout
    summary = _summary(result)
    assert summary["jena_version"] == "6.0.0"
    assert summary["tdb2_query"] == "pass"
    assert summary["fuseki_query"] == "pass"
    assert summary["update_surface"] == "blocked"
    assert summary["admin_surface"] == "blocked"


@pytest.mark.jena_integration
def test_ambient_launcher_overrides_cannot_change_the_verified_runtime(
    tmp_path: Path,
) -> None:
    """Catches caller-controlled launchers, classpaths, logging, or server mode."""
    hostile_root = tmp_path / "ambient-overrides"
    result = _run_verifier(
        tmp_path,
        environment_overrides={
            "JENA_HOME": str(hostile_root / "jena"),
            "FUSEKI_HOME": str(hostile_root / "fuseki"),
            "JAVA": str(hostile_root / "java"),
            "JAVA_HOME": str(hostile_root / "java-home"),
            "CLASSPATH": str(hostile_root / "ambient.jar"),
            "JVM_ARGS": "-Dfinancial.agent.ambient=true",
            "LOGGING": str(hostile_root / "log4j2.properties"),
            "MAIN": "serverUI",
            "FUSEKI_BASE": str(hostile_root / "fuseki-base"),
            "JAVA_TOOL_OPTIONS": "-Dfinancial.agent.java_tool_options=true",
            "_JAVA_OPTIONS": "-Dfinancial.agent.java_options=true",
            "JDK_JAVA_OPTIONS": "-Dfinancial.agent.jdk_java_options=true",
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert _summary(result)["admin_surface"] == "blocked"


@pytest.mark.jena_integration
@pytest.mark.parametrize("forbidden_location", ("project", "jena", "fuseki"))
@pytest.mark.parametrize("environment_variable", ("TMPDIR", "TEMP", "TMP"))
def test_temporary_parent_rejects_repository_and_binary_homes(
    environment_variable: str,
    forbidden_location: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches caller temp variables placing verifier state in protected roots."""
    jena_home, fuseki_home = _require_exact_runtime()
    forbidden_parent = {
        "project": PROJECT_ROOT,
        "jena": jena_home,
        "fuseki": fuseki_home,
    }[forbidden_location]
    for variable in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(environment_variable, str(forbidden_parent))
    monkeypatch.setattr(tempfile, "tempdir", None)
    gettempdir = Mock(side_effect=AssertionError("gettempdir must not be called"))
    mkstemp = Mock(side_effect=AssertionError("mkstemp must not be called"))
    builtin_open = Mock(side_effect=AssertionError("open must not be called"))
    os_open = Mock(side_effect=AssertionError("os.open must not be called"))
    monkeypatch.setattr(verify_jena.tempfile, "gettempdir", gettempdir)
    monkeypatch.setattr(verify_jena.tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(builtins, "open", builtin_open)
    monkeypatch.setattr(verify_jena.os, "open", os_open)

    with pytest.raises(verify_jena.VerificationFailure, match="temporary_state"):
        verify_jena._validated_temp_parent(
            jena_home=jena_home.resolve(),
            fuseki_home=fuseki_home.resolve(),
        )

    assert gettempdir.call_count == 0
    assert mkstemp.call_count == 0
    assert builtin_open.call_count == 0
    assert os_open.call_count == 0


@pytest.mark.jena_integration
@pytest.mark.parametrize("invalid_environment_candidate", (False, True))
def test_temporary_parent_uses_standard_fallback_without_gettempdir(
    invalid_environment_candidate: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catches tempfile usability probes before a safe fallback is selected."""
    jena_home, fuseki_home = _require_exact_runtime()
    for variable in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.delenv(variable, raising=False)
    if invalid_environment_candidate:
        monkeypatch.setenv("TMPDIR", str(tmp_path / "missing"))
    gettempdir = Mock(side_effect=AssertionError("gettempdir must not be called"))
    monkeypatch.setattr(verify_jena.tempfile, "gettempdir", gettempdir)

    temporary_parent = verify_jena._validated_temp_parent(
        jena_home=jena_home.resolve(),
        fuseki_home=fuseki_home.resolve(),
    )

    assert temporary_parent == Path("/tmp").resolve()
    assert gettempdir.call_count == 0
