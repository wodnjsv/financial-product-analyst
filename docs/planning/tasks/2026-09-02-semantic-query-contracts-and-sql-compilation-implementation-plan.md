# Semantic Query Contracts and SQL Compilation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace incomplete flat task slots with complete action-specific semantic query contracts, deterministically lower executable contracts to `LogicalQueryPlanV2`, and execute approved SQL plans without allowing HCX to author SQL or physical schema identifiers.

**Architecture:** Keep the existing V1 intent, `QueryPlan`, and non-SQL execution path readable and behaviorally unchanged. Add a V2 semantic path consisting of deterministic exact locks, one existing HCX axis call, a bounded Contract Candidate Solver, an exceptional offered-ID-only judge, independent Axis/Contract/Plan readiness gates, a semantic logical plan, a server-owned physical binding registry, a parameterized SQL compiler, and a read-only SQL executor. Persist V2 query-contract and logical-plan artifacts separately so no V2 predicate, qualifier, grain, or de-duplication rule is flattened into V1.

**Tech Stack:** Python 3.12, Pydantic 2 strict frozen contracts, JSON registries with canonical SHA-256 pins, SQLAlchemy 2 Core and async PostgreSQL, Alembic, pytest, HyperCLOVA X HCX-007 Structured Outputs for the existing axis call and exceptional candidate-ID judge.

**Spec:** `docs/planning/specs/2026-09-02-semantic-query-contracts-and-sql-compilation-design.md`

## Global Constraints

- Preserve the public `GET /answer` surface and every V1 contract fixture. Do not modify `QueryPlan` to carry V2-only meaning.
- The normal path uses the existing one HCX axis/frame/context call. A second HCX call is allowed only when multiple complete contracts remain, and only if resolver repair was not used. The response is one offered candidate ID.
- HCX never receives or emits SQL, table names, column names, join expressions, formulas, physical metric IDs, or arbitrary registry entries.
- Deterministic code owns exact family, literal, direct field alias, and operator locks. Any conflicting exact lock fails closed.
- SQL uses only registered bindings, registered joins, registered policies, and bound parameters. User text is never interpolated into SQL identifiers or SQL text.
- `AxisReadiness`, `ContractReadiness`, and `PlanReadiness` remain separate. Fast and Compose require all three to pass.
- Public-fund aggregation must state representative-product grain and a verified de-duplication policy. It must not sum share classes naively.
- `public_fund.fee_rate` remains non-executable until its physical source definition and unit are verified. Do not synthesize “total fee” by summing component fee fields during this implementation.
- This plan implements the RDB semantic-SQL executor. Graph, Keyword/Vector Search, and registered Calculation tasks remain supported orchestration capabilities, but their production data executors are a separate Stage 05 deliverable; this plan neither stubs them nor claims they are implemented.
- Production code must not import or read `tests/gold/`, held-out labels, adjudication fixtures, or provider output.
- Do not read, print, stage, or commit `api.txt`, credentials, organizer workbooks, raw provider responses, local databases, or generated runtime artifacts.
- Use TDD for each behavioral change: add one narrow failing assertion, run it and confirm the expected failure, implement the smallest passing behavior, then run the focused suite.
- Each task ends with `git diff --check`, a scoped staged-diff review, and one independently useful conventional commit. Do not merge, push, deploy, or promote a model without separate user approval.

## Compatibility and Migration Order

1. Add the audit and adjudicated expectations without changing runtime behavior.
2. Add V2 semantic models and registries alongside V1.
3. Add deterministic locks and the V2 solver alongside `bind_task_slots()`.
4. Add a V2 resolver entry point while retaining `resolve_task_bound()`.
5. Add `LogicalQueryPlanV2`, its compiler, and a separate semantic compilation wrapper.
6. Add physical bindings and parameterized SQL compilation.
7. Add a separate V2 execution request and SQL executor without changing the V1 `TaskExecutionInput` constructor or behavior.
8. Add Alembic revision `0009` only after the in-memory V2 contracts are stable.
9. Persist `query_contract` and `logical_query_plan` as distinct artifact types; do not overload the existing `query_plan` artifact.
10. Promote no V2 runtime path until all offline gates pass and the live HCX report is reviewed.

## Promotion Gates

| Gate | Required value |
| --- | ---: |
| Adjudicated supported-frame representability | 100% |
| Explicit reason for every adjudicated unsupported frame | 100% |
| False-complete semantic contracts | 0 |
| Unique exact family/field/operator/literal lock precision | 100% |
| Correct complete-contract candidate recall | at least 99% |
| Decoupled contract exact match on supported frames | at least 95% |
| Executable-plan deterministic compile success | 100% |
| Repeat contract/plan/SQL/parameter/manifest byte equivalence | 100% |
| Existing ADR-0022 candidate recall@5 | at least 99% |
| Existing ADR-0022 first-pass structured validity | at least 99% |
| Existing ADR-0022 held-out joint-frame exact match | at least 90% |
| Existing ADR-0022 context-link exact match | at least 95% |
| Existing ADR-0022 OOD false-fast rate | at most 2% |
| Five previously failing live semantic cases | 5/5 exact semantic expectations |
| Request hard deadline | no more than 55,000 ms |

The five-case live check is a connectivity and regression gate, not sufficient promotion evidence. Provider failure, rate limiting, and semantic failure are reported separately.

---

### Task 1: Make semantic contract coverage reproducible and adjudicate the gold meaning

**Files:**

- Create: `tests/evaluation/query_contract/__init__.py`
- Create: `tests/evaluation/query_contract/coverage.py`
- Create: `tests/evaluation/query_contract/query_contract_adjudications.v1.json`
- Create: `tests/evaluation/query_contract/query_contract_requirements.v1.json`
- Create: `tests/evaluation/query_contract/test_coverage_baseline.py`
- Create: `scripts/generate_query_contract_requirements.py`
- Modify: `docs/planning/STATUS.md`

**Preserves:** Runtime resolver and planner behavior; production code never imports evaluation assets.

- [ ] **Step 1: Write the baseline loader and source-pin failure test**

  Add a test that loads all 52 core questions and all 160 held-out cases/209 frames, recomputes each source file SHA-256, and refuses stale requirements:

  ```python
  def test_requirement_snapshot_is_pinned_to_current_sources() -> None:
      snapshot = load_requirement_snapshot(PROJECT_ROOT)
      assert snapshot.core_question_count == 52
      assert snapshot.heldout_case_count == 160
      assert snapshot.heldout_frame_count == 209
      assert snapshot.core_source_hash == file_sha256(CORE_PATH)
      assert snapshot.heldout_source_hash == file_sha256(HELDOUT_PATH)
  ```

  Run:

  ```bash
  python3 -m pytest tests/evaluation/query_contract/test_coverage_baseline.py::test_requirement_snapshot_is_pinned_to_current_sources -q
  ```

  Expected: fail because the loader and snapshot do not exist.

- [ ] **Step 2: Define the adjudication and requirement schemas**

  `query_contract_adjudications.v1.json` contains only reviewed corrections and explicit unsupported decisions. Each entry has `case_id`, `frame_ordinal`, `original_action_id`, `adjudicated_action_id`, `support_status`, `reason_code`, and exact semantic overrides. Qualitative fee requests use `rank`, ascending direction, and `default-limit-5.v1`; numeric fee thresholds use `screen` with field, operator, and typed value.

  `query_contract_requirements.v1.json` is the generated, reviewable full snapshot. Every frame has exactly one of:

  ```json
  {
    "support_status": "supported",
    "action_id": "aggregate",
    "required_components": [
      "scope",
      "aggregation.function",
      "aggregation.target",
      "aggregation.population_grain",
      "aggregation.dedup_policy"
    ]
  }
  ```

  or:

  ```json
  {
    "support_status": "unsupported",
    "reason_code": "SEMANTIC_CONCEPT_NOT_REGISTERED"
  }
  ```

  The generator may read test assets but writes only the deterministic snapshot. It must reject duplicate frame keys, unknown action IDs, missing unsupported reasons, and overrides that do not reference a real frame.

- [ ] **Step 3: Reproduce the current 94/209 representability baseline**

  Implement the V1 representability audit using `config/intent/task-input-contracts.v1.json`. Assert the current baseline before replacing it:

  ```python
  assert report.total_frames == 209
  assert report.representable_frames == 94
  assert report.by_action["lookup"] == CoverageCount(5, 58)
  assert report.by_action["screen"] == CoverageCount(0, 23)
  assert report.by_action["rank"] == CoverageCount(43, 66)
  assert report.by_action["compare"] == CoverageCount(17, 30)
  assert report.by_action["aggregate"] == CoverageCount(8, 11)
  assert report.by_action["calculate"] == CoverageCount(5, 5)
  assert report.by_action["similar"] == CoverageCount(10, 10)
  assert report.by_action["explain"] == CoverageCount(6, 6)
  ```

  Run the full file and confirm it passes without modifying production contracts.

- [ ] **Step 4: Generate, review, and freeze the adjudicated requirement snapshot**

  Run:

  ```bash
  python3 scripts/generate_query_contract_requirements.py --check
  python3 -m pytest tests/evaluation/query_contract/test_coverage_baseline.py -q
  ```

  Expected: the generator reports no stale content; every one of the 209 held-out frames plus the 52 core questions has a supported requirement vector or one explicit unsupported reason.

- [ ] **Step 5: Commit the audit-only deliverable**

  Review that no production file changed, then commit:

  ```bash
  git add tests/evaluation/query_contract scripts/generate_query_contract_requirements.py docs/planning/STATUS.md
  git diff --cached --check
  git diff --cached
  git commit -m "test: freeze semantic query coverage baseline"
  ```

---

### Task 2: Add strict V2 semantic contract types and versioned registries

**Files:**

- Create: `src/financial_agent/intent/query_contracts.py`
- Create: `src/financial_agent/intent/query_contract_registry.py`
- Create: `config/intent/query-contract-registry.v2.json`
- Create: `config/intent/query-operator-registry.v1.json`
- Create: `config/intent/query-policy-registry.v1.json`
- Modify: `src/financial_agent/intent/__init__.py`
- Create: `tests/intent/test_query_contracts.py`
- Create: `tests/intent/test_query_contract_registry.py`

**Preserves:** `SlotKind`, `TaskInputContractDefinition`, `ResolvedTaskContract`, and V1 registry files remain unchanged.

- [ ] **Step 1: Write strict model tests before the models exist**

  Cover one valid instance and every missing completeness component for all eight actions. Include extra-field rejection, frozen-model behavior, duplicate IDs, predicate depth, predicate atom count, and canonical serialization.

  The public type surface is:

  ```python
  class AxisReadiness(str, Enum):
      COMPLETE = "complete"
      AMBIGUOUS = "ambiguous"
      BLOCKED = "blocked"

  class ContractReadiness(str, Enum):
      COMPLETE = "complete"
      AMBIGUOUS = "ambiguous"
      BLOCKED = "blocked"

  class PlanReadiness(str, Enum):
      EXECUTABLE = "executable"
      EXPLORABLE = "explorable"
      LIMITED = "limited"
      BLOCKED = "blocked"

  ResolvedQueryContractV2 = Annotated[
      LookupQueryContractV2
      | ScreenQueryContractV2
      | RankQueryContractV2
      | CompareQueryContractV2
      | AggregateQueryContractV2
      | CalculateQueryContractV2
      | SimilarQueryContractV2
      | ExplainQueryContractV2,
      Field(discriminator="action_id"),
  ]
  ```

  The solver uses a separate internal `SolvedQueryContractCandidateV2` action
  union containing the same semantic bodies but no readiness fields. Only Task
  7 combines one solved candidate with all three readiness assessments and
  constructs `ResolvedQueryContractV2`. Therefore an unassessed candidate can
  never be mistaken for a resolved executable contract.

  Run:

  ```bash
  python3 -m pytest tests/intent/test_query_contracts.py -q
  ```

  Expected: fail with missing module.

- [ ] **Step 2: Implement shared typed components with bounded shapes**

  Add `QueryScopeV2`, `ProjectionSpecV2`, `TypedSemanticValue`, `PredicateAtomV2`, `PredicateAllOfV2`, `PredicateAnyOfV2`, `PredicateNotV2`, `OrderingSpecV2`, `AggregationSpecV2`, `ComparisonSpecV2`, `CalculationSpecV2`, and provenance records. The first release allows at most 16 frames, 8 predicate atoms per frame, predicate depth 3, 8 projections, 4 order terms, and result limits 1–100.

  Percent values retain the semantic unit:

  ```python
  TypedSemanticValue(
      kind="decimal",
      decimal="1",
      unit_id="percent",
  )
  ```

  They are not converted to `0.01` until physical lowering.

- [ ] **Step 3: Implement the eight discriminated variants and completeness validators**

  Each variant includes `contract_schema_version="2.0"`, `frame_id`, scope, qualifiers, result shape, provenance, `axis_readiness`, `contract_readiness`, and `plan_readiness`. Validators enforce the exact completeness table from the approved spec. In particular:

  ```python
  class ScreenQueryContractV2(QueryContractBaseV2):
      action_id: Literal[IntentType.SCREEN]
      predicate: PredicateNodeV2

      @model_validator(mode="after")
      def require_complete_predicate(self) -> Self:
          if predicate_atom_count(self.predicate) < 1:
              raise ValueError("SCREEN_PREDICATE_REQUIRED")
          return self
  ```

  `AggregateQueryContractV2` rejects any instance missing function, target/count population, population grain, or de-duplication policy.

- [ ] **Step 4: Add closed registries and hash pins**

  `query-contract-registry.v2.json` registers variants:

  - `lookup.projection.v2`
  - `screen.predicate.v2`
  - `rank.ordering.v2`
  - `compare.subjects.v2`
  - `aggregate.scalar.v2`
  - `aggregate.grouped.v2`
  - `aggregate.distribution.v2`
  - `calculate.recipe.v2`
  - `similar.policy.v2`
  - `explain.topic.v2`

  `query-operator-registry.v1.json` registers `eq`, `neq`, `lt`, `lte`, `gt`, `gte`, `between`, `in`, `not_in`, `contains`, `is_missing`, and `is_present` with allowed value kinds and arity. `query-policy-registry.v1.json` registers the named default, missingness, stable-tie, comparison, population-grain, de-duplication, normalization, and coverage policies used in the spec. Loader tests reject unknown cross-references and non-canonical ordering.

- [ ] **Step 5: Prove V2 representability and V1 no-drift**

  Add assertions that every adjudicated supported requirement vector is representable by at least one V2 variant, every unsupported frame remains non-representable with its expected reason, and the V1 registry hash and V1 contract fixtures are unchanged.

  Run:

  ```bash
  python3 -m pytest tests/intent/test_query_contracts.py tests/intent/test_query_contract_registry.py tests/evaluation/query_contract/test_coverage_baseline.py tests/intent/test_task_contracts.py tests/contracts -q
  ```

  Expected: all pass; V2 supported representability is 100% and false-complete count is zero.

- [ ] **Step 6: Commit the contract layer**

  Commit as:

  ```bash
  git commit -m "feat: add semantic query contract v2"
  ```

---

### Task 3: Add deterministic Korean locks without building an unbounded alias dictionary

**Files:**

- Create: `src/financial_agent/intent/axis_locks.py`
- Create: `src/financial_agent/intent/operators.py`
- Modify: `src/financial_agent/intent/literals.py`
- Modify: `src/financial_agent/intent/catalog.py`
- Create: `config/intent/korean-nlu-overlay.v3.json`
- Create: `tests/intent/test_axis_locks.py`
- Create: `tests/intent/test_operators.py`
- Modify: `tests/intent/test_literals.py`
- Modify: `tests/intent/test_catalog.py`

- [x] **Step 1: Write exact-lock and conflict tests**

  Cover `공모펀드 -> public_fund`, spacing and Unicode variants, `총보수 -> fee_rate`, `순자산/AUM -> aum`, `이하 -> lte`, `미만 -> lt`, `이상 -> gte`, `초과 -> gt`, `제외 -> not_in/neq` by cardinality, range cues, and negated clauses. Assert that a unique exact lock cannot be removed by an HCX omission and that contradictory exact spans return `EXACT_LOCK_CONFLICT`.

- [x] **Step 2: Implement span-preserving lock records**

  Add:

  ```python
  class ExactSemanticLock(ContractModel):
      lock_id: Identifier
      role: Literal["product_family", "field", "operator", "literal"]
      canonical_id: Identifier
      evidence_span_ids: tuple[Identifier, ...]
      source: Literal["canonical", "direct_alias", "literal"]
  ```

  Only canonical IDs and unique `direct_alias` entries are lockable. Group aliases, ambiguous aliases, fuzzy matches, and trigram candidates remain unlocked choices.

- [x] **Step 3: Extend the literal layer with typed operators, not SQL symbols**

  `OperatorCandidate` stores `operator_id`, semantic arity, evidence span, and compatible value candidate IDs. It never stores `<`, `<=`, or SQL text. Group field/operator/value candidates only when their spans form one clause; do not attach one percentage literal to every field in a multi-predicate sentence.

- [x] **Step 4: Add only reviewed high-trust Korean anchors**

  Version `korean-nlu-overlay.v3.json` from V2 and add the minimum exact anchors needed by the supported questions. Keep broad words such as `보수`, `규모`, `좋은`, and `낮은` as lexical candidates unless the full phrase is uniquely grounded. Assert overlay size and direct-alias uniqueness so growth is reviewable.

- [x] **Step 5: Run precision and regression gates**

  ```bash
  python3 -m pytest tests/intent/test_axis_locks.py tests/intent/test_operators.py tests/intent/test_literals.py tests/intent/test_catalog.py tests/intent/test_candidates.py -q
  ```

  Expected: exact lock precision 100% on adjudicated exact expressions; existing candidate bounds and normalization tests remain green.

- [x] **Step 6: Commit the deterministic language layer**

  Commit as:

  ```bash
  git commit -m "feat: add deterministic semantic query locks"
  ```

---

### Task 4: Implement the bounded Contract Candidate Solver and offered-ID-only judge

**Files:**

- Create: `src/financial_agent/intent/query_contract_solver.py`
- Create: `src/financial_agent/intent/query_contract_judge.py`
- Create: `tests/intent/test_query_contract_solver.py`
- Create: `tests/intent/test_query_contract_judge.py`
- Modify: `src/financial_agent/intent/clova.py`
- Modify: `tests/intent/test_clova.py`

- [ ] **Step 1: Write solver tests for unique, ambiguous, blocked, and overflow outcomes**

  Tests cover action-variant selection, exact-lock reconciliation, family applicability, field/operator/value type compatibility, clause grouping, entity cardinality, context carryover, aggregation policies, canonical deduplication, and stable rejection reasons. Bounds are 8 candidates per unresolved role and 64 complete candidates per frame; reaching a bound returns `CANDIDATE_BOUND_REACHED`, never a silently truncated unique result.

  Public API:

  ```python
  def solve_query_contracts(
      *,
      resolution: ValidatedIntentResolutionV2,
      view: ResolverView,
      exact_locks: tuple[ExactSemanticLock, ...],
      registry: QueryContractRegistryV2,
  ) -> QueryContractCandidateSet:
      return _solve_frames(resolution, view, exact_locks, registry)
  ```

  Run the focused test and confirm missing-module failure.

- [ ] **Step 2: Implement deterministic enumeration and rejection manifests**

  `QueryContractCandidateSet` follows frame order and contains complete candidates, stable `CandidateRejection` records, and ContractReadiness. Candidate IDs are derived from canonical semantic content, not enumeration order. A unique complete candidate is accepted without an additional model call.

- [ ] **Step 3: Write the judge schema and prompt tests**

  The judge request contains only the original question, frame evidence, action/family labels, and compact semantic summaries. Structured output is:

  ```python
  class QueryContractJudgeResponse(ContractModel):
      candidate_id: Identifier
  ```

  Tests assert that the JSON schema enum contains only offered IDs, the prompt contains no physical binding registry and no SQL identifiers, an unknown ID is rejected, timeout stays ambiguous, and no repair call follows a failed judge.

- [ ] **Step 4: Add a separate adapter invocation boundary for the judge**

  Reuse HCX transport, authentication, timeout, and usage accounting, but use a distinct prompt/schema version. Do not add a new provider client. Enforce the request-wide rule:

  ```python
  if resolution.repair_used:
      return ambiguous("EXTRA_MODEL_ALLOWANCE_ALREADY_USED")
  if len(complete_candidates) <= 1:
      return deterministic_result
  return await judge.select_offered_id(
      question=prepared.context.question,
      frame=frame,
      candidates=complete_candidates,
      timeout_seconds=remaining_seconds,
  )
  ```

- [ ] **Step 5: Run solver, judge, and schema-isolation tests**

  ```bash
  python3 -m pytest tests/intent/test_query_contract_solver.py tests/intent/test_query_contract_judge.py tests/intent/test_clova.py tests/intent/test_prompt.py -q
  ```

  Expected: correct candidate recall at least 99%, zero false-complete contracts, and no physical schema token in judge envelopes.

- [ ] **Step 6: Commit the candidate resolver**

  Commit as:

  ```bash
  git commit -m "feat: solve bounded semantic query contracts"
  ```

---

### Task 5: Integrate V2 into the resolver while retaining the V1 entry point

**Files:**

- Modify: `src/financial_agent/intent/service.py`
- Modify: `src/financial_agent/intent/view.py`
- Modify: `src/financial_agent/intent/prompt.py`
- Create: `tests/intent/test_query_contract_service.py`
- Modify: `tests/intent/test_service.py`
- Create: `tests/evaluation/query_contract/test_decoupled_resolution.py`

**Preserves:** `resolve_once()` and `resolve_task_bound()` signatures and behavior.

- [ ] **Step 1: Write one-call, repair, judge, and exact-family service tests**

  Add `resolve_query_contract_candidates()` with this result:

  ```python
  @dataclass(frozen=True, slots=True)
  class QueryContractResolutionAttempt:
      resolution: ValidatedIntentResolutionV2
      candidates: QueryContractCandidateSet
      telemetry: QueryContractResolutionTelemetry
  ```

  Telemetry includes `model_call_count`, `repair_used`, `candidate_judge_used`, candidate counts, rejection counts, per-stage latency, and usage. Assert `model_call_count <= 2` and `not (repair_used and candidate_judge_used)`.

- [ ] **Step 2: Attach exact locks to the prepared server view**

  `prepare()` computes locks once from normalized spans, literals, catalog, and axis definitions. Locks are visible to validation and solver, but the model still sees semantic IDs and evidence only. Reconcile selected axes with locks after HCX validation so `공모펀드` cannot disappear when HCX omits it.

- [ ] **Step 3: Integrate solver and conditional judge**

  Use this order: prepare → axis call → schema repair if needed → semantic validation → exact-lock reconciliation → candidate solve → deterministic tie-break → optional judge. Do not call the V1 slot binder from the V2 method.

- [ ] **Step 4: Add a decoupled evaluator**

  Inject adjudicated axes and measure only candidate recall, exact contract, false-complete, and compile eligibility. Then run the normal resolver path separately. This prevents an action/family error from being misreported as a contract error.

- [ ] **Step 5: Run V1 and V2 resolver suites together**

  ```bash
  python3 -m pytest tests/intent/test_query_contract_service.py tests/evaluation/query_contract/test_decoupled_resolution.py tests/intent/test_service.py tests/intent/test_task_binding.py tests/intent/test_slot_resolution.py -q
  ```

  Expected: V1 tests are unchanged; V2 decoupled exact match is at least 95%, candidate recall is at least 99%, and false-complete count is zero.

- [ ] **Step 6: Commit the resolver integration**

  Commit as:

  ```bash
  git commit -m "feat: integrate semantic query resolution"
  ```

---

### Task 6: Add physical binding coverage and independent PlanReadiness

**Files:**

- Create: `src/financial_agent/planning/physical_bindings.py`
- Create: `src/financial_agent/planning/readiness.py`
- Create: `config/planning/semantic-sql-bindings.v1.json`
- Create: `config/planning/semantic-sql-policies.v1.json`
- Create: `tests/planning/test_physical_bindings.py`
- Create: `tests/planning/test_plan_readiness.py`
- Create: `tests/evaluation/query_contract/test_physical_coverage.py`

- [ ] **Step 1: Write physical binding audit tests from the ingested normalized schema**

  Each binding identifies a semantic field, applicable product family, source kind, approved metric IDs, value kind, storage unit, semantic unit conversion policy, period/date behavior, missingness policy, supported operators, supported aggregates, and required evidence locators. Registry IDs may be exposed to planning; physical metric IDs may not be exposed to HCX.

  The loader rejects a semantic concept absent from the catalog, unknown family, unknown value column enum, duplicate family/concept pairs, unsupported operator/type combinations, or missing evidence requirements.

- [ ] **Step 2: Register only verified bindings**

  Map ETF `aum` and total fee fields to their verified organizer metric IDs. Map public-fund `aum` to `organizer.prfd01n001.net_assets`. Mark `public_fund.fee_rate` unavailable with `PHYSICAL_DEFINITION_UNVERIFIED`; do not create a derived sum from manager, administration, sales, and trustee fee components.

  Physical value columns use a closed enum that server code maps to SQLAlchemy columns:

  ```python
  class ObservationValueColumn(str, Enum):
      DECIMAL = "decimal_value"
      INTEGER = "integer_value"
      TEXT = "text_value"
      BOOLEAN = "boolean_value"
      DATE = "date_value"
  ```

- [ ] **Step 3: Register public-fund representative-product policy conservatively**

  `public-fund-representative-share.v1` uses `relation.relation_record(predicate_id='hasShareClass')` to map each share class to its representative subject. The readiness check is executable only when one canonical representative population can be formed without cycles or ambiguity and the selected target metric has a verified one-value-per-population rule. Otherwise it returns `PUBLIC_FUND_GRAIN_UNVERIFIED`; it never chooses an arbitrary share-class value.

- [ ] **Step 4: Implement `assess_plan_readiness()`**

  ```python
  def assess_plan_readiness(
      contract: SolvedQueryContractCandidateV2,
      bindings: PhysicalBindingRegistry,
      policies: SemanticSqlPolicyRegistry,
  ) -> PlanReadinessResult:
      return _assess_contract(contract, bindings, policies)
  ```

  It checks every scope family, projection, predicate, group, ordering, comparison, recipe, qualifier, join, grain, de-duplication rule, and evidence requirement. It returns all stable reasons and never mutates the semantic contract.

- [ ] **Step 5: Run physical coverage and limitation tests**

  Assert:

  - public-fund AUM sum is executable only with representative grain and verified de-duplication;
  - public-fund total-fee screen is semantically complete but `PlanReadiness.LIMITED`;
  - unknown ESG field is Explore/Limitation, not a fabricated binding;
  - percent conversion is selected by physical binding, not the resolver.

  Run:

  ```bash
  python3 -m pytest tests/planning/test_physical_bindings.py tests/planning/test_plan_readiness.py tests/evaluation/query_contract/test_physical_coverage.py -q
  ```

- [ ] **Step 6: Commit the physical coverage gate**

  Commit as:

  ```bash
  git commit -m "feat: add semantic SQL binding coverage"
  ```

---

### Task 7: Add `LogicalQueryPlanV2` and deterministic semantic planning

**Files:**

- Create: `src/financial_agent/planning/logical_query.py`
- Create: `src/financial_agent/planning/semantic_compiler.py`
- Create: `src/financial_agent/planning/semantic_router.py`
- Modify: `src/financial_agent/planning/__init__.py`
- Create: `tests/planning/test_logical_query.py`
- Create: `tests/planning/test_semantic_router.py`
- Create: `tests/planning/test_semantic_compiler.py`

**Preserves:** Existing `QueryPlanCompilation`, `QueryPlanCompiler`, router, lowering, and V1 graph compilation remain unchanged.

- [ ] **Step 1: Write strict logical-plan tests**

  Add a separate artifact:

  ```python
  class LogicalQueryPlanV2(RuntimeArtifact):
      logical_plan_version: Literal["2.0"] = "2.0"
      logical_plan_id: Identifier
      query_contract_id: Identifier
      resolution_id: Identifier
      route: CompilationRoute
      tasks: tuple[LogicalQueryTaskV2, ...]
      dependencies: tuple[LogicalDependencyV2, ...]
      applied_policy_ids: tuple[Identifier, ...]
      binding_registry_version: Identifier
      binding_registry_hash: Sha256Hex
      contract_registry_version: Identifier
      contract_registry_hash: Sha256Hex
      lowering_records: tuple[SemanticLoweringRecordV2, ...]
  ```

  `LogicalQueryTaskV2` carries semantic contract IDs, semantic fields, typed values, policy IDs, capability, evidence requirements, and typed prior-result bindings. It contains no SQL text, table name, column name, or formula.

- [ ] **Step 2: Add a V2 compilation wrapper rather than widening V1 optionals**

  Define `SemanticQueryPlanCompilation` with `resolved_query_contracts`, `logical_query_plan`, route, archetype cache hit, primitive IDs, all three readiness results, recommended answer disposition, and blocking issues. Executable Fast/Compose routes require a plan and every readiness gate. A limitation uses the existing `CompilationRoute.EXPLORE` with `AnswerDisposition.LIMITATION`; Abstain uses `CompilationRoute.ABSTAIN`. Neither carries an executable plan.

  The semantic compiler combines each `SolvedQueryContractCandidateV2` with its
  Axis, Contract, and Plan readiness records to construct the action-specific
  `ResolvedQueryContractV2`. It refuses to finalize a candidate if readiness
  evidence belongs to another frame, contract ID, registry hash, or dataset pin.

- [ ] **Step 3: Implement four-path semantic routing**

  Fast requires one exact archetype plus all readiness gates. Compose requires complete axes/contracts and executable registered primitives. Explore handles grounded unknown vocabulary/binding search. Limitation is represented as a non-executable planning result with stable reason and the existing answer disposition. Abstain handles unresolved domain/context/policy.

- [ ] **Step 4: Lower complete contracts losslessly**

  Compile every predicate, ordering, limit, grouping, aggregation function, population grain, de-duplication policy, comparison basis, calculation recipe, qualifier, evidence requirement, and context dependency. Verify a reverse comparison function reports no semantic field lost between contract and logical plan.

- [ ] **Step 5: Prove determinism and V1 isolation**

  ```bash
  python3 -m pytest tests/planning/test_logical_query.py tests/planning/test_semantic_router.py tests/planning/test_semantic_compiler.py tests/planning/test_compiler.py tests/planning/test_lowering.py -q
  ```

  Expected: repeated semantic inputs and registry pins produce byte-identical plan JSON and IDs; all V1 planning tests remain green.

- [ ] **Step 6: Commit semantic planning**

  Commit as:

  ```bash
  git commit -m "feat: compile logical query plans v2"
  ```

---

### Task 8: Implement deterministic parameterized SQL compilation

**Files:**

- Create: `src/financial_agent/sql/__init__.py`
- Create: `src/financial_agent/sql/contracts.py`
- Create: `src/financial_agent/sql/compiler.py`
- Create: `src/financial_agent/sql/lowering.py`
- Create: `tests/sql/test_contracts.py`
- Create: `tests/sql/test_compiler.py`
- Create: `tests/sql/test_property_matrix.py`

- [ ] **Step 1: Write compiled-request safety tests**

  Define:

  ```python
  class SqlParameter(ContractModel):
      name: Identifier
      value: ContractValue
      value_kind: Identifier

  class CompiledSqlRequest(ContractModel):
      compiled_request_id: Identifier
      logical_plan_id: Identifier
      task_id: Identifier
      statement: str
      parameters: tuple[SqlParameter, ...]
      lowering_records: tuple[PhysicalLoweringRecord, ...]
      evidence_projection_ids: tuple[Identifier, ...]
      compiler_version: Identifier
      registry_hash: Sha256Hex
  ```

  Tests reject multiple statements, mutation keywords, missing parameters, extra parameters, unknown lowering IDs, and any user-derived identifier. Values such as `"1); DROP TABLE catalog.entity; --"` must appear only in parameters.

- [ ] **Step 2: Implement a closed SQLAlchemy binding map**

  Map `ObservationValueColumn` enum members to imported SQLAlchemy column objects in code. Registry strings never become unchecked identifiers. Compile against normalized `catalog`, `observation`, `relation`, and `evidence` tables. All product families, metric IDs, periods, dates, currency, and literal values are bind parameters.

- [ ] **Step 3: Implement predicate, ordering, and projection lowering**

  Support `eq`, `neq`, `lt`, `lte`, `gt`, `gte`, `between`, `in`, `not_in`, `contains`, `is_missing`, `is_present`, `all_of`, `any_of`, and `not`. Enforce registered operator compatibility, exclude missing/sentinel values through named policies, and add stable product ID as the final tie-break.

- [ ] **Step 4: Implement aggregate and grouping lowering**

  Support `sum`, `count`, `count_distinct` (`COUNT_DISTINCT` semantic function), `avg`, `min`, `max`, and `distribution`. Every aggregate reads the explicit population grain and de-duplication policy. Implement public-fund representative CTE lowering only for the verified policy; return a stable compile rejection otherwise.

- [ ] **Step 5: Implement unit and percent conversion at the physical boundary**

  A semantic `1 percent` is converted according to the binding's registered storage unit. Tests cover percentage points and decimal-fraction storage and assert the resolver output remains identical in both cases.

- [ ] **Step 6: Add generated combination tests**

  Generate product family × action × field kind × operator × value kind combinations plus aggregation function/grain/qualifier cases. Every combination must either produce a valid compiled request or exactly one stable rejection code. No unexpected exception is accepted.

- [ ] **Step 7: Run SQL compiler safety and determinism tests**

  ```bash
  python3 -m pytest tests/sql/test_contracts.py tests/sql/test_compiler.py tests/sql/test_property_matrix.py -q
  ```

  Expected: executable compile success 100%, injection values parameterized, and repeat output byte-identical.

- [ ] **Step 8: Commit the compiler**

  Commit as:

  ```bash
  git commit -m "feat: compile semantic plans to parameterized sql"
  ```

---

### Task 9: Add a read-only SQL executor with evidence-preserving results

**Files:**

- Create: `src/financial_agent/sql/executor.py`
- Create: `src/financial_agent/sql/result_mapping.py`
- Create: `tests/sql/test_executor.py`
- Create: `tests/sql/test_result_mapping.py`
- Create: `tests/integration/test_semantic_sql_postgres.py`
- Modify: `tests/fixtures/db/synthetic_dataset.py`

- [ ] **Step 1: Write the read-only runner boundary tests with an injected engine**

  `ReadOnlySqlRunner.execute(CompiledSqlRequest)` validates plan/task/registry
  pins, opens a read-only transaction, applies the task timeout, executes once,
  and never edits the request or reschedules work. Reject requests containing
  non-read-only SQL even if constructed outside the compiler. Task 10 wraps this
  runner in the existing capability-executor interface.

- [ ] **Step 2: Map rows to existing typed tool results**

  Produce `ResultRow`, `ResultField`, exclusions, warnings, and evidence references. Each returned business value retains entity ID, semantic field ID, unit, currency, applicable date, observation ID, and linked evidence ID when available. Missing values are exclusions/warnings according to policy, not fabricated zeros.

- [ ] **Step 3: Add synthetic PostgreSQL conformance fixtures**

  Extend only synthetic fixtures with domestic ETF, overseas ETF, public fund representative/share-class relations, observations, metric definitions, and evidence links. Include zero, missing, sentinel, equal-tie, mixed-unit, duplicate-share-class, and injection-shaped text values.

- [ ] **Step 4: Verify query semantics end to end in PostgreSQL**

  Cover simple/compound screens, rank with ties, every aggregate, grouping/distribution, period/date filters, public-fund de-duplication, split cross-family execution, missingness, unit conversion, and evidence lineage.

  Run when `FINANCIAL_AGENT_TEST_DATABASE_URL` is configured:

  ```bash
  python3 -m pytest -m postgres tests/integration/test_semantic_sql_postgres.py -q
  ```

  Expected: exact rows, values, exclusions, evidence IDs, and repeated results.

- [ ] **Step 5: Run offline executor tests even without PostgreSQL**

  ```bash
  python3 -m pytest tests/sql/test_executor.py tests/sql/test_result_mapping.py -q
  ```

- [ ] **Step 6: Commit the executor**

  Commit as:

  ```bash
  git commit -m "feat: execute semantic sql read only"
  ```

---

### Task 10: Integrate V2 planning and SQL execution through the bounded Orchestrator

**Files:**

- Create: `src/financial_agent/orchestration/semantic_execution.py`
- Create: `src/financial_agent/orchestration/semantic_graph.py`
- Modify: `src/financial_agent/orchestration/executors.py`
- Modify: `src/financial_agent/orchestration/service.py`
- Modify: `src/financial_agent/orchestration/validation.py`
- Modify: `src/financial_agent/contracts/execution.py`
- Create: `tests/orchestration/test_semantic_graph.py`
- Modify: `tests/orchestration/test_executors.py`
- Modify: `tests/orchestration/test_service.py`
- Create: `tests/integration/test_semantic_query_orchestration.py`

- [ ] **Step 1: Add a separate strict V2 task-execution input**

  Keep the existing `TaskExecutionInput` constructor unchanged. Introduce a
  sibling type and use a closed request union only at the executor boundary:

  ```python
  class SemanticExecutionInputBase(ContractModel):
      request_key: Sha256Hex
      run_id: Identifier
      dataset_version: Identifier
      cutoff_date: date
      created_at: UtcDateTime
      task: ExecutionTask
      logical_query_plan: LogicalQueryPlanV2
      dependency_results: tuple[ToolResult, ...]
      binding_values: tuple[BindingValue, ...]
      binding_types: tuple[BindingTypeInput, ...]

  class SemanticSqlTaskExecutionInput(SemanticExecutionInputBase):
      request_kind: Literal["semantic_sql"] = "semantic_sql"
      compiled_request: CompiledSqlRequest

  class SemanticToolTaskExecutionInput(SemanticExecutionInputBase):
      request_kind: Literal["semantic_tool"] = "semantic_tool"

  SemanticExecutorRequest = Annotated[
      SemanticSqlTaskExecutionInput | SemanticToolTaskExecutionInput,
      Field(discriminator="request_kind"),
  ]
  ExecutorRequest = TaskExecutionInput | SemanticExecutorRequest
  ```

  The SQL branch requires `Capability.RDB_LOOKUP`; the semantic-tool branch
  forbids it. Both verify task ownership, bindings, and pins. Existing V1
  fixtures and call sites do not gain a version field and serialize
  byte-for-byte as before.

- [ ] **Step 2: Compile V2 logical tasks to the existing execution graph contract**

  `SemanticExecutionGraphCompiler` creates registered
  `Capability.RDB_LOOKUP` tasks from compiled SQL requests and registered
  Graph/Search/Calculation tasks from semantic primitives. It preserves typed
  prior-result dependencies and budgets. It cannot invoke an executor.

- [ ] **Step 3: Dispatch both plan versions through one scheduler**

  Keep `Orchestrator.execute(QueryPlanCompilation)` unchanged and add
  `execute_semantic(SemanticQueryPlanCompilation)`. Both delegate to one private
  scheduler that receives a graph plus a request factory. Keep concurrency,
  dependency order, request-wide retry budget, per-task retry limit, hard
  deadline, skip semantics, and outcome calculation unchanged. The Orchestrator
  remains the only scheduler.

- [ ] **Step 4: Register the SQL executor and retain executor authority boundaries**

  `SqlCapabilityExecutor.execute(ExecutorRequest)` rejects the V1 and
  semantic-tool branches, extracts the compiled request from
  `SemanticSqlTaskExecutionInput`, and calls
  `ReadOnlySqlRunner.execute(CompiledSqlRequest)`. It is registered for
  `Capability.RDB_LOOKUP` and cannot invoke HCX, Graph, Search, Calculation, or
  another task. Graph/Search/Calculation capabilities remain injected and
  registered separately.

- [ ] **Step 5: Run V1/V2 orchestration together**

  ```bash
  python3 -m pytest tests/orchestration/test_semantic_graph.py tests/orchestration/test_executors.py tests/orchestration/test_service.py tests/integration/test_semantic_query_orchestration.py tests/integration/test_intent_plan_orchestration.py -q
  ```

  Expected: V1 behavior is unchanged; V2 dependency and retry/deadline behavior matches the existing scheduler invariants.

- [ ] **Step 6: Commit Orchestrator integration**

  Commit as:

  ```bash
  git commit -m "feat: orchestrate semantic query plans"
  ```

---

### Task 11: Persist V2 artifacts with Alembic revision `0009`

**Files:**

- Create: `alembic/versions/0009_semantic_query_artifacts.py`
- Modify: `src/financial_agent/db/schema/operations.py`
- Modify: `src/financial_agent/db/repositories/artifacts.py`
- Modify: `src/financial_agent/contracts/__init__.py`
- Modify: `tests/db/test_artifact_repository.py`
- Modify: `tests/db/test_migration_cycle.py`
- Create: `tests/fixtures/contracts/v2/query_contract.json`
- Create: `tests/fixtures/contracts/v2/logical_query_plan.json`

- [ ] **Step 1: Write repository and migration failures first**

  Assert that `query_contract` restores as the V2 resolved-contract artifact, `logical_query_plan` restores as `LogicalQueryPlanV2`, model metadata is forbidden for both deterministic artifacts, duplicate contract object IDs are idempotent only for byte-identical payloads, and V1 artifacts still restore through existing models.

- [ ] **Step 2: Add versioned artifact wrappers and model dispatch**

  Persist one `ResolvedQueryContractSetV2(RuntimeArtifact)` with `query_contract_id`, source resolution ID, ordered frame contracts, registry pins, judge provenance, and readiness. Persist `LogicalQueryPlanV2` separately. Extend `ArtifactType` and `ARTIFACT_MODELS` without changing `intent_resolution` version dispatch.

- [ ] **Step 3: Implement revision `0009`**

  Extend the artifact-type constraint with `query_contract` and `logical_query_plan`. Update `operations.derive_request_artifact()` and the idempotency branch in `operations.append_request_artifact()` to derive `query_contract_id` and `logical_plan_id` as `contract_object_id`. Add non-blank object-ID checks. Preserve immutability triggers, request-scope pins, and model metadata policy.

  Downgrade must refuse when either V2 artifact type exists; it must never delete those artifacts to make downgrade succeed.

- [ ] **Step 4: Run migration cycle and repository tests**

  ```bash
  python3 -m pytest tests/db/test_artifact_repository.py tests/db/test_migration_cycle.py -q
  ```

  Expected: upgrade `0008 -> 0009`, idempotent append/restore, guarded downgrade, and full downgrade/upgrade cycle all pass on the configured PostgreSQL test database.

- [ ] **Step 5: Verify revision numbering and heads**

  ```bash
  python3 -m alembic heads
  python3 -m alembic history
  ```

  Expected: exactly one head, `0009`, with `down_revision = "0008"`.

- [ ] **Step 6: Commit artifact persistence**

  Commit as:

  ```bash
  git commit -m "feat: persist semantic query artifacts"
  ```

---

### Task 12: Run full offline verification, live HCX regression, and record promotion status

**Files:**

- Create: `tests/evaluation/query_contract/test_end_to_end_metrics.py`
- Create: `scripts/run_semantic_query_benchmark.py`
- Create: `docs/planning/verification/2026-09-02-semantic-query-contracts-and-sql-compilation-verification.md`
- Modify: `docs/planning/STATUS.md`

- [ ] **Step 1: Add fail-closed promotion report tests**

  The report records source hashes, registry hashes, case/frame counts, per-action representability, candidate recall, contract exact match, false-complete count, exact-lock precision, plan readiness distribution, compile success, OOD false-fast, provider success, repair/judge use, calls, tokens, p50/p95 latency, rate limiting, and every gate as `pass`, `fail`, or `unmeasured`. Any missing required metric leaves promotion `deferred`.

- [ ] **Step 2: Run focused semantic suites**

  ```bash
  python3 -m pytest tests/intent/test_query_contracts.py tests/intent/test_query_contract_registry.py tests/intent/test_axis_locks.py tests/intent/test_operators.py tests/intent/test_query_contract_solver.py tests/intent/test_query_contract_judge.py tests/intent/test_query_contract_service.py tests/planning/test_physical_bindings.py tests/planning/test_plan_readiness.py tests/planning/test_logical_query.py tests/planning/test_semantic_router.py tests/planning/test_semantic_compiler.py tests/sql tests/orchestration/test_semantic_graph.py tests/integration/test_semantic_query_orchestration.py tests/evaluation/query_contract -q
  ```

  Expected: zero failures and every offline promotion gate meets its numerical threshold.

- [ ] **Step 3: Run all existing offline tests**

  ```bash
  python3 -m pytest -m "not postgres and not ncp_integration and not performance and not organizer_data and not object_storage and not official_data and not jena_integration and not clova_integration" -q
  ```

  Expected: zero failures, including V1 intent, planning, orchestration, ontology, entity-role, context, evidence, and failure-policy suites.

- [ ] **Step 4: Run configured PostgreSQL verification**

  ```bash
  python3 -m pytest -m postgres tests/db tests/integration/test_semantic_sql_postgres.py -q
  ```

  If no approved test database URL is configured, record the database gate as `unmeasured`; do not substitute SQLite for PostgreSQL migration or SQL semantics.

- [ ] **Step 5: Run the authorized paced HCX regression only after offline gates pass**

  The script loads the existing credential without printing it, uses HCX-007 with thinking disabled, `temperature=0`, `topP=0.1`, `topK=1`, `maxCompletionTokens=4096`, `repetitionPenalty=1.0`, and `seed=42`, waits for provider responses without an artificial 20-second cutoff while still respecting the 55-second request deadline, and paces requests to reduce rate-limit coupling.

  Run the five previously failing representative questions plus exact-family omission, multi-predicate, qualitative rank, threshold screen, COUNT/SUM, grouped aggregate, cross-family comparison, prior-result context, lexical OOD, and domain OOD cases. Raw outputs remain under `/private/tmp`; only aggregate sanitized metrics enter the verification report.

  ```bash
  RUN_CLOVA_INTEGRATION=1 python3 scripts/run_semantic_query_benchmark.py --model HCX-007 --paced --sanitized-report /private/tmp/semantic-query-benchmark.json
  ```

- [ ] **Step 6: Compare baseline and challenger without automatic promotion**

  Report the production one-axis-call path separately from the three-parallel-axis challenger. A challenger may be recommended only if it clears every correctness gate and does not violate the request deadline; this task does not switch the production default.

- [ ] **Step 7: Inspect final scope and secret safety**

  ```bash
  git status --short
  git diff --check
  git diff --stat main...HEAD
  git diff --name-only main...HEAD
  python3 -c 'import pathlib, subprocess, sys; files=subprocess.check_output(["git","ls-files"], text=True).splitlines(); bad=[p for p in files if pathlib.PurePosixPath(p).name in {"api.txt", ".env"} or p.startswith("data/") or pathlib.PurePosixPath(p).suffix in {".xlsx", ".xlsm", ".parquet", ".db", ".sqlite"}]; print("\n".join(bad)); sys.exit(bool(bad))'
  ```

  Review all changed paths. Confirm no organizer raw data, credentials, provider output, runtime database, or generated local artifact is tracked.

- [ ] **Step 8: Write the verification record and commit it**

  The verification document states exact commands, counts, measured results, unavailable gates, residual limitations, and promotion status. `public_fund.fee_rate` remains listed as a semantic-complete/physical-limited case until separately verified.

  Commit as:

  ```bash
  git add docs/planning/verification/2026-09-02-semantic-query-contracts-and-sql-compilation-verification.md docs/planning/STATUS.md tests/evaluation/query_contract/test_end_to_end_metrics.py scripts/run_semantic_query_benchmark.py
  git diff --cached --check
  git diff --cached
  git commit -m "test: verify semantic query execution"
  ```

## Final Acceptance Checklist

- [ ] All 52 core questions and 160 held-out cases/209 frames are pinned to adjudicated semantic expectations.
- [ ] Supported semantic representability is 100%; every unsupported frame has one stable reason.
- [ ] `공모펀드` exact scope survives HCX omission.
- [ ] `총보수가 1% 이하` requires `fee_rate`, `lte`, and typed `1 percent` before ContractReadiness is complete.
- [ ] Qualitative `보수가 낮은` resolves as rank ascending with a recorded default limit, not an incomplete screen.
- [ ] Aggregate execution requires function, target/population, grouping, population grain, and de-duplication policy.
- [ ] `public_fund.fee_rate` cannot execute without a verified physical definition.
- [ ] No V2 predicate, qualifier, grouping, grain, or policy is flattened into V1.
- [ ] HCX and judge envelopes contain no physical schema, SQL, formulas, or arbitrary functions.
- [ ] SQL values are parameterized and identifiers are selected only from closed server mappings.
- [ ] Repeated input and registry pins produce byte-identical contracts, plans, compiled requests, and lowering manifests.
- [ ] Fast/Compose require Axis, Contract, and Plan readiness; OOD paths never become raw-schema Text-to-SQL.
- [ ] V1 contract, resolver, planner, orchestrator, and artifact fixtures remain green.
- [ ] Migration head is exactly `0009`; downgrade is guarded when V2 artifacts exist.
- [ ] No secret, organizer data, provider output, or runtime artifact is tracked.
- [ ] The verification report states `promoted` only when every applicable numerical gate passes; otherwise it states `deferred` with reasons.
