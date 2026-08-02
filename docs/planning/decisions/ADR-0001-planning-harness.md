# ADR-0001: Use a Project-Local Planning Harness

**Date:** 2026-08-02

**Status:** Accepted

## Context

The project needs durable product intent, trade-off rules, and decision history that survive long conversations and new agent sessions. The harness must constrain `what` and `why` without prescribing every implementation action to capable models.

## Decision

Use a project-local planning harness with three responsibilities:

- `docs/planning/HARNESS.md` stores the stable problem definition, ordered criteria, hard constraints, scope, and success measures.
- `docs/planning/decisions/` stores append-only architecture decision records.
- `docs/planning/tasks/` stores dated, task-specific plans for multi-step work.

`AGENTS.md` is the operating gate. It requires agents to read the harness and relevant decisions, state success criteria, receive approval, verify work, and follow the Git policy.

## Rejected Alternatives

### Conversation-only prompt

Rejected because important context can disappear across sessions, compaction, or collaborators, and past rejected alternatives would be repeatedly reconsidered.

### Immediate global Codex skill

Deferred because the process has not yet been tested across enough project tasks. Promoting an immature workflow globally would make later corrections harder and could impose financial-project assumptions on unrelated repositories.

## Consequences

- Planning intent and history become versioned project artifacts.
- Meaningful implementation has an explicit approval gate.
- Minor tasks can remain lightweight, while architectural work receives durable documentation.
- After the process succeeds on several tasks, a separate approved decision may promote the generic parts into a reusable global skill.
