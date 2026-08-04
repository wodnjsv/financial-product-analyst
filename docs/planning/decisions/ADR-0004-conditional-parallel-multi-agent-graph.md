# ADR-0004: Use a Conditional-Parallel Multi-Agent Graph

**Date:** 2026-08-04

**Status:** Accepted

**Supersedes:** ADR-0003 only where it treated multi-agent orchestration as an optional future implementation choice

## Context

The competition evaluates more than data retrieval. The system must quickly understand natural-language intent, coordinate heterogeneous product schemas, perform correct calculations, prevent hallucination, expose evidence, and handle ambiguous or unsupported questions safely.

ADR-0003 correctly framed the product as an internal financial-product desk Copilot but treated multi-agent orchestration as optional and rejected a general-purpose autonomous platform. The user clarified that a well-designed multi-agent architecture is a core competition differentiator. The project therefore needs a purpose-built architecture that gains specialization and parallelism without adding unbounded autonomy, correlated hallucinations, or unnecessary latency.

HyperCLOVA X Chat Completions v3 supports Function calling and Structured Outputs. Structured Outputs can enforce a supported JSON Schema but cannot be requested in the same call as Function calling or inference, so a single model call cannot safely perform typed planning and tool execution together. This constraint favors a two-stage design: agents produce validated plans, and application code dispatches tools.

## Decision

Use a **purpose-built, conditional-parallel multi-agent graph** controlled by a deterministic application orchestrator.

### Control plane

- The application orchestrator is the only component that may schedule agents, call tools, manage deadlines, or retry work.
- Agents cannot invoke other agents recursively or create new execution branches.
- Every transition uses a versioned, schema-validated contract.
- One bounded repair attempt is allowed for a failed plan or answer draft. A second failure produces clarification, limitation, a partial answer, or abstention.

### Agent roles

1. **Intent Planner Agent:** Converts the user question into a domain-neutral `QueryPlan`, including ambiguity and required product families.
2. **Product Specialist Agents:** Domestic bond, domestic ETF, overseas ETF, and public fund specialists convert the common intent into family-specific `DomainExecutionPlan` objects. Only relevant specialists run, and independent specialists run concurrently.
3. **Cross-Product Comparator:** Runs only when multiple product families or incompatible-seeming metrics require semantic mapping and a disclosed comparison decision.
4. **Evidence and Policy Verifier:** Independently checks result-to-source coverage, comparison validity, missingness, exclusions, and prohibited claims.
5. **Answer Synthesizer:** Composes the final response only from a verified `EvidenceBundle` and cannot retrieve new facts.

### Deterministic services

- The data engine owns lookup, filtering, sorting, ranking, aggregation, and financial calculations.
- The comparison rules engine owns deterministic checks for period, unit, currency, tax basis, and aggregation population.
- The evidence ledger binds values and claims to table IDs, product IDs, fields, units, dates, formulas, and exclusion reasons.
- The final claim gate rejects unsupported factual claims before the API response is released.

### Execution policy

- Simple exact lookup takes a fast path through the Planner, one relevant Specialist, deterministic retrieval, verification, and synthesis.
- Single-family analytical queries invoke one Specialist plus the required deterministic tools.
- Cross-product queries fan out only to the relevant Specialists, merge their tool results, and invoke the Comparator before verification.
- No Agent is invoked merely to make the architecture look more agentic. Each invocation must have measurable value for correctness, latency, evidence, or failure handling.

## Reasons

- Conditional routing avoids the latency and cost of invoking all Specialists for every question.
- Parallel execution shortens the critical path for cross-product questions.
- Product-specific prompts and contracts isolate heterogeneous schema knowledge.
- A deterministic orchestrator prevents recursive delegation, tool-call loops, and uncontrolled retry behavior.
- Typed state and deterministic calculations stop free-form model text from becoming executable financial logic.
- Independent verification and a final claim gate reduce unsupported factual answers and make failure behavior testable.
- The design uses the available HyperCLOVA X Structured Outputs capability without coupling typed planning to model-directed tool execution.

## Rejected Alternatives

### Sequential multi-agent chain

Rejected as the primary architecture because each model call extends the critical path and an early mistake propagates through every later Agent. Sequential stages remain only where dependencies require them.

### Debate-and-vote Agent swarm

Rejected because multiple Agents using the same model can repeat or reinforce the same unsupported assumption. Voting also increases latency and token cost without creating authoritative financial evidence.

### One generalist Agent with unrestricted Function calling

Rejected because a single prompt would own intent parsing, schema selection, tool choice, calculations, and explanation. This creates an oversized failure domain and makes typed planning, deterministic testing, and stage-level latency analysis harder.

### Always invoke all four product Specialists

Rejected because it wastes latency and cost on irrelevant domains and increases the amount of state the verifier must inspect.

## Consequences

### Positive

- The architecture directly demonstrates orchestration, specialization, parallelism, grounding, and risk control in the competition proposal.
- Each Agent and contract can be tested independently with synthetic fixtures and gold query plans.
- Fast and complex paths have distinct, measurable latency budgets.
- Failures are localized to a stage and produce a structured limitation instead of an unconstrained answer.

### Costs and risks

- The project must maintain several prompts, schemas, contract versions, and stage-level tests.
- Parallel calls can hit provider quotas or rate limits and require bounded concurrency.
- The Verifier uses the same model family and therefore cannot be treated as independent factual evidence; deterministic checks remain authoritative.
- Structured Outputs and Function calling cannot be combined in one HyperCLOVA X request, so the application orchestrator must perform explicit dispatch between model calls.
- The provisional latency targets require measurement and may force prompt, token, cache, or path reductions.

## Preserved Decisions

- ADR-0003's internal financial-product desk Copilot product frame remains in force.
- ADR-0001's planning gate and ADR-0002's repository-data policy remain in force.
- Personalized investment advice, order execution, unsupported forecasting, and live market-data replacement remain out of scope.

## References

- [CLOVA Studio Structured Outputs](https://api.ncloud-docs.com/docs/en/clovastudio-chatcompletionsv3-so)
- [CLOVA Studio Function calling](https://api.ncloud-docs.com/docs/en/clovastudio-chatcompletionsv3-fc)
- [Mirae Asset AI Festival official FAQ](https://miraeassetfesta.com/notice)
