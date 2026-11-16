# Verification harness ablation

- Date: 2026-11-16
- Status: done, offline only
- Related: ADR-0057, [2026-10-12 verification harness](2026-10-12-verification-harness.md)

## Outcome

Measure how many injected errors reach the final answer with the verification
harness on versus off, on the same fake-adapter, fake-database path.

## Constraints and non-goals

No implementation changes. The experiment only patches the three local
verification functions inside the script. No NVIDIA, PostgreSQL or organizer
data. Generated JSON output stays untracked.

## Work

1. Add `scripts/run_verification_ablation.py`: 20 clean and 30 injected-error
   cases (predicate, value, unit/date/definition, source eligibility, product,
   final text), each run with verification on and off.
2. Record the results and limits in
   `docs/planning/reports/2026-11-16-verification-ablation.md`.

## Success criteria

- Every clean case is delivered with verification on.
- Every injected-error case is blocked with verification on and is delivered
  with verification off, so the difference is attributable to the harness.

Result: met (on 20/20 clean delivered, 0/30 errors delivered; off 30/30 errors
delivered).
