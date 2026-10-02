# Personal semantic search execution — 2026-10-02

## Approved brief

The user approved continuing the previously stated remaining priorities after
committing/pushing the verified NVIDIA migration. Migration commit b5a3e18 was
pushed to codex/nvidia-intent-routing. Follow-up branch is
codex/personal-query-execution, based on that dependency commit; origin/main was
fetched and is an ancestor. Preserve the unmerged personal dataset features.

Assumptions: solo local PostgreSQL tests, pinned personal-2026-08-24-v1 dataset,
existing NVIDIA metadata export approval, deterministic text logs. Do not send
observations or documents to NVIDIA. Outcome: grounded supported questions
execute their approved semantics and return independently checked facts.
Non-goals: HTTP/deployment/main merge, activation, large ingestion, implicit
conversation memory, unsupported metric inference, mixed supplemental-weight
ranking. Constraints: read-only fa_runtime/5s SQL timeout, request bound,
compiler/registry/pin ownership, actual dates and units, unchanged source data.
ADR-0054 records the material alternatives and selected direction.

## Ordered work and verification

1. Connect approved single-task fee screen to semantic SQL execution and an
   evidence/value/source validator and text formatter. Verify a domestic
   fee <=0.1% query against independent read-only SQL, with exact matched and
   displayed counts; altered evidence and plans must fail closed.
2. Add verified domestic P1Y return and bond maturity bindings, metric-specific
   fee lookup/rank unit handling, explicit unavailable overseas P1Y and public
   fee reasons. Verify wrong periods/units, zero/missing and definition versions.
3. Preserve relation-object scope and compile registered holding/manager
   relation conditions with lineage. Verify direction, family/subject IDs,
   unsupported relations, and exact products against independent local SQL.
4. Improve ambiguity/typo/missing-period/compound/follow-up boundaries and
   clarification logs. Verify no unresolved entity or qualifier silently
   becomes a broad executable query. Existing exact names and IDs still pass.
5. Run narrow tests, bounded actual local/NVIDIA examples, then the relevant
   offline suite. Record exact results, inspect scoped final diff and secrets,
   update README/runbook. Commit only verified independently useful changes.

## Progress

- NVIDIA migration committed and pushed; remote head matches b5a3e18.
- Initial code/source investigation completed. Overseas source contains only
  one-day return; fund fee components use source_rate with unverified total.
- Implemented approved semantic plan execution, pinned lineage hydration and
  deterministic verified text. Added metric/version/date/unit support and
  typed manager/holding conditions. Ambiguity, missing qualifiers, unsupported
  Boolean scopes and subtype mismatches remain fail-closed.
- A source missing value in the named TIGER fee lookup initially failed the
  name-only validation guard. It now validates the missing observation and
  explicit exclusion, returning missing plus source rather than inventing zero.
- Fixed date comparands being copied to as-of, benign dependency skips,
  relation-object scope and unrecognized relation-negation/OR variants.
- Initial live SQL timed out while grouping roughly 3.57 million evidence
  records. Pinned metric filters and exact observation-correlated LATERAL
  aggregation preserve all raw result/lineage columns: independent comparisons
  match, fee screen returns 154 rows in 0.490s and named lookup 1 row in 0.017s.
  Budgets were not increased. Broad bond lookup contains 20,497 products and
  cannot satisfy the 10,000-row bound; time/row-limit failures request narrowing.
- First live NVIDIA/SQL six-case attempt: fee and bond-date succeeded;
  scalar/null relation IDs and family IDs in concept links failed strict
  validation, with one shared-deadline timeout. After shape/axis instructions,
  four cases succeeded (fee 154, named 1 missing, domestic return top 5, bond
  date >=2045-01-01 929). Independent SQL confirms exact counts/display IDs,
  ranked IDs and missing status. Manager/holding proposals then mixed object
  types into subject frame types and failed. Shape, relation-object and
  frame-subject type instructions were added without relaxing semantic checks;
  adapter provenance is nvidia-chat-json-proposal-v5.
- Final offline suite on the current implementation:
  3,577 passed, 4 skipped, 516 deselected (73.03s). External integration and
  performance markers were excluded, not passed.
- Final sequential actual GLM retest (live-v5-final): named fee lookup,
  manager filter and holding filter all returned MODEL_TIMEOUT at
  55.134/55.147/55.137s. Named lookup received no completed response;
  manager/holding each received one invalid response before repair exhausted
  the shared deadline. No product facts were released from these failed runs.
- Actual earlier attempts and failures remain under ignored local
  data/personal-search-20261002/ directories. live-v2's four successes are
  historical; later guidance revisions do not turn failed retests into passes.
- Bounded alternative-model probes did not justify switching the default:
  Qwen and Mistral requests were rejected by the current endpoint; Nemotron
  Super (thinking disabled) passed named lookup but failed manager type and
  holding completeness; other Super/Ultra attempts timed out or failed schema.
  These were temporary test settings only. Default GLM and execution budgets
  remain unchanged. No product observations/results/documents were sent.
- A separate synthetic-normal-v3-proposal fixture used the original closed
  dataset/adapter pins and synthetic model identity, with zero external API
  calls and fa_runtime read-only SQL. Manager returned 243 products with 523
  source facts; sampled holding returned 9 products with 9 source facts.
  Independent SQL matched full product ID sets, counts and displayed IDs.
  Directed object IDs, actual validity dates, source eligibility and rendered
  file/sheet-or-CSV/row/column/evidence IDs were verified. Logs are labeled
  synthetic-relations, never NVIDIA acceptance. An initial fixture with an
  arbitrary manifest adapter version was correctly rejected; no pin check was
  weakened to perform the successful test.
- Scoped code/security audit found no reproducible correctness blocker in the
  deterministic execution deliverable. README and runbook disclose the final
  live failures and acceptance boundary. Deliver this verified local module on
  codex/personal-query-execution after the final staged scope/security checks;
  record the commit/push result in the user-facing delivery report.

## Delivery boundary and remaining priority

The independently useful local plan/SQL/lineage/text implementation is verified.
The overall live NVIDIA integration is not complete. Its highest remaining
priority is reliable source-owned frame/type/relation generation within the
existing request budget, followed by repeated live acceptance. Do not broaden
OR/negation, financial calculations, HTTP or data coverage while masking this
failure. Keep actual-model, cached, synthetic and independent SQL verdicts
separate. No main merge, deployment, release activation or bulk ingestion was
performed.

Additional source check: the ETF family tables also contain ETNs (domestic
1,235 ETF / 545 ETN; overseas 5,972 ETF / 65 ETN). ETF scope must therefore
include verified product_type:2 observation/evidence filtering. Preserve the
registered ETF family meaning rather than ranking every ETP in the source.
