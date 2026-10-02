# Personal semantic PostgreSQL search

Approved under ADR-0054, following the NVIDIA migration. Use the bounded
personal dataset and existing environment. This CLI does not activate a dataset,
change observations, expose HTTP, or claim production release-ledger promotion.

## Run

```sh
.venv/bin/python scripts/search_personal_question.py \
  --question '국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘' \
  --api-key-file /path/to/original-workspace/api.txt --display-limit 5
```

Additional examples:

- `TIGER 미국S&P500의 총보수를 알려줘`
- `국내 ETF 중 최근 1년 수익률이 높은 5개를 찾아줘`
- `국내채권 중 만기일이 2045-01-01 이상인 상품을 찾아줘`
- `삼성자산운용이 운용하는 국내 ETF를 찾아줘`
- `2026-08-22 기준 삼성전자를 보유한 국내 ETF를 찾아줘`

These examples describe supported deterministic contracts, not a guarantee of
live model acceptance. Manager/holding execution was verified with synthetic
V3 proposals and the real read-only DB; actual NVIDIA generation for these
relations remains unaccepted. Final named/manager/holding live retests timed out
at the shared 55-second deadline. Do not increase the deadline or bypass semantic
validation to turn these failures into successful answers.

The resolver-only `resolve_personal_intent.py` still returns JSON without product
execution. The older three fixed search plans remain separate. Supply a key
through NVIDIA_API_KEY or the explicit local key file; never commit that file.
The same approved question/catalog/matched-candidate metadata goes to NVIDIA.
No SQL results, observations, documents, keys or hidden reasoning are added to a
second model prompt. The default model remains z-ai/glm-5.3-flash.

## Execution and verification

1. Read actual dataset pins and discover exact catalog entities.
2. Resolve the existing structured V3 proposal, source identities, semantic
   coverage, family locks, typed roles and complete query contracts.
3. Compile the full approved LogicalQueryPlanV2. Relations keep directed object
   conditions separate from product subjects. Date predicate values are not
   copied into as-of qualifiers.
4. Reuse SemanticExecutionGraphCompiler/Orchestrator/SqlCapabilityExecutor and
   ReadOnlySqlRunner. Execution revalidates plan and registry ownership; SQL is
   server-generated with bound values. Run fa_runtime, read-only transactions,
   five-second statement timeout and the resolver's remaining 55-second request
   deadline. Failed/overflowed execution releases no product facts.
5. Read returned evidence/origin/observation/source lineage in one dataset-pinned
   batch. Verify subject/name, definition version, stored/normalized value,
   unit/currency, date/period and cutoff, source eligibility and exact locator.
   Relation evidence must match directed subject/object and date validity.
6. Render deterministic text. Values and sources never come from model prose.

ETF family tables contain ETNs, so ETF queries also require a verified
organizer product_type:2 = ETF observation and supporting source evidence.
Named ETNs remain an explicit unsupported subtype for this entry point.

Full successful screens disclose matching and displayed counts. SQL-ranked
results disclose returned top-N, not the unseen total population. The display
limit is 1–50; runner cardinality is bounded at 10,000 rows and overflow fails
rather than posing as a complete count. Missing/zero remain distinct. An empty
upstream result causes dependent work to be skipped explicitly.
SQL_RESULT_ROW_LIMIT_EXCEEDED and PERSONAL_SQL_TIMEOUT disclose the bound and
ask for a narrower product/date/condition. They do not release partial facts.

Fee percentage_point is displayed as percent without dividing by 100. Numeric
fee thresholds require an explicit percent unit; plain lookup/rank use the
verified source unit. Domestic one-year return uses only P1Y/du_er_1y and retains
source period_end, without invented period_start. Maturity is a date value,
which may be in the future; source snapshot/cutoff remain separate.

## Limits

- Overseas one-year return: SOURCE_ONE_YEAR_RETURN_NOT_PROVIDED. A one-day field
  cannot substitute for one-year return.
- Public-fund total fee: PUBLIC_FUND_TOTAL_FEE_DEFINITION_UNVERIFIED. Do not sum
  source_rate components or infer percent/annualization.
- Holding filters need an explicit as-of date and available sampled relations.
  This does not establish full-market holdings coverage or supplement-weight
  comparability. Manager filters use source relationships, not a live sale list.
- Positive AND relation filters are supported. Relation negation/OR/exclusion
  and general source OR return limitations while Boolean lowering is incomplete.
- Missing/ambiguous family, period, names and prior scope request clarification.
  Exact discovery does not automatically repair arbitrary misspelled names.
  There is no implicit cross-request memory.
- The local fact renderer supports lookup/screen/rank/compare SQL rows. Generic
  aggregates, calculations, relation expansion and document answers have not
  been connected to this new CLI. Registered planning capability alone does not
  imply local output support.
- Mixed date/unit/currency requests still require approved binding semantics;
  unsupported qualifiers are not silently ignored.

## Verification status — 2026-10-02

The final offline suite passed: 3,577 passed, 4 skipped, 516 deselected. Excluded
external integrations and performance markers are not successful checks.

An intermediate actual NVIDIA/DB six-case run passed four cases: fee screen 154,
named fee lookup 1 with verified missing status, domestic P1Y top 5, maturity
>=2045-01-01 929. Independent SQL matched counts, displayed IDs, ranked IDs and
missing status. Later live schema/type errors and timeouts remain recorded;
the final sequential named/manager/holding run timed out in all three cases.
End-to-end live NVIDIA acceptance remains open.

Separate synthetic V3/real DB checks passed manager 243 and sampled holding 9,
including full ID sets, displayed IDs and directed/date/source evidence. Those
checks made no external API calls and do not certify NVIDIA generation.
See [the task plan](../planning/tasks/2026-10-02-personal-semantic-search.md) for
attempt history, independent checks and remaining priority.
