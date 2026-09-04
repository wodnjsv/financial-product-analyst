# ADR-0048: Rebuild the Incomplete Final Dataset with Tiered Graph Validation

- Date: 2026-09-04
- Status: Accepted
- Amends: ADR-0047

## Context

`competition-2026-08-24-final-v1` is an inactive `building` dataset. Its
structured rows were assembled without SEC N-PORT because the required source
object was unavailable at the time. The DART corpus was then carried forward
successfully, but the resulting dataset cannot be activated because its frozen
source set is incomplete.

The required SEC N-PORT object is now available locally as
`2026q2_nport.zip`. Its size (`440,699,889` bytes) and SHA-256
(`077cc836a978a593b29012219395fbe9c303d5e930f5be3b5f4353c3b02296fc`)
match the approved `SEC_NPORT_2026Q2` capture manifest exactly. Earlier
quarters and years are not required for the approved latest-point-in-time
holdings scope at the `2026-08-24` cutoff.

The first full Graph validation also exposed a scale problem. The current
pySHACL path reads the complete N-Quads artifacts into memory, materializes two
additional RDFLib graphs, and executes global SPARQL constraints over the full
projection. It remained CPU-active for approximately 50 minutes without
completing. Retrying the same path would not provide a bounded release gate.

## Decision

Rebuild the exact incomplete target version rather than mutating it in place.

1. Verify the local SEC N-PORT object against the frozen manifest, copy it to
   the manifest-declared capture location, and verify the copied bytes again.
2. Delete only `competition-2026-08-24-final-v1` after proving that it is
   inactive and still in `building` state. Preserve
   `organizer-dart-2026-08-24-v2` and every raw source object.
3. Rebuild `competition-2026-08-24-final-v1` from the complete frozen source
   set, including SEC N-PORT 2026 Q2.
4. Carry forward the verified DART documents, chunks, and vector values without
   calling DART or NCP again.
5. Replace full-release pySHACL validation with a tiered gate:
   - deterministic PostgreSQL/Python preflight validates graph projection
     invariants before RDF export;
   - deterministic export checks and two byte-identical builds validate the
     projection itself;
   - Apache Jena 6.0.0 performs full SHACL, TDB2, competency-query, and
     read-only Fuseki validation;
   - pySHACL remains the development validator for bounded fixtures and
     contract tests, not the full production-sized release artifact.
6. Record stage duration and peak memory as non-deterministic operational
   telemetry outside the component-manifest hash. A timeout, non-zero exit,
   malformed report, or missing expected binding fails closed and prevents
   activation.
7. Create the four component-readiness records and activate only after the
   complete release gate passes.

The Jena result becomes the authoritative full-release SHACL result. The same
tracked ontology and shape files are hashed into the Graph component manifest,
so changing validator engines does not relax or fork the semantic contract.

## Alternatives Considered

### Continue waiting for full pySHACL

Rejected because the observed run exceeded 50 minutes and duplicated the
largest graphs in memory without reaching a release decision.

### Optimize only the SHACL queries and keep pySHACL as the release engine

Rejected for this release because it still leaves full graph parsing and
materialization inside RDFLib. Shape optimization may be revisited later with
benchmarks, but it is not required to activate this dataset safely.

### Add 2026 Q1 and earlier N-PORT files

Rejected because they are outside the approved latest eligible observation
scope and would increase ingestion, storage, and validation cost without
improving the cutoff-date answer contract.

### Patch N-PORT rows into the existing target

Rejected because the existing immutable build manifest would no longer
describe how the dataset was assembled.

## Consequences

- The incomplete target's structured rows and carried-forward corpus are
  rebuilt once, while the verified source DART dataset remains available for
  rollback.
- The final source manifest includes the official SEC N-PORT 2026 Q2 snapshot.
- Full release validation uses two independent layers: relational/projection
  invariants first, semantic/runtime validation second.
- Small pySHACL tests continue to catch shape regressions quickly without
  making local full-data validation unbounded.
- The dataset remains inactive if any source, Graph, Vector, Evidence, or
  determinism check fails.
