# ADR-0055: Connect personal conditions to verified source fields

- Date: 2026-10-11
- Status: Accepted
- Approval: User requested condition/operator/DB-field corrections and retesting
- Scope: Personal read-only semantic execution under ADR-0054

## Decision

Preserve source-owned values and operand spans when solving categorical
conditions. Map Japanese equity to two independent predicates (`Japan`,
`Equity`). Normalize `AA- 이상` using the registered credit-grade order into
`AAA`, `AA+`, `AA0`, `AA-`, retaining the original operator and threshold in
provenance. Reject unregistered, negated or incomplete interpretations rather
than broadening the query.

There is no observed domestic-bond saleability or delisting flag in this master.
Under ADR-0016's organizer purchase assumption, the registered personal policy
may return dataset-time candidates after excluding maturity on/before the pinned
cutoff and nonpositive source remaining days. This is a conservative eligibility
screen, not evidence of current saleability. The answer must disclose the
assumption, dataset cutoff and actual source dates. No buyable-quantity test or
synthetic observed sale flag is allowed.

Represent the source remaining-days metric using its actual numeric type and
source normalization; the legacy catalog integer/derived declaration does not
describe the stored source fact. A default date for AUM or remaining days is
allowed only after read-only verification that the pinned source has one actual
date. Never substitute the cutoff or a maximum date for mixed-date facts.

AUM presence keeps present and zero values and excludes missing values. It needs
no FX conversion because no magnitude comparison, ordering or aggregation is
performed; those operations retain the existing currency safeguards.

Large screens must count the complete distinct-product population using the
same approved predicates, then return an explicitly bounded evidence-verified
display. A display limit is never a claimed full population count.

## Rejected alternatives and reasons

- Lexical grade GTE: does not represent financial grade order.
- General arbitrary string comparisons or model-authored filters: expands the
  execution boundary unnecessarily.
- Inferring live saleability from maturity, positive quantity, or master
  membership: the source cannot establish that fact.
- Dropping saleability or either Japanese-equity condition silently: changes
  the user's question.
- Raising row or time budgets to accommodate an oversized screen: unnecessary
  when exact count and bounded display suffice.

## Consequences

New source fields remain pinned to their metric definitions and evidence.
Dates, grade rules, derived candidate-policy provenance and display truncation
are visible. Unsupported thresholds or mixed-date defaults remain closed.
No database schema, raw source, deployment or release change is authorized.
