# ADR-0024: Use a Bounded Entity-Type Registry and Role-Aware Entity Hints

**Date:** 2026-09-01

**Status:** Accepted

**Amends:** [ADR-0023](ADR-0023-use-server-owned-intent-identities-and-explicit-semantic-coverage.md)
only at the ResolverView, ProposalV2, and v2 validation boundary. The public API,
QueryPlan, and one-call resolver architecture remain unchanged.

**Related:** [Entity Role Hardening Design](../specs/2026-09-01-intent-resolver-entity-role-hardening-design.md),
[ADR-0022](ADR-0022-use-ontology-grounded-intent-resolution.md),
[Planning Harness](../HARNESS.md)

## Context

The first ProposalV2 entity-selection implementation derived the entity types
offered to HCX only from request-local entity candidates, semantic concepts, and
relations. A scoped final review found that the expected frame type was not
expressible in 141 of the 155 semantic-executable held-out cases. The model was
therefore constrained to server-owned IDs but was often not offered the correct
ID.

The same implementation copied each frame's subject types into every entity
hint. For a relation such as
`FinancialProduct --managedBy--> AssetManager`, a valid AssetManager object was
then checked as if it were the FinancialProduct subject and failed closed with
`MODEL_INVALID_ENTITY_TYPE`.

These are contract defects, not evidence that HCX cannot classify entity types.
The answer choices and the subject/object roles must be corrected before live
model quality can be measured.

## Decision

### Offer the complete registered entity-type vocabulary

`ResolverViewV2` exposes the exact, sorted set of entity-type IDs compiled from
the semantic catalog. The current catalog contains 20 registered types. HCX may
select only from this list.

The list is bounded by the versioned catalog and build manifest. It is not a
free-form model vocabulary and is not expanded from user text. Request-local
candidate generation continues to control entity identities, semantic concepts,
relations, literals, references, and evidence.

### Separate frame subject types from entity-hint roles

`frame.entity_type_ids` describes the primary entity or relation subject of the
atomic frame.

Each v2 entity hint separately records:

- a bounded semantic role: `frame_subject` or `relation_object`;
- the expected entity-type IDs for that role;
- a relation ID when the role is `relation_object`; and
- the server-offered candidate entity IDs and selected candidate IDs.

`relation_object` requires exactly one relation ID selected by the same frame.
Its expected types must be compatible with the relation range. `frame_subject`
does not carry a relation ID and its expected types must be compatible with the
frame subject types.

### Validate relation direction explicitly

For every selected relation:

- frame subject types are validated against the relation domain;
- `frame_subject` hints are validated against the frame subject types;
- `relation_object` hints are validated against the selected relation range;
- a selected entity candidate is validated only against its hint's expected
  types and the role-specific endpoint; and
- subject and object endpoints are never silently interchanged.

The deterministic assembler copies these bounded choices. It does not infer a
missing role, choose a relation, or replace a type.

### Prove reachability before model accuracy

Promotion evidence adds a contract-level reachability prerequisite: every gold
frame type in the 155 semantic-executable held-out cases must be expressible by
the generated ResolverView and HCX schema.

The promotion conformance test must exercise the real boundary from ResolverView
through the generated schema, ProposalV2, assembler, validation, and evaluation.
Injecting expected frames directly into `EvaluationPrediction` is not sufficient
evidence that the model-facing contract is attainable.

## Consequences

### Positive

- a registered correct type cannot disappear because an earlier request-local
  candidate stage omitted it;
- the model still cannot invent ontology types or entity IDs;
- relation domain and range semantics are preserved;
- Phase 2 receives explicit entity roles rather than reverse-engineering them;
- schema reachability and model accuracy become separately measurable.

### Costs

- the HCX schema exposes all 20 registered type IDs on each request;
- ProposalV2 and the v2 draft/resolution contracts require a versioned entity
  role field;
- v2 schemas and held-out projections must be refreshed;
- stored v2 evaluation artifacts need to preserve the new fields.

## Rejected Alternatives

### Expand only request-local type candidates

Rejected because a candidate-generation miss can again remove the correct type
before HCX runs. It optimizes a small prompt at the cost of an unreachable
correct answer.

### Derive every frame type from ProductFamily

Rejected because domain OOD, multi-role products, relationship queries, and
ontology distinctions such as RepresentativeFund versus FundShareClass cannot
be represented faithfully by a single family-to-type mapping.

### Remove entity-type constraints

Rejected because it restores free-form model identity, weakens ontology
validation, and makes relation direction errors harder to detect.

## Preserved Decisions

- one normal-path HCX call;
- server-owned candidate, evidence, reference, and artifact IDs;
- fail-closed semantic and context validation;
- byte-compatible v1 artifact schemas;
- unchanged QueryPlan, public API, database schema, and Orchestrator boundary;
- all ADR-0022 promotion gates.

## Non-Approval

This ADR does not approve QueryPlan compilation, orchestration, database
migration, deployment, model promotion, push, or merge operations.
