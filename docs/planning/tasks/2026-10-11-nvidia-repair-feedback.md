# NVIDIA repair feedback — 2026-10-11

## Approved direction

The user requested implementing the prior failure-log analysis. Preserve the
personal semantic execution dependency at 204901a; fetched origin/main remains
an ancestor. Work on codex/nvidia-repair-feedback. ADR-0053/0054 remain in force.

Assumptions: the approved metadata-only NVIDIA export and long-wait diagnostic
permission remain valid. Outcomes: distinguish listing-family spans from named
entity candidates; retain field-specific identifier constraints in the model
schema; send bounded source-owned validation feedback on the existing one repair;
record safe HTTP/transport failure category, status and elapsed time.

Non-goals: alter SQL/data, remove validation, auto-rewrite model meaning, add
model retries, change the historical request contract or deploy/merge/push.
Keep the normal 55-second contract and SQL 5-second timeout. Long-wait API tests
are separate diagnostics followed by verbatim-response validation replay.

Alternatives: restoring every repeated identifier enum adds prompt duplication;
retain only entity-hint mention and semantic-concept enums. Broad rejection
codes alone did not repair the observed failure; provide exact error paths and
allowed source identifiers without echoing arbitrary model text or reasoning.

## Plan and checks

1. Add synthetic regressions reproducing general-family entity hints and family
   IDs in semantic links. Verify rejection plus precise, source-bounded repair
   feedback; valid directed relations and named lookups still pass.
2. Improve NVIDIA schema presentation/guidance and safe provider observations.
   Verify model/server schema ownership, HTTP/transport/timeout distinctions,
   one repair allowance and absence of credentials/body in logs or feedback.
3. Run narrow tests and offline suite. Use approved real NVIDIA questions and
   read-only local DB, including independent SQL checks. Keep actual API,
   cached replay, synthetic and provider failures separately labeled.
4. Update usage/verification documentation and inspect the scoped diff.

Success: reproducible regressions pass; correct relation plans retain object
IDs outside product scope; no illegal model output becomes executable; failures
are diagnosable without secrets; actual-model acceptance is reported honestly.

## Implementation and verification

- NVIDIA adapter provenance is nvidia-chat-json-proposal-v6. Model schema keeps
  entity-hint mention enums and compact-concept enums while omitting repeated
  general evidence lists. Generic family spans do not become named subjects.
- Closed V3 validation adds at most six correction issues, with exact paths,
  source-owned allowed IDs, type/missing-field information and known rejected
  IDs. Unknown model strings are replaced by a fixed unoffered marker; arbitrary
  model text, full invalid responses and hidden reasoning are not re-exported.
  Semantic-link oneOf feedback focuses on the selected branch.
- Intermediate real testing found manager proposals with a correct relation
  object but no managedBy semantic link. Keep that failure in normal-v6.
  Added an explicit two-part relation instruction and targeted missing-link
  feedback; no relation is injected and endpoint validation still rejects it.
- HTTP/transport failures log only stable code/category, HTTP status when
  available and elapsed_ms. Response body, URL, headers and exception text are
  excluded. Automatic provider retries and request/SQL budgets are unchanged.
- Narrow relevant tests: 182 passed. Final offline suite: 3,589 passed,
  4 skipped, 516 deselected (73.39s). Excluded external integrations/performance
  markers are not passes. Synthetic tests cover two-role repair, retained
  conditions and refusal after the existing single repair allowance.
- Final actual NVIDIA plus real read-only DB run: named fee lookup 1 with
  source-verified missing status (15.362s), manager filter 243 (12.714s),
  sampled 2026-08-22 holding filter 9 (9.247s). All three use one real model
  call, no repair, and the unchanged 55-second normal service. This is not
  synthetic or cached-replay acceptance. Earlier failures remain separate.
- Logs stay ignored under data/personal-search-20261011/normal-v6-final in the
  original workspace. Independent SQL verifies named missing status, exact
  manager/security objects, relation direction/date, counts and displayed IDs.
  The 9 holdings are sampled coverage, not a market-wide total.

These three actual examples pass, not every natural-language question. Real
targeted correction is covered by synthetic regressions, not claimed from the
final no-repair API run. Provider availability and latency can still vary.
No database writes, release activation, main merge or remote push was performed.
