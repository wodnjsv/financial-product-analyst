# ADR-0028: Separate Axis Resolution from Task Slot Binding

**Date:** 2026-09-02

**Status:** Accepted

**Approved:** 2026-09-02 — the user approved implementing and testing the
responsibility-separated resolver without another approval gate.

**Supersedes:** [ADR-0027](ADR-0027-use-server-owned-task-contracts-and-locked-bindings.md)
only where ADR-0027 lets the normal HCX call select ambiguous executable slot
values. The server-owned contract, conservative deterministic binding, routing,
and execution decisions remain accepted.

**Related:** [ADR-0022](ADR-0022-use-ontology-grounded-intent-resolution.md),
[ADR-0025](ADR-0025-use-deterministic-query-plan-compilation-and-four-path-routing.md),
[ADR-0026](ADR-0026-use-a-deterministic-bounded-orchestrator.md)

## Context

The live rank request `ETF 중 순자산이 큰 상품 다섯 종목 알려줘` produced the
correct family, action, coverage, and result limit, but HCX omitted the unique
direct-alias `순자산 -> aum`. The ProposalV2 call was doing two different jobs:
understanding the request axes and copying execution inputs. A valid action did
not guarantee a complete executable contract.

ADR-0027 made required inputs explicit and allowed safe server-side locks, but
still left ambiguous slot selection in the same HCX response. That is only a
logical separation. This decision establishes a real runtime boundary.

## Decision

The resolver runs these ordered stages:

1. deterministic preparation produces literals, semantic candidates, entities,
   evidence, and references;
2. the normal HCX call resolves frames, ProductFamily, Action, semantic tags,
   entity roles, context links, and coverage, but no executable task slots;
3. the server selects one versioned `TaskInputContractDefinition` per resolved
   frame;
4. a deterministic `TaskSlotBinder` maps exact literals and unique canonical or
   direct-alias candidates into contract roles;
5. a completeness validator returns `complete`, `ambiguous`, or `blocked`; and
6. only `ambiguous` missing required roles may use one bounded slot-selection
   HCX call. That call can select only offered values for those missing roles and
   cannot change frames, axes, tags, entities, context, or coverage.

Entity role and identity grounding remain part of frame interpretation. Their
canonical entity-slot projection is server-generated from validated entity
hints; it is not an HCX-authored executable task-slot choice.

The conditional slot call consumes the one request-wide LLM repair allowance.
It is never made when no candidate exists, when ontology vocabulary is missing,
or when the frame axes are unresolved. Those cases enter Explore or Abstain.

Three independent axis calls remain an offline challenger. The production
normal path keeps one axis HCX call; the second call is exceptional and bounded.

## Consequences

- HCX can no longer omit an explicit `aum` task input after selecting `rank`.
- Required inputs are derived only after the action contract is known.
- A second call is observable and limited to genuine candidate ambiguity.
- Prompt and response schemas become smaller because executable slot branches
  leave the axis response.
- Candidate recall remains a separate promotion blocker: missing candidates
  cannot be recovered by asking HCX to invent a value.

## Verification Gates

- The axis response schema permits zero executable task-slot assignments only.
- Every resolved frame selects exactly one pinned task contract.
- Unique exact/direct-alias and literal bindings have 100% precision.
- Fast and Compose accept only complete contracts.
- Conditional slot selection makes at most one call and only for offered values.
- No-candidate cases make no second call and route to Explore or Abstain.
- The representative live rank request binds `sort_key=aum` and
  `result_limit=5` after one HCX call.
- All ADR-0022 promotion gates remain in force.

## Non-Goals

- Do not add raw-schema free SQL, model-authored execution recipes, or unbounded
  retries.
- Do not redesign QueryPlan's public shape or the evaluation API.
- Do not claim this change fixes candidate recall or executor correctness.
