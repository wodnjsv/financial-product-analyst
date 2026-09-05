from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
import textwrap

import pytest

from financial_agent.graph.contract import GRAPH_CONTRACT_RELATIVE_PATHS
from financial_agent.graph import jena
from financial_agent.graph.jena import JenaReleaseError, run_jena_release_validation
from financial_agent.graph.queries import build_expected_bindings
from scripts.graph import verify_jena
from scripts.graph.verify_jena import (
    _render_fuseki_config,
    _run as run_verifier_command,
)
from tests.graph.test_graph_exporter import valid_batch


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_outer_watchdog_allows_multiple_bounded_verifier_stages() -> None:
    assert jena._overall_timeout_seconds(1200) == 3600


def test_large_artifact_hashing_does_not_use_path_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact.nq"
    artifact.write_bytes(b"stream this payload")
    expected = sha256(b"stream this payload").hexdigest()

    def reject_full_read(path: Path) -> bytes:
        raise AssertionError(f"full read attempted for {path}")

    monkeypatch.setattr(Path, "read_bytes", reject_full_read)

    assert jena._sha256_path(artifact) == expected
    assert verify_jena._sha256_path(artifact) == expected


def test_fuseki_readiness_probe_does_not_run_a_competency_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    class RunningProcess:
        @staticmethod
        def poll() -> None:
            return None

    def query(endpoint: str, sparql: str, *, timeout: float, stage: str) -> str:
        del endpoint, timeout, stage
        observed.append(sparql)
        return "{}"

    monkeypatch.setattr(verify_jena, "_http_query", query)

    verify_jena._wait_for_fuseki(RunningProcess(), "http://127.0.0.1/query")

    assert len(observed) == 1
    assert "LIMIT 1" in observed[0]
    assert "RelationAssertion" not in observed[0]


def test_verifier_command_can_stream_stdout_directly_to_a_file(tmp_path: Path) -> None:
    output_path = tmp_path / "large-output.ttl"

    result = run_verifier_command(
        "stream",
        [sys.executable, "-c", "print('streamed graph')"],
        environment={},
        stdout_path=output_path,
    )

    assert result.stdout is None
    assert output_path.read_text(encoding="utf-8") == "streamed graph\n"


def test_validation_fuseki_config_adds_only_the_internal_shacl_endpoint() -> None:
    template = (PROJECT_ROOT / "config/fuseki/financial-product.ttl").read_text(
        encoding="utf-8"
    )

    validation_config = _render_fuseki_config(
        template,
        tdb2_location=Path("/tmp/graph-tdb2"),
        include_shacl=True,
    )
    runtime_config = _render_fuseki_config(
        template,
        tdb2_location=Path("/tmp/graph-tdb2"),
        include_shacl=False,
    )

    assert "fuseki:operation fuseki:shacl" in validation_config
    assert "fuseki:name \"shacl\"" in validation_config
    assert "fuseki:operation fuseki:shacl" not in runtime_config
    assert "__TDB2_LOCATION__" not in validation_config


def test_expected_bindings_are_canonical_and_evidence_expanded() -> None:
    """Catches missing Evidence rows or input-order leakage in Jena query truth."""
    batch = valid_batch()

    payload = json.loads(build_expected_bindings(batch))

    assert payload == {
        "cutoff_date": "2026-08-24",
        "dataset_version": "2026-08-24/v1",
        "schema_version": "2",
        "binding_counts": {
            "hasShareClass": 0,
            "holdsSecurity": 2,
            "issuedBy": 0,
            "managedBy": 0,
            "tracksIndex": 0,
        },
        "queries": {
            "hasShareClass": [],
            "holdsSecurity": [
                {
                    "dataset_version": "2026-08-24/v1",
                    "evidence_id": "evidence/1",
                    "object_id": "security/1",
                    "predicate_id": "holdsSecurity",
                    "relation_assertion_id": "relation/보유",
                    "subject_id": "product/상품",
                    "valid_from": "2026-08-01",
                    "valid_to": "2026-08-24",
                },
                {
                    "dataset_version": "2026-08-24/v1",
                    "evidence_id": "evidence/2",
                    "object_id": "security/1",
                    "predicate_id": "holdsSecurity",
                    "relation_assertion_id": "relation/보유",
                    "subject_id": "product/상품",
                    "valid_from": "2026-08-01",
                    "valid_to": "2026-08-24",
                },
            ],
            "issuedBy": [],
            "managedBy": [],
            "tracksIndex": [],
        },
    }


def _contract_hashes() -> dict[str, str]:
    return {
        relative: sha256((PROJECT_ROOT / relative).read_bytes()).hexdigest()
        for relative in GRAPH_CONTRACT_RELATIVE_PATHS
    }


def _verifier_script(
    path: Path,
    *,
    mode: str,
    peak_rss_bytes: int = 1234,
) -> Path:
    report = {
        "conforms": True,
        "contract_hashes": _contract_hashes(),
        "cutoff_date": "2026-08-24",
        "data_hash": sha256(b"data\n").hexdigest(),
        "evidence_hash": sha256(b"evidence\n").hexdigest(),
        "fuseki_version": "6.0.0",
        "java_version": "21",
        "jena_version": "6.0.0",
        "schema_version": "1",
        "stages": {"shacl": "pass", "tdb2_query": "pass"},
    }
    if mode == "hash_mismatch":
        report["data_hash"] = "0" * 64
    source = f"""
import argparse
import json
import sys
import time

parser = argparse.ArgumentParser()
for name in ('jena-home', 'fuseki-home', 'data', 'evidence', 'expected', 'report', 'telemetry', 'timeout-seconds'):
    parser.add_argument('--' + name, required=True)
args = parser.parse_args()
mode = {mode!r}
if mode == 'timeout':
    time.sleep(4)
if mode == 'nonzero':
    raise SystemExit(3)
if mode == 'reported_failure':
    print('stage=shacl error=validation endpoint rejected the graph', file=sys.stderr)
    raise SystemExit(4)
if mode == 'malformed':
    open(args.report, 'w', encoding='utf-8').write('{{')
else:
    open(args.report, 'w', encoding='utf-8').write(json.dumps({report!r}, sort_keys=True, separators=(',', ':')))
open(args.telemetry, 'w', encoding='utf-8').write(json.dumps({{'elapsed_seconds': 0.1, 'peak_rss_bytes': {peak_rss_bytes}}}, sort_keys=True, separators=(',', ':')))
"""
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def _run(tmp_path: Path, script: Path, *, timeout_seconds: int = 10):
    data = tmp_path / "data.nq"
    evidence = tmp_path / "evidence.nq"
    expected = tmp_path / "expected.json"
    data.write_bytes(b"data\n")
    evidence.write_bytes(b"evidence\n")
    expected.write_bytes(build_expected_bindings(valid_batch()))
    jena_home = tmp_path / "jena"
    fuseki_home = tmp_path / "fuseki"
    jena_home.mkdir(exist_ok=True)
    fuseki_home.mkdir(exist_ok=True)
    return run_jena_release_validation(
        data_path=data,
        evidence_path=evidence,
        expected_path=expected,
        jena_home=jena_home,
        fuseki_home=fuseki_home,
        cutoff_date=valid_batch().cutoff_date,
        timeout_seconds=timeout_seconds,
        verifier_path=script,
    )


def test_release_report_is_deterministic_while_telemetry_may_change(
    tmp_path: Path,
) -> None:
    """Catches elapsed time or memory leaking into the manifest-bound report."""
    first = _run(tmp_path, _verifier_script(tmp_path / "first.py", mode="success"))
    second = _run(
        tmp_path,
        _verifier_script(
            tmp_path / "second.py",
            mode="success",
            peak_rss_bytes=9999,
        ),
    )

    assert first.conforms is True
    assert first.report_bytes == second.report_bytes
    assert first.report_hash == second.report_hash
    assert first.telemetry_bytes != second.telemetry_bytes


@pytest.mark.parametrize(
    ("mode", "expected_code", "timeout_seconds"),
    (
        ("nonzero", "JENA_PROCESS_FAILED", 10),
        ("malformed", "JENA_REPORT_INVALID", 10),
        ("hash_mismatch", "JENA_INPUT_HASH_MISMATCH", 10),
        ("timeout", "JENA_TIMEOUT", 1),
    ),
)
def test_release_wrapper_fails_closed(
    tmp_path: Path,
    mode: str,
    expected_code: str,
    timeout_seconds: int,
) -> None:
    """Catches a broken or unbounded external validator being accepted."""
    script = _verifier_script(tmp_path / f"{mode}.py", mode=mode)

    with pytest.raises(JenaReleaseError, match=expected_code):
        _run(tmp_path, script, timeout_seconds=timeout_seconds)


def test_release_wrapper_preserves_only_the_verifier_failure_summary(
    tmp_path: Path,
) -> None:
    script = _verifier_script(tmp_path / "reported.py", mode="reported_failure")

    with pytest.raises(JenaReleaseError, match="JENA_PROCESS_FAILED") as captured:
        _run(tmp_path, script)

    assert captured.value.code == "JENA_PROCESS_FAILED"
    assert captured.value.detail == (
        "stage=shacl error=validation endpoint rejected the graph"
    )
