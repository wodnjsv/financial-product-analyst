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

These examples describe supported contracts, not a universal model guarantee.
The 2026-10-02 live tests failed; the 2026-10-11 V6 fixes subsequently passed
named/manager/holding with actual NVIDIA and the real read-only DB under the
unchanged 55-second deadline. Both histories remain recorded. Never bypass
semantic validation to turn a failed proposal into a successful answer.

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

## Existing question audit — 2026-10-11

The full 217 original-question baseline returned one SQL result, which incorrectly
used the descending default for an explicit lower 10 request. Source extraction
now preserves 하위/작은 as ascending and 상위/큰 as descending, using existing
exact locks and ordering provenance. Ranking count text says 순위 결과.
Replaying the stored NVIDIA proposal through current code and the real read-only
DB matched independent ASC10 IDs, values, dates and displayed source locators.
This local replay is distinct from a fresh NVIDIA request.

Missing demonstratives, false whitespace-joined company names, currency/ticker
collisions and incomplete correction feedback were also fixed. Policy rejection
does not request scope changes that imply the operation can be enabled.
Generic nonanswers, structural failures and timeouts remain separate categories.

After explicit expanded transmission approval, the unchanged217-question V7/V3
rerun completed with141 nonfactual responses,16 policy blocks,5 input rejections,
20 contract/system errors,34 timeouts and one independently source-verified
lower10 result. A separate48-case V8 actual rerun returned one verified result,
13 nonfactual responses,1 policy block,3 contract failures,4 timeouts and26
NVIDIA rate-limit failures. Preserve the original outputs; subset results do not
certify the full question set. Both corrected batches executed SQL only for the
one ranked case; every returned ID,value,unit,date and displayed source was
independently audited.

The V8 ranked output discloses7 rows without actual dates across the10 returned
rows, including those outside the5 displayed. Three other rows have older dates.
All10 source rows have -100% returns,zero closes and elapsed trading-end dates;
the current source policy does not declare -100 missing. Preserve source values
and disclose the limit instead of silently excluding them or substituting the
snapshot date. This verifies stored-source ranking, not current economic
performance. The empty-comparison guard returns existing incomplete qualifier
rejections instead of an uncaught validation error. Incomplete predicate/field
plans explain the service limitation without inventing conditions or running SQL.

The final generic meaning-failure wording and enum-only reference-target repair
feedback were verified using strict stored-response replay and the full offline
suite (3,727 passed,4 skipped,516 deselected). The final one-question live probe
still returned NVIDIA429 without a first response or SQL. Keep that provider
failure separate from the frozen V8 subset and offline correction verification.

AUM needs an explicit verified date unless an approved pinned semantic default
is supplied. No cutoff or MAX date is substituted. Separate synthetic questions
with 2026-08-21 verified domestic ETF AUM top 5 against 1,161 eligible ETF records;
they are not successes for the original undated questions. Stored units remain
source_defined_amount with no inferred KRW conversion. Overseas AUM magnitude
comparisons additionally need a currency normalization policy, and public-fund sums need an approved
grain policy and connected aggregate output. These support gaps remain after
the actual reruns. See [the audit task](../planning/tasks/2026-10-11-existing-question-regression.md).

## Source condition routing — 2026-10-11

The personal normalizer is `intent-normalizer-v4-condition-operands`; NVIDIA's
proposal prompt remains `nvidia-chat-json-proposal-v8`. Source-owned literals,
operator locks and allowed field/value pairs preserve all requested AND terms:

| Question condition | Semantic predicate | Source column / metric version |
| --- | --- | --- |
| 일본 주식형 | region EQ Japan AND asset_class EQ Equity | wu_inv_rgn / wu_inv_ast_type, version 2 |
| 원화채권 | currency EQ KRW in domestic_bond | curr_cd, version 2 |
| AA- 이상 | credit_grade IN AAA, AA+, AA0, AA- | crd_grd, version 2 |
| 판매 가능 | maturity_date GT cutoff AND remaining_days GT 0 day | bond maturity and source remaining_days, version 2 |
| AUM이 있는 | aum IS_PRESENT, including source zero | du_last_aum, version 2 |

Credit expansion retains the original AA-/GTE provenance; arbitrary string
ordering or unregistered thresholds are not enabled. Saleability is a disclosed
organizer purchase assumption, not an observed/live sale status. There is no
sale flag in this bond source. Its cutoff is 2026-08-24, not the current date.
The source remaining-days value is Decimal/day, not an invented calculation.
Negation and incomplete requested conditions must fail closed.

The server supplies an undated request's default only when the approved pinned
metric has one actual date across all source observations: overseas AUM
2026-08-22 or bond remaining days 2026-08-21. Mixed, missing, future or wrong-family
dates yield no default. No cutoff/MAX date substitution or global date filter
is used. AUM presence needs no FX normalization; comparisons/ranks still do.
Static classifications and the future maturity value keep their own source dates.

Independent source reconciliation gives Japan/Equity/ETF 20 products and
Japan/Equity/ETF + fee <=0.5% + AUM present 13. KRW + registered AA- grade set gives
15,848 unique bonds; the disclosed maturity/remaining-days candidate condition
gives 15,777. Source duplicates are counted once, not as separate products.

For terminal screen tasks, the compiler counts all distinct eligible matching
products and materializes the bounded display before source-evidence hydration.
The renderer accepts a full count only from the validated compiler result;
ordinary results still require total count to equal their row cardinality.
Screens producing a downstream population binding cannot use bounded output.

The user approved two local indexes after bond counts hit the unchanged five-second
SQL limit. Apply [personal_condition_indexes.sql](../../scripts/personal_condition_indexes.sql)
only as local owner maintenance, outside a transaction. Its database guard rejects
targets other than financial_agent_local; existing names cause an error rather
than hiding an invalid index. [Rollback](../../scripts/personal_condition_indexes_rollback.sql)
drops only these two additions. Both were built valid/ready; total measured size
499,621,888 bytes, database size 7,214,926,995 bytes. No source rows, existing
indexes or grants/revokes were changed. Search transactions remain read-only.
Partial-index use depends on planning; creation alone does not prove acceptance.

Final local service replay succeeded for all four cases above, followed by
24/24 successful replays (six per question) on one reused service/connection pool.
Counts and evidence were verified; each statement retained its five-second
budget. Overall local processing ranged 0.887–5.965 seconds, including intent,
compilation and evidence hydration. This is a warm local sequential check, not
a cold-start/concurrent-load SLA. Earlier failures and diagnostic variants remain
in the untracked logs; phase-only success is not service acceptance.

Additional direct prepared-plan stress diagnostics still canceled some bond
queries at five seconds, including a forced-generic sale-candidate plan that
could not use the partial metric index. Ordinary EXPLAIN selected both indexes
for all four cases. These stress probes do not replace the successful actual
service replays, but show that latency headroom remains limited. Full ID
projection matched both ETF sets; the broad bond full-ID diagnostic timed out.
Its source-expected sets and verified service counts/displayed IDs are separate.

Fresh NVIDIA probes using the same authorized metadata returned HTTP429 for the
default GLM model; two alternative model probes timed out at 55 seconds. No live
NVIDIA-to-SQL success is established for these condition cases. The local replays
replace only the proposal transport with a test adapter and exercise the actual
deterministic resolver, compiler, read-only runner, proof verifier and renderer.
Offline checks: 3,919 passed, 1 skipped, 519 deselected. See
[ADR-0055](../planning/decisions/ADR-0055-personal-source-condition-routing.md),
[ADR-0056](../planning/decisions/ADR-0056-personal-condition-query-indexes.md) and
[the task](../planning/tasks/2026-10-11-condition-field-routing.md).

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
At that date, end-to-end live NVIDIA acceptance remained open.

Follow-up 2026-10-11: after role-specific ID and targeted correction fixes,
actual normal-service named/manager/holding examples passed 1/243/9 with one
model call each, in 15.362/12.714/9.247s. Independent SQL matched counts,
displayed IDs and missing status. Current offline suite: 3,589 passed,
4 skipped, 516 deselected. This closes acceptance for these three examples;
coverage beyond them, latency stability and HTTP/release integration remain
open. See [the repair task](../planning/tasks/2026-10-11-nvidia-repair-feedback.md).

Separate synthetic V3/real DB checks passed manager 243 and sampled holding 9,
including full ID sets, displayed IDs and directed/date/source evidence. Those
checks made no external API calls and do not certify NVIDIA generation.
See [the task plan](../planning/tasks/2026-10-02-personal-semantic-search.md) for
attempt history, independent checks and remaining priority.
