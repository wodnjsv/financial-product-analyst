# Personal verification harness

- Date: 2026-10-12
- Status: implemented and offline verified; actual NVIDIA and broad bond latency acceptance remain incomplete
- Related decisions: ADR-0007, ADR-0020, ADR-0032, ADR-0050–0056

## Assumptions, outcome and constraints

The active service is the personal pinned local PostgreSQL semantic search path.
Existing production AtomicClaim/ClaimSupport/CalculationRecord/ClaimGate and
compiler ownership validators already implement much of the supplied proposal.
Reuse those authorities rather than creating another claim ledger or SQL parser.
The enhancement must make stage outcomes visible, independently check returned
results against the question's approved task, and prevent altered final text
from being released. Provider failure and an intentionally limited answer must
not be counted as successful factual verification.

No raw-data edits, ingestion, database/schema/index/privilege changes, production
activation, additional LLM judge, arbitrary model SQL, timeout increases, commit
or push. Preserve source missingness, supplemental metric separation and source
authority policies. Graph/Vector projection checks are not executed by this local
SQL path and must be reported as not applicable, never as passing. Source time
uses Asia/Seoul cutoff dates; future maturity values remain legitimate values.

## Alternatives

- New verifiers/claim DB versus an integrated harness around existing checks:
  reuse existing checks and add only the missing local result/final boundaries.
- Numeric regex allowlists versus exact rendering from verified structures:
  choose exact rendering. Numbers in dates, names, source rows and verbatim
  document quotes are not financial claims and must not be misclassified.
- Another LLM judge versus deterministic checks first: implement hard gates in
  this scope. Additional model roles are a separate architecture decision.
- A new global five-tier source hierarchy versus accepted metric/document
  ownership policies: preserve the accepted policies. Do not enable manager
  document fallbacks or silently fill organizer NULL values.

## Work and verification

1. Reuse and record plan/query/evidence gates with a pinned structured report.
   Verify dataset/manifest/cutoff and registered local execution route before
   execution. Failed/unrun/not-applicable stages are distinct from passed stages.
2. Independently validate verified result rows against task scope, predicates,
   qualifiers, rank order/ties/limit and output counts. Reject duplicate subjects
   and fields at the local verification boundary; preserve zero versus missing.
3. Correct source datetime cutoff conversion to Asia/Seoul and test the cutoff
   boundary, including relations and future maturity values. Check registered
   organizer source ownership without changing accepted source priorities.
4. Bind verified result structures to canonical final rendering and reject
   changed values/dates/counts/citations or added prose. Include stage reports in
   text logs and expose them in the local result object/optional CLI report.
5. Add question-level and adversarial tests that assert the failing stage and
   prove no downstream query/rendering after a blocking failure. Run narrow
   tests, the appropriate full offline suite and read-only local regression
   questions. Separate actual NVIDIA trials from transport-replaced replay.
6. Inspect final diff for scope/secrets/source data and document real outcomes,
   limitations, and reused versus newly implemented checks.

Success: tampered requests/results/evidence/final text are blocked at the correct
stage; normal, zero, missing, future-maturity and intentionally limited cases
remain usable; stage hashes/pins/coverage are consistent; checks actually run
pass. No claim of arbitrary calculation, Graph/Vector activation, semantic-judge
accuracy or all-question factual coverage is permitted.

## Delivered

- Added typed `personal-verification.v1` stage records with request/data pins,
  per-task attempts, safe reason codes, complete coverage and artifact/output/
  report hash validation. Failed, unrun, not-applicable, intentionally limited
  and factually verified outcomes are distinct.
- Connected plan and compiler-ownership gates to SQL execution; added live DB
  manifest/cutoff checks in repeatable-read/read-only transactions for SQL and
  evidence hydration, including empty evidence results.
- Added independent local scope, qualifier, predicate, rank/order/tie/limit and
  count checks against returned verified structures. Moved them before producer
  results can bind to dependent SQL. This is not unseen-population recomputation.
- Strengthened registered source workbook/column/family and authority metadata
  checks. Source datetimes use Seoul cutoff dates; future maturity values, zero
  and missingness retain their existing meanings.
- Sealed canonical server output and checked exact final text. Added optional
  exclusive-create CLI JSON reports and explicit final verification text.
- Preserved real SQL/evidence-loading cancellation and bounded retry history.
  Query success, SQL success, evidence-loading failure and later retry success
  are recorded at their actual stages.
- Documented the bridge in the README and
  [personal verification runbook](../../runbooks/personal-verification-harness.md).
  No production Claim/Calculation/Graph/Vector activation or LLM judge was added.

## Verification and observed limits

The final full offline command was:

```sh
.venv/bin/python -m pytest tests \
  -m 'not postgres and not ncp_integration and not performance and not organizer_data and not object_storage and not official_data and not jena_integration and not clova_integration' -q
```

Result: **4,087 passed, 1 skipped, 519 deselected in 101.27s**. The skip was an
explicit PostgreSQL test without `FINANCIAL_AGENT_TEST_DATABASE_URL`; excluded
external/source/performance tests are not passes. Afterwards, one actual
evidence-loading cancellation/retry regression was appended; the dependency
test file passed **4 tests in 14.57s**. The full suite was not rerun solely for
that additional test, and these counts must not be added together. The final
combined personal harness and dependency regression passed **15 tests in
16.37s**. All 13 actual DB replay/targeted report objects passed strict JSON
deserialization and report integrity checks; the seven successful broad replay
counts/display IDs matched the existing independent raw-source expectations.

Final `git diff --check` passed. A scan of all 82 changed/untracked source and
documentation paths found no NVIDIA/private-key secret patterns or raw-data
paths; the index was empty. Existing unrelated pending work was preserved.

The new files test invalid plan/query pins, changed SQL parameters, correct-source
but wrong-condition results, wrong source authority/locators, scope/qualifier/
rank/count violations, source time boundaries, zero/missing/future-maturity,
changed final values/citations/text, report coverage/hash tampering, dependency
blocking and real Orchestrator cancellation/retry records. Existing release,
document, calculation and graph tests remain part of the offline regression;
that does not activate those paths in personal SQL search.

### Local DB replay: model transport replaced, real SQL/evidence/rendering

At the unchanged `personal-2026-08-24-v1` manifest/cutoff, each original question
was run three times in the same bounded read-only engine:

| Question | Success / attempts | Result on success | Elapsed seconds |
| --- | --- | --- | --- |
| 일본 주식형 해외 ETF 찾아줘. | 3/3 | 20 unique products, all displayed | 1.208 / 0.913 / 1.202 |
| 일본 주식형 해외 ETF 중 총보수 0.5% 이하이고 AUM이 있는 상품만 찾아줘. | 3/3 | 13 unique products, all displayed | 1.804 / 1.288 / 1.382 |
| 원화채권 중 AA- 이상 종목 알려줘. | 1/3 | 15,848 total, 5 displayed | 6.862 fail / 5.948 fail / 4.001 pass |
| 현재 판매 가능한 원화채권 중 AA- 이상 종목 알려줘. | 0/3 | No released answer | 6.261 / 6.097 / 5.241, all fail |

Total **7 successes / 5 SQL statement timeouts**. Failures have outer
`PERSONAL_SQL_EXECUTION_FAILED`, execution reason `SQL_STATEMENT_TIMEOUT`,
unrun downstream evidence/final stages and no output hash. The per-statement
5-second limit was preserved; total elapsed time includes other stages.
The existing raw-source expectations are used separately to compare successful
ETF full IDs/counts and credit-bond display IDs/count. Previous task 24/24 warm
replays do not replace these latest failures.

A separate entity-scoped question for 산은캐피탈770-4 succeeded in **1.928s**,
returning 1 product with KRW, AA-, maturity **2028-07-10**, remaining days **689**
at **2026-08-21**, source workbook `prbd01n001_data.xlsx`, row 366 and exact field
locators. This exercises future maturity and the source-owned purchase-candidate
assumption; it does not establish broad-query performance or live sale status.

### Actual NVIDIA: failed before plan

Default model `z-ai/glm-5.3-flash` was called through the actual CLI with the
original overseas ETF question and the already authorized metadata payload.
It returned **429 / MODEL_RATE_LIMITED**. The CLI saved
`{"execution_error":"MODEL_RATE_LIMITED","verification":null}`; no SQL or
post-plan verification ran. The real model's new-question acceptance remains
unverified. No substitute-model success is asserted.

Local artifacts are preserved under the original workspace's ignored
`data/verification-harness-20261012/`, including full offline output, final
`local-proposal-replay-repeat3-summary.json`, targeted bond output, actual NVIDIA
failure report and the human-readable `verification-summary.txt`. Earlier failed
attempts remain separate. No raw data, API keys, database changes, staging,
commit or push were performed for this task.

Remaining follow-up: broad bond count-query latency/execution-plan variance and
actual NVIDIA recovery; general financial calculation/claim release, Graph/
Vector and semantic paraphrase assessment require separate scoped integration.
