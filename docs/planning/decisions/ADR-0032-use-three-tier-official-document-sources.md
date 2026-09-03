# ADR-0032: Use Three-Tier Official Document Sources and Claim-Impact Change Indexing

**Date:** 2026-08-30

**Status:** Accepted

**Approved:** 2026-08-30 — the user approved limiting the document corpus to
three official authority tiers and indexing only change disclosures that affect
an approved Document Claim.

**Related:** [VectorDB Official Document Corpus Minimum Scope Design](../specs/2026-08-29-vector-document-corpus-design.md),
[ADR-0007](ADR-0007-normalized-evidence-ledger-structured-answer-plan.md),
[ADR-0013](ADR-0013-use-lean-source-specific-ingestion.md),
[ADR-0014](ADR-0014-use-bounded-official-source-snapshots.md),
[ADR-0016](ADR-0016-use-2026-08-24-organizer-baseline.md)

## Context

The approved document-corpus design limits Vector retrieval to official,
Claim-bearing source spans, but its source table still permits manager or issuer
website copies as fallbacks. It also permits official change notices without a
complete rule for deciding which notices should consume Vector capacity.

Indexing every official document or every change notice would add repeated legal
language, administrative changes, quantitative tables, and superseded text. It
would increase retrieval noise and corpus size without improving the three
current document question families. Using manager or distributor pages as a
fallback would also weaken the deterministic authority boundary.

## Decision

### Limit admission to three official authority tiers

Only the following source authorities may supply corpus documents:

1. **Regulatory or supervisory filing systems.** Use the filing received and
   served by the competent regulator or supervisor for product structure,
   strategy, and risk Claims.
2. **Official index providers, ministries, and public institutions.** Use their
   original publications only for Claims they own, including index methodology,
   policy-fund structure, and official policy status or change.
3. **Official exchanges and industry associations.** Use their disclosures for
   exchange- or association-owned facts, document discovery, identifier
   cross-checking, and eligible listing or product-change notices.

Issuer, manager, distributor, news, blog, search-result, and generated-summary
pages are not fallback corpus sources. A filing submitted by an issuer remains
tier 1 when the regulator's filing system is the retrieved and preserved source.
If no eligible tier 1–3 document can be verified, record a bounded coverage
status instead of lowering the authority threshold.

### Use one canonical current document per required role

- Domestic ETFs and public funds use the latest effective collective-investment
  prospectus available through the regulatory filing system. Prefer its concise
  or summary portion when it covers every required Claim; use only the missing
  sections from the effective full filing rather than indexing both documents.
- Overseas ETFs use the current regulator-filed Summary Prospectus or
  jurisdictional equivalent. For U.S. products this is normally Form 497K. Add
  an effective regulator-filed supplement or full prospectus only when it
  changes or supplies a required Claim.
- Each unique index uses one effective official methodology from its index
  provider, not one copy per linked product.
- Each approved policy fund or policy institution uses one official base plan
  from the responsible ministry or public institution.
- Domestic bonds retain coverage status but have no initial Vector document
  role for the current question set.

### Separate change-disclosure accounting from Vector admission

Record the identity, source, affected entity, publication time, effective time,
and disposition of every candidate change disclosure found for the target scope
through an approved source. Index its text only when the disclosure changes at
least one approved Claim:

- product name or exact product/index identity;
- investment objective, strategy, or principal investment target;
- tracked index, theme definition, selection or exclusion rules;
- weighting or rebalancing rules;
- principal risk, currency-hedging policy, or derivatives/leverage policy;
- legal or operating structure; or
- policy-fund funding, operator, mandate, or question-relevant official status.

Do not index address, contact, distributor, personnel, fee-only, tax, accounting,
distribution/redemption, ordinary holdings, AUM/NAV/performance, typographical,
or duplicate consolidated-text changes. These dispositions remain auditable in
the manifest or coverage ledger without consuming Vector capacity.

For an admitted change disclosure, chunk only the affected Claim, before/after
content when stated, effective date, affected product or index, and the minimum
reason text needed to interpret the change. Do not chunk the complete notice by
default.

### Preserve the existing corpus budget and Evidence boundary

- Keep one active product document per role, one methodology per unique index,
  and only question-relevant historical changes.
- Keep the target of 8–15 chunks and the soft limit of 20 chunks per product
  scope. Exceeding the limit produces `review_required_chunk_budget`; it does
  not silently truncate or expand the corpus.
- PostgreSQL owns authority, version, coverage, and Evidence metadata. Vector
  search remains a candidate projection and cannot create a relation or Claim.

## Rejected Alternatives

### Index every document and every official change notice

Rejected because official status alone does not make text relevant to an
approved question. Administrative and repeated notices would consume Top-K
capacity and make the corpus grow without a bounded success criterion.

### Index only the current consolidated document

Rejected because it cannot support the approved time-bounded theme and policy
change questions or reconstruct when a material Claim changed.

### Fall back to manager or issuer website copies

Rejected because the user explicitly limited sources to the three approved
authority tiers. Missing eligible documents must remain visible as coverage
limitations rather than being hidden by a lower-authority substitute.

## Consequences

### Positive

- Corpus growth is tied to registered question Claims rather than document
  availability.
- Current product explanations and material change-history questions remain
  supportable without indexing every notice.
- Source authority and no-fallback behavior are deterministic and testable.
- Duplicate product documents and per-product copies of one index methodology
  are avoided.

### Costs and risks

- Some products will remain `document_not_found`, `section_missing`, or another
  bounded status even when a manager website contains useful text.
- Source-specific discovery still needs a reviewed per-product manifest and
  access-method checks.
- Change notices require deterministic Claim-impact classification before
  Vector admission.

## Preserved Decisions

- The organizer baseline remains authoritative for organizer-defined facts and
  missingness.
- Raw official files, embeddings, indexes, and generated outputs remain outside
  Git.
- The `2026-08-24` cutoff and actual publication, availability, and effective
  dates remain mandatory.
- PostgreSQL remains the evidence ledger; Graph and Vector remain projections.
