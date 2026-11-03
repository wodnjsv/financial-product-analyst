# Existing question regression and corrective work — 2026-10-11

## Approved direction

The user requested finding all previously authored expected questions, asking them
through the current service, inspecting answers and correcting failures. This
approves reproductions and surgical fixes under ADR-0053/0054, preserving the
existing uncommitted NVIDIA repair changes on codex/nvidia-repair-feedback.

Assumptions: metadata-only NVIDIA transmission authorization remains in force.
The human-readable core set has 52 cases; latest held-out V3 has 160 questions
(the older versions repeat them); five hybrid-link questions are distinct.
Test all 217 distinct original questions without replacing fictional names,
adding missing scope or changing their dates. Old synthetic/design expectations
are diagnostic, not proof of current local data or executable support.

Outcome: a complete ignored text/JSON execution record and per-case assessment,
reproduced software defects corrected and independently verified. Distinguish
actual correct answers, justified limitations, model/provider/system failures
and incorrect interpretation/output. No blanket claim that all questions work.

Non-goals: new ingestion, fabricated entities/metrics, bulk API data export,
model-authored SQL, weakened validation, competition rollout, commit or push.
Normal request 55 seconds, read-only SQL 5 seconds and single model repair stay
unchanged. Two independent test questions may run concurrently; every request
remains stateless and has its own bounded pipeline. Only questions/catalog/
matched entity metadata go to NVIDIA; SQL facts/results/documents stay local.

Alternatives: test only the core52 versus all distinct authored question sets.
Use all 217 because the user requested all existing questions. Literal original
questions preserve unresolved references/fictional names; substituting actual
products would change the test, so any separate support probes are labeled.
Limitations are not successful factual answers. Unsupported capabilities are
reported as gaps, not bypassed or guessed.

## Plan and success criteria

1. Inventory core/heldout/hybrid questions and save manifest provenance. Run all
   distinct questions through actual NVIDIA + PersonalSemanticSearch. Verify
   every case has text, intent or stable failure code, API timing and disposition.
2. Audit interpretations against authored expected axes/source semantics; audit
   executed plans for preserved conditions and data/source verification. Check
   actual result rows independently for all executable case shapes.
3. Reproduce discovered software defects with targeted offline tests, make the
   smallest compatible corrections, and re-run affected live cases. Retain
   baseline failures separately; make no automatic perpetual model retries.
4. Run relevant tests then broader offline suite, inspect diff/secrets/scope,
   update runbooks and produce readable case-by-case report with remaining gaps.

Success: no question is silently dropped; no unsupported result is represented
as correct; identified code fixes have regression tests; final factual outputs
are verified or explicitly limited. External availability/latency failures and
missing data are reported separately from implementation correctness.

## Reproduced defects and corrections

- MIS-DETF-001 executed the highest rather than lowest10 P1Y returns. Original
  sort-direction extraction omitted 하위, leaving the descending default.
  Added bounded explicit upper/lower and size direction cues to source literals;
  existing solver locks/provenance supply ASC without a new default. Independent
  baseline ledger SQL confirmed exact DESC10 IDs and different ASC10 IDs.
- FLT-DETF-001 falsely discovered 서 연 inside 투자하면서 연금. Prevent
  whitespace-normalized names from starting inside the prior prose word while
  preserving existing contiguous overlap and genuine spaced names/particles.
- Type-qualified demonstratives (이 국내 ETF/이 채권) and 그거 were absent
  from normalization. Add source-bounded spans and word/particle boundaries;
  keep distributive 각각 with explicit source enumerations instead of creating
  an unrelated antecedent requirement. A supplied reference cannot be omitted
  by the proposal: validation rejects missing source references without guessing.
- Actual proposal failures lacked actionable feedback beyond schema validation.
  Supply source-owned family/type applicability, axis cardinality, missing
  relation subject type and known Pydantic invariant codes. No invalid response,
  provider prose or hidden reasoning is echoed. Retain one repair and rejection.
- Ranking text said 상위 결과 even for ascending/lower results. Use the neutral
  순위 결과 count label; full-screen versus returned-rank count meanings stay
  unchanged. Values, ordering, dates and evidence remain compiler/ledger owned.
- Normalizer provenance is intent-normalizer-v3-reference-spans and NVIDIA
  adapter provenance is nvidia-chat-json-proposal-v7. Baseline process retains
  V6/V2, so corrective logs must be separately identified.

Intermediate offline check after direction/source fixes: 3,646 passed,4 skipped,
516 deselected. This is not final acceptance; later changes and actual-model
retests still require verification. Capability/data gaps (AUM/date defaults,
Boolean/controlled-value predicates, general aggregation/calculation/similarity,
documents and unavailable metric definitions) are not erased by structural fixes.

Additional reproduced corrections: missing Korean particles 에/로/으로/보다
were introduced by reference boundary tightening; preserve these source stems
and reject longer words instead. Observed demonstrative/result references such
as 해당 상품들/그 목록/그중/그 지역별 now preserve exact source offsets.
Policy-blocked requests no longer receive scope/date/name clarification text
that would imply those details can enable a prohibited operation.

Intermediate implementation offline check: 3,673 passed,4 skipped,516 deselected in
81.37s. Skips/exclusions are not successful external-integration checks.

AUM audit: the personal factory supplies no semantic-date default, so correct
rank+family+aum proposals can be rejected for missing as_of. The pinned dataset
is building and has no verified AUM snapshot-date declaration. Domestic and
public-fund dates are mixed, and source_defined_amount units are unresolved;
overseas observations share a date but include mixed currencies. No cutoff or
latest date is substituted. ADR-0030's registered-default policy requires a
verified, pinned and disclosed observation date; this audit does not authorize
a new comparison population or unverified amount/unit binding. Local audit
files preserve counts, SQL and source/observation checks.

## Completed checks and remaining acceptance

Baseline V6/V2: all 217 original questions completed, with 217 text outputs and
217 proposal/SQL recording files. Total actual model calls 282; five 4097-code-point
inputs were rejected with QUESTION_INVALID before an API call. Outcomes: 135
without factual answers, 15 policy-blocked, 5 pre-model rejections, 45 model/contract
errors, 16 deadline failures and one executed wrong-direction answer. These
are observable categories, not an accuracy/pass-rate score. Median elapsed
13.986s, p95 55.130s. All 57 audited OOD/policy/injection/boundary cases released
no product SQL facts; overblocking and remaining interpretation failures are
listed in the ignored boundary audit.

A further source collision was reproduced: HKO-NEG-UNI-004's fullwidth USD was
locked as an ETF ticker, removing the currency literal. Discovery now hands
registered KRW/USD following an explicit currency-field cue to the existing
literal extractor. Bare/named ticker uses and longer registered names stay
entities. No new currency normalization or grade comparison is introduced.

Final implementation check after this correction: 3,684 passed,4 skipped,516
deselected in 77.42s. git diff --check passed. No source workbook, key, log,
database write, staged file, commit or push was introduced.

Current local replay: the stored baseline NVIDIA proposal for the unchanged
MIS-DETF-001 question produced ASC lower 10. Independent source observation,
ETF-type and eligible evidence queries matched all 10 IDs,values,units,dates and
displayed source locators; eligible nonmissing ETF population 1013,missing/blank
222 excluded. This is local code/DB verification with zero new NVIDIA calls.
Five separate synthetic AUM probes with an explicit 2026-08-21 date matched
independent top 5 from 1161 ETFs; their altered questions are excluded from the
original-question denominator. Explicit-date overseas AUM still rejects currency
normalization and fund sums reject unverified grain.

Fresh V7 full 217 API rerun: automatic approval review rejected the request
because earlier explicit metadata-export approval specified six cases and did
not explicitly cover the expanded retransmission. Requested user approval for
all 217 questions/catalog/matched-candidate metadata; excluded observations,
documents and query results. No rerun API call was made and no workaround was
used. Final live acceptance remains pending that approval and rerun.

Ignored artifacts in the original workspace's data/existing-questions-20261011/:
all-question-results.txt,comparison.json,baseline/,corrected-local-replay/,
offline-regression.txt,boundary-audit.txt,aum-gap-audit.*,
aum-capability-and-classification-audit.*,mis-detf-baseline-audit.* and
retest-approval-status.json. Failure history and initial diagnostic harness
failures remain separate from subsequent verified local replay.

## Explicit rerun approval

After the concrete request to retransmit all217 questions, registered meanings
and matched candidate name/type/family/internal-ID metadata (excluding DB
observations, documents and query results), the user replied “다시 진행해”.
This authorizes the full V7 rerun. Preserve baseline/local-replay history, keep
the same55s request/5s readonly SQL bounds and two concurrent questions, and
verify every factual output independently. Any remaining invalid or unavailable
answer stays a separate failure/limitation; no result fabrication or validation
bypass is authorized.

## V8 bounded contract guidance correction

The approved failure-fix scope includes repeated scalar reference arrays in
LKP-DETF-001/HKO-CTX-021/HKO-CTX-036 and an incompatible singleton
selected_product/consume_single_result link in HKO-CTX-036. The running V7 batch
uses its frozen code; preserve its records. Assume the registered reference
schema and role/link validation rules remain authoritative.

Add exact optional-single-item reference array examples and role/link guidance
to the NVIDIA adapter, and enum/role-shape-only feedback at existing invalid
link-target checks. Use V8 adapter provenance. Prefer guidance and feedback over
scalar coercion or automatic link correction because those alternatives can
guess a target or change the question's meaning. No validation weakening,
extra retry, new API call, DB write, ingestion or commit is part of this fix.
The same guidance clarifies the existing invariant that every selected or
ambiguous concept must apply to the frame's selected families and subject types;
unsupported meaning stays unmapped instead of borrowing an inapplicable concept.

Verify repeated scalar outputs still reject after one repair, incompatible
links retain INVALID_CONTEXT_GRAPH with safe actionable feedback, every valid
role/link combination remains valid, and schema/source IDs stay unchanged.
Run narrow NVIDIA/context tests and inspect the diff before affected-case live
verification by the parent workflow.

The parent also reproduced missing actual dates in ranked MIS rows. The source
contains -100 returns, zero closes and elapsed trading-end dates, but no approved
-100 missing-value policy; retain values, order, membership and missing-value
classification. Add only a deterministic count disclosure for all ranked rows
without an actual observation date and explain the stored-source ranking cannot
establish a current-date comparison. Never substitute the dataset snapshot date.
Independent local verification of the original MIS lower10 found7 rows without
an actual observation date and3 with older dates. All5 displayed rows were
undated; the disclosure correctly counts7 across the full10, not only display5.
The targeted renderer tests failed before the fix and all49 relevant tests then
passed; broader verification and actual-model acceptance remain separate.

V8 offline verification: the initial contract-shape reproduction had12 failures
and16 valid-shape passes. After the narrow guidance/feedback change, all223
NVIDIA, repair-feedback, context, assembler, existing-regression and CLI tests
passed in3.74s. The32 new cases cover scalar reference rejection after one
repair, all16 valid role/link combinations, incompatible source/replacement
feedback without private IDs, and repeated inapplicable ambiguity rejection.
The CLI/NVIDIA assertions identify V8. No model API or DB write was performed;
the V7 frozen batch and later live V8 acceptance remain separate.

## Empty comparison-field solver correction

Stored HKO-CMP-008 responses reproduced an uncaught ValidationError after
strict proposal/semantic/context validation succeeded. Missing period qualifiers
removed all comparison fields; the empty Cartesian combination then passed
all(empty) and tried to construct a comparison with neither metric nor profile.
The existing ComparisonSpecV2 completeness invariant correctly rejected it.

Within the approved failure-fix scope, add only a nonempty-field-choice guard
to comparison generation. Keep existing qualifier/incomplete-contract rejection
reasons, valid metric/profile rules, V8 adapter provenance and the one-repair
budget. No inferred period, fallback profile, new data/capability or catch-all
exception handling. Verify bare/incomplete comparison stops safely, qualified
comparison remains valid, and both unchanged stored responses replay offline
without any API/DB call. Preserve the frozen V7 failure and identify the solver
revision separately in ignored local replay records.

Verification: after correcting synthetic fixture span/qualifier assumptions,
the faithful reproduction failed3 cases and passed2 before the one-line guard;
all212 comparison/solver/contracts/service/personal tests then passed in5.12s.
Both original responses replayed through strict resolver validation and solving
with2 fake adapter calls and0 actual API/DB calls. The consumer now returns
REQUIRED_QUALIFIER_MISSING for period, with no complete comparison contract;
no factual success is claimed. The ignored HKO-CMP-008-solver-replay.json records
the original response hashes, safe original exception path and before/after
solver code hashes. Adapter V8 and the running V7 records remain unchanged.

## Failure explanation correction

Actual FLT-BOND-001/FLT-OETF-001 and the catalog/solver audit show incomplete
predicate operators or requested field roles before any SQL executes. Their
source conditions can already be explicit; asking for a rewrite alone implies
the user omitted information that the current service cannot represent.
Retain rejection and all independent name/date clarifications. Explain only
that the service could not build the comparison or complete requirement plan;
do not infer data absence or add condition values/operators/default dates.
Verify these failures still execute no SQL and do not solicit a rewrite merely
for the internal incomplete predicate/role reason. Existing unresolved name,
family and genuine missing qualifier guidance must remain unchanged.

The current renderer independently revalidated all ten saved actual V7 MIS
rows against the ledger, then disclosed seven undated rows (three have older
dates). This local rendering verification made zero NVIDIA calls. The initial
diagnostic script's tuple deserialization and hardcoded ten-undated assertion
were repaired without changing application validation or recorded V7 output.

The frozen V8 FLT-OETF-001 result marked explicit Japan/equity source terms as
lexical_ood despite registered region/asset-class meanings. The generic
REQUEST_MEANING_UNRESOLVED explanation therefore cannot establish a user typo
or omitted condition. Within the approved failure-fix scope, change only its
wording to say the current service could not bind the question to supported
meanings and a query plan. Keep its rejection/code, independent entity-name,
family, date and reference guidance, SQL routing and one-repair allowance.
Do not infer absent data, add a classification or retry, or reinterpret the
recorded model output. Reproduce the misleading wording in one targeted test,
then verify the service-owned explanation and existing clarification/search
tests. The finished V8 outputs retain their frozen code revision; record the
new explanation source hash separately. Inspect its three contract errors
using saved responses only, without additional implementation changes.

The generic wording reproduction failed once before its one-line correction;
all77 clarification, personal-search and personal-intent tests then passed
in4.58s. The unchanged FLT-OETF-001 context/view/schema and stored response
replayed through strict resolver solving and personal clarification with
zero API/DB/SQL calls. Its original lexical_ood classification and abstention
remain unchanged. Separate ignored explanation-replay text/JSON files identify
the current explanation source hash without rewriting frozen V8 records.

Saved V8 contract responses also reproduced legitimate model rejection:
CALC-CROSS-001 repair created an entity hint in a maxItems:0 branch with no
offered entity candidate; AMB-SIM-001 repair omitted a required unmapped source
mention while retaining partial coverage. Retain those schema/completeness
checks and preserve diagnostic logs; no further prompt accumulation is approved.

REL-MGR-001 repair fixed its source role but declared result_set/one for
consume_single_result, whose target is entity/one. The existing reference-target
shape check correctly rejects this with INVALID_CONTEXT_GRAPH, but returns no
actionable feedback. Within the approved failure-fix scope, replace only that
plain rejection with bounded feedback containing fixed field/rule names and
registered link/role/target/cardinality enum values. Never export private
canonical IDs, infer a target, correct a model value or add a retry. The strict
predicate, INVALID_CONTEXT_GRAPH code, one-repair budget, V8 adapter/prompt and
zero SQL execution remain unchanged. Verify the recorded invalid shape still
rejects with safe feedback and an explicitly corrected compatible shape passes
offline. Record this context source revision separately from frozen actual V8
output, then run narrow context/assembler/service tests before broader checks.

The recorded target-kind mismatch and a separate cardinality mismatch both
failed the new feedback assertion before the correction. Afterwards187
context/assembler/repair/personal tests and51 service/query-contract tests
passed (238 total). All three original contract cases replayed through the
strict resolver with exactly two stored-response adapter calls each and zero
actual API/DB/SQL calls. Their final error codes are unchanged; REL-MGR-001
now exposes only its enum target-shape mismatch. A separate diagnostic that
explicitly changes only its expected target kind to entity passes strict
validation; this is not application autocorrection or a live factual success.
Ignored v8-contract-errors-replay text/JSON files preserve response hashes and
the context revision hash. V8 adapter/prompt and frozen actual outputs remain
unchanged; broader offline and any focused live verification are separate.


## Final actual runs and independent acceptance

The expanded export approval was granted and automatic approval review allowed
both the full V7 rerun and V8 subset. The earlier rejection above remains
historical; there is no pending metadata-transmission approval for these runs.
V7 and V8 manifests preserve all raw questions and source-file hashes.

- V7/V3 actual full217:277 API attempts;141 nonfactual responses,16 policy
  blocks,5 pre-model length rejections,20 contract/system failures,34 timeouts
  and1 source-verified answer. Median17.933s,p95 55.153s,max55.232s.
  Of34 timeouts,22 followed a received response and12 received none.
  Baseline failures45 to20 is a contract-error reduction; baseline timeouts16
  to34 increased, so no general correctness or reliability claim is justified.
- V8 actual subset48:20 V7 non-timeout contract/system failures plus22
  first-response-then-timeout cases and6 controls;60 API attempts. Outcomes:
  13 nonfactual responses,1 policy block,1 source-verified answer,3 contract
  errors,4 timeouts and26 HTTP429 failures. All26 rate-limited cases received
  no first response. They do not verify corrections. All4 timeouts followed
  a response. Do not merge this selected subset into217-question accuracy.
- Final latest-code REL-MGR-001 probe: unchanged original manifest item,
  one actual API attempt,HTTP429 before a response,0 SQL. This is separate
  from the frozen48-case result and cannot certify the last feedback change.

Independent execution audit found exactly one SQL result per corrected batch,
MIS-DETF-001, with no unaudited/hidden execution. All10 IDs,values,units,actual
observation dates and displayed5 sources matched the ledger; family/type,
P1Y,ASC and limit10 were preserved. V8 printed7 missing actual dates across
all10 results. The source rows all contain -100% returns,zero closes and elapsed
trading-end dates. Current source policy does not define -100 as missing, so
no automatic reclassification/exclusion occurred. Source faithfulness is
verified; economic validity/current-date performance comparison is not.
V7's57 source/policy/OOD boundary cases released no product SQL, but semantic
reasons can still be wrong or overly restrictive. Six corresponding V8 controls
were rate-limited; no latest boundary-accuracy pass is inferred from them.

The actual HKO-CMP-008 rerun now returns bounded qualifier/requirement
limitations instead of PERSONAL_EVALUATION_FAILED. FLT-OETF V8 additionally
misclassified Japan/equity as lexical_ood despite registered region/asset_class;
this model omission is distinct from the server's enum/operator/binding gaps.
Three remaining actual contract failures were reproduced strictly offline:
CALC creates a prohibited empty-candidate entity hint; AMB omits required
unmapped source coverage; REL declares result_set where a selected result
requires entity. Preserve rejection instead of guessing names or references.

Final production changes after the48-case freeze are limited to generic
failure wording and enum-only reference-target feedback. Stored originals
remain rejected, the explicit compatible synthetic shape passes, and the
new guidance is verified separately. Latest implementation provenance is
recorded in ignored latest-implementation-verification.json; no frozen run is
rewritten as though it used these two later changes.

Final verification:3727 passed,4 skipped,516 deselected in82.84s. The offline
command excludes PostgreSQL,NCP,performance,object-storage,official-data,Jena
and CLOVA integration markers. The explicit DB/current-KRX/current-SEC/
organizer-data gates account for4 skips; skips/exclusions are not passed
integration checks. Narrow latest context/service tests passed238 checks and
clarification/search/personal checks passed77. git diff --check passed. Exact
NVIDIA-key scanning found no match in33 changed files and1889 ignored log
files at the final audit point; no paths were staged and no data/PDF/env/key
was staged. No DB write,raw-source edit,commit,push,release or deployment.

Ignored result artifacts under the original project data/existing-questions-20261011:
all-question-results.txt and comparison.json preserve every217 question's
original source expectation,raw question,analysis/route/contract,SQL/output or
stable failure,API calls and timing across distinct runs. Additional
remaining-failure-root-causes.txt,compound-condition-root-causes.txt,boundary
comparisons,execution-audit coverage and independent MIS audits record causes
and limits. The final-probe and offline replay have separate directories.

## Remaining work, in order

1. Complete source-owned categorical/Boolean/existence/grade values and operator
   binding,frame/source-clause ownership and registered physical bindings.
   All requested conditions must survive into a validated executable contract.
2. Establish verified date/unit/currency/grade-order/availability and missingness
   policies from authoritative data. Do not substitute cutoff/MAX,sort grades
   lexicographically or reinterpret ambiguous source numbers.
3. Recheck model/schema/semantic stability after provider availability recovers;
   keep failed exports,scope,deadlines and one-repair budget visible. The
   provider's exact quota/reset reason is not established by HTTP429 alone.
4. Add still-unconnected aggregate/calculation/similarity/document output only
   through an approved scoped design. Fictional names and absent antecedents
   stay explicit limitations instead of being replaced with real products.

These are capability/data/semantic-design gaps beyond the reproduced surgical
regressions. The service does not yet answer all217 authored questions correctly.
