# Intent Resolver Entity Role Hardening Design

**Date:** 2026-09-01

**Status:** Approved design; implementation pending

**Scope:** Stage 06 Phase 1 entity-type reachability and relation-role hardening

**Decision:** [ADR-0024](../decisions/ADR-0024-use-bounded-entity-type-registry-and-role-aware-entity-hints.md)

## 1. Purpose

Correct the two load-bearing defects found after the ProposalV2 contract
hardening:

1. the correct frame entity type is unreachable in 141 of 155
   semantic-executable held-out cases; and
2. a valid relation object is validated as if it had the frame subject type.

The change must make every registered correct type expressible while retaining
server-owned identities, one HCX call, deterministic validation, and exact v1
compatibility.

## 2. Assumptions

- The versioned semantic catalog is authoritative for entity-type IDs and
  currently contains 20 types.
- `frame.entity_type_ids` represents the atomic frame's primary entity or
  relation subject.
- A request-local entity candidate retains its server-owned entity ID and one or
  more catalog ontology types.
- Relation definitions retain authoritative subject and object endpoint types.
- Phase 2 will consume explicit entity roles; it must not infer relation
  direction from surface order.

## 3. Non-goals

- QueryPlan compilation, Fast/Compose/Explore/Abstain routing, or Orchestrator
  scheduling;
- new ontology classes or relations;
- changes to entity retrieval or candidate scoring;
- database schema or migration changes;
- personalized advice, order execution, or model promotion;
- general prompt optimization unrelated to entity types and roles.

## 4. Alternatives

### A. Complete bounded type registry plus role-aware hints — chosen

Expose all 20 catalog type IDs and distinguish frame subjects from relation
objects in ProposalV2. This adds a small fixed schema cost and structurally
eliminates missing answer choices.

### B. Request-local type expansion

Add parent, family, and relation endpoint types only when they can be derived
from the request. This produces a smaller schema but keeps correctness dependent
on candidate recall and can recreate the same unreachable-answer defect.

### C. Deterministic family-to-type mapping

Derive frame types after the model selects ProductFamily. This is fast for the
common four families but cannot represent domain OOD, multi-role products, or
finer ontology distinctions without a growing rule table.

## 5. Contract Changes

### 5.1 ResolverViewV2

Add one authoritative projection:

```text
entity_type_ids[]
  source: SemanticCatalogSnapshot.entity_type_ids
  ordering: ascending ID
  cardinality: 1..20 for the current catalog
```

`offered_entity_type_ids(view)` returns this explicit field. It no longer derives
the answer set from request-local entity, concept, or relation candidates.

The view invariant requires exact equality with the compiled catalog projection
used to build the manifest. Unknown, missing, duplicate, or unsorted IDs fail
before the HCX call.

### 5.2 ProposalV2 entity hint

```text
ProposedEntityHint
  semantic_role: frame_subject | relation_object
  relation_id: [] | [registered_relation_id]
  expected_entity_type_ids: [registered_entity_type_id, ...]
  mention_id: [] | [server_offered_mention_id]
  candidate_entity_ids[]
  selected_candidate_ids[]
```

Invariants:

- `expected_entity_type_ids` is non-empty and a subset of
  `ResolverViewV2.entity_type_ids`.
- `frame_subject` has an empty `relation_id`.
- `relation_object` has exactly one `relation_id`.
- The relation ID must be selected in a `relation` slot of the same frame.
- Candidate and selected IDs remain bounded by the selected mention group.
- A selected candidate must be compatible with at least one expected type.

### 5.3 DraftV2 and validated resolution

Introduce a v2-only role-aware entity hint contract. Preserve the existing v1
`EntityHint` and its serialized schema byte-for-byte.

The assembler copies the role, relation ID, expected types, candidate IDs, and
selected IDs from the proposal after bounds validation. It may assign canonical
hint IDs but may not choose or replace any semantic value.

## 6. Validation Flow

```text
frame.entity_type_ids
  └─ validate against complete registered type set
       └─ for selected relation: validate against relation domain

entity_hint(frame_subject)
  ├─ expected types compatible with frame.entity_type_ids
  └─ selected candidate compatible with expected types

entity_hint(relation_object)
  ├─ relation selected by same frame
  ├─ expected types compatible with relation range
  └─ selected candidate compatible with expected types
```

Endpoint compatibility uses the catalog's class-ancestor closure. A subtype is
valid for an allowed parent. Domain and range are evaluated independently.

Failures remain bounded contract errors:

- unknown type, relation, mention, or entity ID: `MODEL_UNKNOWN_ID`;
- missing or contradictory role fields: `MODEL_SCHEMA_INVALID`;
- selected entity incompatible with the hint: `MODEL_INVALID_ENTITY_TYPE`;
- subject incompatible with relation domain or object incompatible with range:
  `MODEL_INVALID_RELATION`.

These errors may use only the existing request-wide repair allowance.

## 7. Prompt and Structured Output

The generated HCX schema uses only enums from the ResolverView:

- frame type enum: all 20 registered `entity_type_ids`;
- expected hint type enum: the same registered set;
- hint role enum: `frame_subject`, `relation_object`;
- hint relation enum: request-offered relation IDs.

The prompt states that frame types describe the analysis subject, while a named
organization, issuer, manager, index, market, or other related entity must be
represented as `relation_object` when it fills the selected relation's object
endpoint.

No free-form type or relation string is accepted.

## 8. Evaluation and Promotion Evidence

Evaluation separates three layers:

1. **Type reachability:** every expected frame type in all 155
   semantic-executable cases is contained in the real generated schema.
2. **Contract conformance:** a gold-equivalent bounded ProposalV2 can traverse
   assembler and validation without hand-injected frames.
3. **Model accuracy:** live HCX selects the correct frame types and entity roles.

The existing test that copies `case.expected_frames` directly into predictions
does not prove layers 1 or 2 and cannot by itself establish attainable promotion
evidence.

Required cases include:

- domestic/overseas ETF → ETF;
- public fund → PublicFund;
- domestic bond → FinancialProduct;
- vocabulary/domain OOD frames with explicit partial/unmapped coverage;
- `ETF --managedBy--> AssetManager`;
- inverse endpoint and incompatible object negative cases;
- subclass compatibility and multi-role product cases.

## 9. Success Criteria

- expected frame type reachability is `155/155` semantic-executable cases;
- no generated frame type enum is empty while the catalog is valid;
- a real ProposalV2 selecting an AssetManager as `managedBy` object passes;
- a subject/object reversal or incompatible candidate fails closed;
- generated schema, assembler, validator, stored v2 artifacts, and evaluator
  preserve entity role and expected types;
- v1 schemas and canonical serialization remain byte-identical;
- focused intent/evaluation tests, schema freshness, and broad offline regression
  pass;
- no QueryPlan, public API, migration, credential, organizer-data, or raw-live
  output drift is introduced.

After all offline criteria pass, the authorized 12-case HCX smoke may run at
one-second pacing. Provider success, schema validity, semantic exact match,
context, and OOD remain separate metrics. A provider failure is not a semantic
miss, and a successful smoke does not override any ADR-0022 promotion gate.

## 10. Expected Files

- `src/financial_agent/intent/view.py`
- `src/financial_agent/intent/proposal.py`
- `src/financial_agent/intent/prompt.py`
- `src/financial_agent/intent/assembler.py`
- `src/financial_agent/intent/draft.py`
- `src/financial_agent/intent/resolution.py`
- `src/financial_agent/intent/validation.py`
- `src/financial_agent/intent/evaluation.py`
- generated v2 schemas
- focused intent and evaluation tests

Changes outside these files require a new scope decision. In particular, no
database migration, QueryPlan, Orchestrator, or public API file is authorized.
