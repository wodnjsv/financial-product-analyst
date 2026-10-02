# Local search guidance and document grounding fixes — 2026-10-02

## Approval and boundaries

The user explicitly requested diagnosis and correction of the remaining issues
reported by the October 2 retest. Continue the existing personal-local worktree
under ADR-0050 and ADR-0051. The deterministic rendering principle of ADR-0007
applies; this task does not activate the production evidence/release pipeline.

Assumptions: PostgreSQL retrieval rows and bounded hash-checked excerpts are
trusted inputs. The existing snapshot, original KRX missingness and separate
manager weights must remain unchanged. No ingestion, new HTTP service, commit,
push, HCX call or DB write is needed. Test logs remain ignored local artifacts.

Root causes: LIMITATIONS contains example-specific counts/security types;
reference regex scans literal quotation text as if it were application IDs;
the document draft preserves arbitrary model prose and only checks structure.

Chosen direction: actual-query guidance; model document selection contains only
retrieved citation IDs; source fields and complete excerpts are rendered on the
server; final document validation accepts only that source-owned representation.
Free prose, added terminology, arbitrary quote spans and offsets are rejected.
The existing bounded excerpt is not shortened further, preserving its supplied
conditions and negations. This certifies fidelity to retrieved excerpts only,
not PDF extraction quality, complete context or current market information.

Alternatives: another LLM judge cannot deterministically guarantee factuality;
keyword/negation blacklists miss unsupported claims; shorter selectable spans
can remove conditions. Whole-excerpt rendering is simpler and reliable, at the
cost of losing free paraphrased summaries. Historical prose answers remain
rejected; explicitly regenerated source-only outputs are separate derivatives.

## Steps and verifiable success criteria

1. Add regression tests before fixes: limit=1/fewer returns/preferred shares;
   literal [D9] in original text; contradictory/unsupported model prose;
   unknown/missing/duplicate selections; final rendered body tampering.
2. Correct guidance without changing filter/sort/calculation semantics. Build
   one canonical document text from retrieved fields and full excerpts; reject
   free-prose model drafts and altered final text. Keep literal quotes intact.
3. Adapt explicit legacy replay and runbooks to the restricted local contract;
   never relabel old answers as successful or silently strip their prose.
4. Run narrow release/retrieval tests, then the prior broad offline suite.
   Run all three live read-only DB queries and limit/preferred-share probes.
   Recheck source hashes and unchanged KRX observations. Test NVIDIA using the
   approved questions/excerpts and new document-selection contract, without
   recording secrets or hidden reasoning.

Success: displayed counts/types match the query; complete source text containing
reference-like strings survives and passes final validation; false/free prose
or modified output is rejected; all required tests and live checks pass.

## Verification results

- Five guidance regressions failed before the fix, then passed. Ten grounding
  regressions failed before the new contract/body gate, then passed. Three
  additional partial/duplicate quote and dataset-conflict checks reproduced
  final-validation gaps and now pass. Legacy replay has nine regression cases.
- Narrow release/retrieval/answer/ingestion verification: 186 passed.
- Final broad offline suite: 3,192 passed, four explicit-data gates skipped,
  516 external integration/performance cases deselected; no HCX calls.
- Live read-only PostgreSQL: original three queries returned 210/5, 9/5,
  58/3 matched/displayed; three empty searches, limit=1 and preferred-share
  probes passed. Exact document quotes: 3/3, 1,288 characters. Supplement source
  and identity checksums: 18/18 for nine observations. Original KRX captures:
  50 files, 2,925 observations, 19 known and 2,906 unknown; no mismatches.
- NVIDIA GLM-5.3-Flash low-effort temporary harness: three intent calls and
  one citations-only document call all HTTP 200; returned D1/D2/D3 selection
  passed final body/quote verification. No hidden reasoning or key logged.
- Historical Q1/Q2/Q3 response hashes and rejection verdicts preserved. An
  explicitly created Q3 source-only derivative passed independently.
- Generated report: ignored parent workspace
  data/personal-search-20261002-fixed/fix-verification-report.txt.
- git diff --check passed; no commit, push, DB write or source-data mutation.

The chosen restricted contract is recorded in ADR-0052. This is source fidelity
and controlled rendering, not a general semantic judge for arbitrary summaries.
