# Intent Task Contract and Locked Binding Design

**Date:** 2026-09-02

**Status:** Approved design; implementation plan pending review

**Decision:** [ADR-0027](../decisions/ADR-0027-use-server-owned-task-contracts-and-locked-bindings.md)

## 1. Purpose

Make action classification and slot completeness one validated boundary. Every
selected intent frame must identify the server-owned task-input contract it is
trying to satisfy, preserve every explicit deterministic binding, and report
missing required inputs before QueryPlan routing.

The design fixes two observed problems together:

1. HCX can select an action without returning all slots required to execute it.
2. HCX is asked to re-select explicit values already resolved by deterministic
   literals or unique direct semantic aliases.

## 2. Assumptions, Constraints, and Non-Goals

### Assumptions

- One API request may contain multiple ordered clauses and therefore multiple
  intent frames, but no prior API request supplies conversational memory.
- ProductFamily, IntentType, ontology IDs, SemanticQueryCatalog IDs, and
  registered planning primitives remain authoritative.
- Candidate generation can provide exact literals and direct semantic aliases,
  but does not yet meet the global candidate-recall promotion gate.

### Constraints

- Keep one HCX Intent Resolver call on the normal path.
- Keep all model choices bounded to server-offered IDs.
- Keep QueryPlan execution order, policies, capabilities, and budgets
  deterministic and server-owned.
- Do not turn a missing or ambiguous value into a guessed binding.
- Preserve exact evidence and version provenance for every binding.
- Preserve the existing public API and external QueryPlan shape.

### Non-goals

- This change does not improve semantic candidate recall.
- It does not implement SQL, Graph, Keyword, Vector, similarity, or financial
  calculation executors.
- It does not redesign all financial filter, aggregation, or calculation
  semantics beyond the currently registered slot vocabulary.
- It does not promote three HCX calls to the normal path.

## 3. Responsibility Boundary

```text
Deterministic preparation
  normalize -> literals -> semantic candidates -> entity candidates
       |
       +-> lock candidates
       +-> compact task-contract definitions
       |
       v
One HCX call
  frames + axes + ambiguous bindings + entities + context + coverage
       |
       v
Deterministic finalization
  validate -> select task contract -> apply locks -> merge bindings
       -> apply approved defaults -> compute missing roles/readiness
       |
       v
ValidatedIntentResolution with ResolvedTaskContract per frame
       |
       v
QueryPlan compiler -> deterministic recipe -> Orchestrator
```

HCX owns interpretation of ambiguous language. The server owns vocabulary,
contracts, explicit locks, defaults, completeness, routing, and execution.

## 4. Contract Model

### 4.1 TaskInputContractDefinition

The versioned registry defines one or more task-input contracts for the eight
frozen IntentType values. A definition contains:

```yaml
contract_id: rank.v1
action_id: rank
required_slot_kinds: [sort_key, result_limit]
optional_slot_kinds:
  [sort_direction, metric, filter_operator, filter_value,
   period, currency, date_scope]
allowed_value_kinds:
  sort_key: [attribute, metric]
  result_limit: [result_limit]
  sort_direction: [sort_direction]
approved_default_policy_ids:
  sort_direction: rank-direction-from-language-or-desc.v1
result_shape: top_k
```

Definitions are loaded from one registry and projected into ResolverView. The
model never emits the definition body.

### 4.2 Initial contract matrix

This change formalizes the requirements already enforced by the planning
registry and its conditional document path.

| Action | Base required slots | Common optional slots |
| --- | --- | --- |
| `lookup` | none beyond validated family/entity scope | relation, document_topic, date_scope |
| `screen` | filter_value | metric, filter_operator, relation, period, currency, date_scope |
| `rank` | sort_key, result_limit | sort_direction, filter_operator, filter_value, period, currency, date_scope |
| `compare` | metric | comparison_basis, entity, relation, period, currency, date_scope |
| `aggregate` | metric | filter_operator, filter_value, period, currency, date_scope |
| `calculate` | metric | entity, period, currency, date_scope |
| `similar` | similarity_anchor | metric, filter_operator, filter_value |
| `explain` | none for base explanation | entity, relation, document_topic |

When `DOCUMENT_GROUNDED` selects the registered document explanation recipe,
`document_topic` becomes required. When a relation primitive is selected,
`relation` becomes required. Conditional requirements are resolved by the
server from validated tags and registered recipe compatibility, not by prompt
prose.

Future strengthening of screen field/operator/value grouping, aggregation
operators, or calculation operands requires a separately versioned contract;
this change does not silently invent new QueryPlan semantics.

### 4.3 LockCandidate

A request-scoped lock candidate contains:

```yaml
lock_candidate_id: lock-candidate-1
candidate_id: aum
eligible_slot_kinds: [metric, sort_key, comparison_basis]
evidence_ids: [evidence-aum]
match_type: direct_alias
source: semantic_candidate
policy_version: explicit-lock.v1
```

Literal candidates use the same shape with source `literal`, for example
`result_limit=5`.

Lock candidates are not yet canonical slot assignments because the selected
action determines the semantic role. Finalization binds them only after the
frame action and task contract are known.

### 4.4 ResolvedTaskContract

Every selected frame returns:

```yaml
frame_id: frame-1
contract_id: rank.v1
contract_registry_hash: <sha256>
action_id: rank
required_slot_kinds: [sort_key, result_limit]
optional_slot_kinds: [sort_direction, filter_operator, filter_value,
                      period, currency, date_scope]
bindings:
  - slot_kind: sort_key
    value_ids: [aum]
    source: deterministic_lock
    source_ids: [lock-candidate-1]
    evidence_ids: [evidence-aum]
  - slot_kind: result_limit
    value_ids: [literal-result-limit-1]
    source: deterministic_lock
    source_ids: [lock-candidate-2]
    evidence_ids: [evidence-five]
missing_required_slot_kinds: []
applied_default_policy_ids: []
readiness: complete
```

Allowed binding sources are `model`, `deterministic_lock`, `context`, and
`approved_default`. Every source is explicit and auditable.

## 5. Locking Algorithm

For each validated frame:

1. Select the applicable task-input contract from action and validated
   conditional semantics.
2. Collect lock candidates whose eligible roles intersect the contract's
   required or optional roles.
3. Reject candidates inapplicable to the selected product-family scope.
4. Group candidates by slot role and overlapping evidence.
5. Lock a role only when one exact literal or unique exact/direct-alias semantic
   candidate remains.
6. Apply validated slot mutations. UPDATE replaces a prior-context value;
   DELETE and DONTCARE prevent a lock; CARRYOVER remains opt-in.
7. Merge model and context bindings with locks.
8. Deduplicate identical bindings and reject conflicting locked values.
9. Apply only registered defaults and record their policy IDs.
10. Compute missing required roles and readiness.

The precedence order is:

```text
explicit current-frame locked/model evidence
  > valid explicit context update
  > permitted carryover
  > approved default
```

A model choice never overrides a conflicting current-frame lock. Ambiguous
candidates never become locks.

## 6. Model-Facing Changes

ResolverView gains compact task-contract definitions and lock candidates. The
system instruction explains that lock candidates are already resolved request
facts and must not be contradicted. The existing bounded slot proposal remains
the model's channel for ambiguous bindings.

The server does not require HCX to copy the full task contract. Copying
server-owned requirements would add tokens and create another consistency
failure. Instead, the validated resolver response attaches the exact contract
after cross-checking the selected action.

The response schema continues to close every offered ID set and rejects empty
slot values. Contract completeness is a deterministic semantic invariant, not
an array-shape assumption.

## 7. QueryPlan and Routing Changes

The compiler receives the resolved task contracts with the canonical frames and
checks their registry hash against its own loaded registry.

- `complete`: eligible for existing Fast/Compose decisions.
- `defaultable`: deterministic defaults are applied and recorded; compilation
  continues only after the resulting contract is complete.
- `blocked`: Fast and Compose are prohibited. Vocabulary coverage determines
  whether the result enters Explore or Abstain.

Archetype and primitive matching no longer discovers required-slot omissions as
the first line of defense. It revalidates completeness as a defense-in-depth
invariant.

## 8. Error Handling

Stable failures include:

- task contract missing for a selected action;
- action and selected contract mismatch;
- unknown task-contract registry hash;
- locked binding conflict;
- lock candidate not offered by the request view;
- lock candidate inapplicable to the selected family;
- blocked required input presented as Fast-ready; and
- QueryPlan primitive requirement not covered by the resolved task contract.

These are contract or deterministic-validation failures. They do not trigger an
unbounded model retry. Semantic ambiguity remains a semantic outcome.

## 9. One Call Versus Three Calls

The baseline remains one HCX call because the live representative request has
already measured roughly 29 seconds after schema reduction, and the earlier
smoke encountered timeouts and rate limiting.

The three-call challenger mirrors the published Shinhan Card axis split:

```text
parallel call A: ProductFamily/Domain
parallel call B: Action
parallel call C: Tags
then deterministic reconciliation and a separate slot-completion boundary
```

It is benchmarked only if the one-call contract design misses the existing
joint-frame or new required-slot gate. It may replace the baseline only through
a new ADR showing better held-out exactness with acceptable p95 latency, token
use, rate-limit rate, context-link exactness, and request-wide repair behavior.

Three calls are not assumed to fix slot completeness; both challengers use the
same server-owned task contracts and locked-binding algorithm.

## 10. Verification

### Contract tests

- All eight IntentType values have at least one registered task-input contract.
- Every contract uses registered SlotKind and value-kind IDs.
- Conditional document and relation requirements are deterministic.
- Resolver and compiler reject registry-hash drift.

### Lock tests

- `순자산` uniquely locks `aum` after `rank` selects `sort_key`.
- `다섯 종목` locks `result_limit=5`.
- `두 상품군` does not create a result-limit lock.
- Two competing metric candidates remain unlocked.
- An inapplicable family concept remains unlocked and fails validation.
- DELETE/DONTCARE prevents carryover or locking.
- A conflicting HCX value fails closed.

### Completeness and routing tests

- A rank frame missing either required slot is blocked before Fast matching.
- A complete rank frame enters the existing registered Fast archetype.
- Every supported action reports required, present, missing, and readiness.
- Document explanation requires document_topic.
- A relationship route requires relation.
- Compose uses the same completeness invariant as Fast.

### Integration and live tests

1. Run focused resolver, proposal, assembler/finalizer, planning registry,
   router, and compiler tests.
2. Run the complete non-live Intent Resolver and planning suites.
3. Run one paced HCX-007 request for `ETF 중 순자산이 큰 상품 다섯 종목
   알려줘` with the diagnostic timeout override.
4. Require action `rank`, preserved `sort_key=aum`, `result_limit=5`, no missing
   required roles, complete readiness, and a valid QueryPlan.
5. Only after that case passes, run a paced representative sample and record
   structured validity, required-slot exactness, joint-frame exactness, latency,
   token use, and provider errors without committing raw output.

## 11. Success Criteria

1. Every selected frame returns exactly one server-owned resolved task contract.
2. Explicit unique literals and direct aliases survive HCX omission without
   allowing ambiguous server inference.
3. Missing required inputs block Fast and Compose before primitive expansion.
4. The representative live rank case returns a complete `rank.v1` contract and
   valid Fast QueryPlan.
5. Existing strict ontology, entity-role, context, OOD, QueryPlan, and
   Orchestrator tests continue to pass.
6. No credential, raw HCX output, organizer data, or generated runtime artifact
   enters Git.
