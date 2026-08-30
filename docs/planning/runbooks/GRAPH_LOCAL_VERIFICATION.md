# Graph Phase 1 Local Verification

This runbook verifies the tracked ontology, SHACL shapes, generated synthetic
N-Quads, temporary TDB2 load, shared competency queries, and query-only Fuseki
configuration against Apache Jena and Fuseki 6.0.0. The verifier never
downloads a binary or writes runtime state into the repository.

## Prerequisites

- Python 3.12 with the project `graph` and `dev` dependency groups installed
- Java 21 or newer
- The official Apache Jena 6.0.0 and Apache Jena Fuseki 6.0.0 binary archives
- Network access only for the explicit archive installation step below
- Permission to bind a temporary loopback-only TCP port

Confirm Java before installing Jena:

```bash
java -version
```

## Install and verify the official binaries

Keep archives and extracted homes outside the repository. These commands use a
new temporary directory and verify each archive against Apache's published
`.sha512` file before extraction.

```bash
GRAPH_JENA_DIST_DIR="$(mktemp -d)"
cd "$GRAPH_JENA_DIST_DIR"

curl -fLO https://archive.apache.org/dist/jena/binaries/apache-jena-6.0.0.tar.gz
curl -fLO https://archive.apache.org/dist/jena/binaries/apache-jena-6.0.0.tar.gz.sha512
curl -fLO https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-6.0.0.tar.gz
curl -fLO https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-6.0.0.tar.gz.sha512

shasum -a 512 -c apache-jena-6.0.0.tar.gz.sha512
shasum -a 512 -c apache-jena-fuseki-6.0.0.tar.gz.sha512

tar -xzf apache-jena-6.0.0.tar.gz
tar -xzf apache-jena-fuseki-6.0.0.tar.gz

export JENA_HOME="$GRAPH_JENA_DIST_DIR/apache-jena-6.0.0"
export FUSEKI_HOME="$GRAPH_JENA_DIST_DIR/apache-jena-fuseki-6.0.0"
export RUN_JENA_INTEGRATION=1
```

The published SHA-512 values for these exact archives are:

```text
apache-jena-6.0.0.tar.gz
c66b413f0c97e465c8a5a71f2718116134c65efa71205e136a42ad0ee6d39deece0dcbcc99801d806e4b60af5fe886c72eb53c77bc464fe9d2d0f1ba2d3ec1fe

apache-jena-fuseki-6.0.0.tar.gz
8b14dcefade409bb4efd94e05291ea46d50508bf175f6f163f328d1d80183559a4c5b75806802283802a2879405a132b9b311e2277f784a784fa66ce4a9d8722
```

Confirm the extracted runtimes:

```bash
"$JENA_HOME/bin/riot" --version
"$FUSEKI_HOME/fuseki-server" --version
```

Both commands must report `6.0.0`. A different patch release does not satisfy
this exact-runtime gate.

## Run the always-on Graph gate

From the repository root:

```bash
PYTHONPATH=src .venv/bin/python \
  -m pytest tests/graph -m 'not jena_integration' -q
```

This gate requires no external service and covers RDFLib parsing, pySHACL,
projection determinism, manifest behavior, the shared SPARQL queries, and the
read-only client.

## Run the exact Jena/Fuseki gate

All three variables are mandatory. Selecting the marker without them is an
explicit failure, never a skip.

```bash
RUN_JENA_INTEGRATION=1 \
JENA_HOME="$JENA_HOME" \
FUSEKI_HOME="$FUSEKI_HOME" \
PYTHONPATH=src \
  .venv/bin/python -m pytest tests/graph/test_jena_integration.py \
  -m jena_integration -q
```

The integration test creates synthetic N-Quads and exact expected bindings in
pytest's temporary directory, then invokes `scripts/graph/verify_jena.py`. A
successful runner summary contains:

```text
java_version=<21-or-newer>
jena_version=6.0.0
fuseki_version=6.0.0
parse=pass
shacl=pass
tdb2_load=pass
tdb2_query=pass
fuseki_query=pass
update_surface=blocked
graph_store_surface=blocked
temporary_state=removed
fuseki_process=terminated
```

The runner validates the five TBox files, two SHACL files, and both N-Quads;
validates their union with Jena SHACL; loads both named graphs into a temporary
TDB2 database; executes the five shared competency queries through the CLI and
the loopback-only Fuseki query endpoint; compares every normalized binding;
and confirms that update and Graph Store surfaces are unavailable.

## Cleanup behavior

The runner owns its generated validation files, query files, rendered
assembler, Fuseki log, and TDB2 database. It terminates Fuseki in `finally` and
removes the enclosing temporary directory whether the gate passes or fails.
It does not modify either extracted binary home.

The external archive directory is intentionally caller-owned so it can be
reused for later exact-runtime verification. Remove that directory manually
when it is no longer needed; no repository cleanup is required.

## Scope of the result

Passing this runbook proves local Graph Phase 1 compatibility with Apache Jena,
TDB2, and a query-only Fuseki 6.0.0 service. It does not establish NCP network
policy, private-subnet placement, persistent-volume permissions, latency,
backup and recovery, high availability, dataset readiness, dataset activation,
or full Graph question coverage. Those remain separate NCP and later-phase
acceptance gates.
