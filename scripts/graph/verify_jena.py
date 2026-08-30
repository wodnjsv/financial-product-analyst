from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time as monotonic_time
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from financial_agent.graph.queries import build_relation_query


REQUIRED_VERSION = "6.0.0"
QUERY_IDS = ("managedBy", "issuedBy", "tracksIndex", "holdsSecurity", "hasShareClass")
RESULT_VARIABLES = (
    "subject_id",
    "predicate_id",
    "object_id",
    "relation_assertion_id",
    "evidence_id",
    "dataset_version",
    "valid_from",
    "valid_to",
)
REQUIRED_BINDING_KEYS = frozenset(RESULT_VARIABLES[:6])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TBOX_PATHS = tuple(
    PROJECT_ROOT / "ontology" / name
    for name in ("common.ttl", "bond_kr.ttl", "etf_kr.ttl", "etf_gl.ttl", "fund_pub.ttl")
)
SHAPE_PATHS = (
    PROJECT_ROOT / "ontology" / "shapes" / "common.shacl.ttl",
    PROJECT_ROOT / "ontology" / "shapes" / "domain.shacl.ttl",
)
ASSEMBLER_TEMPLATE = PROJECT_ROOT / "config" / "fuseki" / "financial-product.ttl"
RUNTIME_CUSTOMIZATION_VARIABLES = (
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
    "TMP",
    "TMPDIR",
)


class VerificationFailure(RuntimeError):
    def __init__(self, stage: str, detail: str) -> None:
        self.stage = stage
        self.detail = detail
        super().__init__(f"{stage}: {detail}")


def _run(
    stage: str,
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            shell=False,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "command failed").strip().splitlines()
        raise VerificationFailure(stage, detail[-1] if detail else "command failed") from error


def _resolve_home(path: str, label: str) -> Path:
    home = Path(path).expanduser().resolve()
    if not home.is_dir():
        raise VerificationFailure("version", f"{label} is not a directory: {home}")
    return home


def _resolve_executable(home: Path, relative_path: str) -> Path:
    executable = (home / relative_path).resolve()
    if not executable.is_relative_to(home) or not executable.is_file():
        raise VerificationFailure("version", f"missing executable below {home}: {relative_path}")
    if not os.access(executable, os.X_OK):
        raise VerificationFailure("version", f"executable is not runnable: {executable}")
    return executable


def _reported_version(
    stage: str,
    command: Sequence[str],
    environment: Mapping[str, str],
) -> str:
    result = _run(stage, command, environment=environment)
    output = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"\bversion\s+([0-9]+\.[0-9]+\.[0-9]+)\b", output, re.IGNORECASE)
    if match is None:
        raise VerificationFailure(stage, "version output was not recognized")
    version = match.group(1)
    if version != REQUIRED_VERSION:
        raise VerificationFailure(stage, f"required {REQUIRED_VERSION}, found {version}")
    return version


def _sanitized_ambient_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in RUNTIME_CUSTOMIZATION_VARIABLES:
        environment.pop(variable, None)
    return environment


def _verified_java(environment: Mapping[str, str]) -> tuple[Path, int]:
    java_name = shutil.which("java", path=environment.get("PATH"))
    if java_name is None:
        raise VerificationFailure("java_version", "java was not found on PATH")
    java = Path(java_name).resolve()
    if not java.is_file() or not os.access(java, os.X_OK):
        raise VerificationFailure("java_version", f"java is not executable: {java}")
    result = _run(
        "java_version",
        [str(java), "-version"],
        environment=environment,
    )
    match = re.search(r'version "([0-9]+)', f"{result.stdout}\n{result.stderr}")
    if match is None:
        raise VerificationFailure("java_version", "java version output was not recognized")
    major = int(match.group(1))
    if major < 21:
        raise VerificationFailure("java_version", f"Java 21 or newer is required, found {major}")
    return java, major


def _validated_temp_parent(*, jena_home: Path, fuseki_home: Path) -> Path:
    temporary_parent = Path(tempfile.gettempdir()).resolve()
    protected_roots = (
        ("PROJECT_ROOT", PROJECT_ROOT.resolve()),
        ("JENA_HOME", jena_home),
        ("FUSEKI_HOME", fuseki_home),
    )
    for label, protected_root in protected_roots:
        if temporary_parent == protected_root or temporary_parent.is_relative_to(
            protected_root
        ):
            raise VerificationFailure(
                "temporary_state",
                f"temporary parent must be outside {label}: {temporary_parent}",
            )
    return temporary_parent


def _runtime_environment(
    *,
    base_environment: Mapping[str, str],
    jena_home: Path,
    fuseki_home: Path,
    java: Path,
    temporary_root: Path,
) -> dict[str, str]:
    environment = dict(base_environment)
    environment.update(
        {
            "JENA_HOME": str(jena_home),
            "FUSEKI_HOME": str(fuseki_home),
            "FUSEKI_BASE": str(temporary_root / "fuseki-base"),
            "JAVA": str(java),
            "MAIN": "main",
            "TMPDIR": str(temporary_root),
        }
    )
    return environment


def _input_path(value: str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise VerificationFailure("arguments", f"{label} is not a file: {path}")
    return path


def _normalized_binding(binding: Mapping[str, Any], stage: str) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, term in binding.items():
        if name not in RESULT_VARIABLES or not isinstance(term, Mapping):
            raise VerificationFailure(stage, "unexpected SPARQL binding structure")
        value = term.get("value")
        if not isinstance(value, str):
            raise VerificationFailure(stage, f"binding {name} has no string value")
        normalized[name] = value
    if not REQUIRED_BINDING_KEYS <= normalized.keys():
        raise VerificationFailure(stage, "SPARQL binding is missing a required evidence field")
    return dict(sorted(normalized.items()))


def _normalize_sparql_json(payload: str, stage: str) -> list[dict[str, str]]:
    try:
        document = json.loads(payload)
        variables = document["head"]["vars"]
        bindings = document["results"]["bindings"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise VerificationFailure(stage, "malformed SPARQL Results JSON") from error
    if variables != list(RESULT_VARIABLES) or not isinstance(bindings, list):
        raise VerificationFailure(stage, "SPARQL result variables do not match the query contract")
    normalized = [_normalized_binding(binding, stage) for binding in bindings]
    return sorted(normalized, key=lambda row: tuple(row.items()))


def _load_expected(path: Path) -> tuple[str, date, dict[str, list[dict[str, str]]]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        version = document["dataset_version"]
        cutoff = date.fromisoformat(document["cutoff_date"])
        queries = document["queries"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise VerificationFailure(
            "expected_bindings", "invalid expected-bindings document"
        ) from error
    if (
        not isinstance(version, str)
        or not version
        or not isinstance(queries, dict)
        or set(queries) != set(QUERY_IDS)
    ):
        raise VerificationFailure(
            "expected_bindings", "expected queries or dataset version are invalid"
        )

    normalized: dict[str, list[dict[str, str]]] = {}
    for query_id in QUERY_IDS:
        rows = queries[query_id]
        if not isinstance(rows, list):
            raise VerificationFailure("expected_bindings", f"{query_id} bindings must be a list")
        normalized_rows: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, Mapping) or not REQUIRED_BINDING_KEYS <= row.keys():
                raise VerificationFailure("expected_bindings", f"{query_id} binding is incomplete")
            if not set(row) <= set(RESULT_VARIABLES) or not all(
                isinstance(value, str) for value in row.values()
            ):
                raise VerificationFailure("expected_bindings", f"{query_id} binding is invalid")
            normalized_rows.append(dict(sorted(row.items())))
        normalized[query_id] = sorted(normalized_rows, key=lambda row: tuple(row.items()))
    return version, cutoff, normalized


def _write_validation_inputs(
    *,
    riot: Path,
    temporary_root: Path,
    data: Path,
    evidence: Path,
    cutoff: date,
    environment: Mapping[str, str],
) -> tuple[Path, Path]:
    cutoff_end = datetime.combine(
        cutoff + timedelta(days=1),
        time.min,
        timezone(timedelta(hours=9)),
    )
    context = temporary_root / "validation-context.ttl"
    context.write_text(
        "@prefix v: <urn:validation:financial-product#> .\n"
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
        "<urn:validation:financial-product:context>\n"
        f'  v:cutoffDate "{cutoff.isoformat()}"^^xsd:date ;\n'
        f'  v:cutoffEndExclusive "{cutoff_end.isoformat()}"^^xsd:dateTime .\n',
        encoding="utf-8",
    )
    data_union = temporary_root / "validation-data.ttl"
    shapes_union = temporary_root / "validation-shapes.ttl"
    data_result = _run(
        "shacl_prepare",
        [
            str(riot),
            "--merge",
            "--output=TTL",
            *(str(path) for path in TBOX_PATHS),
            str(data),
            str(evidence),
            str(context),
        ],
        environment=environment,
    )
    data_union.write_text(data_result.stdout, encoding="utf-8")
    shapes_result = _run(
        "shacl_prepare",
        [str(riot), "--merge", "--output=TTL", *(str(path) for path in SHAPE_PATHS)],
        environment=environment,
    )
    shapes_union.write_text(shapes_result.stdout, encoding="utf-8")
    return data_union, shapes_union


def _check_shacl(
    shacl: Path,
    data_union: Path,
    shapes_union: Path,
    environment: Mapping[str, str],
) -> None:
    result = _run(
        "shacl",
        [str(shacl), "validate", "--shapes", str(shapes_union), "--data", str(data_union)],
        environment=environment,
    )
    if re.search(r"(?:sh:conforms|/ns/shacl#conforms>)\s+true\b", result.stdout) is None:
        raise VerificationFailure("shacl", "validation did not report sh:conforms true")


def _query_files(root: Path, dataset_version: str) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for query_id in QUERY_IDS:
        path = root / f"{query_id}.rq"
        path.write_text(build_relation_query(query_id, dataset_version), encoding="utf-8")
        paths[query_id] = path
    return paths


def _run_cli_queries(
    *,
    tdbquery: Path,
    tdb2_location: Path,
    query_paths: Mapping[str, Path],
    expected: Mapping[str, list[dict[str, str]]],
    environment: Mapping[str, str],
) -> None:
    for query_id in QUERY_IDS:
        result = _run(
            "tdb2_query",
            [
                str(tdbquery),
                "--loc",
                str(tdb2_location),
                "--query",
                str(query_paths[query_id]),
                "--results=JSON",
            ],
            environment=environment,
        )
        actual = _normalize_sparql_json(result.stdout, "tdb2_query")
        if actual != expected[query_id]:
            raise VerificationFailure("tdb2_query", f"normalized bindings differ for {query_id}")


def _loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _http_query(endpoint: str, sparql: str, *, timeout: float, stage: str) -> str:
    request = Request(
        endpoint,
        data=urlencode({"query": sparql}).encode("ascii"),
        headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as error:
        raise VerificationFailure(stage, f"loopback query failed: {error}") from error


def _wait_for_fuseki(process: subprocess.Popen[str], endpoint: str, sparql: str) -> None:
    deadline = monotonic_time.monotonic() + 20.0
    while monotonic_time.monotonic() < deadline:
        if process.poll() is not None:
            raise VerificationFailure("fuseki_start", f"Fuseki exited with {process.returncode}")
        try:
            _http_query(endpoint, sparql, timeout=1.0, stage="fuseki_start")
            return
        except VerificationFailure:
            monotonic_time.sleep(0.1)
    raise VerificationFailure("fuseki_start", "loopback query endpoint did not become ready")


def _run_http_queries(
    endpoint: str,
    query_paths: Mapping[str, Path],
    expected: Mapping[str, list[dict[str, str]]],
) -> None:
    for query_id in QUERY_IDS:
        payload = _http_query(
            endpoint,
            query_paths[query_id].read_text(encoding="utf-8"),
            timeout=5.0,
            stage="fuseki_query",
        )
        actual = _normalize_sparql_json(payload, "fuseki_query")
        if actual != expected[query_id]:
            raise VerificationFailure("fuseki_query", f"normalized bindings differ for {query_id}")


def _blocked_status(request: Request, stage: str) -> None:
    try:
        with urlopen(request, timeout=5.0) as response:
            status = response.status
    except HTTPError as error:
        status = error.code
    except (URLError, TimeoutError) as error:
        raise VerificationFailure(stage, f"loopback rejection check failed: {error}") from error
    if status not in {404, 405}:
        raise VerificationFailure(stage, f"writable surface returned HTTP {status}")


def _verify_read_only(server_url: str, base_url: str) -> None:
    update_request = Request(
        f"{base_url}/update",
        data=urlencode(
            {
                "update": (
                    "INSERT DATA { "
                    "<urn:blocked:s> <urn:blocked:p> <urn:blocked:o> }"
                )
            }
        ).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    _blocked_status(update_request, "update_surface")

    graph_store_url = f"{base_url}/data?default"
    _blocked_status(Request(graph_store_url, method="GET"), "graph_store_surface")
    _blocked_status(
        Request(
            graph_store_url,
            data=b"<urn:blocked:s> <urn:blocked:p> <urn:blocked:o> .\n",
            headers={"Content-Type": "application/n-triples"},
            method="PUT",
        ),
        "graph_store_surface",
    )
    _blocked_status(
        Request(f"{server_url}/$/datasets", method="GET"),
        "admin_surface",
    )


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5.0)


def verify(arguments: argparse.Namespace) -> dict[str, str]:
    jena_home = _resolve_home(arguments.jena_home, "JENA_HOME")
    fuseki_home = _resolve_home(arguments.fuseki_home, "FUSEKI_HOME")
    data = _input_path(arguments.data, "data")
    evidence = _input_path(arguments.evidence, "evidence")
    expected_path = _input_path(arguments.expected, "expected")
    for path in (*TBOX_PATHS, *SHAPE_PATHS, ASSEMBLER_TEMPLATE):
        if not path.is_file():
            raise VerificationFailure("arguments", f"required tracked file is missing: {path}")

    riot = _resolve_executable(jena_home, "bin/riot")
    shacl = _resolve_executable(jena_home, "bin/shacl")
    tdbloader = _resolve_executable(jena_home, "bin/tdb2.tdbloader")
    tdbquery = _resolve_executable(jena_home, "bin/tdb2.tdbquery")
    fuseki_server = _resolve_executable(fuseki_home, "fuseki-server")
    base_environment = _sanitized_ambient_environment()
    java, java_major = _verified_java(base_environment)
    temporary_parent = _validated_temp_parent(
        jena_home=jena_home,
        fuseki_home=fuseki_home,
    )
    dataset_version, cutoff, expected = _load_expected(expected_path)

    fuseki_process: subprocess.Popen[str] | None = None
    with tempfile.TemporaryDirectory(
        prefix="financial-agent-jena-",
        dir=temporary_parent,
    ) as temporary_name:
        temporary_root = Path(temporary_name)
        environment = _runtime_environment(
            base_environment=base_environment,
            jena_home=jena_home,
            fuseki_home=fuseki_home,
            java=java,
            temporary_root=temporary_root,
        )
        jena_version = _reported_version(
            "jena_version",
            [str(riot), "--version"],
            environment,
        )
        fuseki_version = _reported_version(
            "fuseki_version",
            [str(fuseki_server), "--version"],
            environment,
        )
        for path in (*TBOX_PATHS, *SHAPE_PATHS, data, evidence):
            _run(
                "parse",
                [str(riot), "--validate", str(path)],
                environment=environment,
            )
        tdb2_location = temporary_root / "tdb2"
        data_union, shapes_union = _write_validation_inputs(
            riot=riot,
            temporary_root=temporary_root,
            data=data,
            evidence=evidence,
            cutoff=cutoff,
            environment=environment,
        )
        _check_shacl(shacl, data_union, shapes_union, environment)
        _run(
            "tdb2_load",
            [str(tdbloader), "--loc", str(tdb2_location), str(data), str(evidence)],
            environment=environment,
        )
        query_paths = _query_files(temporary_root, dataset_version)
        _run_cli_queries(
            tdbquery=tdbquery,
            tdb2_location=tdb2_location,
            query_paths=query_paths,
            expected=expected,
            environment=environment,
        )

        template = ASSEMBLER_TEMPLATE.read_text(encoding="utf-8")
        if template.count("__TDB2_LOCATION__") != 1:
            raise VerificationFailure(
                "fuseki_config", "assembler placeholder must occur exactly once"
            )
        rendered = temporary_root / "financial-product.ttl"
        rendered.write_text(
            template.replace("__TDB2_LOCATION__", str(tdb2_location)),
            encoding="utf-8",
        )
        port = _loopback_port()
        server_url = f"http://127.0.0.1:{port}"
        base_url = f"{server_url}/financial-product"
        endpoint = f"{base_url}/query"
        log_path = temporary_root / "fuseki.log"
        try:
            with log_path.open("w", encoding="utf-8") as log_file:
                fuseki_process = subprocess.Popen(
                    [
                        str(fuseki_server),
                        "--conf",
                        str(rendered),
                        "--port",
                        str(port),
                        "--localhost",
                    ],
                    cwd=temporary_root,
                    env=environment,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=False,
                )
                _wait_for_fuseki(
                    fuseki_process,
                    endpoint,
                    query_paths[QUERY_IDS[0]].read_text(encoding="utf-8"),
                )
                _run_http_queries(endpoint, query_paths, expected)
                _verify_read_only(server_url, base_url)
        finally:
            _stop_process(fuseki_process)

    return {
        "java_version": str(java_major),
        "jena_version": jena_version,
        "fuseki_version": fuseki_version,
        "parse": "pass",
        "shacl": "pass",
        "tdb2_load": "pass",
        "tdb2_query": "pass",
        "fuseki_query": "pass",
        "update_surface": "blocked",
        "graph_store_surface": "blocked",
        "admin_surface": "blocked",
        "temporary_state": "removed",
        "fuseki_process": "terminated",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify Graph Phase 1 with Apache Jena 6.0.0")
    parser.add_argument("--jena-home", required=True)
    parser.add_argument("--fuseki-home", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--expected", required=True)
    return parser


def main() -> int:
    try:
        summary = verify(_parser().parse_args())
    except VerificationFailure as error:
        print(f"stage={error.stage} error={error.detail}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"stage=unexpected error={type(error).__name__}: {error}", file=sys.stderr)
        return 1
    for key, value in summary.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
