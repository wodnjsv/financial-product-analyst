# ADR-0020: Treat Organizer Missingness as Authoritative

**Date:** 2026-08-27

**Status:** Accepted

**Approved:** 2026-08-27 — the user explicitly required organizer blank and
null values to remain unavailable instead of being filled from auxiliary data.

**Related:** [ADR-0014](ADR-0014-use-bounded-official-source-snapshots.md),
[ADR-0016](ADR-0016-use-2026-08-24-organizer-baseline.md),
[ADR-0019](ADR-0019-defer-ncp-acceptance-until-local-end-to-end.md),
[Organizer Field Matrix](../specs/organizer-master-field-matrix-2026-08-24.md)

## Context

The organizer states that zero and missing values in the replacement workbooks
are intentional. The existing decisions make the organizer snapshot
authoritative when an organizer value and an external value conflict, but they
do not state strongly enough what happens when the organizer field is blank,
`NULL`, a reviewed placeholder, or otherwise tagged missing.

Using an external official value to fill that organizer field would make the
answer appear more complete while changing the organizer-defined evaluation
fact. It would also make a missing organizer value indistinguishable from a
field that the organizer never supplied. The user therefore requires the
system to treat organizer missingness as a meaningful result and not as an
invitation to impute from an auxiliary source.

## Decision

- A value state is evaluated at the organizer field and canonical-product
  grain. `present` and `zero` remain usable organizer facts. `missing`,
  `placeholder`, and reviewed structurally unavailable states remain
  unavailable.
- If an organizer schema defines a semantic product fact, an external source
  must not fill, replace, rank by, filter by, calculate from, or support a Claim
  for that same semantic fact when the organizer value is unavailable.
- The rule is schema-authoritative, not value-seeking. The system must not scan
  other products, older snapshots, manager pages, KRX, SEC, or another official
  publisher for a substitute value.
- External sources may add only explicitly approved semantics that are absent
  from the organizer schema or are independent normalization inputs. The
  initial allowlist is:
  - ETF or fund `holdsSecurity` relations and holding-level facts;
  - stable security, issuer, exchange, and regulator identifiers used to bind
    those relations;
  - approved ECOS exchange rates used for disclosed currency normalization;
  - source coverage, lineage, and cutoff evidence.
- Semantic equivalence is an explicit reviewed mapping. Name similarity,
  metric labels, model judgment, or a non-null external value cannot establish
  equivalence.
- External raw bytes and immutable manifests may be retained outside Git for
  audit. A blocked substitute value is not written as a releaseable normalized
  product observation. The organizer missing observation and its Evidence
  remain the answer authority.
- KRX ETF daily close and NAV are not current answer-enrichment sources because
  the organizer domestic ETP schema already defines `du_clpr` and
  `du_last_nav`. Their historical parser and historical capture records may
  remain for reproducibility, but the current combined manifest excludes that
  source.
- Stage 05 retrieval and Stage 07 Claim Gate must repeat the same fail-closed
  rule. A later bug in source selection must not make a blocked external value
  releaseable.
- This decision does not require a new table or Alembic migration. Existing
  tagged organizer observations, Source/Evidence records, explicit source
  adapters, and deterministic release policy are sufficient.

## Reasons

- It follows the organizer's explicit missing-value instruction rather than
  maximizing apparent answer coverage.
- It prevents an official but evaluation-inconsistent value from silently
  changing a rank, filter, or calculation.
- It preserves the important distinction between "the organizer supplied the
  field and the value is missing" and "the organizer does not model this
  relation at all."
- It keeps external enrichment small and question-driven.

## Rejected Alternatives

### Fill organizer blanks from any official source

Rejected because official provenance does not override the organizer's
evaluation authority. It also creates date and semantic mismatches that are
hard to disclose consistently.

### Keep both values and let retrieval choose later

Rejected because an accidental metric-priority change could release the
external substitute. The Stage 03 normalized boundary should already exclude
unapproved overlapping product facts.

### Allow the LLM to decide whether an external metric is equivalent

Rejected because semantic authority, missingness, filtering, and ranking must
be deterministic and reproducible.

### Treat missing as zero

Rejected because the organizer explicitly distinguishes them and ranking or
aggregation would become incorrect.

## Consequences

- Some answers will state that a requested value is unavailable even when an
  external website contains a number.
- Current KRX daily price/NAV recapture is removed from the Stage 03 completion
  critical path.
- Domestic and overseas ETF holdings, security identity, and FX enrichment
  remain permitted because they add separate approved semantics.
- Public-fund constituent holdings remain `requires_data` unless a separate
  official source passes the source-approval gate.
- Coverage reports, retrieval tests, and Claim Gate tests must include
  organizer-null/external-present adversarial cases.
