# Final Rebuild and Scalable Graph Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild and activate the complete Stage 03/04 dataset with SEC
N-PORT 2026 Q2 and a bounded, evidence-preserving Graph release gate.

**Architecture:** PostgreSQL remains the authority. A guarded cleanup removes
only the known inactive incomplete target; the complete structured dataset is
then rebuilt and the verified DART corpus is copied locally. Graph release uses
a deterministic batch preflight and two identical exports before Apache Jena
performs full SHACL, TDB2, Fuseki, and read-only validation.

**Tech Stack:** Python 3.12, PostgreSQL 15, SQLAlchemy 2 async Core, pgvector,
RDFLib/pySHACL for bounded tests, Apache Jena/Fuseki 6.0.0, pytest 8.

**Spec:**
`docs/planning/specs/2026-09-04-final-rebuild-and-scalable-graph-validation-design.md`

## Global Constraints

- Target version is exactly `competition-2026-08-24-final-v1`.
- Source DART version is exactly `organizer-dart-2026-08-24-v2`.
- Cutoff is exactly `2026-08-24`.
- Ingest only SEC N-PORT 2026 Q2; do not ingest Q1 or older quarters.
- Preserve raw source objects and the source DART dataset.
- Do not call DART or NCP.
- Do not modify ontology terms, SHACL constraints, DART chunk text, or vectors.
- Keep raw inputs, databases, vectors, Graph outputs, logs, secrets, and
  telemetry outside Git.
- Every database mutation targets an explicit inactive `building` version.
- Any validation failure leaves the target inactive.

---

### Task 1: Guarded cleanup of the incomplete target

**Files:**
- Create: `src/financial_agent/ingestion/final_rebuild.py`
- Modify: `src/financial_agent/ingestion/cli.py`
- Create: `tests/ingestion/test_final_rebuild.py`
- Modify: `tests/ingestion/test_dart_corpus_cli.py`

**Interfaces:**
- Produces:

```python
FINAL_DATASET_VERSION = "competition-2026-08-24-final-v1"

@dataclass(frozen=True, slots=True)
class IncompleteDatasetCleanupReport:
    dataset_version: str
    deleted_counts: Mapping[str, int]

async def remove_incomplete_final_dataset(
    engine: AsyncEngine,
    *,
    dataset_version: str,
) -> IncompleteDatasetCleanupReport: ...
```

- [ ] **Step 1: Write PostgreSQL tests for the safety boundary**

Create fixtures proving that the function refuses a blank or different target,
an absent target, a non-`building` target, the active target, and a target with
a passing validation run. Add a successful case containing dataset-scoped
catalog, relation, observation, Evidence, document, chunk, and embedding rows;
assert that only those target rows are removed and a second dataset is byte-for-
byte/count-for-count unchanged.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/ingestion/test_final_rebuild.py -q
```

Expected: collection/import failure because `final_rebuild` does not exist.

- [ ] **Step 3: Implement the guarded transaction**

Use one transaction, lock the exact dataset row, verify all guards, collect
counts, delete reverse dependency order using the registered SQLAlchemy
metadata for tables carrying `dataset_version`, and delete the dataset row
last. Convert all guard failures to stable `FinalRebuildError.code` values.

- [ ] **Step 4: Add the explicit CLI command**

Add `reset-incomplete-final` using only
`FINANCIAL_AGENT_BUILD_DATABASE_URL` and
`FINANCIAL_AGENT_DATASET_VERSION`. Print canonical aggregate counts without
row payloads or credentials.

- [ ] **Step 5: Run focused and adjacent tests and verify GREEN**

```bash
.venv/bin/python -m pytest tests/ingestion/test_final_rebuild.py tests/ingestion/test_dart_corpus_cli.py -q
```

- [ ] **Step 6: Commit the independently useful safety boundary**

```bash
git add src/financial_agent/ingestion/final_rebuild.py src/financial_agent/ingestion/cli.py tests/ingestion/test_final_rebuild.py tests/ingestion/test_dart_corpus_cli.py
git commit -m "feat: guard incomplete final dataset cleanup"
```

### Task 2: Deterministic Graph preflight

**Files:**
- Create: `src/financial_agent/graph/preflight.py`
- Modify: `src/financial_agent/graph/cli.py`
- Create: `tests/graph/test_graph_preflight.py`
- Modify: `tests/graph/test_graph_cli.py`

**Interfaces:**
- Consumes `GraphProjectionBatch` returned by the existing repeatable-read
  repository load.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class GraphPreflightResult:
    conforms: bool
    counts: Mapping[str, int]
    violation_codes: tuple[str, ...]
    report_bytes: bytes
    report_hash: str

def validate_projection_batch(batch: GraphProjectionBatch) -> GraphPreflightResult: ...
```

- [ ] **Step 1: Write literal-fixture tests for every failure family**

Starting from the existing small valid batch, mutate one fact at a time to
prove detection of duplicate IDs, missing relation endpoints, invalid domain
or range, missing Evidence/source, reversed or post-cutoff dates, missing or
out-of-range holding weights, duplicate holding observation IDs, and relation/
observation mismatch. Assert stable sorted violation codes and canonical JSON.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
.venv/bin/python -m pytest tests/graph/test_graph_preflight.py -q
```

Expected: collection/import failure because `graph.preflight` does not exist.

- [ ] **Step 3: Implement one-pass indexed checks**

Use dictionaries and sets keyed by IDs and relation/date tuples. Do not parse
RDF, execute SPARQL, or make database queries. Return all detected stable codes
in sorted order and hash only canonical deterministic report bytes.

- [ ] **Step 4: Invoke preflight before RDF export**

Make `build_graph_snapshot` stop with `GraphBuildError` before writing N-Quads
when preflight does not conform. Persist `preflight.json` for passing builds.

- [ ] **Step 5: Run focused Graph tests and verify GREEN**

```bash
.venv/bin/python -m pytest tests/graph/test_graph_preflight.py tests/graph/test_graph_cli.py tests/graph/test_graph_exporter.py -q
```

- [ ] **Step 6: Commit the preflight**

```bash
git add src/financial_agent/graph/preflight.py src/financial_agent/graph/cli.py tests/graph/test_graph_preflight.py tests/graph/test_graph_cli.py
git commit -m "feat: add deterministic graph preflight"
```

### Task 3: Deterministic expected bindings and Jena release report

**Files:**
- Modify: `src/financial_agent/graph/queries.py`
- Create: `src/financial_agent/graph/jena.py`
- Modify: `scripts/graph/verify_jena.py`
- Create: `tests/graph/test_jena_release.py`
- Modify: `tests/graph/test_jena_integration.py`

**Interfaces:**
- Produces:

```python
def build_expected_bindings(batch: GraphProjectionBatch) -> bytes: ...

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

def run_jena_release_validation(
    *,
    data_path: Path,
    evidence_path: Path,
    expected_path: Path,
    jena_home: Path,
    fuseki_home: Path,
    cutoff_date: date,
    timeout_seconds: int = 1200,
) -> JenaReleaseResult: ...
```

- [ ] **Step 1: Write expected-binding and subprocess-boundary tests**

Use literal expected JSON for all five predicates. Use a temporary executable
fixture for the wrapper boundary to prove success parsing, timeout failure,
non-zero exit failure, malformed JSON failure, input-hash mismatch failure,
and separation of deterministic report from non-deterministic telemetry.

- [ ] **Step 2: Run the focused tests and verify RED**

```bash
.venv/bin/python -m pytest tests/graph/test_jena_release.py -q
```

Expected: import failure for the new interfaces.

- [ ] **Step 3: Implement canonical expected bindings and the bounded wrapper**

Generate bindings from the projection batch without RDF queries. Launch the
tracked verifier with `shell=False`, a fixed timeout, sanitized environment,
and explicit absolute paths. Verify returned hashes against the exact input
files and tracked contract files.

- [ ] **Step 4: Make the verifier emit two JSON files**

Keep all current Jena checks. Add `--report`, `--telemetry`, and
`--timeout-seconds`; route each external command through the remaining
deadline. The report contains only deterministic outcomes, versions, and
hashes. Telemetry contains elapsed seconds and platform-normalized peak RSS.
Terminate Fuseki in every exit path.

- [ ] **Step 5: Run unit tests and the installed Jena fixture gate**

```bash
.venv/bin/python -m pytest tests/graph/test_jena_release.py -q
RUN_JENA_INTEGRATION=1 .venv/bin/python -m pytest tests/graph/test_jena_integration.py -q
```

The second command runs only when Jena/Fuseki 6.0.0 paths are configured; an
unavailable exact runtime is reported as a blocked runtime prerequisite, not a
passing test.

- [ ] **Step 6: Commit the Jena release boundary**

```bash
git add src/financial_agent/graph/queries.py src/financial_agent/graph/jena.py scripts/graph/verify_jena.py tests/graph/test_jena_release.py tests/graph/test_jena_integration.py
git commit -m "feat: add bounded Jena release validation"
```

### Task 4: Bind release validation into Graph manifests

**Files:**
- Modify: `src/financial_agent/graph/validator.py`
- Modify: `src/financial_agent/graph/manifest.py`
- Modify: `src/financial_agent/graph/cli.py`
- Modify: `tests/graph/test_graph_manifest.py`
- Modify: `tests/graph/test_graph_cli.py`

**Interfaces:**
- `build_graph_manifest` accepts either the bounded pySHACL fixture result or
  the Jena release result through a structural validation-result protocol.
- `build_graph_snapshot` requires explicit Jena/Fuseki homes for a release
  build and writes `data.nq`, `evidence.nq`, `expected-bindings.json`,
  `preflight.json`, `validation.json`, `telemetry.json`, `manifest.json`, and
  `report.json` only after all gates pass.

- [ ] **Step 1: Write failing manifest and CLI tests**

Prove that mismatched data, Evidence, cutoff, preflight, Jena report, or
contract hashes prevents manifest creation; prove telemetry changes do not
change the component-manifest hash; prove failed validation leaves no partial
output.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.venv/bin/python -m pytest tests/graph/test_graph_manifest.py tests/graph/test_graph_cli.py -q
```

- [ ] **Step 3: Implement protocol and atomic release build**

Hash deterministic preflight and Jena report bytes into schema version 2 of
the Graph component manifest. Keep telemetry outside the hash. Preserve the
existing pySHACL interface for bounded tests.

- [ ] **Step 4: Run all non-Jena Graph tests and verify GREEN**

```bash
.venv/bin/python -m pytest tests/graph -q -m 'not jena_integration'
```

- [ ] **Step 5: Commit the Graph release integration**

```bash
git add src/financial_agent/graph/validator.py src/financial_agent/graph/manifest.py src/financial_agent/graph/cli.py tests/graph/test_graph_manifest.py tests/graph/test_graph_cli.py
git commit -m "feat: bind Jena validation to graph manifests"
```

### Task 5: Final readiness and activation service

**Files:**
- Create: `src/financial_agent/ingestion/final_release.py`
- Modify: `src/financial_agent/ingestion/cli.py`
- Create: `tests/ingestion/test_final_release.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class FinalReleaseInputs:
    dataset_version: str
    postgres_manifest_hash: str
    graph_manifest_hash: str
    vector_manifest_hash: str
    evidence_manifest_hash: str

async def validate_and_activate_final_dataset(
    engine: AsyncEngine,
    *,
    inputs: FinalReleaseInputs,
    activate: bool,
) -> FinalReleaseReport: ...
```

- [ ] **Step 1: Write PostgreSQL release-gate tests**

Prove that count drift, DART count drift, vector anomaly, missing source,
manifest mismatch, failed Graph report, or fewer than four readiness components
prevents activation. Prove the passing path records one successful validation
run, four readiness rows, finishes validation, and activates atomically only
when `activate=True`.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.venv/bin/python -m pytest tests/ingestion/test_final_release.py -q
```

- [ ] **Step 3: Implement deterministic checks and stored-function calls**

Use the existing `operations.record_dataset_readiness`,
`operations.finish_dataset_validation`, and `operations.activate_dataset`
functions. Generate validation IDs and report hashes from canonical inputs,
not wall-clock values. Keep activation a final explicit option.

- [ ] **Step 4: Add `finalize-stage03-stage04` CLI command**

Require explicit paths/hashes through validated environment inputs, default to
validation-only, and require `--activate` for the final atomic call. Print only
aggregate status and hashes.

- [ ] **Step 5: Run focused and broader tests and verify GREEN**

```bash
.venv/bin/python -m pytest tests/ingestion/test_final_release.py tests/ingestion/test_final_rebuild.py tests/graph -q -m 'not jena_integration'
```

- [ ] **Step 6: Commit release activation**

```bash
git add src/financial_agent/ingestion/final_release.py src/financial_agent/ingestion/cli.py tests/ingestion/test_final_release.py
git commit -m "feat: add final dataset release gate"
```

### Task 6: Rebuild, validate, and activate the local dataset

**Files:**
- Modify: `docs/planning/tasks/2026-09-04-stage03-stage04-final-assembly-plan.md`
- Runtime outputs only under ignored source roots and `/private/tmp`.

- [ ] **Step 1: Run the complete code verification before mutation**

Run focused tests first, then all non-live tests. Verify migration head `0012`,
PostgreSQL 15, database URL, target/source state, free disk, and exact Q2 hash.

- [ ] **Step 2: Copy and reverify the Q2 ZIP**

Copy the verified download to the exact manifest object key. Re-run size and
SHA-256 checks against all official manifests before touching PostgreSQL.

- [ ] **Step 3: Remove only the guarded incomplete target**

Run `reset-incomplete-final`. Save the aggregate cleanup report outside Git and
verify the DART source dataset and active pointer are unchanged.

- [ ] **Step 4: Rebuild structured sources and carry forward DART**

Run the existing organizer/official build for the exact final version. Require
SEC N-PORT in the frozen manifest and require the build report to pass. Carry
forward DART and require exactly 2,214 documents, 7,267 coverages, 40,149
chunks, and 40,149 dimension-1,024 embeddings.

- [ ] **Step 5: Reconcile PostgreSQL, Evidence, and Vector**

Require zero missing, duplicate, stale, orphan, or wrong-dimension vectors and
no deferred foreign-key failure. Record authoritative table counts and hashes.

- [ ] **Step 6: Build Graph A and B**

Use separate temporary directories and require identical deterministic files
and component-manifest hashes. Run the Jena gate with the 1,200-second watchdog
and preserve only concise validation/telemetry reports until final comparison.

- [ ] **Step 7: Record readiness and activate**

Run finalization first without activation, inspect the four readiness records,
then run the explicit activation call. Confirm the active pointer and run
read-only SQL, Graph, Vector, and Evidence smoke queries.

- [ ] **Step 8: Final verification and documentation**

Run the broad test suite, inspect `git diff --check`, staged diff, status, and
ignored/runtime files. Update the prior runtime task with final measured facts;
do not erase the earlier failed-run history.

- [ ] **Step 9: Commit verified tracked changes only**

```bash
git add docs/planning/decisions/ADR-0048-rebuild-final-dataset-with-tiered-graph-validation.md docs/planning/specs/2026-09-04-final-rebuild-and-scalable-graph-validation-design.md docs/planning/tasks/2026-09-04-stage03-stage04-final-assembly-plan.md docs/planning/tasks/2026-09-05-final-rebuild-and-scalable-graph-validation-plan.md
git diff --cached --check
git commit -m "docs: record final stage03 stage04 activation"
```
