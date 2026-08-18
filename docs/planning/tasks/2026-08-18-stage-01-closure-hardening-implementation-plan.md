# Stage 01 Closure Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-08-18

**Status:** Review-ready; implementation requires explicit user approval

**Goal:** Freeze Stage 01 with strict, immutable, lossless tagged contract values, deterministic canonical hashing, unambiguous ClaimSupport semantics, exact Schema freshness proof, and verified Linux/amd64 behavior on the NCP Ubuntu host.

**Architecture:** Stage 01 owns eight discriminated Pydantic tagged-value models and the only native encode/decode boundary. Existing QueryPlan, ExecutionGraph, ToolResult, Evidence, Calculation, and Claim fields migrate to that wire shape before global strict validation is enabled. JSON Schema remains the structural contract, Pydantic remains the semantic authority, and Stage 02 consumes the frozen representation without a second codec.

**Tech Stack:** Python 3.12, Pydantic 2.13.4, pytest 8.4.2, jsonschema 4.26.0 Draft 2020-12, Docker Engine, Linux/amd64, NCP Ubuntu 24.04.

**Authoritative references:** [Planning Harness](../HARNESS.md), [Runtime Contracts](../architecture/RUNTIME_CONTRACTS.md), [ADR-0005](../decisions/ADR-0005-bounded-llm-typed-capability-execution.md), [ADR-0006](../decisions/ADR-0006-separate-disposition-and-bound-recovery.md), [ADR-0007](../decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md), [ADR-0008](../decisions/ADR-0008-lossless-tagged-contract-values.md), [approved closure design](../specs/2026-08-18-stage-01-closure-hardening-design.md), and [Stage 02 PostgreSQL plan](2026-08-17-stage-02-postgresql-storage-implementation-plan.md).

## Global Constraints

- The fixed data cutoff is exactly `2026-07-11`.
- Keep `schema_version="1.0"` during this pre-freeze correction; the Stage 01 public fields are not frozen until this plan passes.
- Keep the official `EvaluationApiResponse` at exactly five required string fields.
- Use Decimal for financial numeric values and reject binary floating point.
- Every `ScalarValue` and `ContractValue` wire value is explicitly tagged; do not infer a type from a field, predicate, metric, table, or registry.
- Contract models remain frozen and reject unknown fields.
- Raw JSON enters through `model_validate_json`; Python construction uses actual typed values.
- Keep filtering, ranking, aggregation, comparison, and financial calculation outside the language model.
- Do not implement PostgreSQL, a Stage 02 codec, orchestration, the evaluation endpoint, or the future Claim Gate Registry in this plan.
- Claim Gate Registry registration and compatibility checks remain mandatory later; this plan must not weaken or replace them.
- Do not change dependency versions unless Pydantic 2.13.4 demonstrably cannot implement the approved boundary.
- Use only synthetic fixtures. Never stage organizer data, PDFs, workbooks, secrets, databases, Parquet, embeddings, caches, logs, or runtime outputs.
- Do not mark Stage 01 complete until the same locked image builds and exits zero on the NCP Ubuntu Linux/amd64 host.

## Assumptions, Outcome, and Non-Goals

### Assumptions

- The current execution-contract implementation and its 116 host tests are the starting point.
- `requirements/contracts.lock` remains the verification authority for Pydantic, pytest, and jsonschema.
- The current 14-file Schema registry remains closed; only embedded definitions and ClaimSupport bounds may change.
- NCP Docker Engine is already installed and can build the repository checkout.

### Intended outcome

At completion, a Decimal, date, datetime, Boolean, integer, string, null, or flat tuple can cross Python -> JSON -> Pydantic -> canonical hash -> later JSONB without losing its identity. Invalid coercions, ambiguous untagged values, noncanonical Decimals, mismatched ClaimSupport targets, and stale Schema directories fail deterministically.

### Non-goals

- No ontology, data-ingestion, SQL, Graph, Vector, API, or LLM feature is added.
- No new Claim type, evidence kind, financial metric, relation, or answer template is added.
- No broad serializer framework or compatibility shim for the old untagged wire shape is retained.
- No external data is collected or modified.

### Verifiable success criteria

1. All eight tagged models round-trip through JSON and native decoding without type loss.
2. Equivalent Decimal values emit one canonical string; look-alike strings retain the string tag.
3. All ten approved polymorphic fields reject the old untagged wire shape.
4. Strict raw-JSON and typed-Python paths both work, while Python coercions fail.
5. `AtomicClaim.value=null` retains its absence meaning and tagged NullValue is rejected as a factual value.
6. ToolResult cardinality checks use TupleValue.
7. ClaimSupport enforces nonnegative ordinal and support-kind target compatibility.
8. Schema structural tests and Pydantic semantic tests prove their separate authority.
9. Fresh, stale, missing, and extra Schema directory states are all tested.
10. The host suite, Schema check, compile check, Linux/amd64 image, and NCP image run all pass.

## File Responsibility Map

| File | Responsibility |
| --- | --- |
| `src/financial_agent/contracts/values.py` | tagged models, Decimal wire normalization, native encode/decode |
| `src/financial_agent/contracts/base.py` | shared strict immutable model policy and non-value primitives |
| `src/financial_agent/contracts/query.py` | tagged filter values |
| `src/financial_agent/contracts/execution.py` | tagged literal/result/binding values |
| `src/financial_agent/contracts/evidence.py` | tagged Evidence/Calculation/Claim values and ClaimSupport rules |
| `src/financial_agent/contracts/compatibility.py` | TupleValue cardinality compatibility |
| `src/financial_agent/contracts/canonical.py` | JSON-native canonical bytes and hashes |
| `src/financial_agent/contracts/__init__.py` | one public value API for later stages |
| `tests/contracts/conftest.py` | explicit raw-JSON fixture helpers |
| `tests/contracts/test_values.py` | tagged-value and Decimal boundary tests |
| `tests/contracts/test_base.py` | strict Python-versus-JSON ingress tests |
| existing contract tests | cross-contract semantics after wire migration |
| `tests/contracts/test_schema_export.py` | Schema/runtime parity and freshness mutation proof |
| four changed JSON fixtures | approved tagged wire examples |
| seven changed Schema files | generated structural contracts only |

---

### Task 1: Implement the isolated lossless tagged-value module

**Files:**

- Create: `src/financial_agent/contracts/values.py`
- Create: `tests/contracts/test_values.py`

**Interfaces:**

- Consumes: `ContractModel`, `UtcDateTime`, and `require_utc` from `contracts/base.py`.
- Produces: `NullValue`, `StringValue`, `IntegerValue`, `DecimalValue`, `BooleanValue`, `DateValue`, `DateTimeValue`, `TupleValue`, `ScalarValue`, `ContractValue`, `ScalarPrimitive`, `ContractPrimitive`, `encode_contract_value`, and `decode_contract_value`.

- [ ] **Step 1: Write failing scalar, Decimal, tuple, and rejection tests**

Create `tests/contracts/test_values.py` with these exact behavioral groups:

```python
import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from financial_agent.contracts.values import (
    ContractValue,
    DateValue,
    DecimalValue,
    IntegerValue,
    NullValue,
    StringValue,
    TupleValue,
    decode_contract_value,
    encode_contract_value,
)

CONTRACT_VALUE_ADAPTER = TypeAdapter(ContractValue)


@pytest.mark.parametrize(
    ("native", "expected_type", "expected_wire"),
    [
        (None, NullValue, {"type": "null", "value": None}),
        ("2026-07-11", StringValue, {"type": "string", "value": "2026-07-11"}),
        (5, IntegerValue, {"type": "integer", "value": 5}),
        (Decimal("1.00"), DecimalValue, {"type": "decimal", "value": "1"}),
        (date(2026, 7, 11), DateValue, {"type": "date", "value": "2026-07-11"}),
    ],
)
def test_scalar_round_trip_preserves_native_type(native, expected_type, expected_wire):
    encoded = encode_contract_value(native)
    assert isinstance(encoded, expected_type)
    assert encoded.model_dump(mode="json") == expected_wire
    restored = CONTRACT_VALUE_ADAPTER.validate_json(encoded.model_dump_json())
    decoded = decode_contract_value(restored)
    assert type(decoded) is type(native)
    assert decoded == native


def test_mixed_tuple_keeps_one_tag_per_item():
    native = (date(2026, 7, 11), "2026-07-11", Decimal("1.0"), "1.0")
    encoded = encode_contract_value(native)
    assert isinstance(encoded, TupleValue)
    assert [item.type for item in encoded.items] == [
        "date", "string", "decimal", "string"
    ]
    restored = CONTRACT_VALUE_ADAPTER.validate_json(encoded.model_dump_json())
    assert decode_contract_value(restored) == (
        date(2026, 7, 11), "2026-07-11", Decimal("1"), "1.0"
    )
```

Also add parameterized assertions for Boolean before integer, datetime before date, positive and negative zero, high-precision Decimal, exponent input, leading/trailing-zero JSON rejection, JSON numeric Decimal rejection, missing/unknown tag, extra key, tag/value mismatch, non-finite Decimal, float, list, mapping, nested tuple, naive datetime, and non-UTC datetime. Require the Decimal Schema `value` property to be a string with the approved canonical pattern.

- [ ] **Step 2: Run the focused test and verify the missing module failure**

Run:

```bash
.venv/bin/python -m pytest tests/contracts/test_values.py -v
```

Expected: collection fails because `financial_agent.contracts.values` does not exist.

- [ ] **Step 3: Implement the tagged models and exact Decimal boundary**

Create `src/financial_agent/contracts/values.py` using this implementation shape:

```python
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationInfo,
    WithJsonSchema,
)

from .base import ContractModel, UtcDateTime, require_utc

_DECIMAL_PATTERN = (
    r"^(?:0|-?[1-9][0-9]*|-?(?:0|[1-9][0-9]*)\.[0-9]*[1-9])$"
)


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("decimal must be finite")
    if value.is_zero():
        return "0"
    sign, digits, exponent = value.as_tuple()
    coefficient = "".join(str(digit) for digit in digits)
    while coefficient.endswith("0"):
        coefficient = coefficient[:-1]
        exponent += 1
    if exponent >= 0:
        rendered = coefficient + ("0" * exponent)
    else:
        split_at = len(coefficient) + exponent
        if split_at > 0:
            rendered = coefficient[:split_at] + "." + coefficient[split_at:]
        else:
            rendered = "0." + ("0" * -split_at) + coefficient
    return ("-" if sign else "") + rendered


def _validate_decimal(value: object, info: ValidationInfo) -> Decimal:
    if info.mode == "json":
        if not isinstance(value, str) or re.fullmatch(_DECIMAL_PATTERN, value) is None:
            raise ValueError("decimal JSON value must be a canonical string")
        return Decimal(value)
    if not isinstance(value, Decimal):
        raise ValueError("decimal Python value must be Decimal")
    if not value.is_finite():
        raise ValueError("decimal must be finite")
    return value


_CanonicalDecimal = Annotated[
    Decimal,
    BeforeValidator(_validate_decimal),
    PlainSerializer(_canonical_decimal, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": _DECIMAL_PATTERN},
        mode="validation",
    ),
]


class _TaggedValueModel(ContractModel):
    model_config = ConfigDict(strict=True)


class NullValue(_TaggedValueModel):
    type: Literal["null"]
    value: None


class StringValue(_TaggedValueModel):
    type: Literal["string"]
    value: str


class IntegerValue(_TaggedValueModel):
    type: Literal["integer"]
    value: int


class DecimalValue(_TaggedValueModel):
    type: Literal["decimal"]
    value: _CanonicalDecimal


class BooleanValue(_TaggedValueModel):
    type: Literal["boolean"]
    value: bool


class DateValue(_TaggedValueModel):
    type: Literal["date"]
    value: date


class DateTimeValue(_TaggedValueModel):
    type: Literal["datetime"]
    value: UtcDateTime


ScalarValue: TypeAlias = Annotated[
    NullValue
    | StringValue
    | IntegerValue
    | DecimalValue
    | BooleanValue
    | DateValue
    | DateTimeValue,
    Field(discriminator="type"),
]


class TupleValue(_TaggedValueModel):
    type: Literal["tuple"]
    items: tuple[ScalarValue, ...]


ContractValue: TypeAlias = Annotated[
    NullValue
    | StringValue
    | IntegerValue
    | DecimalValue
    | BooleanValue
    | DateValue
    | DateTimeValue
    | TupleValue,
    Field(discriminator="type"),
]

ScalarPrimitive: TypeAlias = str | int | Decimal | bool | date | UtcDateTime | None
ContractPrimitive: TypeAlias = ScalarPrimitive | tuple[ScalarPrimitive, ...]
```

Implement the conversion boundary immediately below these definitions:

```python
def _encode_scalar(value: object) -> ScalarValue:
    if value is None:
        return NullValue(type="null", value=None)
    if isinstance(value, bool):
        return BooleanValue(type="boolean", value=value)
    if isinstance(value, int):
        return IntegerValue(type="integer", value=value)
    if isinstance(value, Decimal):
        return DecimalValue(type="decimal", value=value)
    if isinstance(value, datetime):
        require_utc(value)
        return DateTimeValue(type="datetime", value=value)
    if isinstance(value, date):
        return DateValue(type="date", value=value)
    if isinstance(value, str):
        return StringValue(type="string", value=value)
    raise TypeError(f"unsupported contract value: {type(value).__name__}")


def encode_contract_value(value: ContractPrimitive) -> ContractValue:
    if isinstance(value, tuple):
        return TupleValue(
            type="tuple",
            items=tuple(_encode_scalar(item) for item in value),
        )
    return _encode_scalar(value)


def decode_contract_value(value: ContractValue) -> ContractPrimitive:
    if isinstance(value, NullValue):
        return None
    if isinstance(value, TupleValue):
        return tuple(decode_contract_value(item) for item in value.items)
    if isinstance(
        value,
        (
            StringValue,
            IntegerValue,
            DecimalValue,
            BooleanValue,
            DateValue,
            DateTimeValue,
        ),
    ):
        return value.value
    raise TypeError(f"unsupported tagged value: {type(value).__name__}")
```

The branch order is part of the contract: Boolean precedes integer and datetime precedes date. Tuple encoding calls `_encode_scalar` for every item, so nested tuples fail instead of recursing.

- [ ] **Step 4: Run the focused value tests**

Run:

```bash
.venv/bin/python -m pytest tests/contracts/test_values.py -v
```

Expected: all value tests pass and no existing source file has changed.

- [ ] **Step 5: Commit the isolated value boundary**

```bash
git add src/financial_agent/contracts/values.py tests/contracts/test_values.py
git diff --cached --check
git diff --cached
git commit -m "feat: add lossless tagged contract values"
```

### Task 2: Migrate every polymorphic field and fixture to the tagged wire shape

**Files:**

- Modify: `src/financial_agent/contracts/base.py`
- Modify: `src/financial_agent/contracts/__init__.py`
- Modify: `src/financial_agent/contracts/query.py`
- Modify: `src/financial_agent/contracts/execution.py`
- Modify: `src/financial_agent/contracts/evidence.py`
- Modify: `src/financial_agent/contracts/compatibility.py`
- Modify: `tests/fixtures/contracts/v1/query_plan.json`
- Modify: `tests/fixtures/contracts/v1/execution_graph.json`
- Modify: `tests/fixtures/contracts/v1/tool_result.json`
- Modify: `tests/fixtures/contracts/v1/evidence_record.json`
- Modify: `tests/contracts/test_query.py`
- Modify: `tests/contracts/test_execution.py`
- Modify: `tests/contracts/test_compatibility.py`
- Modify: `tests/contracts/test_evidence.py`
- Modify: `tests/contracts/conftest.py`
- Regenerate: `schemas/contracts/v1/query-plan.schema.json`
- Regenerate: `schemas/contracts/v1/execution-graph.schema.json`
- Regenerate: `schemas/contracts/v1/tool-result.schema.json`
- Regenerate: `schemas/contracts/v1/evidence-record.schema.json`
- Regenerate: `schemas/contracts/v1/calculation-record.schema.json`
- Regenerate: `schemas/contracts/v1/atomic-claim.schema.json`

**Interfaces:**

- Consumes: all public types and conversion functions from Task 1.
- Produces: one public `financial_agent.contracts` tagged-value API and ten migrated value fields.

- [ ] **Step 1: Write failing cross-contract wire and cardinality tests**

Add assertions that:

```python
assert plan.filters[0].value.type == "string"
assert graph.tasks[0].literal_inputs[0].value.type == "string"
assert graph.tasks[2].literal_inputs[0].value.type == "integer"
assert result.result_rows[0].fields[1].value.type == "decimal"
assert isinstance(result.binding_values[0].value, TupleValue)
assert evidence.value_or_object_id.type == "decimal"
```

Mutate each fixture back to its old bare scalar or array and require Pydantic `ValidationError`. Add a ToolResult compatibility test where cardinality `one` receives tagged TupleValue and another where cardinality `many` receives tagged StringValue; both must fail for the intended cardinality reason.

- [ ] **Step 2: Run the focused cross-contract tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  tests/contracts/test_query.py \
  tests/contracts/test_execution.py \
  tests/contracts/test_compatibility.py \
  tests/contracts/test_evidence.py -v
```

Expected: failures show that existing fields still accept or return untagged native values.

- [ ] **Step 3: Move aliases out of base and export the Stage 01 value API**

Remove Decimal/date-based `ScalarValue` and `ContractValue` aliases from `base.py`. Keep date/datetime imports needed by `SNAPSHOT_CUTOFF`, `UtcDateTime`, and RuntimeArtifact. In `__init__.py`, import and include in `__all__` all eight tagged models, both tagged aliases, both primitive aliases, and the two conversion functions from `values.py`.

Change imports as follows:

```python
# query.py and execution.py
from .base import ContractModel, Identifier, RuntimeArtifact
from .values import ContractValue

# evidence.py
from .base import ContractModel, Identifier, RuntimeArtifact, Sha256Hex, UtcDateTime
from .values import ContractValue, ScalarValue

# compatibility.py
from .values import TupleValue
```

Keep the ten field names unchanged. Change only `AtomicClaim.value` to `ScalarValue | None`; every other migrated field requires a tagged value object.

- [ ] **Step 4: Change cardinality checks to TupleValue**

Replace native tuple checks with:

```python
if (
    binding_spec.cardinality is Cardinality.ONE
    and isinstance(binding_value.value, TupleValue)
):
    raise ValueError("single binding cannot contain a tuple")
if (
    binding_spec.cardinality is Cardinality.MANY
    and not isinstance(binding_value.value, TupleValue)
):
    raise ValueError("many binding must contain a tuple")
```

- [ ] **Step 5: Add raw-JSON helpers for migrated fixture consumers**

Add these helpers to `tests/contracts/conftest.py`:

```python
@pytest.fixture
def load_fixture_json() -> Callable[[str], str]:
    def load(name: str) -> str:
        return (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    return load


@pytest.fixture
def dump_json() -> Callable[[object], str]:
    def dump(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)
    return dump
```

Change QueryPlan, ExecutionGraph, ToolResult, EvidenceRecord, and their compatibility tests to call `model_validate_json` with the original fixture text or a JSON serialization of a mutated fixture dictionary. This is required before the Decimal wire fixture is introduced: a decoded JSON Decimal string must not be misclassified as typed Python input.

- [ ] **Step 6: Migrate the four synthetic fixtures**

Use these exact replacements:

```json
{"type":"string","value":"security-syn-company"}
{"type":"string","value":"합성전자"}
{"type":"integer","value":5}
{"type":"string","value":"product-syn-etf-a"}
{"type":"decimal","value":"125000000"}
{"type":"tuple","items":[{"type":"string","value":"product-syn-etf-a"}]}
```

Both Evidence AUM fields use the tagged Decimal form. The ToolResult AUM field also uses tagged Decimal; only discrete values such as `top-k` use tagged integer. Preserve all organizer-independent synthetic IDs, units, dates, and hashes.

- [ ] **Step 7: Update direct Python contract construction**

In Evidence/Claim tests, pass `encode_contract_value(...)` or the concrete tagged model rather than a bare polymorphic value. Preserve bare `None` only for `AtomicClaim.value` absence. For the missing-metadata Evidence case, use `NullValue(type="null", value=None)` for both value fields and assert `decode_contract_value(...) is None`; do not assert that the fields themselves are bare None.

Update compatibility mutation payloads to complete tagged objects. The single-cardinality invalid case uses:

```python
{"type": "tuple", "items": [{"type": "string", "value": "security-syn-company"}]}
```

The many-cardinality invalid case uses:

```python
{"type": "string", "value": "product-syn-etf-a"}
```

- [ ] **Step 8: Regenerate the six tagged-value-bearing Schemas**

```bash
.venv/bin/python scripts/export_contract_schemas.py
.venv/bin/python scripts/export_contract_schemas.py --check
git diff --name-only -- schemas/contracts/v1
```

At this task, the changed Schema list must contain exactly QueryPlan, ExecutionGraph, ToolResult, EvidenceRecord, CalculationRecord, and AtomicClaim. ClaimSupport remains unchanged until Task 5.

- [ ] **Step 9: Run all contract tests before global strictness**

Run:

```bash
.venv/bin/python -m pytest tests/contracts -q
```

Expected: all tests pass with tagged values, while global ContractModel strictness is not yet enabled.

- [ ] **Step 10: Commit the wire migration**

```bash
git add \
  src/financial_agent/contracts/base.py \
  src/financial_agent/contracts/__init__.py \
  src/financial_agent/contracts/query.py \
  src/financial_agent/contracts/execution.py \
  src/financial_agent/contracts/evidence.py \
  src/financial_agent/contracts/compatibility.py \
  tests/contracts/conftest.py \
  tests/contracts/test_compatibility.py \
  tests/contracts/test_evidence.py \
  tests/contracts/test_execution.py \
  tests/contracts/test_query.py \
  tests/fixtures/contracts/v1/query_plan.json \
  tests/fixtures/contracts/v1/execution_graph.json \
  tests/fixtures/contracts/v1/tool_result.json \
  tests/fixtures/contracts/v1/evidence_record.json \
  schemas/contracts/v1
git diff --cached --check
git diff --cached
git commit -m "refactor: migrate contracts to tagged values"
```

### Task 3: Enforce strict Python and raw-JSON ingress

**Files:**

- Modify: `src/financial_agent/contracts/base.py`
- Modify: `tests/contracts/test_base.py`
- Modify: `tests/contracts/test_request.py`
- Modify: `tests/contracts/test_query.py`
- Modify: `tests/contracts/test_execution.py`
- Modify: `tests/contracts/test_compatibility.py`
- Modify: `tests/contracts/test_evidence.py`
- Modify: `tests/contracts/test_answer.py`

**Interfaces:**

- Consumes: migrated tagged contracts and existing raw JSON fixtures.
- Produces: one strict ContractModel policy and explicit test helpers for JSON boundaries.

- [ ] **Step 1: Add strictness tests using the raw-JSON helpers from Task 2**

Task 2 already added these helpers to `tests/contracts/conftest.py`:

```python
@pytest.fixture
def load_fixture_json() -> Callable[[str], str]:
    def load(name: str) -> str:
        return (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    return load


@pytest.fixture
def dump_json() -> Callable[[object], str]:
    def dump(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)
    return dump
```

Use them while rewriting `test_base.py` to keep separate JSON-shaped and typed-Python payloads. Add direct proof that raw JSON ISO dates, UTC datetimes, string Enums, and arrays pass through `model_validate_json`, while the equivalent Python strings/lists fail through `model_validate` or model construction. Include negative cases for `"1"` as an integer, `True` as an integer, a date string as a Python date, a datetime string as a Python datetime, and a Python list as a tuple.

- [ ] **Step 2: Run strictness tests before changing ContractModel**

Run:

```bash
.venv/bin/python -m pytest tests/contracts/test_base.py -v
```

Expected: coercion-negative tests fail because ContractModel is still lax.

- [ ] **Step 3: Enable global strict immutable validation**

Change only the shared configuration:

```python
class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )
```

Do not add a lax classmethod or compatibility flag.

- [ ] **Step 4: Convert fixture consumers to raw JSON validation**

For unmodified fixtures, replace:

```python
Model.model_validate(load_fixture("name.json"))
```

with:

```python
Model.model_validate_json(load_fixture_json("name.json"))
```

For mutated fixture dictionaries, keep `load_fixture`, apply the mutation, then call:

```python
Model.model_validate_json(dump_json(payload))
```

Apply this consistently in request, query, execution, compatibility, evidence, and answer tests. Do not feed a decoded external JSON dictionary into strict Python validation.

- [ ] **Step 5: Make direct Python construction genuinely typed**

Use Enum members such as `ClaimType.DIRECT_FACT`, `CalculationType.RANKING`, `SupportKind.DIRECT`, and `AnswerDisposition.ANSWER`. Use `date(2026, 7, 11)` and `datetime(2026, 8, 17, tzinfo=UTC)` for Python model fields. Keep string fields as strings, immutable collections as tuples, and nested contract fields as actual Pydantic objects rather than decoded dictionaries. Continue using `encode_contract_value` for polymorphic values.

The ReleasedAnswer test must use typed metadata:

```python
cutoff_date=date(2026, 7, 11),
created_at=datetime(2026, 8, 17, tzinfo=UTC),
answer_disposition=AnswerDisposition.ANSWER,
claim_bindings=(
    ClaimBinding(
        output_locator="answer:block-summary:slot-ranking",
        claim_ids=("claim-rank-1",),
        evidence_ids=("evidence-aum-1",),
    ),
),
```

- [ ] **Step 6: Verify no fixture dictionary uses the Python ingress path**

Run:

```bash
rg -n "model_validate\((load_fixture|payload)" tests/contracts --glob '!test_base.py'
```

Expected: no matches for fixture or mutated JSON payload validation. Deliberate Python-boundary tests may still call `model_validate` with typed values.

- [ ] **Step 7: Run the complete strict contract suite**

```bash
.venv/bin/python -m pytest tests/contracts -q
```

Expected: all tests pass, including raw JSON fixture parsing and Python coercion rejection.

- [ ] **Step 8: Commit strict ingress**

```bash
git add src/financial_agent/contracts/base.py tests/contracts
git diff --cached --check
git diff --cached
git commit -m "fix: enforce strict contract ingress"
```

### Task 4: Canonicalize only validated models and JSON-native mappings

**Files:**

- Modify: `src/financial_agent/contracts/canonical.py`
- Modify: `tests/contracts/test_canonical.py`

**Interfaces:**

- Consumes: tagged model JSON serializers from Tasks 1-3.
- Produces: unchanged `canonical_json_bytes` and `canonical_sha256` signatures with a narrower, explicit Mapping value policy.

- [ ] **Step 1: Write failing canonical identity and rejection tests**

Add tests that prove:

```python
first = FilterSpec(
    subtask_id="q1",
    field_id="field-aum",
    operator_id="operator-eq",
    value=encode_contract_value(Decimal("1.00")),
)
second = FilterSpec(
    subtask_id="q1",
    field_id="field-aum",
    operator_id="operator-eq",
    value=encode_contract_value(Decimal("1E+0")),
)
text = FilterSpec(
    subtask_id="q1",
    field_id="field-aum",
    operator_id="operator-eq",
    value=encode_contract_value("1"),
)

assert canonical_sha256(first) == canonical_sha256(second)
assert canonical_sha256(first) != canonical_sha256(text)
assert canonical_json_bytes(first) == canonical_json_bytes(first.model_dump(mode="json"))
```

Keep mapping-key order stability and simple `build_request_key` tests. Parameterize rejected schema-less Mapping values over Decimal, date, UTC datetime, Enum, tuple, float, set, unsupported object, and non-string key.

- [ ] **Step 2: Run canonical tests and verify the current gaps**

```bash
.venv/bin/python -m pytest tests/contracts/test_canonical.py -v
```

Expected: tagged Decimal identity tests may already pass because DecimalValue owns its JSON serializer, but rejection tests fail for values such as tuple, float, or string-valued Enum that the current schema-less Mapping path still accepts.

- [ ] **Step 3: Add one recursive JSON-native validator**

Implement a private helper with this exact precedence:

```python
def _json_native(value: object) -> object:
    if isinstance(value, Enum):
        raise TypeError("schema-less mappings cannot contain Enum values")
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return [_json_native(item) for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical mapping keys must be strings")
        return {key: _json_native(item) for key, item in value.items()}
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")
```

Import `Enum`. For BaseModel input, call `model_dump(mode="json", exclude=...)` first and validate that JSON-native result. For Mapping input, validate `dict(value)` directly. Preserve sorted keys, compact separators, UTF-8, `allow_nan=False`, and top-level `exclude_fields` behavior.

- [ ] **Step 4: Run canonical and full contract tests**

```bash
.venv/bin/python -m pytest tests/contracts/test_canonical.py -v
.venv/bin/python -m pytest tests/contracts -q
```

Expected: Decimal-equivalent models hash identically; tagged Decimal and tagged string differ; schema-less typed mappings fail with TypeError.

- [ ] **Step 5: Commit canonical hashing**

```bash
git add src/financial_agent/contracts/canonical.py tests/contracts/test_canonical.py
git diff --cached --check
git diff --cached
git commit -m "fix: canonicalize validated contract values"
```

### Task 5: Close ClaimSupport and Schema/runtime authority gaps

**Files:**

- Modify: `src/financial_agent/contracts/evidence.py`
- Modify: `tests/contracts/test_evidence.py`
- Modify: `tests/contracts/test_schema_export.py`
- Regenerate: `schemas/contracts/v1/claim-support.schema.json`

**Interfaces:**

- Consumes: strict tagged contracts and the existing exact 14-file Schema registry.
- Produces: closed ClaimSupport semantics, Schema parity tests, mutation proof, and byte-current generated Schemas.

- [ ] **Step 1: Write exhaustive ClaimSupport tests**

Test all five SupportKind values. `CALCULATION` with only calculation_id passes. `DIRECT`, `SCOPE`, `EXCLUSION`, and `POLICY` with only evidence_id pass. For each kind, test wrong target, both targets, no target, and `ordinal=-1`. Keep ordinal zero valid.

Add a Schema assertion:

```python
schema = ClaimSupport.model_json_schema(mode="validation")
assert schema["properties"]["ordinal"]["minimum"] == 0
```

- [ ] **Step 2: Run focused ClaimSupport tests and verify failure**

```bash
.venv/bin/python -m pytest tests/contracts/test_evidence.py -k claim_support -v
```

Expected: negative ordinal and support-kind/target mismatches currently pass.

- [ ] **Step 3: Implement field-local and cross-field support rules**

Change the field and validator to:

```python
ordinal: int = Field(ge=0)

@model_validator(mode="after")
def validate_support_target(self) -> "ClaimSupport":
    if self.support_kind is SupportKind.CALCULATION:
        if self.calculation_id is None or self.evidence_id is not None:
            raise ValueError("calculation support requires calculation_id only")
    elif self.evidence_id is None or self.calculation_id is not None:
        raise ValueError("evidence support requires evidence_id only")
    return self
```

Do not add hand-written JSON Schema `if/then` conditions.

- [ ] **Step 4: Add exact Schema freshness mutation tests**

Import `check_schemas` and prove four isolated states:

```python
def test_schema_freshness_accepts_exact_export(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    check_schemas(tmp_path)


def test_schema_freshness_rejects_modified_file(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    target = tmp_path / "query-plan.schema.json"
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        check_schemas(tmp_path)


def test_schema_freshness_rejects_missing_file(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    (tmp_path / "query-plan.schema.json").unlink()
    with pytest.raises(ValueError):
        check_schemas(tmp_path)


def test_schema_freshness_rejects_extra_file(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    (tmp_path / "extra.schema.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        check_schemas(tmp_path)
```

- [ ] **Step 5: Add JSON Schema versus Pydantic authority tests**

Use `Draft202012Validator(..., format_checker=FormatChecker())`. Add one structurally invalid tagged Decimal payload that both validators reject. Add two semantically invalid payloads that structural Schema accepts but Pydantic rejects: a ClaimSupport with `support_kind="calculation"` and only evidence_id, and a RequestContext with valid date syntax but cutoff `2026-07-12`.

Assert the evaluation response Schema still has exactly the five required string properties and `additionalProperties` is false.

- [ ] **Step 6: Run focused Schema tests before regeneration**

```bash
.venv/bin/python -m pytest \
  tests/contracts/test_evidence.py \
  tests/contracts/test_schema_export.py -v
.venv/bin/python scripts/export_contract_schemas.py --check
```

Expected: runtime tests pass after the code change; the committed Schema check fails because generated files are stale.

- [ ] **Step 7: Regenerate and review the exact Schema set**

```bash
.venv/bin/python scripts/export_contract_schemas.py
.venv/bin/python scripts/export_contract_schemas.py --check
git diff --name-only -- schemas/contracts/v1
```

At this task, the uncommitted changed list must be exactly:

```text
schemas/contracts/v1/claim-support.schema.json
```

Confirm the other thirteen Schema files, especially `evaluation-api-response.schema.json`, have no new diff in this task. The six tagged-value-bearing Schemas were already reviewed and committed in Task 2.

- [ ] **Step 8: Run the complete contract suite and commit**

```bash
.venv/bin/python -m pytest tests/contracts -q
.venv/bin/python scripts/export_contract_schemas.py --check
git add src/financial_agent/contracts/evidence.py tests/contracts/test_evidence.py tests/contracts/test_schema_export.py schemas/contracts/v1
git diff --cached --check
git diff --cached
git commit -m "test: close contract schema boundaries"
```

### Task 6: Verify, freeze, and hand Stage 01 to NCP and Stage 02

**Files:**

- Modify after all verification passes: `docs/planning/STATUS.md`
- Modify after all verification passes: `docs/planning/specs/2026-08-18-stage-01-closure-hardening-design.md`
- Modify after all verification passes: `docs/planning/tasks/2026-08-17-stage-01-runtime-contracts-implementation-plan.md`
- Modify after all verification passes: `docs/planning/tasks/2026-08-18-stage-01-closure-hardening-implementation-plan.md`

**Interfaces:**

- Consumes: all five verified implementation commits and the locked container build.
- Produces: final Stage 01 freeze evidence and an explicit Stage 02 entry gate.

- [ ] **Step 1: Run fresh host verification**

```bash
.venv/bin/python -m pytest tests/contracts -q
.venv/bin/python scripts/export_contract_schemas.py --check
.venv/bin/python -m compileall -q src/financial_agent scripts tests/contracts
git diff --check
```

Record the exact passed test count. Any failure keeps Stage 01 open.

- [ ] **Step 2: Build and run the locked Linux/amd64 image locally**

```bash
docker build --platform linux/amd64 -f docker/contracts.Dockerfile -t financial-agent-contracts:stage-01 .
docker run --rm --platform linux/amd64 financial-agent-contracts:stage-01
```

Both commands must exit zero. The build itself reruns contract tests and Schema freshness inside the image.

- [ ] **Step 3: Inspect repository scope before push**

```bash
git status --short
git diff --check
git log --oneline origin/codex/financial-agent-core..HEAD
git diff --name-only origin/codex/financial-agent-core..HEAD
```

Verify that no path under `data/`, no organizer PDF/workbook, no `.env`, secret, database, Parquet, embedding, cache, log, or runtime output is committed. Leave unrelated `.gstack/` untracked.

The Schema paths in the branch-wide diff must be exactly the seven files listed in the success criteria: the six tagged-value-bearing Schemas from Task 2 and ClaimSupport from Task 5.

- [ ] **Step 4: Push the verified task branch for NCP reproduction**

```bash
git push origin codex/financial-agent-core
```

Do not merge to main or deploy the application service.

- [ ] **Step 5: Rebuild the exact branch on the NCP Ubuntu host**

On the NCP server repository:

```bash
git fetch origin codex/financial-agent-core
git switch codex/financial-agent-core
git pull --ff-only origin codex/financial-agent-core
git rev-parse HEAD
sudo docker build --no-cache --platform linux/amd64 -f docker/contracts.Dockerfile -t financial-agent-contracts:stage-01 .
sudo docker run --rm --platform linux/amd64 financial-agent-contracts:stage-01
echo $?
```

Require the pulled commit to match the pushed HEAD and the final exit code to be `0`. A build or run failure must be fixed and rerun on both host and NCP; it cannot be documented as completion.

- [ ] **Step 6: Record actual completion evidence and freeze Stage 01**

Only after NCP exit zero:

- change this plan status to `Complete`;
- change the closure design status to `Implemented and verified`;
- close the six-item Stage 01 review register in the original Stage 01 plan;
- update STATUS with the host test count, Schema check, local image result, NCP commit SHA, and NCP exit zero;
- state that the Stage 01 tagged fields and generated Schemas are frozen inputs to Stage 02;
- retain the mandatory future Claim Gate Registry note.

- [ ] **Step 7: Commit and push the completion record**

```bash
git add \
  docs/planning/STATUS.md \
  docs/planning/specs/2026-08-18-stage-01-closure-hardening-design.md \
  docs/planning/tasks/2026-08-17-stage-01-runtime-contracts-implementation-plan.md \
  docs/planning/tasks/2026-08-18-stage-01-closure-hardening-implementation-plan.md
git diff --cached --check
git diff --cached
git commit -m "docs: complete stage 01 contract freeze"
git push origin codex/financial-agent-core
```

## Final Review Checklist

- [ ] All ten polymorphic fields use the tagged wire representation.
- [ ] No old untagged fixture value remains.
- [ ] Decimal JSON is a canonical pattern-constrained string and Python holds Decimal.
- [ ] JSON number under the Decimal tag fails.
- [ ] Date/datetime-looking strings remain StringValue when tagged as string.
- [ ] NullValue and AtomicClaim absence remain distinct.
- [ ] TupleValue is flat and every item is tagged.
- [ ] Python coercion fails while raw JSON dates, datetimes, Enums, and arrays work.
- [ ] Canonical model hashing is stable and schema-less typed Mapping values fail.
- [ ] ClaimSupport kind, target, and ordinal rules pass exhaustive tests.
- [ ] JSON Schema and Pydantic authority are tested separately.
- [ ] Schema freshness detects exact, modified, missing, and extra states.
- [ ] Exactly seven expected Schema files changed and the evaluation API Schema did not.
- [ ] Host, container, and NCP checks all pass with the locked dependencies.
- [ ] No protected data or generated runtime artifact is committed.
- [ ] Stage 02 references the Stage 01 value types and contains no second Python codec.
- [ ] Claim Gate Registry remains explicitly mandatory and unimplemented.
