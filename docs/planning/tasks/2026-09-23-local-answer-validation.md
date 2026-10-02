# Local search answer validation — 2026-09-23

## Approval and scope

The user approved fixing answer verification after the September 18 NVIDIA
search test. Continue the existing personal-local worktree without changing
its unrelated in-progress dataset work. ADR-0050 permits this local profile;
ADR-0007's production structured-claim verifier remains authoritative for
production. This small validator does not replace it or certify prose facts.

The failing temporary harness no longer exists in /tmp. Preserve its saved
responses and extract its answer contract into a permanent function with an
offline replay entry point. Prefer explicit rejection over silently dropping
invalid quotes. No model calls, database mutations, data supplementation,
automatic repair, production integration, or source-quote rendering changes.

## Steps and acceptance

1. Add synthetic regression tests for SQL quotes, missing/malformed fields,
   unknown references, document coverage, and exact source quotations.
2. Implement separate SQL/document validation paths returning stable error
   codes, never KeyError/StopIteration for malformed JSON-compatible input.
3. Replay all three saved responses without changing them. Q1/Q2 must reject
   nonempty SQL quotes; Q3 must reject the altered quote. Valid synthetic
   examples must pass. Run the release test suite and inspect task files.

This checks the local output contract and literal citations, not whether all
natural-language claims are true. The original failed answers stay failed.

## Verification result

- 34 synthetic validator regression cases passed.
- Release suite plus answer-contract tests: 67 passed.
- Saved Q1/Q2 now return SQL_QUOTES_MUST_BE_EMPTY without accessing excerpt.
- Saved Q3 returns QUOTE_NOT_VERBATIM; its altered quote remains rejected.
- Replay CLI exits 1 for rejected answers and writes only diagnostic JSON to
  stdout. Original response SHA256 values were unchanged after replay.
- Local replay output: data/personal-search-20260918/answer-validation-replay-20260923.json
  in the parent workspace (untracked; no raw data added to fixtures).
- No API calls, production verifier changes, commit, or push performed.
