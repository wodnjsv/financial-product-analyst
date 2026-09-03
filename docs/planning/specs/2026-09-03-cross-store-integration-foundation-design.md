# PostgreSQL, Graph, and Vector Integration Foundation Design

**Date:** 2026-09-03

**Status:** Approved 2026-09-03

**Scope:** Merge the verified Graph Phase 1 core with the current organizer and
DART Vector branch, make the current PostgreSQL dataset projectable, and add
the deterministic document-candidate-to-Evidence boundary required before a
retrieved chunk may support a Claim.

**Related:** [Planning Harness](../HARNESS.md),
[ADR-0007](../decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md),
[ADR-0018](../decisions/ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md),
[ADR-0021](../decisions/ADR-0021-amend-minimal-ontology-for-question-contract-semantics.md),
[ADR-0031](../decisions/ADR-0031-use-ncp-bge-m3-for-dart-embeddings.md),
[Graph Phase 1 Design](2026-08-30-stage-04-graph-phase-1-design.md)

## 1. Problem

The current local PostgreSQL dataset contains the organizer master, 2,214 DART
documents, 40,149 document chunks, and 40,149 exact BGE-M3 embeddings. Its
3,555,838 observations and 78,532 relations have complete normalized Evidence
origins. Document retrieval, however, deliberately returns candidates without
Evidence IDs, and no request path yet promotes a selected document span into
the Evidence ledger.

The Graph Phase 1 core is complete on `codex/graph-phase1-core` but is not
merged into the current branch. Its tests pass, but loading the current dataset
fails because it still reads the pre-rebaseline `product_type` metric instead
of the authoritative source-qualified organizer metrics. No real ABox or
Fuseki dataset has been built from the current PostgreSQL dataset.

These gaps mean that the three storage capabilities cannot yet participate in
one verified request: Graph can find structured relationships, Vector can find
text candidates, but only PostgreSQL Evidence may authorize a Claim.

## 2. Goals

1. Integrate the existing Graph Phase 1 implementation without rewriting it
   its verified ontology, SHACL, exporter, manifest, Jena, or Fuseki boundary.
2. Project the current organizer dataset using the authoritative rebaseline
   product-type metrics and reject unresolved ETF/ETN identity.
3. Preserve all 40,149 current embeddings byte-for-byte and avoid any full
   organizer or DART rebuild.
4. Convert only selected document candidates into immutable
   `document_span` Evidence after retrieval and before Claim generation.
5. Make one request capable of joining Graph relationship results and Vector
   document results through the same `dataset_version` and product entity ID.
6. Generate and validate one real local Graph artifact from the current
   PostgreSQL dataset, while keeping the dataset inactive.
7. Produce an exact readiness audit identifying what remains for the later
   official-structured-source integration and final activation.

## 3. Non-goals

- Do not re-embed existing chunks or call NCP for a corpus rebuild.
- Do not create Evidence for every document chunk before it is retrieved.
- Do not store document text or embedding vectors in Fuseki.
- Do not invent normalized RiskFactor entities from section headings alone.
- Do not claim real `hasRiskFactor` Graph coverage until a separately approved
  risk-factor extraction and identity contract exists.
- Do not import SEC N-PORT, KRX holdings, ECOS, or other large official sources
  in this integration-foundation change.
- Do not activate the dataset, write NCP PostgreSQL, or deploy NCP Fuseki.
- Do not modify organizer-provided source files or force ambiguous identities.

## 4. Chosen Architecture

### 4.1 Authority and projection boundary

PostgreSQL remains the only authority for entities, observations, relations,
documents, sources, Evidence, and calculations. Fuseki remains a reproducible
read-only relationship projection. pgvector remains a document-candidate
index. Neither a Graph binding nor a Vector hit may directly support a Claim.

The integrated request flow is:

```text
PostgreSQL entity resolution
  -> Graph relationship candidate lookup
  -> Vector/keyword document candidate lookup
  -> deterministic Evidence promotion
  -> PostgreSQL Evidence bundle and Claim generation
  -> deterministic verification
```

Every handoff carries the same `dataset_version` and canonical product
`entity_id`. Graph relationship results additionally carry PostgreSQL
`relation_id` and `evidence_id`. Promoted document results carry `document_id`,
`chunk_id`, and the newly persisted `evidence_id`.

### 4.2 Branch integration

The current `codex/vector-corpus-source-policy` branch is the integration base
because it owns the latest migration, DART documents, and exact embeddings.
Graph Phase 1 commits are brought onto that base with conflicts resolved only
at shared dependency, status, and question-contract files. Graph modules,
ontology files, SHACL shapes, and read-only Fuseki configuration retain their
existing public interfaces unless the current schema requires a tested
compatibility correction.

### 4.3 Product type correction

The Graph repository must not read the obsolete generic `product_type` metric.
It uses these organizer-authoritative metrics:

- `organizer.pref01n001.product_type` for domestic ETPs;
- `organizer.pref02n001.product_type` for overseas ETPs; and
- `organizer.pref02n001.is_etn` only as a consistency check, not as a substitute
  for a missing product type.

Only present text values `ETF` and `ETN` are accepted. Conflicting values,
missing values on an ETP participating in a typed Graph relation, and a
disagreement between overseas `product_type` and `is_etn` fail the projection.
No type is inferred from a product name.

The organizer-authoritative dataset contains 47 `tracksIndex` relations whose
subject is an ETN. The ontology therefore permits `tracksIndex` from any
`ExchangeTradedProduct` (`ETF` or `ETN`) and from `PublicFund`, while retaining
the ETF/ETN disjointness rule. This amendment is recorded separately rather
than silently changing ADR-0021.

### 4.4 Document Evidence promotion

The existing `DocumentCandidateHit.evidence_id=None` boundary is preserved for
search. A new deterministic promoter accepts a selected hit, the validated
claim requirement, and the request scope. It re-reads the authoritative rows
for the exact dataset, entity binding, document, profile, chunk, source, and
source artifact before creating Evidence.

One promoted Evidence record represents one `(dataset_version, entity_id,
document_id, chunk_id, claim predicate)` tuple. Its identifier and record hash
are deterministic. It uses:

- `evidence_kind=document_span`;
- the bound product as `subject_id`;
- the approved document claim as `predicate_id`;
- `chunk_id` as the normalized object reference;
- source, publication, availability, and effective dates from authoritative
  PostgreSQL rows;
- page, section, and sentence span from the exact chunk; and
- `OriginReference(origin_kind="document_chunk")` so
  `evidence_document_origin` points back to the chunk.

The promoter is idempotent. Repeating the same promotion returns the existing
Evidence when the payload matches and fails closed on a payload conflict. A
search result that fails publisher, cutoff, entity binding, content hash, or
source-artifact verification is not promoted.

This request-time design follows ADR-0007: Vector and keyword search find
candidates, and only selected, validated spans become Evidence. It avoids
pre-creating tens of thousands of unused Evidence records.

### 4.5 Graph document boundary

This phase does not duplicate the entire document corpus in Fuseki. Product to
document restriction remains an indexed PostgreSQL join through
`document_entity_binding`, followed by Vector search. The ontology keeps
`documentedBy` and `hasRiskFactor` in its approved vocabulary, but real
`hasRiskFactor` ABox coverage remains unsupported until risk factors have an
approved normalized identity instead of being inferred from arbitrary text.

This is intentional capability routing rather than an omission: Graph handles
multi-hop structured relationships, Vector handles semantic document search,
and PostgreSQL Evidence joins their verified results.

### 4.6 Real Graph artifact

After integration and type correction, the existing read-only repository loads
the current dataset in one repeatable-read snapshot. The exporter generates
deterministic data and Evidence N-Quads, and the existing RDFLib/pySHACL and
Jena/Fuseki gates validate them. Generated N-Quads and TDB2 data remain local
and untracked.

Only relation predicates actually present in PostgreSQL receive real ABox
coverage. An approved predicate with no current official relation remains
explicitly unsupported; an empty Graph result is never treated as proof that a
relationship does not exist.

## 5. Failure Handling

- A branch conflict affecting schema or question semantics stops integration
  for explicit review; it is not resolved by choosing one side wholesale.
- A product-type conflict fails the complete Graph artifact, with aggregate
  diagnostics kept outside Git.
- A document hit that cannot be revalidated returns a stable evidence-promotion
  failure and cannot enter a Claim.
- Existing Vector reconciliation must remain exact at 40,149 before and after
  every integration task.
- Generated Graph artifacts are published only after deterministic byte and
  manifest equality across two runs.
- Dataset readiness and activation remain absent even when all local gates in
  this phase pass.

## 6. Verification

The integration is accepted only when all of the following hold:

1. The pre-integration Graph unit suite remains green.
2. The current full suite and the integrated Graph suite pass together.
3. The current dataset loads through `GraphProjectionRepository` without an
   unsupported type, relation, Evidence, source, date, or metric error.
4. Two real Graph exports from the same PostgreSQL snapshot have identical
   N-Quads bytes and component manifests.
5. RDFLib/pySHACL and Apache Jena/Fuseki 6.0.0 accept the generated artifact.
6. A real structured relationship query returns its PostgreSQL relation and
   Evidence IDs.
7. A real ETF and a real public-fund document query each promote one selected
   hit to Evidence and round-trip the exact product, document, chunk, source,
   page, section, and dataset identifiers.
8. A combined retrieval test joins one Graph result and one promoted Vector
   result under one product and dataset without creating unsupported Claims.
9. Vector reconciliation remains `eligible=40149`, `exact=40149`, with zero
   missing, duplicate, stale, orphan, or wrong-dimension rows.
10. No organizer file, DART PDF, generated graph, local database, credential,
    or local report is committed.

## 7. Deferred Workstream

After this foundation passes, official structured sources are integrated as a
separate approved workstream. Its inputs are the already verified KRX holdings
implementation, bounded SEC coverage, ECOS exchange-rate data, and their
existing source manifests. It must rebuild or extend one final dataset without
overwriting organizer-authoritative missing values, then repeat PostgreSQL,
Graph, Vector, Evidence, manifest, readiness, and activation gates.

That workstream remains separate because SEC storage and local disk capacity
are materially different from branch and Evidence integration. The foundation
must not be made dependent on a large external-source reload.

## 8. Success State

Completion of this design means the current organizer and DART corpus can be
used by PostgreSQL, Graph, and Vector in one local evidence-verified request.
It does not mean the final competition dataset is active or that all approved
Graph predicates and external official sources have real-data coverage.
