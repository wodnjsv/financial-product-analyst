# Semantic Query Contracts and SQL Compilation Design

**Date:** 2026-09-02

**Status:** Written specification; user review pending

**Decision:** [ADR-0029](../decisions/ADR-0029-use-semantic-query-contracts-and-deterministic-sql-compilation.md)

## 1. Outcome

Convert one Korean financial-product question into a complete, auditable
semantic query contract and then into deterministic SQL or a registered
non-SQL operation. The system must distinguish three different statements:

1. the request axes were understood;
2. every semantic input required by the task is present; and
3. the current dataset can execute that meaning safely.

Only the third statement authorizes execution.

```text
Question
  -> deterministic normalization and bounded candidates
  -> one HCX axis/frame/context resolution
  -> exact locks + registered contract candidate solver
       0 complete candidates -> Explore / Abstain
       1 complete candidate  -> accept
       >1 complete candidates -> deterministic tie-break
                                -> optional bounded plan-ID judge
  -> ResolvedQueryContractV2
  -> LogicalQueryPlanV2
  -> deterministic SQL / Graph / Search / Calculation executor
```

## 2. Baseline and Problem Statement

The current `TaskInputContractDefinition` is an action-level flat list. Its
minimum requirements are too weak:

| Action | Current required inputs | Structural defect |
| --- | --- | --- |
| `lookup` | none | projection, entity, or approved profile may all be absent |
| `screen` | `filter_value` | field and operator may be absent |
| `rank` | `sort_key`, `result_limit` | scope, direction policy, and predicates are not grouped |
| `compare` | `metric` | comparison subjects and basis may be absent |
| `aggregate` | `metric` | function, grain, grouping, and de-duplication may be absent |
| `calculate` | `metric` | recipe and operands may be absent |
| `similar` | `similarity_anchor` | anchor identity and scoring policy are conflated |
| `explain` | none | subject or approved explanation profile may be absent |

The design audit covered the 160 Korean held-out questions as 209 atomic action
frames. The current contracts fully represented 94 frames, 45.0 percent. The
per-action baseline was:

| Action | Fully representable / total |
| --- | ---: |
| `lookup` | 5 / 58 |
| `screen` | 0 / 23 |
| `rank` | 43 / 66 |
| `compare` | 17 / 30 |
| `aggregate` | 8 / 11 |
| `calculate` | 5 / 5 |
| `similar` | 10 / 10 |
| `explain` | 6 / 6 |

The implementation plan must turn this one-time audit into a reproducible
static coverage test before changing production behavior.

## 3. Assumptions, Constraints, and Non-Goals

### Assumptions

- Requests are stateless across API calls, but one request may contain multiple
  ordered frames with typed prior-result references.
- The four product-family values, eight action values, ontology, semantic
  catalog, physical observation registry, and missingness policies remain
  authoritative.
- The organizer product masters and approved official additions define what can
  be executed; the language model cannot extend data coverage.
- Archetypes optimize common paths but do not define all valid combinations.

### Constraints

- Keep one HCX axis call on the normal path.
- Keep all model output bounded to server-offered IDs.
- Keep physical schema, SQL, formulas, policies, and scheduling server-owned.
- Parameterize all user values; never interpolate them as SQL text.
- Preserve evidence, candidate, registry, ontology, dataset, and compiler
  provenance through execution.
- Preserve the public `GET /answer` response contract.
- Fail closed when a semantic input cannot be represented or bound.

### Non-goals

- This design does not approve personalized advice, forecasting, order
  execution, or real-time data outside the approved dataset.
- It does not make raw-schema Text-to-SQL a fallback.
- It does not require an alias for every possible Korean phrase.
- It does not promote three parallel HCX axis calls.
- It does not claim that an existing held-out label is correct without semantic
  adjudication.

## 4. Sources of Truth

The implementation uses distinct versioned registries with one owner each.

| Registry | Owns | Must not own |
| --- | --- | --- |
| Semantic query catalog | abstract fields, metrics, relations, types, applicability, qualifiers | physical SQL names |
| Korean NLU overlay | high-trust labels, spacing variants, operator cues, paraphrase anchors | entity identity database or execution rules |
| Query contract registry | action variants, required components, defaults, result shape | SQL text |
| Physical binding registry | family-specific source, field/expression binding, type, unit, date, missingness, aggregation support | Korean wording |
| Policy registry | comparison, normalization, population grain, de-duplication, coverage | model prompt prose |
| Recipe registry | registered financial calculations and operand types | free-form formulas |

All runtime artifacts pin registry versions and hashes. A mismatched pin is a
system contract failure, not a semantic limitation.

## 5. Language Preparation and Exact Locks

Deterministic preparation performs:

1. Unicode and spacing normalization without changing stored source evidence;
2. numeric, percent, currency, date, period, direction, and result-limit literal
   extraction;
3. exact product-family matching where one expression has one registered scope,
   such as `공모펀드 -> public_fund`;
4. operator matching for at least equality, inequality, ranges, membership, and
   exclusion, including `이하`, `미만`, `이상`, `초과`, and `제외`;
5. exact canonical and direct-alias field candidates such as
   `총보수 -> fee_rate` where a catalog concept exists;
6. bounded lexical candidates for non-exact expressions; and
7. entity and typed context candidates from the current request.

Only exact literals and unique canonical or direct aliases are lockable. A lock
must be compatible with the resolved frame, action contract, selected family,
and evidence span. Conflicts fail closed. Non-exact candidates remain choices
for HCX or the contract solver.

The overlay is deliberately small and high precision. Coverage grows primarily
from canonical catalog labels, normalized variants, bounded lexical retrieval,
and held-out failure analysis rather than an attempt to hand-write every
surface form.

## 6. Contract Grammar

`ResolvedQueryContractV2` is a closed union selected by `action_id`. Every
variant contains `frame_id`, `scope`, `qualifiers`, `result_shape`, provenance,
and the three readiness results.

### 6.1 Scope

```yaml
scope:
  product_family_ids: [public_fund]
  entity_refs: []
  prior_result_binding: null
```

At least one of product-family scope, explicit entity scope, or typed
prior-result scope is required. A generic family expression may expand to a
registered set only through an explicit scope policy.

### 6.2 Projection

```yaml
projections:
  field_concept_ids: [product_name, fee_rate, aum]
  default_profile_id: null
```

A projection uses explicit field concepts or one approved profile. The compiler
expands a profile deterministically and records the expansion.

### 6.3 Predicate tree

```yaml
predicate:
  all_of:
    - field_concept_id: fee_rate
      operator_id: lte
      value:
        kind: decimal
        decimal: "1"
        unit_id: percent
      null_policy_id: exclude_missing.v1
```

Predicate nodes are `all_of`, `any_of`, `not`, or atoms. An atom is complete
only with a field, type-compatible operator, typed value or value set, and
registered missingness policy. The first implementation may bound nesting
depth and atom count, but must reject overflow explicitly rather than truncate.

### 6.4 Ordering and limits

```yaml
ordering:
  - field_concept_id: aum
    direction: desc
    nulls_policy_id: exclude_missing.v1
    tie_break_policy_id: stable-product-id.v1
limit: 5
```

Direction and limit may use approved defaults only when the policy is named and
recorded. Deterministic tie behavior is mandatory.

### 6.5 Aggregation

```yaml
aggregation:
  function_id: sum
  target_field_concept_id: aum
  group_by_field_concept_ids: []
  population_grain_id: representative_product
  dedup_policy_id: public-fund-representative-share.v1
```

Supported function IDs are `sum`, `count`, `count_distinct`, `avg`, `min`,
`max`, and `distribution`. `count` still requires an explicit population grain.
`distribution` requires grouping or a registered bucket policy. Public-fund
totals require a verified representative-fund grain or an explicit limitation.

### 6.6 Comparison

```yaml
comparison:
  subject_refs: [entity-a, entity-b]
  metric_concept_ids: [fee_rate]
  basis_policy_id: same-definition-period-unit.v1
  normalization_policy_id: null
```

The subjects may be explicit entities, groups, or prior results. A metric list
without subjects or a comparison profile is incomplete. Cross-family
normalization occurs only through an approved policy with evidence.

### 6.7 Calculation

```yaml
calculation:
  recipe_id: registered-recipe-id
  operands:
    - role_id: principal
      value_ref: literal-principal
    - role_id: rate
      field_concept_id: yield_rate
```

The recipe registry owns formulas, operand types, rounding, and evidence
requirements. HCX cannot author a formula.

### 6.8 Similarity and explanation

Similarity requires an anchor entity or prior-result reference, registered
similarity policy, dimensions, coverage threshold, and limit. A metric or
attribute can be a similarity dimension but is not itself an anchor.

Explanation requires an entity/scope plus a document topic or approved data
explanation profile. It can compile to registered Graph, Keyword, or Vector
tasks but never to an unrestricted search agent.

## 7. Action-Specific Completeness

| Action | Complete only when |
| --- | --- |
| `lookup` | scope plus explicit projections or approved default profile |
| `screen` | scope plus at least one complete predicate atom |
| `rank` | scope, ordering field, direction/default, limit/default; optional complete predicate |
| `compare` | two or more subjects or group basis, plus metric/projection or approved comparison profile |
| `aggregate` | scope, function, target or count population, population grain, de-duplication policy; valid optional grouping/predicate |
| `calculate` | scope/entity, registered recipe, and every required operand |
| `similar` | anchor, policy, dimensions/default profile, coverage threshold, and limit |
| `explain` | subject/scope plus topic or approved explanation profile |

Qualitative ordering such as `보수가 낮은 상품` is `rank` ascending with a
registered default limit when no threshold is stated. It is not a complete
`screen`. A phrase such as `총보수가 1% 이하` is `screen` because field,
operator, and value are all explicit.

## 8. Candidate Solving

For each axis-resolved frame, the server:

1. selects contract variants registered for the action;
2. applies exact family, literal, field, operator, entity, and context locks;
3. enumerates only role-compatible offered candidates for unresolved inputs;
4. prunes candidates by family applicability, value type, evidence grouping,
   qualifier compatibility, population policy, and context cardinality;
5. evaluates the variant completeness invariant;
6. records every rejection with a stable reason; and
7. deduplicates semantically equivalent contracts by canonical serialization.

Candidate enumeration has configured per-role and total bounds. Reaching a
bound produces a visible ambiguity result; candidates are never silently
dropped and treated as unique.

Resolution order is:

```text
unique exact lock
  -> unique complete candidate after deterministic pruning
  -> deterministic evidence/applicability tie-break
  -> optional bounded HCX candidate-plan-ID judge
  -> Explore or Abstain if still unresolved
```

The judge sees the original question, frame evidence, and compact semantic
summaries of complete candidates. It returns only a candidate ID. It cannot
change axes, add a field, invent a value, or emit SQL. It shares the single
request-wide extra LLM allowance with schema repair.

## 9. Readiness and Four-Path Routing

### AxisReadiness

`complete` requires resolved frame boundaries, action, scope, semantic tags,
entity roles, and context links. Otherwise the outcome is `ambiguous` or
`blocked`.

### ContractReadiness

`complete` requires exactly one canonical contract satisfying its variant
invariant. Multiple complete contracts are `ambiguous`; missing vocabulary or
required values are `blocked`.

### PlanReadiness

`executable` requires a physical binding and applicable policy for every field,
relation, qualifier, grouping, recipe, and evidence requirement. Otherwise it
is `explorable`, `limited`, or `blocked` with stable reasons.

Routing is then deterministic:

| Route | Conditions |
| --- | --- |
| Fast | all readiness gates pass and one exact archetype matches |
| Compose | all readiness gates pass and registered primitives can compose the plan |
| Explore | axes are grounded but vocabulary or physical coverage can be searched within registered catalogs/documents |
| Abstain | domain/context/policy is unresolved, prohibited, or unsafe |

An action can be correct while ContractReadiness is blocked. A semantic
contract can be complete while PlanReadiness is limited. These outcomes must
not be flattened into one `resolution_status`.

## 10. LogicalQueryPlanV2 and SQL Compiler Boundary

`LogicalQueryPlanV2` carries semantic IDs and typed values, not SQL identifiers.
It preserves:

- scope sources and joins by registered binding IDs;
- projections;
- predicate tree;
- aggregation, grouping, grain, and de-duplication;
- comparison or calculation operations;
- ordering, ties, and limit;
- period, currency, unit, as-of, and missingness qualifiers;
- evidence requirements and every applied policy ID; and
- typed prior-result dependencies.

The deterministic SQL compiler:

1. validates every registry and dataset pin;
2. resolves semantic fields through family-specific physical bindings;
3. selects only registered joins and expressions;
4. validates operator and aggregation support against field types;
5. applies missingness and de-duplication policies;
6. emits parameterized SQL plus typed parameters;
7. returns a manifest of semantic-to-physical lowering records; and
8. rejects lossful or unsupported lowering with a stable reason.

The compiler never receives model prose. The executor never changes the plan;
it validates the compiled request, runs it read-only, and returns rows plus
evidence locators and execution metadata.

V1 plans remain available for historical and non-SQL paths during migration.
No adapter may erase V2 semantics. The implementation plan must choose a
versioned migration order and compatibility tests before modifying runtime
contracts.

## 11. Worked Examples

### Fee threshold screen

```text
Question: 공모펀드 중 총보수가 1% 이하인 상품을 찾아줘

exact locks:
  scope = [public_fund]
  field = fee_rate
  operator = lte
  value = 1 percent

contract:
  Screen(scope, Predicate(fee_rate, lte, 1 percent))

result:
  AxisReadiness=complete
  ContractReadiness=complete
  PlanReadiness=executable only if public_fund.fee_rate binding exists
```

### Public-fund AUM total

```text
Question: 전체 공모펀드의 순자산 합계는?

exact locks:
  scope = [public_fund]
  target = aum
  function = sum

server policy:
  population_grain = representative_product
  dedup_policy = public-fund-representative-share.v1

contract:
  Aggregate(public_fund, sum(aum), representative_product, dedup-policy)
```

If the representative key or policy is unavailable, AxisReadiness and
ContractReadiness may be complete while PlanReadiness is limited. The system
must not sum share classes directly.

### Qualitative fee request

```text
Question: 보수가 낮은 ETF 알려줘

contract:
  Rank(scope=registered ETF scope,
       order_by=fee_rate asc,
       limit=registered default,
       tie_policy=stable-product-id.v1)
```

There is no invented threshold and therefore no Screen predicate.

### Context re-rank inside one request

```text
Question: ETF 중 순자산 상위 5개를 찾고, 그 상품 중 수익률 1위는?

frame 1:
  Rank(ETF scope, aum desc, limit=5) -> binding result_set_1
frame 2:
  Rank(prior_result_binding=result_set_1, return_rate desc, limit=1)
```

The second frame consumes the first result set. It does not query all ETFs
again and does not rely on cross-request memory.

## 12. Verification Strategy

### 12.1 Static contract coverage

- Turn every adjudicated supported frame from the 52 core questions and the
  160-case/209-frame Korean set into an expected semantic requirement vector.
- Assert that at least one registered contract variant can represent it.
- Assert that every unsupported frame has one explicit unsupported reason.
- Report per-action and overall coverage; do not use Fast-path rate as a goal.

### 12.2 Contract unit and property tests

- Field/operator/value compatibility and predicate grouping.
- AND, OR, NOT, range, membership, and exclusion cases.
- Ordering defaults, explicit directions, limits, nulls, and stable ties.
- Every aggregation function, grouping, count grain, and de-duplication policy.
- Comparison subjects, qualifiers, and cross-family compatibility.
- Calculation recipe operands and type rejection.
- Exact lock conflicts, ambiguous candidates, and enumeration bounds.
- Canonical serialization and byte-equivalent repeatability.

Generated combinations cover product family × action × field kind × operator ×
value kind, plus aggregation grain and qualifier dimensions. Each case must
compile or return one stable rejection reason.

### 12.3 SQL compiler tests

Use synthetic, approved fixtures and a read-only disposable database to verify:

- simple and compound predicates;
- parameterization and injection resistance;
- deterministic joins, ordering, ties, and limits;
- `SUM`, `COUNT`, `COUNT DISTINCT`, `AVG`, `MIN`, `MAX`, grouping, and
  distribution;
- public-fund representative-product de-duplication;
- period, currency, unit, as-of, missingness, and sentinel handling;
- cross-family split or approved normalization; and
- identical plan, SQL, parameters, results, and lowering manifest on repeat.

### 12.4 Resolver and live HCX tests

Re-run the previous five representative failures and add cases for:

- exact family present versus omitted by HCX;
- one and multiple predicates;
- qualitative ordering versus numeric threshold;
- `COUNT` versus `SUM`;
- grouped aggregate and public-fund de-duplication;
- cross-family comparison;
- typed prior-result context;
- lexical OOD and domain OOD.

Record structured validity, action and family exactness, candidate recall,
contract exact match, false-complete rate, compile success, omission rate,
provider calls, latency, and rate limiting. Decoupled tests inject correct axes
to separate contract/compiler failures from resolver failures.

Raw provider outputs, credentials, organizer data, and local runtime artifacts
remain untracked.

## 13. Implementation Sequence After Specification Approval

1. Add a reproducible coverage audit and adjudicate incorrect or ambiguous gold
   semantics before changing contracts.
2. Add `ResolvedQueryContractV2` and versioned contract/operator/policy
   registries with unit tests.
3. Add exact family and operator locks plus the minimal high-trust Korean field
   anchors required by supported questions.
4. Add the bounded Contract Candidate Solver and optional candidate-ID judge.
5. Add `LogicalQueryPlanV2` and lossless provenance.
6. Add the deterministic semantic-to-SQL compiler and synthetic database tests.
7. Integrate V2 through routing, graph compilation, and the existing bounded
   Orchestrator without giving executors scheduling authority.
8. Run focused, broad, property, and end-to-end local verification.
9. Run the approved paced live HCX benchmark and compare the one-call baseline
   with any parallel challenger.
10. Promote no new path until every applicable gate passes.

The detailed implementation plan must name exact files, tests, migration order,
compatibility boundaries, and numerical promotion thresholds. This design does
not authorize those implementation edits yet.

## 14. Success Criteria

1. Every adjudicated supported SQL question has a complete semantic contract;
   unsupported questions have an explicit non-executable outcome.
2. False-complete contract acceptance is zero.
3. `공모펀드` cannot disappear from an exact explicit question because HCX
   omitted it.
4. `총보수가 1% 이하` cannot be complete without `fee_rate`, `lte`, and the
   typed literal `1 percent`; physical unit conversion remains deterministic.
5. Aggregate totals cannot execute without function, target/population, grain,
   and de-duplication policy.
6. HCX emits no physical schema, SQL, arbitrary function, or formula.
7. Same semantic contract and registry pins produce byte-equivalent logical
   plans and compiled requests.
8. Fast and Compose execute only when Axis, Contract, and Plan readiness all
   pass.
9. Existing ontology, entity-role, context, evidence, failure, and Orchestrator
   invariants remain green.
10. No credential, organizer raw data, provider output, or generated runtime
    artifact enters Git.
