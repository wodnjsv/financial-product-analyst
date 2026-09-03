# ADR-0034: Allow ETN `tracksIndex` Relations

**Date:** 2026-09-03

**Status:** Accepted

**Approved:** 2026-09-03 — the user selected the option that preserves the 47
organizer-authoritative ETN index relations instead of excluding them from the
Graph projection.

**Amends:** [ADR-0021](ADR-0021-amend-minimal-ontology-for-question-contract-semantics.md)

**Related:** [Cross-store Integration Foundation](../specs/2026-09-03-cross-store-integration-foundation-design.md),
[ADR-0018](ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md)

## Context

Graph Phase 1 defined the `tracksIndex` domain as `ETF` or `PublicFund`. The
current 2026-08-24 organizer dataset contains 4,344 ETP `tracksIndex`
relations: 4,297 have an ETF subject and 47 have an ETN subject. The source
also provides exact source-qualified `product_type` observations that preserve
the ETF/ETN distinction.

After correcting the Graph repository to read those current observations, all
47 ETN relations would fail the existing domain gate even though they are
organizer-authoritative and semantically valid. Silently omitting them would
make the Graph projection incomplete and conflict with the fail-closed
projection policy.

## Decision

- Change the `tracksIndex` domain from `ETF | PublicFund` to
  `ExchangeTradedProduct | PublicFund`.
- Continue to type each exchange-traded product as exactly one of `ETF` or
  `ETN`; the existing disjointness constraint remains mandatory.
- Continue to require an `Index` object, a PostgreSQL relation ID, eligible
  Evidence, the exact dataset version, and temporal validation.
- Derive ETF or ETN type only from the approved source-qualified organizer
  observations. Do not infer type from a name, ticker, index, or relation.
- Update the TBox, SHACL domain shape, repository domain map, and positive and
  negative fixtures together.
- Do not change any other predicate, class, relation, or question-support
  declaration under this ADR.

## Rejected Alternative

### Exclude ETN `tracksIndex` relations from Graph

Rejected because it discards 47 official organizer relations, requires a
predicate-specific exception in an otherwise exact projection, and makes a
zero-result Graph query misleading unless every excluded ETN is carried
through separate coverage logic.

## Consequences

- Current organizer ETF and ETN index relationships can be projected without
  weakening product-type identity.
- Existing ETF-only questions must still filter the product type explicitly;
  broadening the relation domain does not make an ETN an ETF.
- The Graph ontology remains at 13 domain predicates and PostgreSQL remains the
  authority for the relation and its Evidence.
