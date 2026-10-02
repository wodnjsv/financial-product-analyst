# ADR-0054: Execute approved semantic searches in the personal local profile

- Date: 2026-10-02
- Status: Accepted
- Approval: The user requested committing/pushing the NVIDIA migration and
  continuing the remaining work in priority order.
- Related: ADR-0013, ADR-0020, ADR-0024, ADR-0025, ADR-0026, ADR-0029,
  ADR-0050, ADR-0051, ADR-0052, ADR-0053.

## Decision

Connect the personal NVIDIA resolver's approved LogicalQueryPlanV2 to the
existing deterministic SemanticSqlCompiler and ReadOnlySqlRunner. Start with
domestic ETF fee screening, then verified metric bindings, typed relation
conditions, and ambiguity reporting. The local CLI returns deterministic text
logs with products, values, actual dates, source locators and counts.

The compiler-owned plan, binding definitions and dataset pin remain execution
authorities. Never translate a semantic plan into the three older fixed search
names, discard predicates, execute model-authored SQL, or weaken runner
ownership checks. Execute dependent tasks in plan order within a bounded local
request. No public API, deployment, main merge, dataset activation or new bulk
ingestion is approved by this decision.

Hydrate returned evidence using the same dataset and verify source identity,
subject, approved metric definition/version, stored value/unit/currency and
date before rendering a factual field. Retain raw ledger records unchanged.
This local read-only bridge does not claim production release-ledger promotion.
For uncapped successful screening, disclose full matching and displayed counts;
for SQL-ranked results disclose returned top-N, never imply a population count.
Overflow is a failure, not a truncated complete population.

ETF source families contain ETNs. Require the verified organizer product_type:2
observation and evidence to preserve ETF-only scope; named ETNs are unsupported.
Keep full counts and lineage when narrowing evidence aggregation to the pinned
dataset/metric/observation. Do not increase SQL or request budgets to conceal
unbounded queries. Verified source missing values remain explicit omissions,
distinct from zero. Unsupported source disjunction and relation negation fail
closed until their complete Boolean meaning can be lowered.

ETF fee lookup/ranking without a numeric threshold can use the verified binding
storage unit. Numeric thresholds retain explicit semantic unit validation; no
global percent default is added. Domestic trailing one-year cumulative return
uses only the verified du_er_1y mapping and P1Y; do not invent period_start.
Bond maturity is a date value, not an observation/as-of date. Preserve its
unit=None and snapshot/source dates. Overseas one-year return has no source
field, and public-fund total-fee definition/unit are unverified: keep those
queries non-executable and state the concrete reason.

Holding-security and asset-manager conditions must preserve directed typed
relation objects separately from product subject scope and bind to registered
relations with evidence. Missing or ambiguous names, periods, or follow-up
scope cause a clarification/limitation instead of widening the search. This
decision allows useful clarification text in personal mode; it does not add
implicit cross-request memory or waive the historical competition stateless API.

## Alternatives and reasons

- Reusing fixed searches by keyword would be smaller but loses approved query
  meaning. Reuse the existing semantic compiler instead.
- A full production graph/API rollout adds unnecessary integration for solo
  local tests. Use a bounded local executor and existing SQL ownership checks.
- Inferring overseas annual returns or summing public-fund fee components would
  add unsupported facts. Preserve the data/definition limitations.
- A universal percent default breaks mixed fee/AUM queries. Use metric-specific
  storage semantics only where verified.

This amends ADR-0029's historical promotion gates only for the explicit personal
entry point, consistently with ADR-0050 and ADR-0053. Deterministic calculation,
evidence checks, immutable sources, policy restrictions and repository data
exclusions remain mandatory.
