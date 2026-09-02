# Responsibility-Separated Intent Resolution Design

**Date:** 2026-09-02

**Status:** Approved for implementation

**Decision:** [ADR-0028](../decisions/ADR-0028-separate-axis-resolution-from-task-slot-binding.md)

## Outcome

Turn one Korean request into an executable, auditable task contract without
asking HCX to both understand the request and copy deterministic values.

```text
Question
  -> deterministic candidates
  -> HCX axis/frame/context resolution
  -> server intent + TaskInputContract selection
  -> deterministic TaskSlotBinder
  -> completeness gate
       complete  -> Fast / Compose
       ambiguous -> one bounded slot HCX call -> revalidate
       blocked   -> Explore / Abstain
```

## Responsibility Matrix

| Concern | Owner |
| --- | --- |
| normalization, literals, aliases, entity candidates | deterministic preparation |
| frame split, ProductFamily, Action, tags, coverage, references | axis HCX call |
| entity semantic role and bounded identity choice | axis HCX call + server validation |
| intent identity and task contract | deterministic matcher |
| required/optional role definitions and defaults | versioned server registry |
| exact and unique task-slot values | deterministic binder |
| ambiguous missing required slot | optional bounded slot HCX call |
| primitive selection, routing, scheduling, SQL/Graph/Search/Calculation | deterministic compiler/orchestrator/executors |

## Task Contract Registry

The initial registry derives its required slots from the accepted planning
primitives and adds only action-level optional roles already supported by the
canonical SlotKind vocabulary.

| Action | Required |
| --- | --- |
| lookup | none |
| screen | filter_value |
| rank | sort_key, result_limit |
| compare | metric |
| aggregate | metric |
| calculate | metric |
| similar | similarity_anchor |
| explain | none; document_topic when DOCUMENT_GROUNDED |

A selected relation makes `relation` required. Registry IDs, versions, hashes,
required roles, and readiness are returned beside the canonical resolution.

## Deterministic Binding Rules

The binder works per frame and only over evidence located in that frame's
segments.

1. An exact literal maps by kind: result limit, sort direction, period,
   currency, date, or filter value.
2. A semantic candidate maps only when its concept kind is allowed by the
   contract role.
3. `canonical_id` and `direct_alias` are lock-eligible. Group, ambiguous, and
   trigram candidates are never auto-locked.
4. A role is locked only when one eligible value remains and its product-family
   applicability covers every selected family.
5. One mention cannot silently populate competing roles. Action-specific
   priority maps `rank` concepts to `sort_key`, compare/aggregate/calculate to
   `metric`, and similarity anchors to `similarity_anchor`.
6. Evidence spans, mention IDs, candidate IDs, match kinds, and policy version
   are retained in the returned binding provenance.
7. Existing explicit context mutations are applied before readiness is final.

## Conditional Slot Resolution

An exceptional second HCX call is allowed only when all are true:

- frame, family, action, tags, context, and coverage already validated;
- at least one required role is missing;
- that role has two or more bounded, applicable offered values;
- the role is not missing because the ontology lacks vocabulary; and
- the request-wide repair allowance is unused.

Its schema contains only `(frame_id, slot_kind, selected_value_ids)` for the
specific missing roles. Returned IDs are revalidated and merged; any attempt to
change other state is impossible by schema. Failure leaves the contract blocked.

## Runtime Artifacts

`TaskBoundIntentResolution` wraps the existing validated resolution and adds:

- task-contract registry version and hash;
- one `ResolvedTaskContract` per frame;
- canonical bindings with source provenance;
- missing required slots and readiness;
- conditional-slot-call usage.

The wrapped canonical resolution contains the server-bound `SlotAssignment`
values so the existing QueryPlan lowering remains stable. QueryPlan compilation
also verifies the task-contract registry hash and refuses incomplete contracts.

## Success Criteria

1. Axis HCX output cannot select executable task slots.
2. The representative rank request becomes complete with one HCX call.
3. Ambiguous offered values use at most one additional bounded call.
4. Vocabulary-missing requests do not call HCX again.
5. Fast/Compose never receive an incomplete contract.
6. Existing context, entity-role, QueryPlan, router, and orchestrator regressions
   remain green.
