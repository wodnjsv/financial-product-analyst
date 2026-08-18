# Stage 01 Closure Hardening Design

**Date:** 2026-08-18

**Status:** Approved amended design; implementation remains gated on the dedicated plan

**Related:** [Planning Harness](../HARNESS.md), [Runtime Contracts](../architecture/RUNTIME_CONTRACTS.md), [ADR-0005](../decisions/ADR-0005-bounded-llm-typed-capability-execution.md), [ADR-0006](../decisions/ADR-0006-separate-disposition-and-bound-recovery.md), [ADR-0007](../decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md), [ADR-0008](../decisions/ADR-0008-lossless-tagged-contract-values.md), [Stage 01 Runtime Contracts Plan](../tasks/2026-08-17-stage-01-runtime-contracts-implementation-plan.md), [Stage 02 PostgreSQL Storage Plan](../tasks/2026-08-17-stage-02-postgresql-storage-implementation-plan.md)

## 1. Purpose

Stage 01 already defines and verifies the public runtime contract models, deterministic schemas, execution-graph compatibility, and Linux/amd64 portability. Before those fields are frozen for Stage 02 PostgreSQL storage, the closure review must resolve six gaps:

1. Python and JSON inputs do not yet have an explicit strictness boundary.
2. JSON Schema structural validation and Pydantic semantic validation are not documented and tested as separate authorities.
3. Canonical serialization is not defined for all approved scalar values and currently fails for date, datetime, and Decimal values inside raw mappings.
4. `ClaimSupport` does not yet enforce nonnegative ordinals or make `support_kind` agree with its target type.
5. Schema freshness checking is not directly proven against stale, missing, and extra files.
6. The current untagged `ScalarValue` and `ContractValue` JSON representation erases the distinction between Decimal, date, datetime, and look-alike strings.

The sixth issue was reproduced during implementation-plan self-review:

```text
Decimal("1.0")               -> JSON "1.0"                  -> str "1.0"
date(2026, 7, 11)            -> JSON "2026-07-11"           -> str "2026-07-11"
UTC datetime                 -> JSON "...T00:00:00Z"        -> str "...T00:00:00Z"
```

The exported union Schema also permits these values through an ordinary string branch. Without an explicit tag, a valid contract cannot round-trip through JSON with its Python type intact, and a financial Decimal can collide with a text value in canonical hashing. Stage 01 cannot be frozen while this ambiguity remains.

This design closes all six gaps without adding a database, orchestration runtime, Claim Gate Registry, or evaluation API server.

## 2. Approved Direction

Use one Stage 01 closure-hardening amendment with five independently testable implementation tasks:

1. replace untagged polymorphic values with lossless tagged contract values;
2. enforce strict Python-versus-JSON ingress;
3. canonicalize approved tagged values and nested contract structures;
4. enforce `ClaimSupport` semantic constraints;
5. document and test the JSON Schema/runtime boundary, exact schema set, and host/NCP portability.

The work may use separate focused commits, but it remains one contract-freeze gate. Deferring tagged values to Stage 02 is rejected because QueryPlan, ToolResult, Evidence, Calculation, Claim, hashes, and request artifacts must already agree on one wire representation before persistence begins.

## 3. Assumptions and Constraints

- The fixed data cutoff remains `2026-07-11`.
- Stage 01 public artifact model names and the official five-string evaluation API remain unchanged.
- Stage 01 fields are not frozen until this amendment passes; therefore `schema_version="1.0"` remains valid during this pre-freeze correction.
- All contract models remain immutable and reject unknown fields.
- Financial numeric values use `Decimal`, never binary floating-point.
- Every polymorphic contract value is self-describing in JSON and retains its type without consulting a predicate, metric, table, or registry.
- JSON fixtures contain synthetic data only. Organizer data, external snapshots, secrets, databases, embeddings, and generated runtime outputs remain outside Git and the Docker context.
- Pydantic `2.13.4` behavior is fixed by the reviewed contract dependency lock.
- The normal runtime continues to use only the approved Intent Resolver and Answer Composer LLM roles. This amendment adds no LLM behavior.

## 4. Lossless Tagged Contract Values

### 4.1 Wire representation

Every value carried by a field typed as `ScalarValue` or `ContractValue` uses an explicit JSON object.

Scalar forms:

```json
{"type":"null","value":null}
{"type":"string","value":"2026-07-11"}
{"type":"integer","value":5}
{"type":"decimal","value":"1.25"}
{"type":"boolean","value":false}
{"type":"date","value":"2026-07-11"}
{"type":"datetime","value":"2026-08-17T00:00:00Z"}
```

Tuple form:

```json
{
  "type": "tuple",
  "items": [
    {"type":"date","value":"2026-07-11"},
    {"type":"string","value":"2026-07-11"},
    {"type":"decimal","value":"1"},
    {"type":"string","value":"1.0"}
  ]
}
```

All objects reject extra fields. The `type` field is required; a default must not allow it to disappear from JSON Schema. Tuple items are scalar tagged values only, so nested tuples remain invalid.

### 4.2 Pydantic types

Add a focused `contracts/values.py` module containing eight frozen strict value models:

- `NullValue`
- `StringValue`
- `IntegerValue`
- `DecimalValue`
- `BooleanValue`
- `DateValue`
- `DateTimeValue`
- `TupleValue`

Each model has a required Literal `type` and its correctly typed `value` or `items` field. `ScalarValue` is a discriminator-based union of the seven scalar models. `ContractValue` is the same union plus `TupleValue`.

These models, aliases, and conversion functions are exported from `financial_agent.contracts`; Stage 02 and later stages import this single public definition instead of reaching into an internal module or declaring a second representation.

The module also defines native Python aliases and the only two conversion functions:

```text
ScalarPrimitive = str | int | Decimal | bool | date | UtcDateTime | None
ContractPrimitive = ScalarPrimitive | tuple[ScalarPrimitive, ...]

encode_contract_value(value: ContractPrimitive) -> ContractValue
decode_contract_value(value: ContractValue) -> ContractPrimitive
```

Encoding checks Boolean before integer and datetime before date. It rejects float, list, mapping, nested tuple, naive datetime, non-UTC datetime, and unsupported objects. Decoding returns the exact native type represented by the tag.

`DecimalValue` stores a real Decimal in Python, emits a canonical decimal string in JSON, and restores a Decimal from that tagged string. Date and datetime models likewise retain native Python types after JSON round-trip. A string that looks like a date or Decimal remains a `StringValue` because its tag is authoritative.

The Decimal boundary is asymmetric by design: Python construction requires an actual finite `Decimal`, while raw JSON requires a string in the `value` member. A JSON number under `type="decimal"` is a tag/value mismatch and fails. The exported JSON Schema therefore presents the Decimal payload as a pattern-constrained string, not as Pydantic's broader default Decimal number-or-string input. Equivalent mode-aware validation and serialization may be implemented with a focused annotated field type, but the public model and wire shape remain exactly those defined above.

### 4.3 Decimal wire rule

Decimal identity is numeric rather than representational:

- `Decimal("1.0")`, `Decimal("1.00")`, and `Decimal("1E+0")` emit `{"type":"decimal","value":"1"}`;
- positive and negative Decimal zero emit value `"0"`;
- insignificant trailing zeros are removed without applying the ambient Decimal context or rounding the value;
- scientific notation is rendered as an exact plain decimal string;
- NaN and positive or negative infinity are rejected.

The implementation derives sign, coefficient digits, and exponent from `Decimal.as_tuple()`, removes trailing coefficient zeros while adjusting the exponent, and places the decimal point directly. It must not use a context-sensitive normalization operation that can round high-precision financial values.

The canonical JSON string and exported Schema use this grammar: `^(?:0|-?[1-9][0-9]*|-?(?:0|[1-9][0-9]*)\.[0-9]*[1-9])$`. It permits exact plain integers and nonzero fractional tails, including values such as `-0.125`, while excluding exponents, leading zeros, trailing fractional zeros, and negative zero.

Raw source formatting and meaningful display precision remain available through `raw_value_repr`, units, rounding rules, and display policies.

### 4.4 Field migration

The existing public aliases remain named `ScalarValue` and `ContractValue`, but their meaning changes from ambiguous native unions to tagged Pydantic unions before the 1.0 freeze. The following embedded fields therefore change wire shape:

- `QueryPlan.FilterSpec.value`
- `ExecutionGraph.NamedValue.value`
- `ToolResult.ResultField.value`
- `ToolResult.BindingValue.value`
- `EvidenceRecord.value_or_object_id`
- `EvidenceRecord.normalized_value`
- `CalculationParameter.value`
- `CalculationRecord.result_value`
- `ClaimQualifier.value`
- `AtomicClaim.value`

`AtomicClaim.value` remains nullable at the field level because JSON null means “no value target” for qualifier-only limitation and policy claims. A tagged `NullValue` is an explicit value and is not valid as an AtomicClaim factual value. This preserves the existing object/value/qualifier-only semantics without conflating field absence with a tagged null observation.

Cardinality checks no longer inspect a native tuple. They inspect `TupleValue`: cardinality `one` rejects `TupleValue`, while `many` requires it.

### 4.5 Stage 02 ownership

Stage 01 becomes the authority for tagged value classes, Decimal normalization, and encode/decode behavior. Stage 02 stores the exact Stage 01 tagged JSON shape in JSONB and applies database CHECK constraints to the same shape.

The Stage 02 plan must remove its persistence-only duplicate `TaggedScalar`, `TaggedTuple`, and `TaggedValue` dataclasses. Its repository and PostgreSQL validation reuse Stage 01 contract serialization and fixtures. This avoids two codecs that can disagree about Decimal, date, datetime, Boolean/integer identity, or tuple shape.

## 5. Strict Ingress Boundary

### 5.1 Contract model policy

`ContractModel` uses strict Pydantic validation in addition to the existing `extra="forbid"` and `frozen=True` settings.

Strictness has two intentional ingress behaviors:

- **Raw JSON ingress:** JSON-producing boundaries pass the original `str`, `bytes`, or `bytearray` to `model_validate_json`. JSON strings remain the valid representation for explicitly typed ISO dates, UTC datetimes, Enum values, and tagged Decimal payloads; JSON arrays remain the representation of non-polymorphic tuple fields.
- **Python ingress:** deterministic internal components use model construction or `model_validate` with already typed Python values. They use `encode_contract_value` when populating a polymorphic value field. A Python string is not coerced to an integer, a Boolean is not coerced to `0` or `1`, and a Python date or datetime field receives the corresponding Python type.

A decoded JSON dictionary is not reclassified as typed Python input. A boundary that has already decoded external or persisted JSON must pass it through a JSON adapter before contract validation. Stage 02 repository work must retain this distinction when reconstructing artifacts from JSONB.

No additional general validation framework is introduced. The Pydantic model methods and the two tagged-value conversion functions remain the contract entry points.

### 5.2 Required behavior

- Updated valid JSON fixtures pass strict `model_validate_json` validation.
- Every tagged ContractValue fixture round-trips to the same tagged model and native decoded type.
- ISO date and UTC datetime strings continue to work when they arrive inside explicitly tagged or explicitly typed JSON fields.
- Equivalent Python calls require actual date, datetime, integer, tuple, Decimal, and Enum values.
- Python coercions such as `"1" -> 1`, `True -> 1`, list-to-tuple, or untagged polymorphic values fail.
- Later API, LLM structured-output, and PostgreSQL adapters cannot select a lax or untagged path.

## 6. Canonical Serialization

### 6.1 Scope

`canonical_json_bytes` and `canonical_sha256` continue to accept a contract `BaseModel` or `Mapping[str, Any]`. This remains a contract hashing utility, not a general-purpose serialization framework.

Contract artifacts are hashed from a validated model. Canonicalization uses its JSON-mode dump after the tagged value serializers have produced the approved wire representation. The tag keeps polymorphic types distinct, while explicitly typed model fields supply their own date, datetime, Enum, Boolean, integer, and string semantics.

Mapping input remains available for small JSON-native hash inputs such as `build_request_key`. It accepts only string keys and already JSON-shaped null, string, Boolean, integer, list, and mapping values. It does not accept native Decimal, date, datetime, Enum, tuple, or other Python objects because a schema-less mapping cannot prove whether such a value belongs to a polymorphic or explicitly typed field. A caller hashing a contract artifact must construct and validate the contract model first; Mapping input is not a validation bypass. Mapping keys are sorted by the final JSON encoder, and list order is preserved.

### 6.2 Tagged identity and scalar rules

Tagged values retain their `type` field in canonical bytes. Therefore:

```text
{"type":"decimal","value":"1"}
```

and

```text
{"type":"string","value":"1"}
```

have different bytes and hashes.

Explicitly typed non-polymorphic date and UTC datetime model fields serialize as ISO strings, with UTC datetimes using `Z`. Integer zero, Boolean false, and null remain distinct JSON values.

An untagged raw Decimal is not a valid ContractValue. Financial models must encode it before assignment. `DecimalValue` is responsible for emitting the canonical Decimal string before the model reaches the canonical JSON encoder; the canonicalizer does not infer or add a tag.

### 6.3 Containers and rejected values

- Nested contract models and ordinary model tuple/list fields become JSON-native mappings and ordered arrays through the model's JSON-mode dump.
- JSON-native Mapping/list inputs are traversed recursively to reject unsupported values and non-string keys.
- `TupleValue` retains its tagged object with an ordered `items` array.
- `ContractValue` permits one tagged scalar or one flat `TupleValue`; nested tuple/list values are rejected.
- Mapping input containing a non-string key, binary floating-point value, native tuple, Decimal, date, datetime, Enum, set, or unsupported Python object is rejected explicitly.
- Top-level `exclude_fields` behavior remains unchanged.

## 7. ClaimSupport Semantics

`ClaimSupport` keeps its current fields and adds these invariants:

- `ordinal` is an integer greater than or equal to zero.
- `support_kind="calculation"` requires exactly one `calculation_id` and forbids `evidence_id`.
- `support_kind` in `direct`, `scope`, `exclusion`, or `policy` requires exactly one `evidence_id` and forbids `calculation_id`.
- Missing both targets and setting both targets remain invalid.

The nonnegative ordinal is structural and appears as `minimum: 0` in the generated ClaimSupport JSON Schema. The relationship between `support_kind` and target ID remains a Pydantic semantic invariant rather than duplicated JSON Schema `if/then` logic.

## 8. JSON Schema and Runtime Authority

### 8.1 Structural authority

Generated Draft 2020-12 JSON Schemas describe the portable contract shape:

- required and optional fields;
- tagged value discriminators and per-tag value types;
- tuple item shape and the prohibition on nested TupleValue;
- JSON types and non-polymorphic array shapes;
- Enum values;
- identifier and SHA-256 patterns;
- unknown-field rejection;
- field-local bounds such as `ordinal >= 0`.

The schemas for QueryPlan, ExecutionGraph, ToolResult, EvidenceRecord, CalculationRecord, and AtomicClaim are expected to change because they embed tagged values. The exact generated set must be reviewed; unrelated response, request-context, source, bundle, verification, AnswerPlan, ReleasedAnswer, and evaluation API schemas must remain unchanged unless Pydantic produces a documented shared-definition effect.

### 8.2 Semantic authority

Pydantic runtime validation remains authoritative for invariants that span fields, objects, or artifacts, including:

- the exact fixed cutoff;
- UTC requirements and deadline relationships;
- AtomicClaim absence/object/value rules;
- identifier reference integrity;
- DAG acyclicity, binding ownership, cardinality, and critical-path budgets;
- support-kind-to-target compatibility;
- QueryPlan–ExecutionGraph and ExecutionGraph–ToolResult compatibility.

The project does not duplicate these rules in hand-written JSON Schema conditions. Tests explicitly demonstrate that some semantically invalid payloads can pass structural Schema validation but must fail runtime validation. This is expected behavior, not Schema/runtime drift.

### 8.3 Format validation

Parity tests use a Draft 2020-12 validator with format checking enabled when testing date and datetime syntax. Schema syntax checking alone is not treated as payload format validation.

## 9. Schema Freshness Mutation Proof

`check_schemas(expected_dir)` remains the single freshness check. Tests create isolated temporary schema directories and prove all four states:

1. an exact fresh export passes;
2. modifying one committed schema makes the check fail;
3. deleting one expected schema makes the check fail;
4. adding an unregistered schema file makes the check fail.

No production code change is required if the current checker already satisfies these tests. Diagnostic improvements are allowed only if they do not broaden the interface or weaken exact byte comparison.

## 10. Error Handling

- Invalid contract or tagged-value input raises Pydantic `ValidationError` at the ingress boundary.
- `encode_contract_value` rejects unsupported native Python types with `TypeError` and invalid values with `ValueError`.
- `decode_contract_value` accepts only a validated tagged ContractValue.
- Stale, missing, or extra generated schemas cause the schema freshness command to exit nonzero.
- None of these deterministic contract failures are sent to an LLM repair path.
- Runtime integration will later map repeated contract violations to the ADR-0006 system-failure policy; that HTTP implementation is outside this amendment.

## 11. Test Design

### 11.1 Lossless value tests

- Round-trip every scalar tag through Python model → JSON → Pydantic model → native decode.
- Distinguish date-looking and decimal-looking strings from real date and Decimal values.
- Normalize equivalent Decimals to one emitted JSON string and hash.
- Preserve Boolean versus integer and null versus absent field semantics.
- Round-trip mixed scalar TupleValue while rejecting nested TupleValue.
- Reject missing/unknown tags, extra keys, tag/value mismatch, float, list, mapping, naive/non-UTC datetime, and non-finite Decimal.
- Prove tagged Decimal and tagged string produce different canonical bytes and hashes.
- Prove a validated contract model and its equivalent JSON-native wire mapping produce identical canonical bytes.
- Reject native Decimal/date/datetime/tuple values supplied through schema-less Mapping input while retaining simple JSON-native request-key hashing.

### 11.2 Strict ingress tests

- All updated committed JSON fixtures validate through strict raw-JSON ingress.
- Python strings and Booleans cannot populate integer fields.
- Python date/datetime strings fail while typed values pass.
- JSON ISO date and UTC datetime strings pass in tagged or explicitly typed locations.
- Untagged values fail in every ContractValue field.

### 11.3 Cross-contract tests

- QueryPlan filters, ExecutionGraph literal inputs, ToolResult result fields and bindings, Evidence values, Calculation parameters/results, Claim qualifiers/values all preserve their tags.
- ToolResult cardinality checks use TupleValue rather than Python tuple coercion.
- AtomicClaim JSON null still means no value target, while tagged null is rejected as a factual Claim value.
- QueryPlan–ExecutionGraph and ExecutionGraph–ToolResult compatibility remains deterministic after the value migration.

### 11.4 ClaimSupport tests

- Every valid support-kind/target combination passes.
- Every mismatched, missing, duplicate, or negative-ordinal combination fails.
- The exported ClaimSupport schema contains the nonnegative bound.

### 11.5 Schema boundary tests

- Representative missing-field, extra-field, invalid type, invalid tag, invalid Enum, and invalid pattern payloads fail both JSON Schema and Pydantic validation.
- Representative cross-field semantic payloads pass structural Schema validation and fail Pydantic validation.
- Stale, missing, and extra schema mutations fail the exact freshness check.
- The official `EvaluationApiResponse` schema remains exactly five required string fields with no additions.

## 12. Verification and Completion Gate

The amendment is complete only when fresh evidence confirms all of the following:

1. focused red/green tests pass for each changed behavior;
2. the complete contract test suite passes;
3. every updated JSON fixture uses the required tagged representation;
4. generated schemas are byte-current and the changed-schema list is reviewed;
5. Python bytecode compilation and repository diff checks pass;
6. the official evaluation API schema remains unchanged;
7. no organizer data, PDF, workbook, external snapshot, secret, local database, embedding, cache, or runtime output is staged;
8. the locked Linux/amd64 verification image builds and runs successfully;
9. the same image is rebuilt and run on the NCP Ubuntu host with exit code 0.

After this gate passes, Stage 01 public fields and schemas may be frozen for the Stage 02 handoff.

## 13. Non-Goals

- Do not implement PostgreSQL DDL, repositories, JSONB adapters, or database CHECK functions in Stage 01.
- Do not retain a second persistence-only TaggedValue model in Stage 02.
- Do not implement the Orchestrator, Capability Executors, retries, deadline controller, or evaluation API endpoint.
- Do not implement or weaken the mandatory future Claim Gate Registry compatibility check.
- Do not add new Claim types, evidence kinds, financial calculations, or ontology relations.
- Do not create a broad serialization or validation framework beyond the eight tagged value models and two conversion functions.
- Do not refresh dependency versions unless a verified incompatibility blocks this exact design.

## 14. Resulting Stage Boundary

On completion, Stage 01 will own a strict, immutable, lossless, schema-exportable contract boundary. Every polymorphic value will preserve its type through JSON, hashing, and later JSONB persistence without contextual inference. Stage 02 can then store the exact Stage 01 tagged shape and enforce it in PostgreSQL without inventing another codec or conflicting Decimal, date, datetime, Boolean/integer, null, tuple, or coercion policy.
