# ADR-0021: Amend the Minimal Ontology for Question-Contract Semantics

**Date:** 2026-08-30

**Status:** Accepted

**Approved:** 2026-08-30 — the user approved the recommended contract-first
sequence and the targeted ontology amendments before TTL and SHACL work.

**Amends:** [ADR-0018](ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md)

**Related:** [Question Capability Contract Normalization](../specs/2026-08-29-question-capability-contract-normalization-design.md),
[Financial Ontology Architecture](../architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md),
[Core Evaluation Set](../specs/core-evaluation-set.md)

## Context

The frozen internal catalog contains 52 question cases and 50 historical
`required_relations` names. Those names mix domain relationships, numeric
metrics, controlled product attributes, document claims, provenance, and
answerability checks.

A case-by-case audit found that 23 questions require Graph traversal. After
normalizing historical aliases, all of their paths fit the 13 domain predicates
accepted by ADR-0018. The remaining cases use structured PostgreSQL facts,
calculations, document Evidence, or policy gates. Expanding the Graph vocabulary
would duplicate those authorities.

The audit also found four logical gaps that must be resolved before TTL and
SHACL implementation:

- product risk grades and bond credit grades are not explicitly separated;
- policy programs such as the official document example cannot be typed without
  forcing them into `FinancialProduct`;
- document publisher and effective-time requirements are not modeled as a
  complete provenance boundary; and
- `Region`, `AssetClass`, grades, currency, and statuses are named concepts but
  their controlled-attribute boundary is not explicit.

## Decision

- Retain the 13 domain traversal predicates from ADR-0018. Do not add
  `investsInRegion`, `investsInAssetClass`, or `publishedBy` to that set.
- Amend only ADR-0018's minimum-class clause by adding the competency-required
  `PolicyProgram` and by separating `ProductRiskGrade` from `CreditGrade`.
- Treat `Region`, `AssetClass`, grades, currency, availability, sale status,
  pension eligibility, hedge policy, offering type, and rate structure as
  controlled attributes. PostgreSQL remains their fact authority; ontology and
  SHACL validate type, vocabulary, scheme version, source, and temporal
  eligibility.
- Permit `documentedBy` from `FinancialProduct`, `Organization`, or
  `PolicyProgram` to `OfficialDocument`.
- Treat publisher identity, publication time, effective interval, availability
  time, document version, and source object as document provenance properties,
  not domain traversal predicates.
- Require risk-factor support to bind to a `DocumentChunk` and its page,
  section, source span, and Evidence record.
- Normalize the 52-case question contract into six requirement groups:
  `entities`, `attributes`, `metrics`, `relations`, `document_claims`, and
  `control_checks`.
- Preserve all 52 case IDs, question text, support levels, target support
  levels, and expected dispositions during normalization.
- Complete and verify the normalized question contract and logical ontology
  documents before implementing TTL, SHACL, ABox materialization, or Fuseki
  loading.

## Rejected Alternatives

### Promote all 50 historical names to Graph predicates

Rejected because most names represent observations, attributes, claim types,
or controls. Graph projection would duplicate PostgreSQL authority and make
ordinary filters depend on RDF traversal.

### Add Region and AssetClass as new core relationships

Rejected because the evaluated cases use them as deterministic filters and
similarity dimensions. A controlled attribute with official mapping and SHACL
validation is sufficient.

### Add `publishedBy` as a fourteenth domain predicate

Rejected because the publisher is needed to validate document authority and
cutoff eligibility, not to expand the product relationship graph. It belongs
to the document provenance contract.

### Leave product risk and bond credit grade under one concept

Rejected because their schemes, meaning, and comparison rules differ. A shared
grade concept could permit invalid cross-family ordering.

### Force a policy program into `FinancialProduct`

Rejected because doing so would assert a product identity that the official
documents may not support and would make entity resolution less reliable.

## Consequences

- ADR-0018's canonical-product, multi-role, 13-predicate, SourceRecord, and
  PostgreSQL-authority decisions remain unchanged.
- The TBox stays small but gains the exact classes and semantic property groups
  required by the 52-case catalog.
- Stage 04 competency tests can reject accidental Graph predicates and invalid
  grade, document, or policy typing before any ABox is loaded.
- The question contract becomes the executable boundary between Stage 03 facts
  and Stage 04 ontology, Graph, Keyword, and Vector projections.
- This ADR does not approve a PostgreSQL migration, new data collection,
  dataset activation, NCP write, or a change to question support coverage.
