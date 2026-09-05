# ADR-0049: Harden Final Graph Projection and Validation

- Date: 2026-09-05
- Status: Accepted
- Amends: ADR-0018, ADR-0048

## Context

The first complete SEC N-PORT projection exposed three production-scale facts
that the bounded fixtures did not contain:

1. official N-PORT percentages can be negative for short positions or exceed
   100 for leveraged exposure, while `holdingWeightPercentage` is deliberately
   constrained to `[0, 100]`;
2. 615 valid fund-of-fund relations hold a product that also has the economic
   role of a `Security`; and
3. materializing either the complete SHACL union or 1.3 million competency
   query bindings in process memory exhausts the local release host.

PostgreSQL remains the lossless authority. Clamping, taking absolute values,
fabricating entity types from names, or weakening the SHACL contract would
change source meaning.

## Decision

- Preserve every official holding value in PostgreSQL and Evidence.
- Omit a `holdsSecurity` relation from the Graph projection when its approved
  weight is unknown, negative, or above 100. Do not clamp or rewrite it.
- When a canonical product is the object of a projected `holdsSecurity`
  relation, add the compatible `Security` role alongside its product roles.
  This role comes from the stored relation, never from its name.
- Keep full deterministic projection preflight, full N-Quads parsing, full
  TDB2 loading, and full SHACL validation. Run SHACL against the disk-backed
  TDB2 union through a temporary loopback-only Fuseki SHACL endpoint rather
  than constructing a second in-memory graph.
- Verify each release predicate in both TDB2 CLI and read-only Fuseki using:
  - the full Evidence-expanded binding count; and
  - up to 25 deterministic exact bindings, including relation and Evidence IDs.
    Never split one relation's Evidence group at the sample boundary.
- Probe Fuseki readiness with a bounded one-row dataset query. Do not use a
  competency query as the readiness probe because a valid production-scale
  query can exceed the one-second startup polling timeout.
- Keep the runtime Fuseki configuration query-only. The SHACL endpoint exists
  only in the temporary validation process and is removed before runtime
  read-only checks.

## Rejected Alternatives

### Clamp or take the absolute value of N-PORT percentages

Rejected because it would turn short or leveraged exposure into a different
financial fact.

### Drop product-as-security holdings

Rejected because fund-of-fund holdings are valid official relationships and
the ontology does not make `FinancialProduct` and `Security` disjoint.

### Compare every competency-query row in memory

Rejected because it duplicates authority already covered by deterministic
preflight and artifact hashes and is not bounded at the final data scale.

## Consequences

- PostgreSQL retains the complete source meaning while Graph remains conformant
  to its intentionally narrower holding-weight contract.
- Fund-of-fund traversal remains available without name-based inference.
- Release validation stays full-data for structure, SHACL, loading, and counts,
  while exact row comparison has a deterministic memory bound.
- Any count mismatch, sample mismatch, SHACL violation, parse failure, or
  writable Fuseki surface still fails closed and prevents activation.
