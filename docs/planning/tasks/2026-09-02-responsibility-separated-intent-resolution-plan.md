# Responsibility-Separated Intent Resolution Implementation Plan

**Status:** Implemented and verified locally; model promotion remains gated by
the full held-out benchmark.

> **For agentic workers:** Use test-driven development and verification-before-completion for every implementation task.

**Goal:** Implement and verify `axis resolution -> server task contract -> task slot binding -> bounded ambiguity resolution` while preserving QueryPlan behavior.

**Architecture:** Keep ProposalV2 as the validated frame/context envelope, but make its production response schema axis-only. Add a versioned server task-contract registry and a `TaskSlotBinder` that enriches the validated resolution. Wrap both in a typed `TaskBoundIntentResolution`; let the compiler accept only complete pinned contracts. Add one optional schema-bounded HCX slot-selection call for eligible ambiguity.

**Tech Stack:** Python 3.12+, Pydantic v2, pytest, JSON registries, HCX-007 Structured Outputs.

**Spec:** [Responsibility-Separated Intent Resolution Design](../specs/2026-09-02-responsibility-separated-intent-resolution-design.md)

## Global Constraints

- Preserve one normal-path HCX call and one request-wide repair allowance.
- Keep entity grounding and context behavior compatible.
- Never auto-bind group, ambiguous, or fuzzy semantic matches.
- Never ask HCX to select a value not already offered by the server.
- Keep deterministic execution and the public QueryPlan/API shape unchanged.
- Do not commit credentials, live payloads, raw organizer data, or logs.

## Task 1: Add the versioned task-contract registry

**Files:**
- Create: `config/intent/task-input-contracts.v1.json`
- Create: `src/financial_agent/intent/task_contracts.py`
- Create: `tests/intent/test_task_contracts.py`

1. Write failing tests for all eight actions, unique IDs, registered SlotKind
   values, deterministic hash, and conditional relation/document requirements.
2. Implement the smallest strict loader and resolver.
3. Run `pytest tests/intent/test_task_contracts.py -q`.

## Task 2: Make the production HCX response axis-only

**Files:**
- Modify: `src/financial_agent/intent/prompt.py`
- Modify: `tests/intent/test_prompt.py`
- Modify: `tests/intent/test_service.py`

1. Write failing tests that the production response schema fixes
   `slot_assignments.maxItems` to zero while keeping axes, tags, entity hints,
   coverage, and context fields.
2. Update the prompt instruction and schema builder.
3. Verify old model slot assignments are rejected by the production schema.

## Task 3: Implement deterministic task-slot binding

**Files:**
- Create: `src/financial_agent/intent/task_binding.py`
- Create: `tests/intent/test_task_binding.py`
- Modify: `src/financial_agent/intent/service.py`
- Modify: `src/financial_agent/intent/__init__.py`

1. Write failing tests for `순자산 -> sort_key=aum`, native-Korean result
   limits, family applicability, ambiguous aliases, provenance, and readiness.
2. Implement typed contract/binding artifacts and conservative binder rules.
3. Enrich the canonical resolution only with validated deterministic bindings.
4. Return `TaskBoundIntentResolution` from the new service path while retaining
   the old validation method for compatibility tests.

## Task 4: Add bounded ambiguous-slot selection

**Files:**
- Create: `src/financial_agent/intent/slot_resolution.py`
- Create: `tests/intent/test_slot_resolution.py`
- Modify: `src/financial_agent/intent/service.py`

1. Write failing fake-adapter tests for eligible ambiguity, no-candidate block,
   offered-ID enforcement, one-call limit, and repair-budget use.
2. Implement a minimal prompt/schema containing only missing required roles and
   their offered candidate IDs.
3. Re-run the deterministic binder and completeness gate after selection.

## Task 5: Enforce task completeness in QueryPlan compilation

**Files:**
- Modify: `src/financial_agent/planning/compiler.py`
- Modify: `tests/planning/test_compiler.py`

1. Write failing tests for complete, registry-hash mismatch, and blocked task
   contracts.
2. Accept `TaskBoundIntentResolution`, validate its registry pin, and compile
   its enriched canonical resolution through the existing lowering code.
3. Preserve compatibility only where existing tests construct legacy fixtures.

## Task 6: Regression and live HCX verification

**Files:**
- Modify: `docs/planning/tasks/2026-09-02-hcx-semantic-coverage-schema-fix.md`
- Modify: this plan with measured results only.

1. Run focused intent and planning tests.
2. Run the full non-live suite.
3. Run one paced live HCX-007 request without a 20-second diagnostic cap.
4. Verify one model call, action `rank`, `sort_key=aum`, `result_limit=5`,
   complete task contract, and compiler eligibility.
5. Inspect the final diff and staged paths for secrets and raw output.

## Verification Record

- Focused Intent, held-out intent evaluation, Planning, and Orchestrator:
  `472 passed, 1 deselected`.
- Exported Intent schemas: freshness check passed.
- HCX-007 representative request:
  - provider success: yes;
  - elapsed: 9,285 ms;
  - model calls: 1;
  - action: `rank`;
  - families: `domestic_etf`, `overseas_etf`;
  - server task contract: `rank.v1`;
  - server bindings: `sort_key=aum`, `result_limit=5` literal ID;
  - readiness: `complete`;
  - conditional slot call: not used;
  - usage: 5,980 prompt, 409 completion, 6,389 total tokens.
- The unrestricted repository-wide collection was not measurable in the
  resolver-only virtual environment because optional ingestion dependencies
  `openpyxl` and `boto3` are absent. This is an environment limitation, not a
  passing or failing result for those suites.
- No credential, raw HCX response, organizer data, or live report was written
  into the repository.
