# ADR-0053: NVIDIA intent resolution for personal local use

- Date: 2026-10-02
- Status: Accepted
- Approval: The user explicitly requested replacing HCX with NVIDIA API in the
  existing intent resolver and improving its identified shortcomings.
- Scope: ADR-0050 personal profile. This supersedes the historical HCX-only
  transport and V3 shadow-only use for this bounded local entry point. It does
  not promote the competition deployment or unrelated executors.

## Decision

Reuse the existing semantic catalog, source-owned mention IDs, exact locks,
entity candidates, typed proposal validation and deterministic routing. Add an
NVIDIA adapter behind the existing invocation boundary; share provider-neutral
result contracts rather than couple the resolver to the historical adapter.
Use the previously tested GLM-5.3-Flash model with configurable NVIDIA model ID.
Provider JSON mode is not a substitute for local schema and semantic validation.

Accept a raw question through a tracked local CLI/service. Discover bounded,
source-grounded catalog entity mentions before the semantic call, bind candidates
to actual dataset IDs and expose product families, operations, conditions,
ambiguities and execution limitations. Never silently route an overseas ETF,
bond, public fund or an unsupported request to a domestic ETF example query.
Only a supported, fully validated route may execute; incomplete interpretation
must remain explicit and must not run a guessed query.

Do not let the model generate SQL, financial values, physical bindings or
unregistered defaults. Keep one normal semantic call and the existing mutually
exclusive repair/judge allowance under an overall deadline. Keep credentials
and hidden reasoning out of artifacts. Original data and source-owned local
document output remain unchanged.

## Alternatives and reasons

- Keep the three-field experimental classifier: rejected because it cannot
  represent product-family scope, entity roles or ambiguous/unsupported input.
- Replace the existing resolver with a new general agent: rejected because it
  discards tested catalogs, semantic contracts and deterministic validation.
- Add an unconditional model call for entity extraction: rejected initially
  because catalog-grounded discovery can provide existing names without an
  additional model hop. Discovery gaps must be visible rather than guessed.
- Activate the full Graph/competition stack: unnecessary for the personal
  PostgreSQL use case and outside this change.

## Verification and limitations

Add transport tests for errors, deadlines and malformed results; entity mention
tests for source ranges, overlapping names and bounded ambiguity; and natural
question integration tests for four-family routing, named products, compound
conditions and refusal to execute unsupported or ambiguous requests. Run the
relevant existing resolver/planning tests before broader offline verification.
Use a small read-only local DB/NVIDIA probe without logging keys or reasoning.
Model-specific live behavior and missing execution bindings must be reported
separately from interpretation correctness; synthetic tests do not certify all
possible natural-language questions.
