from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import MappingProxyType
from typing import Mapping

from financial_agent.graph.contract import GRAPH_CONTRACT_RELATIVE_PATHS


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_VERIFIER = _PROJECT_ROOT / "scripts" / "graph" / "verify_jena.py"
_RUNTIME_VARIABLES = (
    "JENA_HOME",
    "FUSEKI_HOME",
    "FUSEKI_BASE",
    "JAVA",
    "JAVA_HOME",
    "CLASSPATH",
    "JVM_ARGS",
    "LOGGING",
    "MAIN",
    "JAVA_TOOL_OPTIONS",
    "_JAVA_OPTIONS",
    "JDK_JAVA_OPTIONS",
)


class JenaReleaseError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class JenaReleaseResult:
    conforms: bool
    report_bytes: bytes
    report_hash: str
    telemetry_bytes: bytes
    validated_data_hash: str
    validated_evidence_hash: str
    validated_cutoff_date: str
    contract_hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "contract_hashes",
            MappingProxyType(dict(sorted(self.contract_hashes.items()))),
        )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _load_canonical_json(path: Path, code: str) -> tuple[dict[str, object], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise JenaReleaseError(code) from None
    if not isinstance(value, dict) or raw != _canonical_json(value):
        raise JenaReleaseError(code)
    return value, raw


def _contract_hashes() -> dict[str, str]:
    return {
        relative: sha256((_PROJECT_ROOT / relative).read_bytes()).hexdigest()
        for relative in GRAPH_CONTRACT_RELATIVE_PATHS
    }


def run_jena_release_validation(
    *,
    data_path: Path,
    evidence_path: Path,
    expected_path: Path,
    jena_home: Path,
    fuseki_home: Path,
    cutoff_date: date,
    timeout_seconds: int = 1200,
    verifier_path: Path = _DEFAULT_VERIFIER,
) -> JenaReleaseResult:
    if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise JenaReleaseError("JENA_TIMEOUT_INVALID")
    inputs = (data_path, evidence_path, expected_path, verifier_path)
    if any(not path.is_file() for path in inputs):
        raise JenaReleaseError("JENA_INPUT_MISSING")
    if not jena_home.is_dir() or not fuseki_home.is_dir():
        raise JenaReleaseError("JENA_RUNTIME_MISSING")

    environment = os.environ.copy()
    for name in _RUNTIME_VARIABLES:
        environment.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="financial-agent-jena-release-") as root:
        report_path = Path(root) / "validation.json"
        telemetry_path = Path(root) / "telemetry.json"
        command = (
            sys.executable,
            str(verifier_path.resolve()),
            "--jena-home",
            str(jena_home.resolve()),
            "--fuseki-home",
            str(fuseki_home.resolve()),
            "--data",
            str(data_path.resolve()),
            "--evidence",
            str(evidence_path.resolve()),
            "--expected",
            str(expected_path.resolve()),
            "--report",
            str(report_path),
            "--telemetry",
            str(telemetry_path),
            "--timeout-seconds",
            str(timeout_seconds),
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            env=environment,
            start_new_session=True,
        )
        try:
            process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            raise JenaReleaseError("JENA_TIMEOUT") from None
        if process.returncode != 0:
            raise JenaReleaseError("JENA_PROCESS_FAILED")

        report, report_bytes = _load_canonical_json(
            report_path, "JENA_REPORT_INVALID"
        )
        _, telemetry_bytes = _load_canonical_json(
            telemetry_path, "JENA_TELEMETRY_INVALID"
        )

    data_hash = sha256(data_path.read_bytes()).hexdigest()
    evidence_hash = sha256(evidence_path.read_bytes()).hexdigest()
    contract_hashes = _contract_hashes()
    if (
        report.get("schema_version") != "1"
        or report.get("conforms") is not True
        or report.get("cutoff_date") != cutoff_date.isoformat()
    ):
        raise JenaReleaseError("JENA_REPORT_INVALID")
    if (
        report.get("data_hash") != data_hash
        or report.get("evidence_hash") != evidence_hash
    ):
        raise JenaReleaseError("JENA_INPUT_HASH_MISMATCH")
    if report.get("contract_hashes") != contract_hashes:
        raise JenaReleaseError("JENA_CONTRACT_HASH_MISMATCH")

    return JenaReleaseResult(
        conforms=True,
        report_bytes=report_bytes,
        report_hash=sha256(report_bytes).hexdigest(),
        telemetry_bytes=telemetry_bytes,
        validated_data_hash=data_hash,
        validated_evidence_hash=evidence_hash,
        validated_cutoff_date=cutoff_date.isoformat(),
        contract_hashes=contract_hashes,
    )
