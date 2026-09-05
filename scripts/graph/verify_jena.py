from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import resource
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

from rdflib import Graph, URIRef

from financial_agent.graph.queries import build_relation_count_query, build_relation_query


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
    "TEMP",
    "TMP",
    "TMPDIR",
)
TEMP_ENVIRONMENT_VARIABLES = ("TMPDIR", "TEMP", "TMP")
STANDARD_TEMP_PARENTS = (Path("/tmp"), Path("/var/tmp"), Path("/usr/tmp"))
FUSEKI_READINESS_QUERY = "SELECT ?g WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 1"


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
    stdout_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        if stdout_path is None:
            return subprocess.run(
                list(command),
                cwd=cwd,
                env=dict(environment),
                capture_output=True,
                text=True,
                shell=False,
                check=True,
            )
        with stdout_path.open("w", encoding="utf-8") as output:
            return subprocess.run(
                list(command),
                cwd=cwd,
                env=dict(environment),
                stdout=output,
                stderr=subprocess.PIPE,
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
    protected_roots = (
        ("PROJECT_ROOT", PROJECT_ROOT.resolve()),
        ("JENA_HOME", jena_home),
        ("FUSEKI_HOME", fuseki_home),
    )

    def protected_label(candidate: Path) -> str | None:
        for label, protected_root in protected_roots:
            if candidate == protected_root or candidate.is_relative_to(protected_root):
                return label
        return None

    environment_candidates: list[Path] = []
    for variable in TEMP_ENVIRONMENT_VARIABLES:
        raw_candidate = os.environ.get(variable)
        if not raw_candidate:
            continue
        try:
            lexical_candidate = Path(raw_candidate).expanduser().absolute()
        except (OSError, RuntimeError):
            continue
        label = protected_label(lexical_candidate)
        if label is not None:
            raise VerificationFailure(
                "temporary_state",
                f"{variable} must be outside {label}: {lexical_candidate}",
            )
        try:
            resolved_candidate = lexical_candidate.resolve()
        except (OSError, RuntimeError):
            continue
        label = protected_label(resolved_candidate)
        if label is not None:
            raise VerificationFailure(
                "temporary_state",
                f"{variable} must be outside {label}: {resolved_candidate}",
            )
        environment_candidates.append(resolved_candidate)

    for candidate in environment_candidates:
        if candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK):
            return candidate

    for fallback in STANDARD_TEMP_PARENTS:
        lexical_candidate = fallback.absolute()
        if protected_label(lexical_candidate) is not None:
            continue
        try:
            resolved_candidate = lexical_candidate.resolve()
        except (OSError, RuntimeError):
            continue
        if protected_label(resolved_candidate) is not None:
            continue
        if resolved_candidate.is_dir() and os.access(
            resolved_candidate, os.W_OK | os.X_OK
        ):
            return resolved_candidate

    raise VerificationFailure("temporary_state", "no safe temporary parent is available")


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


def _normalize_count_json(payload: str, stage: str) -> int:
    try:
        document = json.loads(payload)
        variables = document["head"]["vars"]
        bindings = document["results"]["bindings"]
        value = bindings[0]["binding_count"]["value"]
        count = int(value)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as error:
        raise VerificationFailure(stage, "malformed SPARQL count result") from error
    if variables != ["binding_count"] or len(bindings) != 1 or count < 0:
        raise VerificationFailure(stage, "SPARQL count result is invalid")
    return count


def _load_expected(
    path: Path,
) -> tuple[str, date, dict[str, list[dict[str, str]]], dict[str, int]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        version = document["dataset_version"]
        cutoff = date.fromisoformat(document["cutoff_date"])
        queries = document["queries"]
        counts = document["binding_counts"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise VerificationFailure(
            "expected_bindings", "invalid expected-bindings document"
        ) from error
    if (
        not isinstance(version, str)
        or not version
        or document.get("schema_version") != "2"
        or not isinstance(queries, dict)
        or set(queries) != set(QUERY_IDS)
        or not isinstance(counts, dict)
        or set(counts) != set(QUERY_IDS)
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts.values())
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
        if len(normalized[query_id]) > counts[query_id]:
            raise VerificationFailure(
                "expected_bindings", f"{query_id} sample exceeds its binding count"
            )
    return version, cutoff, normalized, counts


def _write_validation_inputs(
    *,
    riot: Path,
    temporary_root: Path,
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
    shapes_union = temporary_root / "validation-shapes.ttl"
    _run(
        "shacl_prepare",
        [str(riot), "--merge", "--output=TTL", *(str(path) for path in SHAPE_PATHS)],
        environment=environment,
        stdout_path=shapes_union,
    )
    return context, shapes_union


def _check_shacl_endpoint(
    endpoint: str,
    shapes_path: Path,
    *,
    timeout: float,
) -> None:
    request = Request(
        endpoint,
        data=shapes_path.read_bytes(),
        headers={
            "Accept": "text/turtle",
            "Content-Type": "text/turtle",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as error:
        raise VerificationFailure("shacl", f"loopback validation failed: {error}") from error
    try:
        report = Graph().parse(data=payload, format="turtle")
    except Exception as error:
        raise VerificationFailure("shacl", "validation report is not Turtle") from error
    conforms = tuple(
        report.objects(
            None,
            URIRef("http://www.w3.org/ns/shacl#conforms"),
        )
    )
    if not conforms or not all(value.toPython() is True for value in conforms):
        component = next(
            report.objects(
                None,
                URIRef("http://www.w3.org/ns/shacl#sourceConstraintComponent"),
            ),
            None,
        )
        detail = "validation did not report sh:conforms true"
        if component is not None:
            detail = f"validation failed constraint={component}"
        source_shape = next(
            report.objects(
                None,
                URIRef("http://www.w3.org/ns/shacl#sourceShape"),
            ),
            None,
        )
        if source_shape is not None:
            detail = f"{detail} shape={source_shape}"
        result_path = next(
            report.objects(
                None,
                URIRef("http://www.w3.org/ns/shacl#resultPath"),
            ),
            None,
        )
        if result_path is not None:
            detail = f"{detail} path={result_path}"
        raise VerificationFailure("shacl", detail)


def _render_fuseki_config(
    template: str,
    *,
    tdb2_location: Path,
    include_shacl: bool,
) -> str:
    if template.count("__TDB2_LOCATION__") != 1:
        raise VerificationFailure(
            "fuseki_config", "assembler placeholder must occur exactly once"
        )
    rendered = template.replace("__TDB2_LOCATION__", str(tdb2_location))
    if not include_shacl:
        return rendered
    marker = "  fuseki:dataset <#dataset> ."
    if rendered.count(marker) != 1:
        raise VerificationFailure("fuseki_config", "dataset marker must occur exactly once")
    shacl_endpoint = (
        "  fuseki:endpoint [\n"
        "    fuseki:operation fuseki:shacl ;\n"
        '    fuseki:name "shacl"\n'
        "  ] ;\n"
    )
    return rendered.replace(marker, shacl_endpoint + marker)


def _query_files(
    root: Path,
    dataset_version: str,
    expected: Mapping[str, list[dict[str, str]]],
) -> tuple[dict[str, Path], dict[str, Path]]:
    paths: dict[str, Path] = {}
    count_paths: dict[str, Path] = {}
    for query_id in QUERY_IDS:
        path = root / f"{query_id}.rq"
        relation_ids = tuple(
            sorted({row["relation_assertion_id"] for row in expected[query_id]})
        )
        path.write_text(
            build_relation_query(
                query_id,
                dataset_version,
                relation_ids=relation_ids or None,
            ),
            encoding="utf-8",
        )
        paths[query_id] = path
        count_path = root / f"{query_id}-count.rq"
        count_path.write_text(
            build_relation_count_query(query_id, dataset_version),
            encoding="utf-8",
        )
        count_paths[query_id] = count_path
    return paths, count_paths


def _run_cli_queries(
    *,
    tdbquery: Path,
    tdb2_location: Path,
    query_paths: Mapping[str, Path],
    count_query_paths: Mapping[str, Path],
    expected: Mapping[str, list[dict[str, str]]],
    expected_counts: Mapping[str, int],
    environment: Mapping[str, str],
) -> None:
    for query_id in QUERY_IDS:
        count_result = _run(
            "tdb2_query",
            [
                str(tdbquery),
                "--optimize=false",
                "--loc",
                str(tdb2_location),
                "--query",
                str(count_query_paths[query_id]),
                "--results=JSON",
            ],
            environment=environment,
        )
        if _normalize_count_json(count_result.stdout, "tdb2_query") != expected_counts[query_id]:
            raise VerificationFailure("tdb2_query", f"binding count differs for {query_id}")
        result = _run(
            "tdb2_query",
            [
                str(tdbquery),
                "--optimize=false",
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


def _wait_for_fuseki(process: subprocess.Popen[str], endpoint: str) -> None:
    deadline = monotonic_time.monotonic() + 20.0
    while monotonic_time.monotonic() < deadline:
        if process.poll() is not None:
            raise VerificationFailure("fuseki_start", f"Fuseki exited with {process.returncode}")
        try:
            _http_query(
                endpoint,
                FUSEKI_READINESS_QUERY,
                timeout=1.0,
                stage="fuseki_start",
            )
            return
        except VerificationFailure:
            monotonic_time.sleep(0.1)
    raise VerificationFailure("fuseki_start", "loopback query endpoint did not become ready")


def _run_http_queries(
    endpoint: str,
    query_paths: Mapping[str, Path],
    count_query_paths: Mapping[str, Path],
    expected: Mapping[str, list[dict[str, str]]],
    expected_counts: Mapping[str, int],
) -> None:
    for query_id in QUERY_IDS:
        count_payload = _http_query(
            endpoint,
            count_query_paths[query_id].read_text(encoding="utf-8"),
            timeout=60.0,
            stage="fuseki_query",
        )
        if _normalize_count_json(count_payload, "fuseki_query") != expected_counts[query_id]:
            raise VerificationFailure("fuseki_query", f"binding count differs for {query_id}")
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
    tdbloader = _resolve_executable(jena_home, "bin/tdb2.tdbloader")
    tdbquery = _resolve_executable(jena_home, "bin/tdb2.tdbquery")
    fuseki_server = _resolve_executable(fuseki_home, "fuseki-server")
    base_environment = _sanitized_ambient_environment()
    java, java_major = _verified_java(base_environment)
    temporary_parent = _validated_temp_parent(
        jena_home=jena_home,
        fuseki_home=fuseki_home,
    )
    dataset_version, cutoff, expected, expected_counts = _load_expected(expected_path)

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
        context, shapes_union = _write_validation_inputs(
            riot=riot,
            temporary_root=temporary_root,
            cutoff=cutoff,
            environment=environment,
        )
        _run(
            "tdb2_load_contract",
            [
                str(tdbloader),
                "--loc",
                str(tdb2_location),
                "--graph=urn:validation:financial-product:contract",
                *(str(path) for path in TBOX_PATHS),
                str(context),
            ],
            environment=environment,
        )
        _run(
            "tdb2_load",
            [str(tdbloader), "--loc", str(tdb2_location), str(data), str(evidence)],
            environment=environment,
        )
        query_paths, count_query_paths = _query_files(
            temporary_root,
            dataset_version,
            expected,
        )
        _run_cli_queries(
            tdbquery=tdbquery,
            tdb2_location=tdb2_location,
            query_paths=query_paths,
            count_query_paths=count_query_paths,
            expected=expected,
            expected_counts=expected_counts,
            environment=environment,
        )

        template = ASSEMBLER_TEMPLATE.read_text(encoding="utf-8")
        rendered = temporary_root / "financial-product.ttl"
        rendered.write_text(
            _render_fuseki_config(
                template,
                tdb2_location=tdb2_location,
                include_shacl=True,
            ),
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
                )
                _check_shacl_endpoint(
                    f"{base_url}/shacl?graph=union",
                    shapes_union,
                    timeout=float(arguments.timeout_seconds),
                )
        finally:
            _stop_process(fuseki_process)

        rendered.write_text(
            _render_fuseki_config(
                template,
                tdb2_location=tdb2_location,
                include_shacl=False,
            ),
            encoding="utf-8",
        )
        fuseki_process = None
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
                )
                _run_http_queries(
                    endpoint,
                    query_paths,
                    count_query_paths,
                    expected,
                    expected_counts,
                )
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


def _sha256_path(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _contract_hashes() -> dict[str, str]:
    return {
        path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix(): _sha256_path(path)
        for path in (*TBOX_PATHS, *SHAPE_PATHS)
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json(path: Path | None, value: object) -> None:
    if path is None:
        return
    path.write_bytes(_canonical_json(value))


def _peak_rss_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify Graph Phase 1 with Apache Jena 6.0.0")
    parser.add_argument("--jena-home", required=True)
    parser.add_argument("--fuseki-home", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--telemetry", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    return parser


def main() -> int:
    started = monotonic_time.monotonic()
    arguments = _parser().parse_args()
    if arguments.timeout_seconds <= 0:
        print("stage=arguments error=timeout must be positive", file=sys.stderr)
        return 1
    try:
        summary = verify(arguments)
    except VerificationFailure as error:
        print(f"stage={error.stage} error={error.detail}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"stage=unexpected error={type(error).__name__}: {error}", file=sys.stderr)
        return 1
    _, cutoff, _, _ = _load_expected(Path(arguments.expected))
    report = {
        "conforms": True,
        "contract_hashes": _contract_hashes(),
        "cutoff_date": cutoff.isoformat(),
        "data_hash": _sha256_path(Path(arguments.data)),
        "evidence_hash": _sha256_path(Path(arguments.evidence)),
        "fuseki_version": summary["fuseki_version"],
        "java_version": summary["java_version"],
        "jena_version": summary["jena_version"],
        "schema_version": "1",
        "stages": {
            key: value
            for key, value in summary.items()
            if key
            not in {
                "java_version",
                "jena_version",
                "fuseki_version",
            }
        },
    }
    telemetry = {
        "elapsed_seconds": round(monotonic_time.monotonic() - started, 6),
        "peak_rss_bytes": _peak_rss_bytes(),
        "schema_version": "1",
    }
    _write_json(arguments.report, report)
    _write_json(arguments.telemetry, telemetry)
    for key, value in summary.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
