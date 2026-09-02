# ADR-0029: Use Semantic Query Contracts and Deterministic SQL Compilation

**Date:** 2026-09-02

**Status:** Accepted

**Approved:** 2026-09-02 — the user approved expanding incomplete SQL
contract coverage, separating semantic query interpretation from physical SQL,
and validating the result against the full supported question boundary.

**Supersedes:** [ADR-0027](ADR-0027-use-server-owned-task-contracts-and-locked-bindings.md)
and [ADR-0028](ADR-0028-separate-axis-resolution-from-task-slot-binding.md)
only where they define one flat required/optional slot list per action. Their
server-owned contracts, conservative deterministic binding, axis/slot
responsibility split, and fail-closed routing remain accepted.

**Amends:** [ADR-0025](ADR-0025-use-deterministic-query-plan-compilation-and-four-path-routing.md)
where it requires every newly resolved SQL meaning to fit the original
`QueryPlan` shape. A versioned internal `LogicalQueryPlanV2` may replace that
shape for semantic SQL execution; the public `GET /answer` API remains
unchanged and no meaning may be discarded to preserve V1 compatibility.

**Related:** [ADR-0005](ADR-0005-bounded-llm-typed-capability-execution.md),
[ADR-0006](ADR-0006-separate-disposition-and-bound-recovery.md),
[ADR-0022](ADR-0022-use-ontology-grounded-intent-resolution.md),
[ADR-0023](ADR-0023-use-server-owned-intent-identities-and-explicit-semantic-coverage.md),
[ADR-0024](ADR-0024-use-bounded-entity-type-registry-and-role-aware-entity-hints.md),
[ADR-0026](ADR-0026-use-a-deterministic-bounded-orchestrator.md), and
[Semantic Query Contracts and SQL Compilation Design](../specs/2026-09-02-semantic-query-contracts-and-sql-compilation-design.md)

## Context

The current task-input registry prevents some missing-slot errors, but its flat
contracts do not describe complete SQL meaning. For example, `screen` requires
only `filter_value`; it can therefore report `complete` without a field or
operator. `aggregate` identifies a metric but does not require an aggregation
function, grouping, population grain, or de-duplication policy. The current
`QueryPlan` likewise has filters, metrics, and operations but no complete
predicate tree, projection, aggregation, comparison-subject, or registered
calculation-recipe boundary.

A design audit against the 160-case Korean held-out set found 209 atomic action
frames. Only 94 frames, 45.0 percent, were fully representable by the current
flat contracts. Sixty-seven frames required at least one semantic slot kind the
selected action contract did not allow. This explains false-complete outcomes;
it is not evidence that HCX successfully understood an executable query.

Two live observations expose different failure classes:

- `공모펀드 중 총보수가 1% 이하인 상품` can select the family but cannot form a
  complete predicate when `총보수` and `이하` are not represented as bounded
  field and operator candidates.
- `전체 공모펀드의 순자산 합계` can select `aggregate` and `aum` while omitting
  the explicit family. That is a false negative in model selection. Because
  `공모펀드` is an exact, unique family expression, it should be a deterministic
  lock rather than a value HCX must copy.

Patching individual aliases or adding more optional slots cannot establish
whether every supported SQL question is representable and executable.

## Decision

### Define the supported boundary explicitly

The supported SQL boundary is every lookup, predicate filter, rank, compare,
aggregate, and registered calculation combination that can be grounded in the
four organizer product masters, the approved semantic catalog, physical
bindings, comparison rules, and data-quality policies.

An unknown field, unavailable physical binding, prohibited comparison,
unsupported calculation, or unresolvable domain is not converted into SQL. It
uses Explore, Limitation, or Abstain under the existing four-path and failure
policies.

### Replace flat slot lists with action-specific semantic contracts

Introduce the closed union `ResolvedQueryContractV2` with separate variants
for `lookup`, `screen`, `rank`, `compare`, `aggregate`, `calculate`, `similar`,
and `explain`. Each variant has its own completeness invariant. Shared
components include:

- product-family, entity, or prior-result scope;
- explicit projections or a registered default projection profile;
- typed predicate trees whose atoms contain field, operator, and value;
- relations, ordering, limit, period, currency, as-of date, and unit qualifiers;
- aggregation function, target, grouping, population grain, and de-duplication;
- comparison subjects and basis;
- registered calculation recipe and operands; and
- evidence and candidate provenance for every resolved input.

No giant structure whose optional fields change meaning by convention is
allowed. A contract is complete only when its selected variant's invariant is
satisfied.

### Keep language resolution bounded and make exact facts server-owned

Deterministic preparation produces normalized literals, high-trust Korean
anchors, exact product-family locks, operator candidates, semantic field
candidates, entity candidates, and typed context references. It does not try to
enumerate every Korean paraphrase manually.

The normal HCX axis call continues to resolve atomic frames, action, ambiguous
family scope, tags, entity roles, context links, and semantic coverage. It does
not write SQL, physical table or column names, formulas, contract bodies, or
execution recipes.

After action resolution, a deterministic Contract Candidate Solver enumerates
only registered contract variants and compatible bindings. It rejects
incomplete or type-incompatible combinations. One surviving complete candidate
is accepted. With no surviving candidate, the request uses Explore or Abstain.
If more than one semantically complete candidate remains after deterministic
evidence and applicability checks, one exceptional bounded HCX call may select
only an offered candidate-plan ID.

That exceptional judge consumes the same request-wide extra LLM allowance used
for resolver repair; a request may use repair or candidate judging, never both.
This narrowly supersedes ADR-0022 and ADR-0028 where they prohibit a second call
for semantic ambiguity. It does not make a second call part of the normal path.

Three parallel family/action/tag calls and a larger-model combiner remain an
offline benchmark challenger. They are not promoted without better measured
contract exactness and acceptable latency, rate-limit, token, and context-link
results.

### Compile semantics, not model-authored SQL

Introduce a versioned internal `LogicalQueryPlanV2`. The deterministic compiler
maps only registered semantic IDs to approved physical bindings, predicates,
joins, grouping, de-duplication, ordering, limits, and calculation recipes.
Identifier quoting, parameter binding, missingness handling, and financial
calculation behavior are compiler or executor responsibilities.

HCX cannot emit SQL fragments, table names, column names, aggregation
expressions, or arbitrary functions. An ontology concept without a valid
family-specific physical binding is non-executable even when the language
mapping is correct.

The original QueryPlan remains readable for historical fixtures and non-SQL
paths during migration. A V1-to-V2 or V2-to-V1 adapter is allowed only when it
is lossless and covered by conformance tests. The semantic SQL path must never
drop a predicate, qualifier, grouping, grain, or de-duplication policy to fit V1.

### Separate three readiness decisions

Every frame records independent readiness axes:

- `AxisReadiness`: frame, action, scope, tags, and context are resolved;
- `ContractReadiness`: all semantic inputs required by the selected contract
  variant are complete and unambiguous; and
- `PlanReadiness`: every semantic input has an approved physical binding and
  executable policy.

Fast and Compose require all three. A complete action label does not imply a
complete contract, and a complete semantic contract does not imply executable
data coverage.

### Make aggregation grain and de-duplication mandatory

Aggregate contracts explicitly support `SUM`, `COUNT`, `COUNT_DISTINCT`,
`AVG`, `MIN`, `MAX`, and `DISTRIBUTION`. They must state the aggregation target,
population grain, and de-duplication policy. Public-fund totals may not sum
share-class duplicates unless a verified representative-fund key and approved
policy make the population explicit.

### Treat archetypes as optimized plans, not supported intent definitions

Archetypes remain a cache for frequent, exact plans. Novel valid semantic
combinations proceed through deterministic contract solving and Compose. An
archetype miss is not an OOD classification.

## Verification and Promotion Gates

Before the semantic SQL path can become the default:

- static representability must be 100 percent for every adjudicated supported
  frame in the 52 core questions and the held-out Korean evaluation set;
- unsupported frames must map to an explicit Explore, Limitation, or Abstain
  reason rather than a partial executable contract;
- false-complete acceptance must be zero;
- exact unique family, field, operator, and literal lock precision must be
  100 percent;
- supported contract exact match and deterministic compile success must meet
  thresholds fixed in the implementation plan before benchmark execution;
- generated family/action/field-kind/operator/value-kind combinations must
  either compile or produce one stable rejection reason;
- SQL conformance tests must cover compound predicates, ordering and ties,
  grouping, every supported aggregate, public-fund de-duplication, period,
  currency, missingness, and deterministic parameterization;
- the five previously failing representative live questions must pass their
  adjudicated semantic expectation; and
- single-call baseline and any parallel-call challenger must be reported
  separately. No challenger is promoted on anecdotal examples.

Promotion remains blocked while ADR-0022 candidate-recall or live-model gates
fail. Contract coverage does not waive resolver promotion requirements.

## Rejected Alternatives

### Patch the current flat TaskInputContract action by action

Rejected because optional slot accumulation cannot express predicate grouping,
aggregation grain, comparison subjects, registered calculations, or structural
completeness.

### Let HCX generate a raw SQL AST or SQL text

Rejected because it exposes physical schema and executable freedom to the
model, weakens ontology applicability and missingness controls, and makes
financial calculations harder to reproduce.

### Resolve a contract template and values in independent production calls

Rejected as the default because both outputs share frame, scope, and context
semantics. Enumerating compatible server-owned candidates captures the intended
freedom reduction without accepting incompatible cross-products. The parallel
design remains a benchmark challenger.

### Add every Korean phrase as a hand-maintained alias

Rejected because the list would drift and remain incomplete. The approved
boundary uses a small high-precision anchor layer plus generated bounded
candidates, with HCX resolving only the residual ambiguity.

## Consequences

### Positive

- `complete` now means that an executable semantic query is structurally whole.
- Exact Korean facts cannot disappear because HCX omitted them.
- SQL generation is deterministic, parameterized, testable, and independent of
  model phrasing.
- Aggregate totals have explicit population and de-duplication meaning.
- Resolver, contract, compiler, and executor accuracy can be measured
  separately.
- Novel valid combinations do not require one archetype per question.

### Costs and risks

- Runtime contracts, registries, compiler inputs, fixtures, and artifact
  schemas need coordinated versioning.
- Physical binding coverage can become the next bottleneck after language
  candidate recall improves.
- Candidate enumeration must be bounded to avoid a combinatorial explosion.
- Existing held-out labels require semantic adjudication where a qualitative
  phrase such as `보수가 낮은` should be rank-ascending rather than a threshold
  screen.
- Supporting both V1 and V2 during migration adds temporary complexity.

## Preserved Decisions

- One HCX Intent Resolver and one Answer Composer remain the normal path.
- Only the deterministic Orchestrator schedules model and executor calls.
- Filtering, sorting, ranking, aggregation, financial calculation, and evidence
  verification remain deterministic.
- Model outputs remain limited to server-offered IDs.
- The four-path Fast, Compose, Explore, and Abstain policy remains.
- Cross-request conversational memory, personalized advice, order execution,
  and unsupported forecasts remain out of scope.

## Non-Approval

This ADR approves the architecture direction only. It does not approve runtime
implementation, schema migration, generated SQL execution, model promotion,
deployment, push, or merge. The written specification must be reviewed before a
detailed implementation plan is approved.
