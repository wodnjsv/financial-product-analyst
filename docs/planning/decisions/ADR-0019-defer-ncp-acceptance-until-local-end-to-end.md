# ADR-0019: Defer NCP Acceptance Until Local End-to-End Readiness

**Date:** 2026-08-26

**Status:** Accepted

**Approved:** 2026-08-26 — the user approved completing and verifying the
service locally before incurring further NCP database and server costs.

**Supersedes:** Only the sequencing clauses in ADR-0013, ADR-0014, the current
Stage 03 rebaseline plan, and ROADMAP that require an intermediate NCP
`building` acceptance before local Stage 04–07 implementation. Their data,
lineage, cutoff, permission, and final deployment requirements remain in
force.

**Related:** [ADR-0013](ADR-0013-use-lean-source-specific-ingestion.md),
[ADR-0014](ADR-0014-use-bounded-official-source-snapshots.md),
[ADR-0016](ADR-0016-use-2026-08-24-organizer-baseline.md),
[ADR-0018](ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md),
[Competition Roadmap](../ROADMAP.md)

## Context

Stage 02 already proved the PostgreSQL migration, permission, and representative
query boundaries on NCP. Repeating NCP acceptance after each subsequent local
data or application increment creates avoidable cost while the ontology,
retrieval engine, orchestration, Claim Gate, renderer, and evaluation API are
not yet complete.

The remaining implementation can be exercised against local PostgreSQL,
Fuseki, vector, and API equivalents without weakening its deterministic data
contracts. NCP-specific network, managed-service permission, Linux/amd64,
latency, high-availability, load-balancer, backup, and recovery behavior cannot
be inferred from local tests and therefore still require an explicit final
acceptance gate.

## Decision

- Complete Stage 03–07 functional implementation and end-to-end verification
  against local infrastructure first.
- Keep every intermediate dataset inactive until PostgreSQL, Graph, Vector,
  Evidence, retrieval, Claim Gate, renderer, and the local evaluation API are
  ready together.
- Defer new NCP database writes, Object Storage publication, Fuseki deployment,
  HyperCLOVA X canaries, load-balancer checks, and operational drills to the
  Stage 08 deployment gate.
- Preserve the existing NCP capability and portability results as historical
  evidence. Do not represent them as proof of the final service image or final
  dataset.
- Require Stage 08 to repeat the final migrations and permission checks, load
  one inactive final dataset, verify read-only runtime access, import the graph
  and vector projections, run representative latency tests, then activate only
  after all readiness checks pass.
- Do not claim NCP latency, parity, high availability, recovery, or public
  endpoint readiness before those final checks run.
- Keep organizer and official raw data, local databases, generated graphs,
  embeddings, and manifests outside Git under the existing repository data
  policy.

## Rejected Alternatives

### Continue one NCP acceptance after every Stage 03 increment

Rejected because it spends managed-service resources before later local
components can consume the dataset, and it repeats a partial acceptance that
must be run again for the final service.

### Eliminate NCP acceptance entirely

Rejected because local tests cannot verify VPC access, managed PostgreSQL
permissions, final Linux/amd64 images, HyperCLOVA X integration, load balancing,
backup recovery, or the public evaluation endpoint.

### Develop only against NCP from this point forward

Rejected because it increases cost and iteration time for deterministic code
that can be verified more cheaply and quickly with local equivalents.

## Consequences

- Stage 03 completion becomes a local deterministic data and Evidence gate;
  it no longer waits on an intermediate NCP `building` load.
- Stage 04–07 may proceed after their local predecessor gates pass.
- Stage 08 becomes a larger but explicit infrastructure acceptance boundary and
  must budget enough time for final data load, performance tuning, and recovery
  rehearsal.
- A local pass is necessary but not sufficient for deployment. Any NCP-specific
  failure reopens the affected implementation or infrastructure task before
  activation.
