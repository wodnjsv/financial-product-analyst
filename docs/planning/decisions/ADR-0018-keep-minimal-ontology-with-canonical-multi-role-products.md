# ADR-0018: Keep the Minimal Ontology with Canonical Multi-Role Products

**Date:** 2026-08-25

**Status:** Accepted

**Related:** [ADR-0016](ADR-0016-use-2026-08-24-organizer-baseline.md),
[ADR-0017](ADR-0017-adopt-current-cutoff-with-legacy-preservation.md),
[Financial Ontology Architecture](../architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md),
[280-field Matrix](../specs/organizer-master-field-matrix-2026-08-24.md)

## Context

The replacement organizer workbooks change the source grains and expose exact
identity overlap without introducing a new evaluated relationship family.
There are 217 checksum-valid, unique ISIN overlaps between the domestic ETP
and public-fund masters. Domestic bonds also repeat one product across market,
date, and information-sequence source records. The organizer will not provide
its internal code tables, and `BUYABLE_QUANTITY` is explicitly invalid.

Treating every source row or source table membership as a separate ontology
entity would double-count products and turn provenance details into financial
relationships. Adding new relations for source membership, sale lots, or the
invalid availability field would make the ontology larger without answering a
new competency question.

## Decision

- Keep the existing minimum class vocabulary and the 13 approved core
  relations.
- Use one canonical product entity whenever the organizer-authoritative exact
  identity index resolves a product uniquely.
- Permit one canonical product to carry more than one compatible role type.
  In particular, a domestic ETF that is also represented as a public-fund
  share class may be typed as both `DomesticETF` and `FundShareClass`. `ETF`
  and `ETN` remain disjoint.
- Do not create `owl:sameAs` links between duplicate source-created entities.
  Prevent those duplicate entities from being created in the first place.
- Keep source-table membership, workbook rows, and bond sale-lot grains in the
  PostgreSQL `SourceRecord` and Evidence boundary. They are not ontology
  classes or relations.
- Keep price, yield, AUM, return, distribution, volatility, availability, and
  other numeric or status facts in versioned PostgreSQL observations. The
  ontology provides metric and status vocabularies but does not calculate or
  rank them.
- Derive the competition-specific bond purchase candidate status
  deterministically from explicit delisting or listing-end facts. Do not map
  `BUYABLE_QUANTITY` and do not add a purchase relation.
- Do not promote code-only values into `Industry`, `Region`, `AssetClass`,
  `RiskGrade`, or other controlled concepts without an official mapping.
  Preserve undecodable codes only as source Evidence.
- Keep the TBox identifier `urn:ontology:financial-product:v1`. Materialize the
  current ABox and Evidence graphs under the `2026-08-24` dataset version.
- Validate ontology projections with SHACL for allowed predicate domain and
  range, ETF/ETN disjointness, permitted ETF/share-class multi-typing,
  relation Evidence linkage, and dataset-relative temporal eligibility.

## Rejected Alternatives

### Redesign the entire ontology from the 280 workbook fields

Rejected because 208 fields are observations and 27 are Evidence-only. A
workbook-column ontology would duplicate the normalized fact ledger and make
source revisions alter the semantic model unnecessarily.

### Add source-record, listing-lot, and availability relations now

Rejected because PostgreSQL already represents their required grain and no
approved evaluation path requires those new graph edges. A later tested query
may justify a separate ADR.

### Keep ETF and public-fund source rows as separate products joined by `sameAs`

Rejected because filtering and aggregation could still count both nodes. Exact
identity resolution must precede entity creation.

### Make every product-family class mutually disjoint

Rejected because the organizer's exact identifiers prove that an ETF may also
appear as a public-fund share class. Only economically incompatible types such
as ETF and ETN are disjoint.

## Consequences

- The ontology remains small and aligned to competency questions rather than
  workbook columns.
- The identity pre-scan becomes a prerequisite for both normalized writes and
  ontology materialization.
- SHACL fixtures must include valid ETF/share-class multi-typing and invalid
  ETF/ETN multi-typing.
- Graph results continue to return PostgreSQL relation and Evidence IDs before
  they can support a Claim.
- New source fields generally require metric definitions and mapping tests, not
  new ontology predicates.
