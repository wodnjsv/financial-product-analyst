# Stage 01 Closure Hardening Design

**Date:** 2026-08-18

**Status:** Approved design; written specification awaiting user review before implementation planning

**Related:** [Planning Harness](../HARNESS.md), [Runtime Contracts](../architecture/RUNTIME_CONTRACTS.md), [ADR-0005](../decisions/ADR-0005-bounded-llm-typed-capability-execution.md), [ADR-0006](../decisions/ADR-0006-separate-disposition-and-bound-recovery.md), [ADR-0007](../decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md), [Stage 01 Runtime Contracts Plan](../tasks/2026-08-17-stage-01-runtime-contracts-implementation-plan.md)

## 1. Purpose

Stage 01 already defines and verifies the public runtime contract models, deterministic schemas, execution-graph compatibility, and Linux/amd64 portability. Before those fields are frozen for Stage 02 PostgreSQL storage, five closure-review gaps must be resolved:

1. Python and JSON inputs do not yet have an explicit strictness boundary.
2. JSON Schema structural validation and Pydantic semantic validation are not documented and tested as separate authorities.
3. Canonical serialization is not defined for all approved scalar values and currently fails for date, datetime, and Decimal values inside raw mappings.
4. `ClaimSupport` does not yet enforce nonnegative ordinals or make `support_kind` agree with its target type.
5. Schema freshness checking is not directly proven against stale, missing, and extra files.

This design closes those gaps without adding a database, orchestration runtime, Claim Gate Registry, or evaluation API server.

## 2. Approved Direction

Use one Stage 01 closure-hardening amendment with four independently testable implementation tasks:

1. strict Python-versus-JSON ingress;
2. canonical scalar and nested-container serialization;
3. `ClaimSupport` semantic constraints;
4. JSON Schema boundary documentation, mutation tests, schema refresh, and full host/NCP verification.

The work may use separate focused commits, but it remains one contract-freeze gate. Splitting it into multiple design cycles would repeat schema and NCP verification without changing the approved boundaries. Deferring any item to Stage 02 would allow the storage schema to encode an incomplete Stage 01 contract and is rejected.

## 3. Assumptions and Constraints

- The fixed data cutoff remains `2026-07-11`.
- Stage 01 public model names and the official five-string evaluation API remain unchanged.
- Stage 01 fields are not frozen until this amendment passes; therefore `schema_version="1.0"` remains valid during this pre-freeze correction.
- All contract models remain immutable and reject unknown fields.
- Financial numeric values use `Decimal`, not binary floating-point.
- JSON fixtures contain synthetic data only. Organizer data, external snapshots, secrets, databases, embeddings, and generated runtime outputs remain outside Git and the Docker context.
- Pydantic `2.13.4` behavior is fixed by the reviewed contract dependency lock.
- The normal runtime continues to use only the approved Intent Resolver and Answer Composer LLM roles. This amendment adds no LLM behavior.

## 4. Strict Ingress Boundary

### 4.1 Contract model policy

`ContractModel` uses strict Pydantic validation in addition to the existing `extra="forbid"` and `frozen=True` settings.

Strictness has two intentional ingress behaviors:

- **Raw JSON ingress:** JSON-producing boundaries pass the original `str`, `bytes`, or `bytearray` to `model_validate_json`. JSON strings remain the valid representation for explicitly typed ISO dates, UTC datetimes, and Enum values; JSON arrays remain the valid representation for tuple fields.
- **Python ingress:** deterministic internal components use model construction or `model_validate` with already typed Python values. A Python string is not coerced to an integer, a Boolean is not coerced to `0` or `1`, and a Python date or datetime field receives the corresponding Python type.

A decoded JSON dictionary is not reclassified as typed Python input. A boundary that has already decoded external or persisted JSON must pass it through a JSON adapter before contract validation. Stage 02 repository work must retain this distinction when reconstructing artifacts from JSONB.

No additional general validation framework is introduced. The Pydantic model methods remain the contract entry points, and tests provide small fixture helpers for raw JSON and mutated JSON payloads.

### 4.2 Required behavior

- Existing valid JSON fixtures pass strict `model_validate_json` validation.
- ISO date and UTC datetime strings continue to work when they arrive through JSON.
- Equivalent Python calls require actual date, datetime, integer, tuple, and Enum values.
- Python coercions such as `"1" -> 1` and `True -> 1` fail.
- The behavior is documented so later API, LLM structured-output, and PostgreSQL adapters cannot silently choose a lax path.

## 5. Canonical Serialization

### 5.1 Scope

`canonical_json_bytes` and `canonical_sha256` continue to accept a contract `BaseModel` or `Mapping[str, Any]`. They gain one small recursive conversion step before standard JSON serialization. This is a contract hashing utility, not a general-purpose serialization framework.

For a model, canonicalization begins from its Python-mode dump so Decimal, date, datetime, Enum, Boolean, integer, and string values are still distinguishable before conversion. For a mapping, only string keys are accepted. Mapping keys are sorted by the final JSON encoder, and tuple/list order is preserved.

### 5.2 Scalar rules

| Input | Canonical JSON representation |
| --- | --- |
| `str` | JSON string |
| `bool` | JSON `true` or `false` |
| `int` | JSON integer, including `0` |
| `None` | JSON `null` |
| finite `Decimal` | normalized decimal string |
| `date` | `YYYY-MM-DD` string |
| UTC `datetime` | ISO datetime string using `Z` |
| string-valued Enum | its Enum value, then the applicable scalar rule |

Boolean handling occurs before integer handling because Python Boolean is an integer subtype. Datetime handling occurs before date handling because Python datetime is a date subtype.

### 5.3 Decimal identity

Canonical Decimal identity is numeric rather than representational:

- `Decimal("1.0")`, `Decimal("1.00")`, and `Decimal("1E+0")` serialize as `"1"`;
- positive and negative Decimal zero serialize as `"0"`;
- insignificant trailing zeros are removed without applying the ambient Decimal context or rounding the value;
- scientific notation is rendered as an exact plain decimal string;
- NaN and positive or negative infinity are rejected.

The implementation derives sign, coefficient digits, and exponent from `Decimal.as_tuple()`, removes trailing coefficient zeros while adjusting the exponent, and places the decimal point directly. It must not use a context-sensitive normalization operation that can round high-precision financial values.

Source formatting and meaningful display precision do not belong in the hash representation. They remain available through `raw_value_repr`, units, rounding rules, and display policies.

### 5.4 Containers and rejected values

- Nested model, mapping, tuple, and list structures are converted recursively.
- Tuple and list values both become ordered JSON arrays for canonical bytes.
- `ContractValue` remains narrower: it permits one scalar or one flat tuple of scalars and rejects nested tuples or lists.
- The canonicalizer's ability to hash a nested contract model does not make a nested value valid for `ContractValue`.
- Non-string mapping keys, binary floating-point values, sets, non-UTC datetimes, non-finite Decimals, and unsupported Python objects are rejected explicitly.
- Top-level `exclude_fields` behavior remains unchanged.

## 6. ClaimSupport Semantics

`ClaimSupport` keeps its current fields and adds the following invariants:

- `ordinal` is an integer greater than or equal to zero.
- `support_kind="calculation"` requires exactly one `calculation_id` and forbids `evidence_id`.
- `support_kind` in `direct`, `scope`, `exclusion`, or `policy` requires exactly one `evidence_id` and forbids `calculation_id`.
- Missing both targets and setting both targets remain invalid.

The nonnegative ordinal is structural and appears as `minimum: 0` in the generated ClaimSupport JSON Schema. The relationship between `support_kind` and target ID remains a Pydantic semantic invariant rather than duplicated JSON Schema `if/then` logic.

This aligns Stage 01 with the Stage 02 evidence-ledger design: calculations support derived claims through `CalculationRecord`, while direct, scope, exclusion, and policy support refer to the corresponding `EvidenceRecord`.

## 7. JSON Schema and Runtime Authority

### 7.1 Structural authority

Generated Draft 2020-12 JSON Schemas describe the portable contract shape:

- required and optional fields;
- JSON types and array shapes;
- Enum values;
- identifier and SHA-256 patterns;
- unknown-field rejection;
- field-local bounds such as `ordinal >= 0`.

External tools may use these schemas for structural validation and interface generation.

### 7.2 Semantic authority

Pydantic runtime validation remains authoritative for invariants that span fields, objects, or artifacts, including:

- the exact fixed cutoff;
- UTC requirements and deadline relationships;
- XOR and conditional field relationships;
- identifier reference integrity;
- DAG acyclicity, binding ownership, and critical-path budgets;
- support-kind-to-target compatibility;
- QueryPlan–ExecutionGraph and ExecutionGraph–ToolResult compatibility.

The project does not duplicate these rules in hand-written JSON Schema conditions. Tests explicitly demonstrate that some semantically invalid payloads can pass structural Schema validation but must fail runtime validation. This is expected behavior, not Schema/runtime drift.

### 7.3 Format validation

Parity tests use a Draft 2020-12 validator with format checking enabled when testing date and datetime syntax. Schema syntax checking alone is not treated as payload format validation.

## 8. Schema Freshness Mutation Proof

`check_schemas(expected_dir)` remains the single freshness check. Tests create isolated temporary schema directories and prove all four states:

1. an exact fresh export passes;
2. modifying one committed schema makes the check fail;
3. deleting one expected schema makes the check fail;
4. adding an unregistered schema file makes the check fail.

No production code change is required if the current checker already satisfies these tests. Diagnostic improvements are allowed only if they do not broaden the interface or weaken exact byte comparison.

## 9. Error Handling

- Invalid contract input raises Pydantic `ValidationError` at the ingress boundary.
- Unsupported canonical Python types raise `TypeError`.
- Invalid canonical values, such as non-UTC datetime or non-finite Decimal, raise `ValueError`.
- Stale, missing, or extra generated schemas cause the schema freshness command to exit nonzero.
- None of these deterministic contract failures are sent to an LLM repair path.
- Runtime integration will later map repeated contract violations to the ADR-0006 system-failure policy; that HTTP implementation is outside this amendment.

## 10. Test Design

### 10.1 Strict ingress tests

- All committed JSON fixtures validate through strict raw-JSON ingress.
- Python strings and Booleans cannot populate integer fields.
- Python date/datetime strings fail while typed values pass.
- JSON ISO date and UTC datetime strings pass.
- JSON arrays populate tuple fields, while Python list-to-tuple coercion fails.

### 10.2 Canonical tests

- Mapping key order does not change bytes or SHA-256.
- Numerically equivalent Decimals produce identical bytes and hashes.
- Decimal zero, integer zero, Boolean false, and null stay distinguishable.
- Date and UTC datetime use the approved strings.
- A model and an equivalent typed mapping produce identical canonical bytes.
- Nested ordinary containers serialize deterministically.
- Nested `ContractValue`, non-UTC datetime, non-finite Decimal, float, set, unsupported object, and non-string mapping key cases fail for the intended reason.

### 10.3 ClaimSupport tests

- Every valid support-kind/target combination passes.
- Every mismatched, missing, duplicate, or negative-ordinal combination fails.
- The exported ClaimSupport schema contains the nonnegative bound.

### 10.4 Schema boundary tests

- Representative missing-field, extra-field, invalid type, invalid Enum, and invalid pattern payloads fail both JSON Schema and Pydantic validation.
- Representative cross-field semantic payloads pass structural Schema validation and fail Pydantic validation.
- Stale, missing, and extra schema mutations fail the exact freshness check.
- The official `EvaluationApiResponse` schema remains exactly five required string fields with no additions.

## 11. Verification and Completion Gate

The amendment is complete only when fresh evidence confirms all of the following:

1. focused red/green tests pass for each changed behavior;
2. the complete contract test suite passes;
3. generated schemas are byte-current;
4. Python bytecode compilation and repository diff checks pass;
5. only the intended ClaimSupport schema changes, unless a reviewed strictness change deterministically affects another schema;
6. the official evaluation API schema remains unchanged;
7. no organizer data, PDF, workbook, external snapshot, secret, local database, embedding, cache, or runtime output is staged;
8. the locked Linux/amd64 verification image builds and runs successfully;
9. the same image is rebuilt and run on the NCP Ubuntu host with exit code 0.

After this gate passes, Stage 01 public fields and schemas may be frozen for the Stage 02 handoff.

## 12. Non-Goals

- Do not implement PostgreSQL DDL, repositories, JSONB adapters, or tagged persistence values.
- Do not implement the Orchestrator, Capability Executors, retries, deadline controller, or evaluation API endpoint.
- Do not implement or weaken the mandatory future Claim Gate Registry compatibility check.
- Do not add new Claim types, evidence kinds, financial calculations, or ontology relations.
- Do not create a broad serialization or validation framework.
- Do not refresh dependency versions unless a verified incompatibility blocks this exact design.

## 13. Resulting Stage Boundary

On completion, Stage 01 will own a strict, immutable, schema-exportable contract boundary with deterministic canonical hashing and unambiguous Claim-to-support semantics. Stage 02 may then map those frozen contracts into PostgreSQL without inventing coercion, numeric identity, ordinal, target-type, or Schema-authority rules of its own.
