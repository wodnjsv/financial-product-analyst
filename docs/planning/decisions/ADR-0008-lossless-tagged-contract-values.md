# ADR-0008: Use Lossless Tagged Values at the Stage 01 Contract Boundary

**Date:** 2026-08-18

**Status:** Accepted

**Related:** [Runtime Contracts](../architecture/RUNTIME_CONTRACTS.md), [Stage 01 Closure Hardening Design](../specs/2026-08-18-stage-01-closure-hardening-design.md), [ADR-0007](ADR-0007-normalized-evidence-ledger-structured-answer-plan.md)

## Context

The initial `ScalarValue` and `ContractValue` aliases used an untagged union of string, integer, Decimal, Boolean, date, UTC datetime, null, and a flat tuple. Pydantic could validate those native Python values, but their JSON representation was ambiguous. Decimal, date, and datetime values became JSON strings and were restored through the ordinary string branch. A date-looking string and an actual date, or a Decimal and a numeric-looking string, could therefore collide in round-trip persistence and canonical hashing.

Stage 02 must persist these values in PostgreSQL JSONB. Deferring the distinction to a database-only codec would leave QueryPlan, ToolResult, Evidence, Calculation, Claim, hashes, and persisted artifacts with two competing representations before the public Stage 01 contract is frozen.

## Decision

- Stage 01 owns one lossless tagged value representation for every `ScalarValue` and `ContractValue` field.
- The scalar tags are `null`, `string`, `integer`, `decimal`, `boolean`, `date`, and `datetime`; `tuple` contains an ordered flat list of tagged scalar items.
- The eight public frozen Pydantic models and the native encode/decode functions live in `financial_agent.contracts`.
- Decimal JSON payloads are canonical plain strings. Equivalent finite Decimal values have one wire representation; exponent notation, leading zeros, trailing fractional zeros, negative zero, NaN, and infinity are not valid wire values.
- Raw JSON is validated with `model_validate_json`. Python construction is strict and uses typed Python values plus `encode_contract_value` for polymorphic fields.
- Contract artifacts are canonically hashed from validated models. Schema-less Mapping input remains limited to JSON-native values and cannot carry native Decimal, date, datetime, Enum, or tuple objects.
- `AtomicClaim.value` alone remains field-nullable so qualifier-only limitation and policy Claims can represent the absence of a value target. A tagged `NullValue` remains an explicit observation and is not a factual AtomicClaim value.
- Stage 02 stores and validates the exact Stage 01 tagged JSON shape. It must not introduce a second persistence-only Python TaggedValue model or infer types from predicates, fields, or table context.

The official five-string evaluation API response is unchanged.

## Rejected Alternatives

### Keep the untagged union and rely on Pydantic union order

Rejected because JSON has already erased the native type before union selection. Reordering branches cannot reliably distinguish a date-looking or Decimal-looking string from intentional text.

### Add tags only in the PostgreSQL repository

Rejected because runtime hashes, fixtures, LLM structured output, and pre-persistence artifacts would still use a different ambiguous representation. Two codecs could also disagree about Decimal normalization, Boolean-versus-integer identity, or tuple items.

### Infer types from predicates or metric registries

Rejected because a value would not be self-describing and could change meaning when copied, replayed, or validated outside that registry. It would also couple generic runtime contracts to later ontology and storage state.

### Serialize every value as a string

Rejected because it loses Boolean, integer, null, temporal, and numeric identity and makes comparison and calculation depend on contextual parsing.

## Consequences

### Positive

- JSON and JSONB round trips preserve exact scalar identity without contextual inference.
- Canonical hashes distinguish real Decimal/date/datetime values from look-alike strings.
- Mixed tuples retain an independent tag for every item.
- JSON Schema can describe the portable tagged structure while Pydantic remains authoritative for cross-field semantics.
- Stage 02 can enforce one frozen wire format instead of maintaining a duplicate codec.

### Costs and risks

- Existing contract fixtures and all polymorphic value fields require a one-time wire migration before the 1.0 freeze.
- Deterministic components must explicitly encode native values on write and decode them for calculation or comparison.
- Tagged JSON is more verbose than an untagged scalar.
- Decimal validation and serialization require focused mode-aware Pydantic code and parity tests.

## Preserved Decisions

- The fixed data cutoff remains `2026-07-11`.
- Financial arithmetic continues to use Decimal rather than binary floating point.
- Contract models remain immutable, versioned, and closed to unknown fields.
- Pydantic runtime validation remains authoritative for semantic and cross-artifact invariants.
- Claim Gate Registry compatibility remains mandatory in the later release path and is not implemented by this decision.
