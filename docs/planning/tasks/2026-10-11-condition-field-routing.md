# Condition values, operators and physical fields

- Date: 2026-10-11
- Status: local condition execution verified; live NVIDIA validation remains blocked by provider failures
- Decision: ADR-0055

## Assumptions and outcome

The personal pinned PostgreSQL dataset is the test population. Japanese equity
ETFs must preserve both `Japan` and `Equity` predicates. Credit grades use the
registered grade sequence, never lexical ordering. The bond master does not
prove current saleability; the organizer's purchase assumption is disclosed and
restricted to candidates with maturity after the dataset cutoff and positive
source remaining days. No claim of live saleability is permitted.

## Scope and constraints

Connect source-owned categorical literals and operator operands to the selected
semantic fields, register verified physical bindings, and verify returned text
and numeric facts against their evidence. Preserve every requested AND condition.
The source remaining-days numeric type must agree with its catalog type.
Only a single source-verified date can supply a pinned default for AUM or source
remaining days. AUM presence includes zero and needs no currency conversion.

No raw-data edits, ingestion, database writes, general model-authored SQL,
deployment, commit, or push. Keep the SQL 5-second and service 55-second budgets,
bounded output and the single shared model repair. Only previously authorized
question/catalog/candidate metadata may be sent to NVIDIA.

## Alternatives

- Use an ordered SQL grade comparison, or normalize `AA- 이상` into an allowed
  grade set. Choose the smaller registered IN expansion while retaining the
  original threshold/operator provenance.
- Treat saleability as an unavailable live fact, or execute the disclosed
  organizer-assumed dataset candidate policy. Choose the latter only for the
  registered domestic-bond policy. Do not invent an observed sale flag.
- Waive all AUM date/currency requirements, or supply a verified date and waive
  FX only for presence predicates. Choose the latter; comparisons keep their
  existing requirements.
- Return an oversized list, or count all matching products and verify a bounded
  display. Choose an exact compiler-owned count with a clearly bounded display.

## Work and verification

1. Literal/operator/semantic linking: test offsets, masking, negation, field-value
   compatibility, grade order and preservation of all compound conditions.
2. Physical binding and evidence validation: test source types, parameterized
   predicates, qualifier consumption, and rejection of tampered text facts.
3. Local PostgreSQL replay: compare the original Japanese ETF query with the
   independently derived 13-product source set; independently verify the bond
   candidate population, complete count and bounded evidence display.
4. Real NVIDIA tests of the original and focused condition questions: retain
   full text traces and distinguish API failures from correct answers.
5. Run the relevant broader offline checks and inspect the diff for scope,
   secrets and generated files. Report only checks actually run.

Success requires source-consistent predicates reaching SQL, independently
matching counts/product sets, verified evidence in displayed answers, explicit
date/saleability limitations, and passing relevant tests. API rate limits are
reported as failed external validation, never as a successful answer test.

## Approved amendment: exact-count indexes

The initial ETF replays matched the independently audited 20/13 products.
Both broad bond counts exceeded the unchanged five-second SQL limit; hydration
of five known matching products took 0.035 seconds. Two alternative SQL/JIT
diagnostics did not solve the bottleneck.

The user explicitly approved two reviewed indexes and retesting. ADR-0056
supersedes only the no-database-writes constraint for these indexes. Create
them concurrently, sequentially, through a local maintenance connection;
check capacity, definitions and validity, preserve runtime read-only permissions,
then repeat actual parameterized queries and independent source comparisons.
No source-row changes, timeout increase, ingestion, commit or push are included.

## Implementation and verification results

- Registered Japan/Equity and KRW source literals and their field-specific
  operands. Preserved original source spans, product-name masking, AND terms
  and exact operator/value provenance. Unknown values and missing/negative
  requested conditions still fail closed.
- Normalized only the registered AA-/GTE threshold to AAA, AA+, AA0, AA- IN;
  expanded domestic-bond sale candidates through the disclosed policy rather
  than a fabricated observed status. Aligned remaining_days with Decimal/day.
- Verified five new physical bindings against raw source schemas and eligible
  ledger observations/evidence. Added typed text/boolean fact validation and
  metric-specific qualifier consumption; arbitrary semantic units remain invalid.
- Added only single actual-date pinned defaults for overseas AUM (2026-08-22)
  and source bond remaining days (2026-08-21). Presence includes zero without FX;
  AUM magnitude comparisons keep their conversion requirements.
- Counted the full distinct eligible screen population before bounded display
  hydration; dependent-population screens retain their full binding boundary.
  Materialized only the display CTE to avoid optimizer inlining before hydration.

Initial local ETF queries passed at 20/13, while both broad bond SQLs hit five
seconds. Indexes alone did not establish reliable success. Exact source-count
and display-hydration diagnostics isolated the bottleneck, and scalar/JIT/query
variants were not retained. After the two indexes and display materialization,
an exclusive actual service replay succeeded at 20/13/15,848/15,777 in
1.036/1.204/3.802/3.501 seconds overall. The original generic SQL and failed
parallel diagnostic/service attempts remain separate in local logs.

Six replays per question on one reused service/connection pool then passed
24/24. Overall elapsed ranges were Japan 0.887–1.330s, original ETF
1.076–1.356s, credit 2.204–5.039s, sale candidate 3.362–5.965s. Every query
retained the PostgreSQL five-second statement budget; overall time also includes
intent, ownership validation and separate evidence hydration. Independent raw
XLSX audit matched all 24 full/display counts, displayed IDs, source positions,
values, currencies and dates. This is warm local sequential acceptance, not a
cold-start/concurrent-load or all-natural-language success claim.

Both approved indexes are valid/ready. Measured additions: 14,917,632 bytes for
the metric partial index and 484,704,256 for the reverse origin index;
499,621,888 bytes total. Database after builds: 7,214,926,995 bytes, with about
14 GiB filesystem headroom. No source rows or privileges were changed. Existing
fa_runtime INSERT ACL on evidence_observation_origin was observed; application
search remains protected by read-only transactions and compiler-owned SQL.
Do not equate that boundary with every effective ACL being SELECT-only.

Final relevant tests passed; final broader offline suite: **3,919 passed,
1 skipped, 519 deselected** in 85.42s. The skipped explicit PostgreSQL test
environment and excluded external/organizer/performance integrations are not
successful checks. A preexisting AUM orchestration fixture had an invalid KRW
semantic unit; corrected that fixture to unit=None, retaining currency=KRW
and the compiler's semantic-unit guard. Final independent source/SQL reviews
found no additional defects.

Fresh default GLM NVIDIA requests returned HTTP429 without a proposal. Separate
GLM-5.3 and Nemotron-3.5-Lightning probes timed out at the unchanged 55-second
service deadline. A later focused Japan query still returned HTTP429. Therefore
none of these live calls proves NVIDIA-to-DB acceptance for the new conditions.
Local tests replace only the proposal adapter; deterministic resolution,
planning, actual read-only SQL, evidence checks and rendering are exercised.
No production model change, budget increase, commit or push was made.

Detailed source audits, compiled request traces, provider errors, initial failed
attempts, final 24 replays and index build/rollback diagnostics remain untracked
under the original workspace's data/condition-routing-20261011 directory.

Final index-plan audit selected both new indexes in the ordinary parameterized
EXPLAIN for all four cases. Separate direct PREPARE stress probes are not the
same as actual service replay: forced generic plans could not use the partial
metric index, and the sale-candidate query exceeded five seconds; custom bond
probes also exceeded five seconds in that later diagnostic sequence. Type
differences alone were not established as the cause. Performance headroom and
cache/load sensitivity remain open despite the successful 24 service replays.
Full compiler-population ID projection matched the 20/13 ETF sets; both broad
bond full-ID projections hit five seconds. Do not claim those two projections
passed: their independently reconciled source expectations, complete service
counts and bounded displayed-ID/source verification are separate checks.
