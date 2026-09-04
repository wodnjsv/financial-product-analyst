# Final Dataset Rebuild and Scalable Graph Validation Design

- Date: 2026-09-04
- Status: Accepted
- Decision: [ADR-0048](../decisions/ADR-0048-rebuild-final-dataset-with-tiered-graph-validation.md)

## 1. Outcome

Produce and activate one reproducible
`competition-2026-08-24-final-v1` dataset that contains:

- all eight organizer tables at the `2026-08-24` baseline;
- the frozen KRX, ECOS, SEC Series/Class, and SEC N-PORT 2026 Q2 snapshots;
- the already verified DART document corpus and BGE-M3 vectors; and
- a deterministic Graph projection that passes bounded preflight plus the full
  Apache Jena release gate.

## 2. Assumptions and Constraints

- The evaluation cutoff remains `2026-08-24` in Asia/Seoul.
- SEC N-PORT is used for the latest eligible point-in-time holdings snapshot,
  not for historical time-series analysis.
- Only `2026q2_nport.zip` is an input to this build. The locally present Q1 ZIP
  is not deleted and is not ingested.
- PostgreSQL 15 remains the authority for structured facts, Evidence,
  documents, and pgvector values.
- Graph and Vector remain projections bound back to PostgreSQL IDs.
- The organizer baseline wins on conflicting evaluation fields.
- Raw organizer data, official files, databases, graph outputs, logs, and
  embeddings remain untracked.
- No DART download, PDF extraction, rechunking, or NCP embedding request is
  permitted in this run.
- The source dataset `organizer-dart-2026-08-24-v2` must remain unchanged.
- Approximately 36 GiB is currently free. Every large phase must check its
  required reserve before starting and clean only its own temporary output.

## 3. Non-goals

- Building historical N-PORT coverage from Q1 or older years.
- Expanding the ontology or changing the meaning of any relation.
- Adding new product-source mapping heuristics.
- Re-embedding existing DART chunks.
- Implementing Stage 05 calculations, the public `/answer` API, or NCP
  deployment.
- Treating missing SEC coverage as proof that a holding does not exist.

## 4. Source Admission

The N-PORT object is admitted only when all of these values match the frozen
manifest:

| Field | Required value |
| --- | --- |
| Object name | `2026q2_nport.zip` |
| Size | `440699889` bytes |
| SHA-256 | `077cc836a978a593b29012219395fbe9c303d5e930f5be3b5f4353c3b02296fc` |
| Source code | `SEC_NPORT_2026Q2` |
| Vintage date | `2026-06-30` |
| Available at | `2026-07-09T00:00:00Z` |

The file is copied, not moved, into the object key declared by the existing
capture manifest. The source and destination hashes are checked after the
copy. A mismatch stops before any database mutation.

## 5. Bounded Target Replacement

The cleanup operation accepts one explicit dataset version and refuses to run
unless all conditions hold:

1. the requested version is exactly
   `competition-2026-08-24-final-v1`;
2. the row exists and its state is `building`;
3. it is not the active dataset;
4. it is not the DART source dataset; and
5. no validation run has completed successfully for it.

Deletion uses schema-owned foreign-key order inside one transaction. The
command prints pre-delete table counts and verifies that the target has zero
remaining rows after commit. It never accepts a wildcard, prefix, or blank
version. Raw files and the source DART dataset are outside its deletion scope.

## 6. Rebuild Flow

```text
verify Q2 ZIP and all manifests
              ↓
delete exact inactive building target
              ↓
organizer + KRX + ECOS + SEC Series/Class + N-PORT build
              ↓
carry forward DART documents/chunks/vector values
              ↓
PostgreSQL, Evidence, and Vector reconciliation
              ↓
Graph preflight → Graph A/B → Jena/Fuseki gate
              ↓
four readiness records → atomic activation → smoke checks
```

The structured build and DART carry-forward remain idempotent within a fresh
`building` target. Any payload conflict fails closed.

## 7. Tiered Graph Validation

### 7.1 PostgreSQL/Python preflight

The preflight runs in one repeatable-read, read-only transaction and checks the
same release-critical invariants before generating RDF:

- dataset exists, has the expected cutoff, and is still `building`;
- relation predicate is approved;
- relation subject and object exist in the same dataset;
- subject/object ontology types satisfy the approved domain and range;
- every projected relation has at least one valid Evidence record and source;
- IDs are unique within their projection type;
- relation dates are ordered and all dates/timestamps obey the cutoff;
- every projected holding weight is present, numeric, in `[0, 100]`, has one
  applicable date, and belongs to exactly one `holdsSecurity` assertion;
- holding observation IDs and relation/date weight keys are unique;
- document and risk-factor provenance IDs resolve to the same dataset and
  Evidence lineage.

Checks use set-based SQL or indexed Python dictionaries, never per-node SPARQL
queries. The preflight returns a canonical JSON report containing counts,
failure codes, elapsed time, and a report hash. Any failure prevents RDF
export.

### 7.2 Deterministic export

Graph A and Graph B are built in separate temporary directories from the same
immutable PostgreSQL version. Their data, Evidence, manifest, predicate counts,
and expected competency-query bindings must be byte-identical. Temporary
outputs are removed on failure.

### 7.3 Full Apache Jena gate

Apache Jena 6.0.0 is the only full-data SHACL release engine. It must:

1. parse all tracked ontology, shape, data, and Evidence files;
2. run the complete tracked SHACL contract and report `sh:conforms true`;
3. load data and Evidence into a temporary TDB2 dataset;
4. reproduce the deterministic expected bindings for `managedBy`, `issuedBy`,
   `tracksIndex`, `holdsSecurity`, and `hasShareClass` through both the TDB2 CLI
   and Fuseki HTTP query path;
5. prove update, Graph Store, and admin surfaces are unavailable; and
6. remove the temporary Jena state and terminate Fuseki.

The verifier emits two machine-readable JSON documents. The deterministic
validation report contains stage outcomes, tool versions, and hashes of its
inputs and tracked contracts and is bound into the component manifest. The
operational telemetry contains elapsed seconds and peak resident memory and is
not manifest-bound because those values vary between otherwise identical
builds. A configurable watchdog defaults to 20 minutes for the full local
release run. Timeout and resource-limit exits are failures, never warnings.

### 7.4 pySHACL boundary

pySHACL remains in unit and small-fixture tests to verify detailed failure
messages and shape behavior. The full production-sized release path must not
materialize RDFLib union and explicit-type copies of the complete dataset.

## 8. Manifest and Readiness Binding

The Graph component manifest includes or binds to:

- dataset version and cutoff date;
- data and Evidence N-Quads hashes;
- deterministic preflight report hash;
- Jena validation report hash;
- ontology and SHACL contract hashes;
- predicate and projected-row counts; and
- expected competency-query binding hash.

PostgreSQL, Graph, Vector, and Evidence readiness rows must reference the same
final dataset manifest. Activation is a separate atomic call after all four
rows pass.

## 9. Failure Recovery

- Before target deletion, a failed source/hash preflight changes nothing.
- After target deletion, a failed phase leaves only an inactive `building`
  target that can be deleted and rebuilt again by the same guarded command.
- The DART source dataset and all raw source captures remain rollback inputs.
- No partial Graph artifact replaces a completed artifact; publication uses an
  atomic directory rename only after validation succeeds.
- A failed Jena or performance gate leaves the dataset inactive and retains a
  concise diagnostic report outside Git.

## 10. Verifiable Success Criteria

- The Q2 source and capture copy match the required size and SHA-256.
- All approved official manifests and referenced objects validate before the
  database build starts.
- The rebuilt source manifest contains SEC N-PORT 2026 Q2.
- DART counts remain exactly 2,214 documents, 7,267 coverages, 40,149 chunks,
  and 40,149 dimension-1,024 embeddings.
- Vector reconciliation has zero missing, duplicate, stale, orphan, or
  wrong-dimension rows.
- Graph preflight reports zero violations.
- Graph A and B are byte-identical.
- Full Jena SHACL, TDB2, Fuseki, and read-only checks pass within the watchdog
  and record their timings and peak memory.
- The four readiness components pass against one manifest.
- `operations.active_dataset` changes to the final version only after every
  preceding condition passes.
- Focused tests, Graph tests, and the appropriate broader test suite pass.
- The final diff contains no raw source data, database files, vectors, logs, or
  credentials.

## 11. Planned Implementation Surface

After this design is accepted, the implementation plan will limit changes to:

- a guarded incomplete-target cleanup command;
- a deterministic Graph preflight report and tests;
- machine-readable, timed Jena validation output and tests;
- Graph build/manifest wiring for the two validation report hashes;
- final-release readiness and activation tests; and
- the runtime task record.

Existing ontology terms, SHACL constraints, source parsers, DART chunk text,
and embedding values are not changed.
