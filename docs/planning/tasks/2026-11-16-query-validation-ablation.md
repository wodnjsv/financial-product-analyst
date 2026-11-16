# Query validation ablation

- Date: 2026-11-16
- Status: done, offline only
- Related: [verification harness ablation](2026-11-16-verification-ablation.md)

## Outcome

Measure how many invalid queries reach SQL execution with the pre-execution
query validation on versus off, using the same fake model adapter and a fake
runner that records the SQL it receives.

## Constraints and non-goals

No implementation changes. The script only patches four existing checks:
product-family exact locks, product-family ambiguity, disjunction scope and
pre-execution recompilation. No NVIDIA, PostgreSQL or organizer data.
Generated JSON output stays untracked. Missing-period requests are excluded
because no SQL can be compiled without a period, so there is no off arm.

## Work

1. Add `scripts/run_query_validation_ablation.py`: 20 clean and 23 invalid
   cases (wrong family, ambiguous family, disjunction, tampered request), each
   run with validation on and off.
2. Record the results and limits in
   `docs/planning/reports/2026-11-16-query-validation-ablation.md`.

## Success criteria

- Every clean case reaches SQL execution with validation on.
- Every invalid case is stopped before SQL execution with validation on and
  reaches SQL execution with validation off.

Result: met (on 20/20 clean reached SQL, 0/23 invalid reached SQL; off 23/23
invalid reached SQL). Two runs produced identical output.
