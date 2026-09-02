# HCX Semantic Coverage Schema Fix

**Date:** 2026-09-02

**Status:** Approved and in progress

## Outcome

Align the HCX Structured Outputs schema with the accepted semantic-coverage
invariant so a `covered` frame cannot carry an OOD reason or evidence and an
uncovered frame must carry both.

## Assumptions and constraints

- Keep one normal-path HCX call and strict fail-closed server validation.
- Do not repair or silently accept an invalid semantic choice.
- Use only the JSON Schema subset supported by CLOVA Studio.
- Keep credentials, raw HCX output, organizer data, and live reports outside Git.
- Do not promote the resolver merely because this defect is fixed; every
  ADR-0022 promotion gate remains binding.

## Non-goals

- Do not redesign the intent ontology or QueryPlan contract.
- Do not change candidate recall, routing, SQL execution, or answer generation.
- Do not make the 300-second diagnostic timeout the production default.

## Verified root cause

The live HCX response selected `state=covered` together with an OOD reason and
evidence. The generated response schema allowed that cross-field combination,
while `FrameSemanticCoverage` correctly rejected it. The resulting frame-drop
error was a validation cascade, not a separate model failure.

## Implementation and verification

- [x] Add a failing schema-contract test for the exact covered/uncovered shapes.
- [x] Encode the invariant as two `anyOf` branches in the model-facing schema.
- [x] Reject empty slot assignments and hide slot kinds with no offered value.
- [x] Extract bounded native-Korean result limits such as `다섯 종목` and
      `세 개` without treating `두 상품군` as a result limit.
- [x] Run focused prompt, proposal, assembler, service, and CLOVA adapter tests.
- [x] Run the broader non-live Intent Resolver regression.
- [x] Run one sanitized live HCX case with the diagnostic timeout override.
- [x] Record latency, token use, schema validity, and semantic accuracy without
      committing raw model output.
- [x] Inspect the final diff for secrets, raw output, and scope drift.

## Live finding after the contract fix

The corrected schema produced a provider-success, ProposalV2-valid, fully
validated resolution. Reducing impossible slot branches lowered the request
schema from 26.9 KB to 17.8 KB in the first post-fix measurement and lowered
latency from 46.3 seconds to 29.0 seconds. After native-Korean literal support,
the model selected the correct action, family, entity type, coverage, context,
and result limit but omitted the unambiguous direct-alias `aum` sort key.

A prompt-v5 experiment explicitly required complete rank slots and minimal
evidence. It still omitted the sort key and selected every offered evidence ID,
so the experiment was removed. The remaining defect is architectural: the
array-shaped model proposal cannot require all action-specific slots, and the
server currently does not pre-resolve unambiguous explicit slots.

## Success criteria

1. The generated schema cannot represent the observed invalid combination.
2. Existing strict server validation remains unchanged.
3. Focused and broader non-live tests pass.
4. One live provider-success response passes ProposalV2 schema validation.
5. Any remaining semantic error is reported separately from schema validity.
