# ADR-0027: Use Server-Owned Task Contracts and Locked Explicit Bindings

**Date:** 2026-09-02

**Status:** Accepted

**Approved:** 2026-09-02 — the user approved restructuring intent resolution
around axis classification, server-owned task contracts, deterministic explicit
value locking, and fixed downstream execution recipes, with three parallel HCX
axis calls retained only as a measured challenger.

**Amends:** [ADR-0023](ADR-0023-use-server-owned-intent-identities-and-explicit-semantic-coverage.md)
only where it prohibits the assembler from materializing a semantic choice that
the model omitted. A server-validated locked binding is now an allowed source;
the server still may not infer an ambiguous or unoffered value.

**Related:** [ADR-0022](ADR-0022-use-ontology-grounded-intent-resolution.md),
[ADR-0025](ADR-0025-use-deterministic-query-plan-compilation-and-four-path-routing.md),
[ADR-0026](ADR-0026-use-a-deterministic-bounded-orchestrator.md),
[Intent Task Contract and Locked Binding Design](../specs/2026-09-02-intent-task-contract-and-locked-binding-design.md)

## Context

The first successful live HCX-007 ProposalV2 run proved that the provider,
Structured Outputs schema, server assembler, and strict semantic validators can
complete end to end. It also exposed a semantic-completeness defect. For the
question `ETF 중 순자산이 큰 상품 다섯 종목 알려줘`, deterministic candidate
generation offered the direct alias `순자산 -> aum` and literal extraction
offered `다섯 종목 -> result_limit=5`. HCX selected `rank` and the result limit
but omitted `sort_key=aum`.

The output was schema-valid because the proposal represents slots as an optional
array. JSON shape validity therefore did not imply that the selected action's
required execution inputs were complete. The server later detected the missing
slot only when QueryPlan compilation attempted to expand the rank primitive.

The same boundary unnecessarily asks HCX to re-select values that deterministic
code has already resolved without ambiguity. This increases omission and
contradiction risk and obscures the distinction between language understanding
and executable task readiness.

The publicly documented Shinhan Card design reinforces the separation of
responsibilities: small models classify Domain, Action, and Tag; deterministic
graph matching resolves an intent; a separate information-extraction stage
collects parameters; and the resolved intent selects a predefined execution
chain. The published material does not establish slot-completeness enforcement,
so this project must retain its stricter fail-closed boundary.

## Decision

### Add a server-owned task-input contract to every selected frame

Each supported action has a versioned `TaskInputContractDefinition`. The
definition owns its required and optional slot roles, allowed value kinds,
approved default policies, and result shape. It is generated from one versioned
registry shared by Intent Resolution and QueryPlan compilation; prompt text is
not an independent source of truth.

After action, family, tags, and context are validated, the server selects exactly
one applicable task-input contract for each frame. The model does not invent or
rewrite contract IDs, primitive IDs, capabilities, policies, or execution order.

The validated resolution exposes a `ResolvedTaskContract` containing:

- the selected contract ID, version, and registry hash;
- the selected action and frame ID;
- required and optional slot roles;
- canonical slot bindings with source provenance;
- missing required slot roles; and
- a readiness state of `complete`, `defaultable`, or `blocked`.

QueryPlan compilation may use Fast only when every frame's task contract is
`complete`. Approved defaults are applied deterministically and recorded before
the contract becomes complete. A blocked contract cannot be hidden by archetype
matching.

### Lock only explicit, unambiguous server-resolved values

Normalization, literal extraction, and semantic candidate generation may emit
request-scoped lock candidates. A value becomes a locked binding only when all
of the following are true:

1. it comes from an exact deterministic literal or one unique exact/direct-alias
   semantic candidate;
2. the selected task contract permits the candidate kind for that slot role;
3. no competing candidate covers the same semantic role;
4. the concept applies to the selected product-family scope; and
5. no validated context mutation updates, deletes, or marks the slot DONTCARE.

The server may materialize an omitted locked binding into the canonical frame.
This is canonicalization of a prevalidated request fact, not model repair or
semantic invention. Each materialized binding preserves its original evidence,
candidate ID, match type, and lock policy version.

If HCX proposes the same binding, the server deduplicates it. If HCX proposes a
different value for a locked role, validation fails closed with a stable contract
error. If more than one candidate remains, no lock is created and HCX retains
the semantic choice.

### Keep one HCX call on the normal path

The normal resolver continues to make one bounded HCX call for frame
segmentation, product-family scope, action, tags, ambiguous slot choices,
entities, context links, and semantic coverage. The ResolverView includes a
compact projection of task-input definitions and lock candidates so the model
can reason about the same contracts that the server validates.

Three independent Domain/ProductFamily, Action, and Tag calls do not by
themselves solve slot completeness. They also risk cross-axis disagreement,
triple token use, provider rate limiting, and inconsistent context links. A
three-call design remains an offline benchmark challenger. Promoting it requires
a separate ADR backed by better held-out joint frame and required-slot exactness
without violating the request deadline or recovery budget.

### Keep execution selection deterministic

Task-input contracts state what a frame needs; they do not authorize the model
to plan execution. The QueryPlan compiler still chooses registered archetypes or
primitive compositions from validated axes, tags, context, and complete
bindings. The Orchestrator remains the only scheduler. SQL, Graph, search,
ranking, aggregation, similarity, and calculation stay deterministic.

## Consequences

### Positive

- A schema-valid `rank` frame can no longer be treated as execution-ready while
  `sort_key` or `result_limit` is missing.
- Explicit values such as `순자산 -> aum` and `다섯 종목 -> 5` are not exposed
  to avoidable model omission.
- Every frame reports why it is ready or blocked before routing.
- Intent Resolution and QueryPlan compilation validate the same versioned input
  requirements.
- HCX remains focused on ambiguous Korean semantics and context rather than
  deterministic copying.

### Costs and risks

- A new versioned task-contract projection and resolved-contract artifact are
  required.
- Resolver, schema, compiler, fixtures, and provenance versions must move
  together.
- Lock criteria must remain conservative; a false lock is worse than a missing
  lock.
- Existing candidate-recall failure is not fixed by this decision. A correct
  value that was never generated cannot be locked or selected.

## Rejected Alternatives

### Prompt-only completeness instructions

Rejected because a live prompt experiment still omitted `sort_key=aum` and
selected excessive evidence. Prose cannot guarantee action-dependent array
completeness.

### Let HCX echo the full execution recipe

Rejected because primitive IDs, policies, budgets, evidence requirements, and
execution order are server-owned and deterministic. Model-authored execution
contracts would create another source of truth.

### Unconditionally insert the top semantic candidate

Rejected because candidate scores are not proof of role, applicability, or lack
of conflict. Only exact, unique, role-compatible candidates may be locked.

### Make three parallel HCX calls the default now

Rejected because the current live adapter has already shown high latency and
rate limiting, the axes share frame and context semantics, and three axis calls
still require a separate slot-completion stage.

## Verification and Promotion Gates

In addition to every ADR-0022 gate:

- unknown or conflicting locked-binding acceptance must be zero;
- every selected frame must carry exactly one validated task contract;
- Fast-route required-slot completeness must be 100 percent;
- held-out explicit locked-binding precision must be 100 percent;
- held-out required-slot exact match must be at least 99 percent for supported
  frames with gold required inputs;
- no blocked contract may enter Fast; and
- the representative live rank question must return `sort_key=aum` and
  `result_limit=5` with preserved evidence and no model repair.

Failure of a gate blocks promotion and does not justify relaxing validation.

## Preserved Decisions

- QueryPlan and the public `GET /answer` contract remain unchanged.
- The normal path uses one Intent Resolver HCX call and one Answer Composer HCX
  call.
- The request-wide shared LLM repair allowance remains one.
- Semantic OOD, execution failure, and answer disposition remain separate.
- No cross-request memory, personalized advice, order execution, unsupported
  forecast, or model-generated financial calculation is added.
