# ADR-0023: Use Server-Owned Intent Identities and Explicit Semantic Coverage

**Date:** 2026-09-01

**Status:** Proposed — direction approved in conversation; written design pending review

**Amends:** [ADR-0022](ADR-0022-use-ontology-grounded-intent-resolution.md)
only at the model-facing proposal boundary. The external `RequestContext → Intent
Resolver → QueryPlan` architecture remains unchanged.

**Related:** [Intent Resolver Contract Hardening Design](../specs/2026-09-01-intent-resolver-contract-hardening-design.md),
[Intent Resolver Design](../specs/2026-08-31-intent-resolver-design.md),
[Planning Harness](../HARNESS.md)

## Context

HCX-007 live preflight proved that native Structured Outputs can produce a
schema-shaped response, but also exposed three failure modes in the Phase 1
boundary:

- model-created frame, reference, link, and slot IDs can disagree across fields;
- ProductFamily and IntentType IDs are offered without bounded Korean axis
  definitions in `ResolverView`;
- vocabulary and domain OOD have no direct per-frame coverage field, so an
  unsupported property can remain `resolved`.

Prompt-only elaboration was tested and rejected. It reduced strict validation
from 10 of 12 cases to 8 of 12 while failing to fix context and OOD behavior.
The boundary therefore needs stronger structure rather than more prose.

## Decision

### Separate model proposal from server-owned draft

HCX emits a new strict `IntentResolutionProposalV2`. It contains bounded semantic
choices and positional references, but no server-owned artifact IDs and no raw
character offsets.

The deterministic server assembler:

1. validates all selected enum, candidate, evidence, and ordinal values;
2. assigns frame, slot, reference, link, mutation, and evidence IDs;
3. resolves positional references to those IDs;
4. produces the existing ID-rich `IntentResolutionDraft`; and
5. passes that draft through the existing semantic and context validators.

The assembler may canonicalize representation but may not invent a missing
semantic choice, choose an antecedent, or replace an unknown concept.

### Add bounded axis definitions to ResolverView

`ResolverView` includes short ProductFamily and IntentType definitions with
Korean preferred labels and bounded surface forms. IDs remain authoritative in
the existing enums; Korean language data remains authoritative in the NLU
overlay. The projection joins those authorities and does not create a new
hand-maintained intent vocabulary.

### Make evidence server-owned

Normalization and candidate generation produce request-scoped evidence
candidates containing the exact segment, text, and Unicode offsets. HCX selects
only evidence candidate IDs. It does not calculate offsets or copy evidence text.

### Add explicit frame semantic coverage

Each proposed frame includes one of:

- `covered`: every requested semantic needed for the frame is mapped;
- `partial`: at least one requested semantic is mapped and at least one is not;
- `unmapped`: the operation or domain cannot be grounded.

`partial` and `unmapped` require server-offered evidence IDs and a bounded reason:
`lexical_ood`, `domain_ood`, `unsupported_operation`, or
`missing_critical_semantic`. They create a blocking issue and cannot qualify for
a later Fast route. Combination OOD remains `covered` when all constituent IDs
are registered.

Policy tags remain separate from semantic coverage. Exact policy cues from the
NLU overlay are deterministically enriched; downstream policy handling, not the
resolver, selects the final answer disposition.

### Preserve one HCX call and fail-closed validation

The normal path still uses one HCX structured call. Unknown candidates, unknown
evidence, invalid ordinals, forward dependencies, cycles, and incompatible slot
values fail closed. Resolver validation is not relaxed to improve coverage.

## Consequences

### Positive

- cross-field ID typos can no longer create invalid context graphs;
- the model chooses semantics instead of performing bookkeeping;
- character-offset arithmetic leaves the model boundary;
- lexical, domain, and combination OOD become distinguishable inputs to Phase 2;
- axis definitions reach HCX as bounded data rather than system-prompt prose.

### Costs

- one additional internal proposal contract and deterministic assembler are
  required;
- prompt, schema, proposal, and adapter versions must be bumped together;
- evaluation fixtures need v2 proposal and assembled-draft projections;
- v1 and v2 require a shadow comparison before promotion.

## Rejected alternatives

- **Longer system prompts:** empirically reduced validation and did not solve OOD.
- **Repair arbitrary model IDs after validation:** unsafe when multiple targets
  exist and obscures the original model error.
- **Let the model continue emitting offsets:** unreliable for Korean Unicode
  spans and unnecessary when the server already owns the source text.
- **Fully deterministic intent parsing:** current candidate recall is below the
  promotion gate and Korean compound/context interpretation still benefits from
  one bounded HCX call.

## Preserved decisions

- QueryPlan and the public API remain unchanged.
- Phase 2 owns QueryPlan compilation and Fast/Compose/Explore/Abstain routing.
- Phase 3 owns orchestration and execution scheduling.
- No cross-request memory, personalized advice, order execution, or unsupported
  forecasts are added.
- All ADR-0022 promotion gates remain in force.

## Non-approval

This ADR does not approve implementation, migration, model promotion, Phase 2
compiler work, Orchestrator work, deployment, or push/merge operations.
