# Stage 01 Runtime Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-08-17

**Status:** Complete; runtime contracts frozen for Stage 02 after closure hardening and NCP verification

**Goal:** Create the executable, immutable, schema-exportable runtime contracts that every later data, ontology, orchestration, verification, rendering, API, and Naver Cloud component must use.

**Architecture:** Use a small Python 3.12 package containing strict Pydantic v2 domain models. Separate request planning, execution, evidence, verification, and answer contracts into focused modules; keep financial execution and persistence out of this stage. Export deterministic JSON Schemas and validate the same package in a Linux/amd64 container so later Naver Cloud deployment does not depend on a developer's macOS environment.

**Tech Stack:** Python 3.12, Pydantic 2.x, pytest 8.x, jsonschema 4.x, standard-library `hashlib`/`json`/`unicodedata`, Docker with a Python 3.12 slim Linux image.

### Approved 2026-08-18 container-hardening amendment

The Naver Cloud host runs Ubuntu, while the Stage 01 verification image keeps a portable Linux/amd64 Python slim userland. The host distribution does not require changing the container base image. Container verification must install the exact contract runtime and test dependency graph recorded in `requirements/contracts.lock`; any lock refresh is an explicit reviewed change. A repository-root `.dockerignore` must keep Git metadata, organizer data, secrets, local databases, virtual environments, caches, logs, and generated outputs out of the Docker build context. This amendment does not implement the final Agent API image or change any public runtime contract.

### Approved 2026-08-18 execution-contract-hardening amendment

`ExecutionTask` adds `subtask_id` and `produces_bindings` so the Orchestrator can prove which QueryPlan subtask owns each compiled task and which task uniquely produces each intermediate result. Local graph validation must reject undeclared, duplicate, self-consumed, incorrectly owned, or dependency-disconnected bindings and reject a critical path whose consecutive tasks are not directly connected or whose serial budget exceeds `total_budget_ms`. Deterministic cross-artifact validation must prove QueryPlan–ExecutionGraph identity, subtask, operation, capability, and binding-spec compatibility, then prove ExecutionGraph–ToolResult task, result-type, binding-type, and cardinality compatibility. Error and empty ToolResult states cannot carry successful rows or binding values.

The exact implementation sequence is defined in [Stage 01 Execution Contract Hardening Plan](2026-08-18-stage-01-execution-contract-hardening-plan.md). This amendment changes internal Stage 01 schema fields before the Stage 02 freeze; it does not change the organizer-facing five-string evaluation API.

## Implementation Status at 2026-08-18

- Tasks 1–7 were implemented in commits `c5d387d` through `36ffa82`.
- AnswerPlan's Stage 01 structural boundary was locked in `4dc6c30`; Claim Gate Registry compatibility remains a mandatory later-layer check.
- Dependency locking and Docker build-context protection were added in `69998f5`.
- The verification image was corrected to include its own Dockerfile and `.dockerignore` test inputs in `822fbf0`.
- The execution-contract hardening amendment was implemented in `60de716`; the host passed 116 contract tests and the Schema freshness check.
- NCP Ubuntu/Linux-amd64 verification of `60de716` completed successfully: the image build completed its locked install, full contract suite, and Schema check, and the container command exited with code 0.
- Closure hardening was implemented in `57ce82e`∼`b5f42e7`; the host passed 224 contract tests and NCP commit `b5f42e777d7edb13f980a19bc531a360a3209b85` exited 0 in the locked Linux/amd64 verification container.
- The development Mac had no Docker runtime. The user explicitly approved the successful NCP no-cache Linux/amd64 rebuild and run as the duplicate local-container verification substitute.
- Stage 01 is complete. Its tagged value fields, public contract names, and 14 generated Schemas are frozen inputs to Stage 02.

**Authoritative design references:**

- [Planning Harness](../HARNESS.md)
- [Runtime Contracts](../architecture/RUNTIME_CONTRACTS.md)
- [Evidence, Verification, and Rendering](../architecture/EVIDENCE_VERIFICATION_AND_RENDERING.md)
- [Failure and Disposition Policy](../architecture/FAILURE_AND_DISPOSITION_POLICY.md)
- [NCP Deployment Architecture](../architecture/NCP_DEPLOYMENT_ARCHITECTURE.md)
- [ADR-0005](../decisions/ADR-0005-bounded-llm-typed-capability-execution.md)
- [ADR-0006](../decisions/ADR-0006-separate-disposition-and-bound-recovery.md)
- [ADR-0007](../decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md)

## Global Constraints

- The contract cutoff is exactly `2026-07-11`. Do not replace an older observation date with the cutoff date.
- All public contract models reject unknown fields and are immutable after construction.
- Runtime artifact collections use immutable tuples. JSON arrays remain valid input and are normalized to tuples by Pydantic.
- Arbitrary mutable JSON objects are not contract field values. Structured parameters use immutable tuples of named values.
- `RequestContext`, `QueryPlan`, `ExecutionGraph`, `ToolResult`, `EvidenceBundle`, `VerificationReport`, `AnswerPlan`, and `ReleasedAnswer` share the approved runtime metadata.
- `SourceRecord`, `EvidenceRecord`, `CalculationRecord`, `AtomicClaim`, and `ClaimSupport` are ledger-domain contracts, not ORM models in this stage.
- `candidate_claim_ids` and `releaseable_claim_ids` are different fields with different lifecycle meanings.
- Do not introduce `AnswerDraft`, `allowed_claims`, a mixed disposition Enum, raw chain-of-thought, executable SQL/SPARQL, arbitrary formulas, or Composer-authored factual strings.
- Monetary and financial numeric values use `Decimal`, never binary floating-point, after deterministic normalization.
- This stage does not implement PostgreSQL DDL, ingestion, retrieval, calculations, ontology, Graph, Vector, HyperCLOVA X, FastAPI, or the public `/answer` endpoint.
- Do not read or commit organizer workbooks. Tests use synthetic IDs and values only.
- The package must install and run on Linux/amd64 Python 3.12, which is the baseline for the Naver Cloud Agent API container.
- Do not hardcode `/Users/...`, local workspace paths, NCP account identifiers, endpoints, credentials, or secrets.
- Generated JSON Schemas are tracked; caches, wheels, virtual environments, raw data, databases, and generated runtime outputs remain untracked.
- The verification container installs with `requirements/contracts.lock` as a mandatory pip constraint. Do not widen or refresh a pin without reviewing the resulting schemas and full contract test output.
- `.dockerignore` must enforce the repository data policy at the Docker build-context boundary; explicit `COPY` instructions are not a substitute because ignored local files can otherwise still be sent to the Docker daemon.
- Every task follows test-first implementation and ends in an independently reviewable commit.

---

## Planned File Structure

```text
.dockerignore
.python-version
pyproject.toml
requirements/
└─ contracts.lock
docker/
└─ contracts.Dockerfile
schemas/
└─ contracts/
   └─ v1/
      ├─ request-context.schema.json
      ├─ query-plan.schema.json
      ├─ execution-graph.schema.json
      ├─ tool-result.schema.json
      ├─ source-record.schema.json
      ├─ evidence-record.schema.json
      ├─ calculation-record.schema.json
      ├─ atomic-claim.schema.json
      ├─ claim-support.schema.json
      ├─ evidence-bundle.schema.json
      ├─ verification-report.schema.json
      ├─ answer-plan.schema.json
      ├─ released-answer.schema.json
      └─ evaluation-api-response.schema.json
scripts/
└─ export_contract_schemas.py
src/
└─ financial_agent/
   ├─ __init__.py
   └─ contracts/
      ├─ __init__.py
      ├─ answer.py
      ├─ base.py
      ├─ canonical.py
      ├─ enums.py
      ├─ evidence.py
      ├─ execution.py
      ├─ query.py
      ├─ request.py
      ├─ schema_export.py
      └─ validation.py
tests/
├─ __init__.py
├─ contracts/
│  ├─ __init__.py
│  ├─ conftest.py
│  ├─ test_answer.py
│  ├─ test_base.py
│  ├─ test_canonical.py
│  ├─ test_evidence.py
│  ├─ test_execution.py
│  ├─ test_query.py
│  ├─ test_request.py
│  └─ test_schema_export.py
└─ fixtures/
   └─ contracts/
      └─ v1/
         ├─ answer_plan.json
         ├─ evidence_record.json
         ├─ evidence_bundle.json
         ├─ execution_graph.json
         ├─ query_plan.json
         ├─ request_context.json
         ├─ tool_result.json
         └─ verification_report.json
```

## Synthetic Fixture Baseline

All seven runtime fixtures describe one synthetic request and use these exact shared values:

| Field | Value |
| --- | --- |
| `question_id` | `Q-SYN-001` |
| `question` | `합성전자 편입 ETF를 AUM순으로 5개 알려줘. 이 상품들 중 수익률이 가장 높은 상품을 알려줘.` |
| `schema_version` | `1.0` |
| `request_key` | `5fb658a65798ff794b8f3ac0414da936ecd806469109317e2a27c11e513d78b4` |
| `run_id` | `run-syn-001` |
| `dataset_version` | `2026-07-11-v1` |
| `cutoff_date` | `2026-07-11` |
| `created_at` | `2026-08-17T00:00:00Z` |
| `deadline_at` | `2026-08-17T00:00:55Z` |
| synthetic product | `product-syn-etf-a` |
| synthetic security | `security-syn-company` |
| ranking Claim | `claim-rank-1` |

`request_context.json` uses two ordered segments. Segment `s2` is `이 상품들 중 수익률이 가장 높은 상품을 알려줘.` and its `ReferenceMention` has `text="이 상품들"`, `start_char=0`, and exclusive `end_char=5`. Hash-only fixture fields that are not semantically recalculated in Stage 01 use these exact values: `result_hash="b"*64`, `record_hash="c"*64`, `calculation_hash="d"*64`, `claim_hash="e"*64`, `bundle_hash="f"*64`, `plan_hash="0"*64`, `response_hash="1"*64`, `content_checksum="2"*64`, and `population_hash="3"*64`. In actual JSON files, write the repeated 64-character string, not the Python multiplication expression.

## Contract Boundary Map

| Module | Owns | Must not own |
| --- | --- | --- |
| `base.py` | strict immutable base classes, runtime metadata, shared scalar/value/ID aliases | domain Enums, hashes, business verification |
| `enums.py` | every approved finite vocabulary used by contracts | display labels, database codes not approved by contracts |
| `canonical.py` | question normalization, canonical JSON bytes, SHA-256 hashes | financial formulas, response rendering |
| `validation.py` | reusable unique-ID, reference, and DAG validation helpers | orchestration or retries |
| `request.py` | raw single-request context and surface mentions | entity resolution results, prior request state |
| `query.py` | typed intent, references, filters, metrics, operations, dependencies | SQL, SPARQL, Python expressions |
| `execution.py` | allowed execution DAG and typed tool results | tool dispatch or calculations |
| `evidence.py` | ledger-domain records, bundles, deterministic check results | ORM mappings, persistence, verifier execution |
| `answer.py` | verification report, structured answer plan, released/API response | Composer factual strings in `AnswerPlan` |

## Public Interface Freeze

The following imports are the Stage 01 public symbol boundary. Their names remain stable. Field-level schemas become frozen only after the 2026-08-18 execution-contract amendment passes the revised Stage 01 completion gate and the schemas are freshly exported. Later stages may add models without renaming these symbols unless an approved ADR changes the contract.

```python
from financial_agent.contracts import (
    RequestContext,
    QueryPlan,
    ExecutionGraph,
    ToolResult,
    SourceRecord,
    EvidenceRecord,
    CalculationRecord,
    AtomicClaim,
    ClaimSupport,
    EvidenceBundle,
    CheckResult,
    VerificationReport,
    AnswerPlan,
    ReleasedAnswer,
    EvaluationApiResponse,
    build_request_key,
    canonical_sha256,
)
```

### Task 1: Bootstrap the NCP-portable contract package and strict base models

**Files:**

- Create: `.python-version`
- Create: `pyproject.toml`
- Create: `src/financial_agent/__init__.py`
- Create: `src/financial_agent/contracts/__init__.py`
- Create: `src/financial_agent/contracts/base.py`
- Create: `tests/contracts/test_base.py`

**Interfaces:**

- Consumes: Python 3.12 only.
- Produces: `CONTRACT_SCHEMA_VERSION`, `SNAPSHOT_CUTOFF`, `ContractModel`, `RuntimeArtifact`, `Identifier`, `Sha256Hex`, `UtcDateTime`, `ScalarValue`, `ContractValue`.

- [ ] **Step 1: Write the failing strictness, immutability, UTC, and cutoff tests**

```python
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from financial_agent.contracts.base import RuntimeArtifact


class ExampleArtifact(RuntimeArtifact):
    value: str


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "request_key": "a" * 64,
        "run_id": "run-001",
        "dataset_version": "2026-07-11-v1",
        "cutoff_date": "2026-07-11",
        "producer": "test",
        "created_at": "2026-08-17T00:00:00Z",
        "value": "ok",
    }


def test_runtime_artifact_rejects_unknown_fields() -> None:
    payload = valid_payload() | {"unknown": True}
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(payload)


def test_runtime_artifact_is_frozen() -> None:
    artifact = ExampleArtifact.model_validate(valid_payload())
    with pytest.raises(ValidationError):
        artifact.value = "changed"


@pytest.mark.parametrize("bad_cutoff", ["2026-07-10", "2026-07-12"])
def test_runtime_artifact_requires_fixed_cutoff(bad_cutoff: str) -> None:
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(valid_payload() | {"cutoff_date": bad_cutoff})


def test_runtime_artifact_rejects_naive_created_at() -> None:
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(
            valid_payload() | {"created_at": datetime(2026, 8, 17)}
        )


def test_runtime_artifact_rejects_non_utc_created_at() -> None:
    with pytest.raises(ValidationError):
        ExampleArtifact.model_validate(
            valid_payload() | {"created_at": "2026-08-17T09:00:00+09:00"}
        )


def test_runtime_artifact_accepts_utc_created_at() -> None:
    artifact = ExampleArtifact.model_validate(valid_payload())
    assert artifact.created_at == datetime(2026, 8, 17, tzinfo=UTC)
    assert artifact.cutoff_date == date(2026, 7, 11)
```

- [ ] **Step 2: Run the test and verify the package does not exist**

Run: `python -m pytest tests/contracts/test_base.py -v`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'financial_agent'`.

- [ ] **Step 3: Create the minimal package metadata**

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "financial-product-agent"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "pydantic>=2.10,<3",
]

[project.optional-dependencies]
dev = [
  "jsonschema>=4.23,<5",
  "pytest>=8,<9",
]

[tool.pytest.ini_options]
addopts = "-ra --strict-config --strict-markers"
testpaths = ["tests"]

[tool.setuptools.packages.find]
where = ["src"]
```

Set `.python-version` to exactly:

```text
3.12
```

Set `src/financial_agent/__init__.py` to:

```python
"""Financial Product Agent core package."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Implement the strict base contracts**

```python
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, TypeAlias

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

CONTRACT_SCHEMA_VERSION = "1.0"
SNAPSHOT_CUTOFF = date(2026, 7, 11)

Identifier = Annotated[
    str,
    Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must use UTC")
    return value


UtcDateTime = Annotated[datetime, AfterValidator(require_utc)]
ScalarValue: TypeAlias = str | int | Decimal | bool | date | UtcDateTime | None
ContractValue: TypeAlias = ScalarValue | tuple[ScalarValue, ...]


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class RuntimeArtifact(ContractModel):
    schema_version: Literal["1.0"] = CONTRACT_SCHEMA_VERSION
    request_key: Sha256Hex
    run_id: Identifier
    dataset_version: Identifier
    cutoff_date: date = SNAPSHOT_CUTOFF
    producer: Identifier
    created_at: UtcDateTime

    @field_validator("cutoff_date")
    @classmethod
    def validate_cutoff(cls, value: date) -> date:
        if value != SNAPSHOT_CUTOFF:
            raise ValueError("cutoff_date must be 2026-07-11")
        return value

```

Do not strip or normalize arbitrary strings in `ContractModel`. In particular, `RequestContext.question` must preserve the organizer's original request. `normalize_question()` is used only when computing `request_key`.

Export only implemented public symbols from `contracts/__init__.py` at this point.

- [ ] **Step 5: Install and run the focused test**

Run: `python -m pip install -e '.[dev]'`

Run: `python -m pytest tests/contracts/test_base.py -v`

Expected: all base-contract tests PASS.

- [ ] **Step 6: Commit the package base**

```bash
git add .python-version pyproject.toml src/financial_agent tests/contracts/test_base.py
git diff --cached --check
git commit -m "feat: bootstrap strict runtime contracts"
```

### Task 2: Freeze approved Enums, canonical JSON, and request keys

**Files:**

- Create: `src/financial_agent/contracts/enums.py`
- Create: `src/financial_agent/contracts/canonical.py`
- Modify: `src/financial_agent/contracts/__init__.py`
- Create: `tests/contracts/test_canonical.py`

**Interfaces:**

- Consumes: `ContractModel`, `RuntimeArtifact`.
- Produces: approved Enum classes, `normalize_question(question: str) -> str`, `build_request_key(question_id: str, question: str, dataset_version: str, schema_version: str) -> str`, `canonical_json_bytes(value, exclude_fields=()) -> bytes`, `canonical_sha256(value, exclude_fields=()) -> str`.

- [ ] **Step 1: Write failing canonicalization tests**

```python
from financial_agent.contracts.canonical import (
    build_request_key,
    canonical_sha256,
    normalize_question,
)


def test_normalize_question_is_unicode_and_whitespace_stable() -> None:
    assert normalize_question("  삼성전자\u3000ETF\n질문 ") == "삼성전자 ETF 질문"


def test_request_key_changes_with_dataset_version() -> None:
    first = build_request_key("Q-001", "삼성전자 ETF", "2026-07-11-v1", "1.0")
    second = build_request_key("Q-001", "삼성전자 ETF", "2026-07-11-v2", "1.0")
    assert first != second
    assert len(first) == 64


def test_canonical_hash_ignores_mapping_order() -> None:
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})
```

- [ ] **Step 2: Run the test and verify missing modules**

Run: `python -m pytest tests/contracts/test_canonical.py -v`

Expected: FAIL during collection because `canonical.py` does not exist.

- [ ] **Step 3: Implement the exact approved finite vocabularies**

Create `enums.py` with `str, Enum` classes containing these exact values:

Enum member names are the uppercase form of their values. For example, `ToolStatus.EMPTY = "empty"`, `AnswerDisposition.ABSTAIN = "abstain"`, and `ReferenceMentionType.ELLIPSIS = "ellipsis"`.

```text
InteractionMode: competition
EntityResolutionStatus: unresolved, resolved, ambiguous, not_found, invalid_at_cutoff
IntentType: lookup, screen, rank, compare, aggregate, calculate, similar, explain
ProductFamily: domestic_bond, domestic_etf, overseas_etf, public_fund
SubtaskImportance: critical, required_independent, optional
InitialAnswerability: supported, requires_normalization, requires_additional_data, unsupported
Capability: rdb_lookup, graph_traversal, keyword_search, vector_search, financial_calculation, ranking, similarity, comparison
ToolStatus: success, empty, unsupported, invalid_input, timeout, transient_error, permanent_error
ResultType: row_set, scalar, entity_ref, relation_path, calculation, comparison_decision
ExecutionOutcome: completed, completed_with_failures, failed
VerificationStatus: pass, fail
AnswerDisposition: answer, partial, limitation, abstain
EvidenceKind: observation, relation, document_span, query_scope, exclusion, policy
CutoffStatus: eligible, after_cutoff, unknown_vintage, inapplicable
CalculationType: conversion, return, ranking, aggregation, comparison, similarity
ClaimType: direct_fact, relation, derived_metric, rank, similarity, no_match, data_limitation, policy_boundary
SupportKind: direct, calculation, scope, exclusion, policy
CheckStatus: pass, fail, warning, not_applicable
CheckTargetType: claim, evidence, calculation, subtask
Repairability: none, ledger_rebuild, llm_repair
BlockType: summary, fact_list, table, comparison, calculation, limitation, abstention
ResultShape: single_value, product_list, top_k, comparison_table, explanation
ReferenceTargetKind: entity_mention, binding
ReferenceMentionType: explicit, ellipsis
Cardinality: one, many
```

Do not add user-facing Korean labels to these Enums. Display labels belong to the later Renderer registry.

- [ ] **Step 4: Implement canonical serialization and SHA-256**

```python
import hashlib
import json
import unicodedata
from collections.abc import Collection, Mapping
from typing import Any

from pydantic import BaseModel


def normalize_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question)
    return " ".join(normalized.split())


def canonical_json_bytes(
    value: BaseModel | Mapping[str, Any],
    *,
    exclude_fields: Collection[str] = (),
) -> bytes:
    payload = (
        value.model_dump(mode="json", exclude=set(exclude_fields))
        if isinstance(value, BaseModel)
        else dict(value)
    )
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(
    value: BaseModel | Mapping[str, Any],
    *,
    exclude_fields: Collection[str] = (),
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(value, exclude_fields=exclude_fields)
    ).hexdigest()


def build_request_key(
    question_id: str,
    question: str,
    dataset_version: str,
    schema_version: str,
) -> str:
    payload = {
        "dataset_version": dataset_version,
        "question": normalize_question(question),
        "question_id": question_id,
        "schema_version": schema_version,
    }
    return canonical_sha256(payload)
```

- [ ] **Step 5: Run the canonical and base tests**

Run: `python -m pytest tests/contracts/test_base.py tests/contracts/test_canonical.py -v`

Expected: all base and canonicalization tests PASS.

- [ ] **Step 6: Commit the stable vocabulary and hashes**

```bash
git add src/financial_agent/contracts tests/contracts/test_canonical.py
git diff --cached --check
git commit -m "feat: define contract vocabulary and hashes"
```

### Task 3: Implement RequestContext and QueryPlan without executable model output

**Files:**

- Create: `src/financial_agent/contracts/validation.py`
- Create: `src/financial_agent/contracts/request.py`
- Create: `src/financial_agent/contracts/query.py`
- Modify: `src/financial_agent/contracts/__init__.py`
- Create: `tests/contracts/test_request.py`
- Create: `tests/contracts/test_query.py`
- Create: `tests/fixtures/contracts/v1/request_context.json`
- Create: `tests/fixtures/contracts/v1/query_plan.json`

**Interfaces:**

- Consumes: runtime metadata, approved Enums, immutable `ContractValue`.
- Produces: `Segment`, `NamedEntityMention`, `ReferenceMention`, `RequestContext`, `Subtask`, `EntityResolutionRequest`, `ResolvedReference`, `BindingSpec`, `DependencyEdge`, `FilterSpec`, `MetricSpec`, `OperationSpec`, `AmbiguityDecision`, `QueryPlan`.

- [ ] **Step 1: Write failing request-context tests**

Test the following exact invariants:

```python
def test_request_context_owns_all_segments_and_surface_mentions(load_fixture) -> None:
    context = RequestContext.model_validate(load_fixture("request_context.json"))
    assert [segment.segment_id for segment in context.segments] == ["s1", "s2"]
    assert context.reference_mentions[0].text == "이 상품들"


def test_request_context_rejects_unknown_segment_reference(load_fixture) -> None:
    payload = load_fixture("request_context.json")
    payload["reference_mentions"][0]["segment_id"] = "missing"
    with pytest.raises(ValidationError):
        RequestContext.model_validate(payload)


def test_request_context_deadline_is_at_most_55_seconds(load_fixture) -> None:
    payload = load_fixture("request_context.json")
    payload["deadline_at"] = "2026-08-17T00:00:56Z"
    with pytest.raises(ValidationError):
        RequestContext.model_validate(payload)
```

The fixture must use only synthetic identifiers and this question:

```text
합성전자 편입 ETF를 AUM순으로 5개 알려줘. 이 상품들 중 수익률이 가장 높은 상품을 알려줘.
```

- [ ] **Step 2: Run request tests and verify they fail**

Run: `python -m pytest tests/contracts/test_request.py -v`

Expected: FAIL because `RequestContext` is not defined.

- [ ] **Step 3: Implement RequestContext and its nested models**

Create `tests/__init__.py` and `tests/contracts/__init__.py` as empty package markers. Create `tests/contracts/conftest.py` with this shared synthetic fixture loader:

```python
import json
from collections.abc import Callable
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "contracts" / "v1"


@pytest.fixture
def load_fixture() -> Callable[[str], dict[str, object]]:
    def load(name: str) -> dict[str, object]:
        return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))

    return load
```

Use these exact fields:

```python
class Segment(ContractModel):
    segment_id: Identifier
    ordinal: int
    text: str


class NamedEntityMention(ContractModel):
    mention_id: Identifier
    segment_id: Identifier
    text: str
    expected_entity_types: tuple[Identifier, ...]
    resolution_status: EntityResolutionStatus = EntityResolutionStatus.UNRESOLVED


class ReferenceMention(ContractModel):
    mention_id: Identifier
    segment_id: Identifier
    text: str
    start_char: int
    end_char: int


class RequestContext(RuntimeArtifact):
    question_id: str
    question: str
    mode: InteractionMode = InteractionMode.COMPETITION
    segments: tuple[Segment, ...]
    named_entities: tuple[NamedEntityMention, ...] = ()
    reference_mentions: tuple[ReferenceMention, ...] = ()
    deadline_at: UtcDateTime
```

Add one `model_validator(mode="after")` that enforces:

1. Segment IDs and mention IDs are unique.
2. Segment ordinals equal `0..n-1` in tuple order.
3. Every mention references an existing segment, its character range is within that segment, and the sliced text equals `ReferenceMention.text`.
4. `created_at < deadline_at <= created_at + 55 seconds`.
5. `question_id` and `question` are not empty after stripping.
6. `request_key` equals `build_request_key(question_id, question, dataset_version, schema_version)` without modifying `question`.

- [ ] **Step 4: Write failing QueryPlan reference and DAG tests**

```python
def test_query_plan_binds_ellipsis_to_preceding_output(load_fixture) -> None:
    plan = QueryPlan.model_validate(load_fixture("query_plan.json"))
    binding = plan.resolved_references[0]
    assert binding.mention_type is ReferenceMentionType.ELLIPSIS
    assert binding.target_kind is ReferenceTargetKind.BINDING
    assert binding.target_id == "s1.top5_products"


def test_query_plan_rejects_cycle(load_fixture) -> None:
    payload = load_fixture("query_plan.json")
    payload["dependency_edges"].append(
        {"upstream_subtask_id": "q2", "downstream_subtask_id": "q1"}
    )
    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)


def test_query_plan_contains_no_executable_query_fields() -> None:
    schema_text = json.dumps(QueryPlan.model_json_schema())
    for forbidden in ("sql", "sparql", "python_expression", "formula_text"):
        assert forbidden not in schema_text.lower()
```

- [ ] **Step 5: Implement reusable graph validation**

`validation.py` must expose:

```python
from collections import defaultdict, deque
from collections.abc import Collection, Iterable


def require_unique_ids(ids: Iterable[str], *, label: str) -> None:
    values = list(ids)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} contains duplicate IDs")

def require_known_ids(
    referenced: Iterable[str],
    available: Collection[str],
    *,
    label: str,
) -> None:
    unknown = sorted(set(referenced) - set(available))
    if unknown:
        raise ValueError(f"{label} contains unknown IDs: {unknown}")

def require_acyclic_edges(
    node_ids: Collection[str],
    edges: Iterable[tuple[str, str]],
) -> None:
    nodes = set(node_ids)
    edge_list = list(edges)
    require_unique_ids(
        (f"{left}->{right}" for left, right in edge_list),
        label="edges",
    )

    adjacency: dict[str, set[str]] = defaultdict(set)
    indegree = {node: 0 for node in nodes}
    for left, right in edge_list:
        require_known_ids((left, right), nodes, label="edge")
        if left == right:
            raise ValueError("self dependency is not allowed")
        adjacency[left].add(right)
        indegree[right] += 1

    ready = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    processed = 0
    while ready:
        node = ready.popleft()
        processed += 1
        for target in sorted(adjacency[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    if processed != len(nodes):
        raise ValueError("dependency graph contains a cycle")
```

Implement `require_acyclic_edges` with Kahn's algorithm. Raise `ValueError` for an unknown node, self-edge, duplicate edge, or when the processed-node count differs from the node count.

- [ ] **Step 6: Implement the QueryPlan model family**

Use these exact fields and no free-form executable fields:

```python
class Subtask(ContractModel):
    subtask_id: Identifier
    intent_type: IntentType
    importance: SubtaskImportance
    operation_ids: tuple[Identifier, ...]


class EntityResolutionRequest(ContractModel):
    resolution_request_id: Identifier
    mention_id: Identifier
    expected_entity_types: tuple[Identifier, ...]


class ResolvedReference(ContractModel):
    reference_id: Identifier
    segment_id: Identifier
    mention_type: ReferenceMentionType
    target_kind: ReferenceTargetKind
    target_id: Identifier


class BindingSpec(ContractModel):
    binding_name: Identifier
    value_type: Identifier
    producer_subtask_id: Identifier
    cardinality: Cardinality


class DependencyEdge(ContractModel):
    upstream_subtask_id: Identifier
    downstream_subtask_id: Identifier


class FilterSpec(ContractModel):
    subtask_id: Identifier
    field_id: Identifier
    operator_id: Identifier
    value: ContractValue


class MetricSpec(ContractModel):
    subtask_id: Identifier
    metric_id: Identifier
    period_id: Identifier | None = None
    unit_id: Identifier | None = None
    currency: str | None = None
    return_type_id: Identifier | None = None


class OperationSpec(ContractModel):
    subtask_id: Identifier
    operation_id: Identifier
    parameter_ids: tuple[Identifier, ...] = ()


class AmbiguityDecision(ContractModel):
    issue_code: Identifier
    policy_id: Identifier
    outcome_id: Identifier
    disclosure_required: bool


class QueryPlan(RuntimeArtifact):
    intent_types: tuple[IntentType, ...]
    product_families: tuple[ProductFamily, ...]
    subtasks: tuple[Subtask, ...]
    entity_resolution_requests: tuple[EntityResolutionRequest, ...] = ()
    resolved_references: tuple[ResolvedReference, ...] = ()
    binding_specs: tuple[BindingSpec, ...] = ()
    dependency_edges: tuple[DependencyEdge, ...] = ()
    filters: tuple[FilterSpec, ...] = ()
    metrics: tuple[MetricSpec, ...] = ()
    operations: tuple[OperationSpec, ...]
    result_shape: ResultShape
    ambiguity_decisions: tuple[AmbiguityDecision, ...] = ()
    requested_capabilities: tuple[Capability, ...]
    initial_answerability: InitialAnswerability
```

The `QueryPlan` validator must verify unique subtask, binding, operation, and reference IDs; every nested `subtask_id` exists; every dependency endpoint exists; binding producers exist; resolved binding targets exist; and the dependency graph is acyclic.

- [ ] **Step 7: Run the request and query contract tests**

Run: `python -m pytest tests/contracts/test_request.py tests/contracts/test_query.py -v`

Expected: all request and query tests PASS.

- [ ] **Step 8: Commit the planning boundary**

```bash
git add src/financial_agent/contracts tests/__init__.py tests/contracts tests/fixtures/contracts/v1
git diff --cached --check
git commit -m "feat: add request and query contracts"
```

### Task 4: Implement the deterministic execution graph and typed tool result

**Files:**

- Create: `src/financial_agent/contracts/execution.py`
- Modify: `src/financial_agent/contracts/__init__.py`
- Create: `tests/contracts/test_execution.py`
- Create: `tests/fixtures/contracts/v1/execution_graph.json`
- Create: `tests/fixtures/contracts/v1/tool_result.json`

**Interfaces:**

- Consumes: `QueryPlan` IDs, `Capability`, graph validation helpers.
- Produces: `NamedValue`, `ExecutionTask`, `ExecutionGraph`, `ResultField`, `ResultRow`, `BindingValue`, `Exclusion`, `ResultWarning`, `ToolResult`.

- [ ] **Step 1: Write failing execution invariants**

```python
def test_execution_graph_preserves_dependencies_and_budget(load_fixture) -> None:
    graph = ExecutionGraph.model_validate(load_fixture("execution_graph.json"))
    assert graph.total_budget_ms == 20_000
    assert graph.tasks[-1].depends_on == ("t2",)


def test_execution_graph_rejects_task_beyond_total_budget(load_fixture) -> None:
    payload = load_fixture("execution_graph.json")
    payload["tasks"][0]["budget_ms"] = 20_001
    with pytest.raises(ValidationError):
        ExecutionGraph.model_validate(payload)


def test_tool_result_empty_is_a_valid_non_error_status(load_fixture) -> None:
    payload = load_fixture("tool_result.json") | {
        "status": "empty",
        "result_rows": [],
        "binding_values": [],
    }
    assert ToolResult.model_validate(payload).status is ToolStatus.EMPTY
```

- [ ] **Step 2: Run execution tests and verify missing models**

Run: `python -m pytest tests/contracts/test_execution.py -v`

Expected: FAIL because `ExecutionGraph` and `ToolResult` are not defined.

- [ ] **Step 3: Implement exact execution fields**

```python
class NamedValue(ContractModel):
    name: Identifier
    value: ContractValue


class ExecutionTask(ContractModel):
    task_id: Identifier
    capability: Capability
    operation_id: Identifier
    literal_inputs: tuple[NamedValue, ...] = ()
    binding_inputs: tuple[Identifier, ...] = ()
    depends_on: tuple[Identifier, ...] = ()
    expected_output_type: ResultType
    required_evidence_fields: tuple[Identifier, ...]
    budget_ms: int


class ExecutionGraph(RuntimeArtifact):
    graph_id: Identifier
    tasks: tuple[ExecutionTask, ...]
    binding_specs: tuple[BindingSpec, ...] = ()
    critical_path: tuple[Identifier, ...]
    total_budget_ms: int


class ResultField(ContractModel):
    field_id: Identifier
    value: ContractValue
    unit_id: Identifier | None = None
    currency: str | None = None
    applicable_date: date | None = None


class ResultRow(ContractModel):
    row_id: Identifier
    entity_ids: tuple[Identifier, ...]
    fields: tuple[ResultField, ...]


class BindingValue(ContractModel):
    binding_name: Identifier
    value_type: Identifier
    value: ContractValue


class Exclusion(ContractModel):
    subject_id: Identifier
    rule_id: Identifier
    reason_code: Identifier


class ResultWarning(ContractModel):
    warning_code: Identifier
    related_ids: tuple[Identifier, ...] = ()


class ToolResult(RuntimeArtifact):
    task_id: Identifier
    status: ToolStatus
    result_type: ResultType
    result_rows: tuple[ResultRow, ...] = ()
    binding_values: tuple[BindingValue, ...] = ()
    evidence_refs: tuple[Identifier, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    warnings: tuple[ResultWarning, ...] = ()
    result_hash: Sha256Hex
    latency_ms: int
```

Use `Field(ge=0)` for all millisecond fields and `Field(gt=0)` for task budgets. The `ExecutionGraph` validator must reject duplicate task IDs, unknown dependencies, cycles, unknown critical-path IDs, task budgets above `total_budget_ms`, and a `total_budget_ms` above `55_000`.

The `ToolResult` validator must reject duplicate field IDs within a row and duplicate binding names. It must not convert `empty` into an error.

- [ ] **Step 4: Run the focused execution tests**

Run: `python -m pytest tests/contracts/test_execution.py -v`

Expected: all execution tests PASS.

- [ ] **Step 5: Commit the execution boundary**

```bash
git add src/financial_agent/contracts tests/contracts/test_execution.py tests/fixtures/contracts/v1/execution_graph.json tests/fixtures/contracts/v1/tool_result.json
git diff --cached --check
git commit -m "feat: add execution graph contracts"
```

### Task 5: Implement normalized ledger-domain records and immutable EvidenceBundle

**Files:**

- Create: `src/financial_agent/contracts/evidence.py`
- Modify: `src/financial_agent/contracts/__init__.py`
- Create: `tests/contracts/test_evidence.py`
- Create: `tests/fixtures/contracts/v1/evidence_record.json`
- Create: `tests/fixtures/contracts/v1/evidence_bundle.json`

**Interfaces:**

- Consumes: approved evidence Enums, `ScalarValue`, `Sha256Hex`, runtime metadata.
- Produces: `SourceLocator`, `SourceRecord`, `EvidenceRecord`, `CalculationParameter`, `PopulationDefinition`, `CalculationRecord`, `ClaimQualifier`, `AtomicClaim`, `ClaimSupport`, `MissingData`, `AppliedDefault`, `Limitation`, `EvidenceBundle`, `CheckResult`.

- [ ] **Step 1: Write failing ledger and bundle invariant tests**

```python
def test_claim_support_requires_exactly_one_support_target() -> None:
    with pytest.raises(ValidationError):
        ClaimSupport(
            claim_id="claim-1",
            support_kind="direct",
            evidence_id="evidence-1",
            calculation_id="calculation-1",
            support_role="value",
            ordinal=0,
        )


def test_evidence_bundle_keeps_candidate_claims_unreleased(load_fixture) -> None:
    bundle = EvidenceBundle.model_validate(load_fixture("evidence_bundle.json"))
    assert bundle.candidate_claim_ids == ("claim-rank-1",)
    assert "releaseable_claim_ids" not in bundle.model_fields


def test_after_cutoff_evidence_can_be_represented_for_rejection(load_fixture) -> None:
    payload = load_fixture("evidence_record.json") | {
        "applicable_date": "2026-07-12",
        "cutoff_status": "after_cutoff",
    }
    evidence = EvidenceRecord.model_validate(payload)
    assert evidence.cutoff_status is CutoffStatus.AFTER_CUTOFF


def test_ranking_calculation_requires_population_definition() -> None:
    with pytest.raises(ValidationError):
        CalculationRecord(
            calculation_id="calculation-rank-1",
            calculation_type="ranking",
            formula_id="ranking.desc.v1",
            formula_version="v1",
            input_evidence_ids=("evidence-aum-1",),
            input_calculation_ids=(),
            parameters=(),
            population_definition=None,
            exclusion_evidence_ids=(),
            tie_break_rule="product-id-asc",
            result_value=1,
            unit="rank",
            currency=None,
            rounding_rule=None,
            calculation_hash="d" * 64,
        )


def test_atomic_claim_rejects_object_and_value_together() -> None:
    with pytest.raises(ValidationError):
        AtomicClaim(
            claim_id="claim-invalid-1",
            claim_type="direct_fact",
            subtask_id="q1",
            subject_id="product-syn-etf-a",
            predicate_id="managedBy",
            object_id="manager-syn-a",
            value="duplicate-value",
            unit=None,
            currency=None,
            qualifiers=(),
            display_policy_id="text.v1",
            claim_hash="e" * 64,
        )
```

The last test is intentional: the contract can carry rejected evidence, while the later Verifier decides that it cannot support a released Claim.

- [ ] **Step 2: Run evidence tests and verify missing models**

Run: `python -m pytest tests/contracts/test_evidence.py -v`

Expected: FAIL because the evidence models are not defined.

- [ ] **Step 3: Implement source and evidence records**

Use these exact fields:

```python
class SourceLocator(ContractModel):
    locator_type: Identifier
    uri_or_object_key: str
    record_key: str | None = None
    sheet: str | None = None
    row: int | None = None
    column: str | None = None
    page: int | None = None
    section: str | None = None
    sentence_start: int | None = None
    sentence_end: int | None = None


class SourceRecord(ContractModel):
    source_id: Identifier
    publisher: Identifier
    publisher_type: Identifier
    source_title: str
    source_type: Identifier
    authority_tier: Identifier
    source_locator_root: str
    content_checksum: Sha256Hex
    license_or_usage_note: str | None = None
    eligible_for_claim: bool


class EvidenceRecord(ContractModel):
    evidence_id: Identifier
    evidence_kind: EvidenceKind
    source_id: Identifier
    dataset_version: Identifier
    subject_id: Identifier | None = None
    predicate_id: Identifier | None = None
    value_or_object_id: ScalarValue
    normalized_value: ScalarValue
    unit: Identifier | None = None
    currency: str | None = None
    applicable_date: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    published_at: UtcDateTime | None = None
    available_at: UtcDateTime | None = None
    vintage_date: date | None = None
    source_locator: SourceLocator
    raw_value_repr: str | None = None
    parser_version: Identifier
    mapping_version: Identifier
    cutoff_status: CutoffStatus
    record_hash: Sha256Hex
    scope_completeness: Literal["closed_world", "bounded_unknown"] | None = None
```

The validator must require `scope_completeness` only for `evidence_kind=query_scope`, reject it for other kinds, and ensure `valid_to >= valid_from` when both exist. It must not infer missing dates, units, currencies, or values.

- [ ] **Step 4: Implement calculation, Claim, and support records**

```python
class CalculationParameter(ContractModel):
    parameter_id: Identifier
    value: ContractValue


class PopulationDefinition(ContractModel):
    population_id: Identifier
    scope_evidence_id: Identifier
    filter_ids: tuple[Identifier, ...]
    member_count: int = Field(ge=0)
    population_hash: Sha256Hex


class CalculationRecord(ContractModel):
    calculation_id: Identifier
    calculation_type: CalculationType
    formula_id: Identifier
    formula_version: Identifier
    input_evidence_ids: tuple[Identifier, ...] = ()
    input_calculation_ids: tuple[Identifier, ...] = ()
    parameters: tuple[CalculationParameter, ...] = ()
    population_definition: PopulationDefinition | None = None
    exclusion_evidence_ids: tuple[Identifier, ...] = ()
    tie_break_rule: Identifier | None = None
    result_value: ScalarValue
    unit: Identifier | None = None
    currency: str | None = None
    rounding_rule: Identifier | None = None
    calculation_hash: Sha256Hex


class ClaimQualifier(ContractModel):
    qualifier_id: Identifier
    value: ContractValue


class AtomicClaim(ContractModel):
    claim_id: Identifier
    claim_type: ClaimType
    subtask_id: Identifier
    subject_id: Identifier
    predicate_id: Identifier
    object_id: Identifier | None = None
    value: ScalarValue
    unit: Identifier | None = None
    currency: str | None = None
    qualifiers: tuple[ClaimQualifier, ...] = ()
    display_policy_id: Identifier
    claim_hash: Sha256Hex


class ClaimSupport(ContractModel):
    claim_id: Identifier
    support_kind: SupportKind
    evidence_id: Identifier | None = None
    calculation_id: Identifier | None = None
    support_role: Identifier
    ordinal: int
```

`ClaimSupport` must enforce exclusive-or between `evidence_id` and `calculation_id`. `AtomicClaim` must require exactly one of `object_id` and non-null `value`, except `data_limitation` and `policy_boundary`, which may use a structured qualifier-only Claim.

`CalculationRecord` must require `population_definition` for `ranking` and `aggregation`, require `tie_break_rule` for `ranking`, and require at least one input Evidence or Calculation ID for every calculation type.

- [ ] **Step 5: Implement immutable bundles and check results**

```python
class MissingData(ContractModel):
    subtask_id: Identifier
    requirement_id: Identifier
    reason_code: Identifier


class AppliedDefault(ContractModel):
    subtask_id: Identifier
    policy_id: Identifier
    value_id: Identifier


class Limitation(ContractModel):
    subtask_id: Identifier
    reason_code: Identifier
    related_evidence_ids: tuple[Identifier, ...] = ()


class EvidenceBundle(RuntimeArtifact):
    bundle_id: Identifier
    answered_subtasks: tuple[Identifier, ...]
    unanswered_subtasks: tuple[Identifier, ...]
    evidence_ids: tuple[Identifier, ...]
    calculation_ids: tuple[Identifier, ...]
    candidate_claim_ids: tuple[Identifier, ...]
    exclusion_evidence_ids: tuple[Identifier, ...] = ()
    missing_data: tuple[MissingData, ...] = ()
    applied_defaults: tuple[AppliedDefault, ...] = ()
    limitations: tuple[Limitation, ...] = ()
    bundle_hash: Sha256Hex


class CheckResult(ContractModel):
    check_id: Identifier
    target_type: CheckTargetType
    target_id: Identifier
    rule_id: Identifier
    rule_version: Identifier
    status: CheckStatus
    reason_code: Identifier
    related_evidence_ids: tuple[Identifier, ...] = ()
    repairability: Repairability
```

The bundle validator must reject duplicate IDs, overlap between answered and unanswered subtasks, and a `bundle_hash` that is not 64 lowercase hexadecimal characters. It does not run source, cutoff, calculation, or policy verification in this stage.

- [ ] **Step 6: Run the evidence tests**

Run: `python -m pytest tests/contracts/test_evidence.py -v`

Expected: all evidence tests PASS.

- [ ] **Step 7: Commit ledger-domain contracts**

```bash
git add src/financial_agent/contracts tests/contracts/test_evidence.py tests/fixtures/contracts/v1/evidence_record.json tests/fixtures/contracts/v1/evidence_bundle.json
git diff --cached --check
git commit -m "feat: add evidence and claim contracts"
```

### Task 6: Implement VerificationReport, structured AnswerPlan, ReleasedAnswer, and official API response

**Files:**

- Create: `src/financial_agent/contracts/answer.py`
- Modify: `src/financial_agent/contracts/__init__.py`
- Create: `tests/contracts/test_answer.py`
- Create: `tests/fixtures/contracts/v1/verification_report.json`
- Create: `tests/fixtures/contracts/v1/answer_plan.json`

**Interfaces:**

- Consumes: `CheckResult`, Claim IDs, approved disposition and block Enums.
- Produces: `SubtaskCoverage`, `RejectedClaim`, `DispositionReason`, `RepairAction`, `VerificationReport`, `ClaimSlot`, `AnswerRow`, `AnswerBlock`, `AnswerPlan`, `ClaimBinding`, `ReleasedAnswer`, `EvaluationApiResponse`.

- [ ] **Step 1: Write failing disposition and release-set tests**

```python
def test_pass_can_recommend_limitation(load_fixture) -> None:
    payload = load_fixture("verification_report.json") | {
        "verification_status": "pass",
        "recommended_answer_disposition": "limitation",
        "releaseable_claim_ids": ["claim-limit-1"],
    }
    report = VerificationReport.model_validate(payload)
    assert report.recommended_answer_disposition is AnswerDisposition.LIMITATION


def test_releaseable_and_rejected_claims_must_be_disjoint(load_fixture) -> None:
    payload = load_fixture("verification_report.json")
    payload["rejected_claims"] = [
        {"claim_id": "claim-rank-1", "reason_code": "SOURCE_INVALID"}
    ]
    with pytest.raises(ValidationError):
        VerificationReport.model_validate(payload)
```

- [ ] **Step 2: Write failing AnswerPlan and five-string API tests**

```python
def test_answer_plan_contains_ids_but_no_factual_text_fields(load_fixture) -> None:
    plan = AnswerPlan.model_validate(load_fixture("answer_plan.json"))
    schema = json.dumps(AnswerPlan.model_json_schema()).lower()
    assert plan.blocks[0].template_id == "ranking.intro.v1"
    for forbidden in ("text", "product_name_value", "source_name", "rendered_value"):
        assert forbidden not in schema


def test_api_response_has_exactly_five_string_fields() -> None:
    response = EvaluationApiResponse(
        question_id="Q-001",
        question="합성 질문",
        retrieved_context="[SOURCE-1] 합성 근거",
        think_trace="[의도] 합성 조회",
        answer="합성 답변",
    )
    assert set(response.model_dump()) == {
        "question_id",
        "question",
        "retrieved_context",
        "think_trace",
        "answer",
    }
    assert all(isinstance(value, str) for value in response.model_dump().values())
```

- [ ] **Step 3: Run answer tests and verify missing models**

Run: `python -m pytest tests/contracts/test_answer.py -v`

Expected: FAIL because the answer models are not defined.

- [ ] **Step 4: Implement VerificationReport with separate state axes**

```python
class SubtaskCoverage(ContractModel):
    subtask_id: Identifier
    importance: SubtaskImportance
    answered: bool
    reason_code: Identifier | None = None


class RejectedClaim(ContractModel):
    claim_id: Identifier
    reason_code: Identifier


class DispositionReason(ContractModel):
    reason_code: Identifier
    related_claim_ids: tuple[Identifier, ...] = ()


class RepairAction(ContractModel):
    action_id: Identifier
    action_type: Literal["ledger_rebuild", "llm_repair"]
    target_id: Identifier


class VerificationReport(RuntimeArtifact):
    verification_report_id: Identifier
    verification_status: VerificationStatus
    recommended_answer_disposition: AnswerDisposition | None
    claim_checks: tuple[CheckResult, ...]
    calculation_checks: tuple[CheckResult, ...]
    subtask_coverage: tuple[SubtaskCoverage, ...]
    releaseable_claim_ids: tuple[Identifier, ...]
    rejected_claims: tuple[RejectedClaim, ...] = ()
    warnings: tuple[Identifier, ...] = ()
    disposition_reasons: tuple[DispositionReason, ...] = ()
    repair_actions: tuple[RepairAction, ...] = ()
```

Validate unique IDs, disjoint released/rejected Claim sets, and the following state rule: `verification_status=pass` requires a non-null answer disposition; `verification_status=fail` requires a null disposition and an empty releaseable set. Do not add execution failures to `AnswerDisposition`.

- [ ] **Step 5: Implement an AnswerPlan that cannot carry factual strings**

```python
class ClaimSlot(ContractModel):
    slot_id: Identifier
    claim_id: Identifier


class AnswerRow(ContractModel):
    cells: tuple[ClaimSlot, ...]


class AnswerBlock(ContractModel):
    block_id: Identifier
    block_type: BlockType
    template_id: Identifier
    claim_slots: tuple[ClaimSlot, ...] = ()
    columns: tuple[Identifier, ...] = ()
    rows: tuple[AnswerRow, ...] = ()


class AnswerPlan(RuntimeArtifact):
    verification_report_id: Identifier
    answer_disposition: AnswerDisposition
    renderer_profile_id: Identifier
    blocks: tuple[AnswerBlock, ...]
    source_display: Literal["inline_numbered"] = "inline_numbered"
    plan_hash: Sha256Hex
```

Validate unique block IDs and unique slot IDs within each block/row. Do not add `text`, `title`, `value`, `source_name`, arbitrary Markdown, or HTML fields. The later Claim Gate, not this structural model, checks Claim membership and template-slot compatibility.

- [ ] **Step 6: Implement final rendered and API transport contracts**

```python
class ClaimBinding(ContractModel):
    output_locator: str
    claim_ids: tuple[Identifier, ...]
    evidence_ids: tuple[Identifier, ...]


class ReleasedAnswer(RuntimeArtifact):
    answer_disposition: AnswerDisposition
    answer_text: str
    retrieved_context_text: str
    think_trace_text: str
    claim_bindings: tuple[ClaimBinding, ...]
    response_hash: Sha256Hex


class EvaluationApiResponse(ContractModel):
    question_id: str
    question: str
    retrieved_context: str
    think_trace: str
    answer: str
```

`EvaluationApiResponse` must contain exactly these five required string fields. HTTP status mapping belongs to the API implementation stage.

- [ ] **Step 7: Run the answer and all existing contract tests**

Run: `python -m pytest tests/contracts -v`

Expected: all contract tests PASS.

- [ ] **Step 8: Commit verification and answer contracts**

```bash
git add src/financial_agent/contracts tests/contracts/test_answer.py tests/fixtures/contracts/v1/verification_report.json tests/fixtures/contracts/v1/answer_plan.json
git diff --cached --check
git commit -m "feat: add verification and answer contracts"
```

### Task 7: Export deterministic JSON Schemas and prove Linux/amd64 NCP portability

**Files:**

- Create: `scripts/export_contract_schemas.py`
- Create: `src/financial_agent/contracts/schema_export.py`
- Create: `tests/contracts/test_schema_export.py`
- Create: `tests/contracts/test_container_verification.py`
- Create: `schemas/contracts/v1/*.schema.json`
- Create: `docker/contracts.Dockerfile`
- Create: `requirements/contracts.lock`
- Create: `.dockerignore`

**Interfaces:**

- Consumes: all Stage 01 public contract models.
- Produces: deterministic UTF-8 JSON Schema files and a Linux/amd64 verification image.

- [ ] **Step 1: Write the failing schema-registry test**

```python
import json
from pathlib import Path

from jsonschema.validators import Draft202012Validator

from financial_agent.contracts.schema_export import export_schemas

EXPECTED_SCHEMA_FILES = {
    "request-context.schema.json",
    "query-plan.schema.json",
    "execution-graph.schema.json",
    "tool-result.schema.json",
    "source-record.schema.json",
    "evidence-record.schema.json",
    "calculation-record.schema.json",
    "atomic-claim.schema.json",
    "claim-support.schema.json",
    "evidence-bundle.schema.json",
    "verification-report.schema.json",
    "answer-plan.schema.json",
    "released-answer.schema.json",
    "evaluation-api-response.schema.json",
}


def test_schema_export_is_complete_and_current(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    assert {path.name for path in tmp_path.iterdir()} == EXPECTED_SCHEMA_FILES
    for path in tmp_path.iterdir():
        Draft202012Validator.check_schema(json.loads(path.read_text("utf-8")))


def test_committed_schemas_match_fresh_export(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    committed = Path("schemas/contracts/v1")
    for expected in EXPECTED_SCHEMA_FILES:
        assert (tmp_path / expected).read_bytes() == (committed / expected).read_bytes()
```

- [ ] **Step 2: Run the schema test and verify export is missing**

Run: `python -m pytest tests/contracts/test_schema_export.py -v`

Expected: FAIL because the exporter and committed schemas do not exist.

- [ ] **Step 3: Implement a closed schema registry and deterministic exporter**

`schema_export.py` must expose `SCHEMA_REGISTRY`, `export_schemas(output_dir: Path)`, and `check_schemas(expected_dir: Path)`. The script imports these functions and owns only CLI argument parsing. Use this exact registry:

```python
SCHEMA_REGISTRY = {
    "request-context": RequestContext,
    "query-plan": QueryPlan,
    "execution-graph": ExecutionGraph,
    "tool-result": ToolResult,
    "source-record": SourceRecord,
    "evidence-record": EvidenceRecord,
    "calculation-record": CalculationRecord,
    "atomic-claim": AtomicClaim,
    "claim-support": ClaimSupport,
    "evidence-bundle": EvidenceBundle,
    "verification-report": VerificationReport,
    "answer-plan": AnswerPlan,
    "released-answer": ReleasedAnswer,
    "evaluation-api-response": EvaluationApiResponse,
}
```

Serialize each `model_json_schema(mode="validation")` with this exact expression:

```python
rendered = json.dumps(
    model.model_json_schema(mode="validation"),
    ensure_ascii=False,
    sort_keys=True,
    indent=2,
) + "\n"
```

Support:

```text
python scripts/export_contract_schemas.py
python scripts/export_contract_schemas.py --check
```

The default command writes `schemas/contracts/v1`. `--check` exports into a temporary directory and exits nonzero if any committed file is missing, extra, or byte-different.

Use this exact CLI boundary in `scripts/export_contract_schemas.py`:

```python
import argparse
from pathlib import Path

from financial_agent.contracts.schema_export import check_schemas, export_schemas

DEFAULT_OUTPUT = Path("schemas/contracts/v1")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check_schemas(DEFAULT_OUTPUT)
    else:
        export_schemas(DEFAULT_OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Generate and validate all schemas**

Run: `python scripts/export_contract_schemas.py`

Run: `python -m pytest tests/contracts/test_schema_export.py -v`

Run: `python scripts/export_contract_schemas.py --check`

Expected: schema tests PASS and `--check` exits 0 without changing files.

- [ ] **Step 5: Add the NCP-compatible Linux verification image**

Create `docker/contracts.Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_CONSTRAINT=/app/requirements/contracts.lock

WORKDIR /app

COPY .dockerignore ./
COPY pyproject.toml ./
COPY requirements/contracts.lock ./requirements/contracts.lock
COPY docker/contracts.Dockerfile ./docker/contracts.Dockerfile
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY schemas/ ./schemas/
COPY tests/ ./tests/

RUN python -m pip install ".[dev]" \
    && python -m pytest tests/contracts -q \
    && python scripts/export_contract_schemas.py --check

CMD ["python", "scripts/export_contract_schemas.py", "--check"]
```

This image is a Stage 01 verification image, not the final Agent API image. It uses no local volume, database, cloud credential, macOS package, or absolute host path.

The lock file pins the complete contract runtime and test dependency graph used by this image. Before building, `tests/contracts/test_container_verification.py` must confirm that every declared application/test dependency has an exact lock entry, the Dockerfile makes that lock a mandatory constraint, and the Docker build-context policy covers representative secret, organizer-data, local-database, virtual-environment, cache, and generated-output paths.

- [ ] **Step 6: Build and run the Linux/amd64 image**

Run: `docker build --platform linux/amd64 -f docker/contracts.Dockerfile -t financial-agent-contracts:stage-01 .`

Expected: image build succeeds and all contract tests run successfully inside the build.

Run: `docker run --rm --platform linux/amd64 financial-agent-contracts:stage-01`

Expected: container exits 0 after confirming committed schemas are current.

- [ ] **Step 7: Run the complete Stage 01 verification**

Run: `python -m pytest tests/contracts -q`

Run: `python scripts/export_contract_schemas.py --check`

Run: `git diff --check`

Expected: all tests PASS, schema check exits 0, and Git reports no whitespace errors.

- [ ] **Step 8: Audit repository safety before the final Stage 01 commit**

Run: `git status --short --ignored`

Verify manually from the output:

- no file under `data/` is staged;
- no organizer PDF or workbook is staged;
- no `.env`, credential, token, local database, Parquet, embedding, cache, or log is staged;
- only source, schema, synthetic fixture, test, and container-verification files belong to Stage 01.

- [ ] **Step 9: Commit deterministic schemas and NCP portability proof**

```bash
git add docker/contracts.Dockerfile scripts/export_contract_schemas.py src/financial_agent/contracts/schema_export.py schemas/contracts/v1 tests/contracts/test_schema_export.py
git diff --cached --check
git diff --cached
git commit -m "test: verify contract schemas on linux"
```

## Stage 01 Completion Gate

Stage 01 is complete only when all of the following are evidenced by fresh command output:

- `python -m pytest tests/contracts -q` passes.
- `python scripts/export_contract_schemas.py --check` exits 0.
- `docker build --platform linux/amd64 -f docker/contracts.Dockerfile -t financial-agent-contracts:stage-01 .` succeeds.
- `docker run --rm --platform linux/amd64 financial-agent-contracts:stage-01` exits 0.
- The verification image installs through the reviewed exact dependency lock, and the build context excludes repository-policy-protected local artifacts.
- Every public model rejects extra fields and top-level runtime artifacts enforce the fixed cutoff.
- `QueryPlan` and `ExecutionGraph` reject unknown references and cyclic dependencies.
- Every `ExecutionTask` identifies its owning QueryPlan subtask and explicitly declares the bindings it can produce.
- `ExecutionGraph` rejects undeclared or duplicate binding producers, disconnected consumers, invalid critical paths, and critical-path budgets above `total_budget_ms`.
- Deterministic compatibility checks reject QueryPlan–ExecutionGraph and ExecutionGraph–ToolResult identity, ownership, operation, capability, result-type, binding-type, or cardinality mismatches.
- `ToolResult` rejects successful payloads attached to `empty` or error states.
- Evidence contracts preserve after-cutoff and unsupported records for rejection without releasing them.
- `VerificationReport` keeps execution failure separate from answer disposition.
- `AnswerPlan` contains only approved IDs and layout structure, never factual strings.
- `EvaluationApiResponse` exposes exactly five required string fields.
- The same schema files are produced byte-for-byte on the development host and Linux/amd64 container.
- No organizer source data, external snapshot, secret, database, or generated runtime artifact is staged.

## Stage 02 Handoff

The [Stage 02 PostgreSQL Storage implementation plan](2026-08-17-stage-02-postgresql-storage-implementation-plan.md) may start only after Stage 01, including the 2026-08-18 execution-contract amendment, is implemented, verified, and reviewed. Stage 02 maps these contract IDs and immutable artifacts to PostgreSQL 15 DDL, Alembic migrations, foreign keys, normalized association tables, indexes, and NCP Cloud DB integration tests. It must consume the freshly exported final Stage 01 schemas without renaming the frozen public interfaces.

## Stage 01 Closure-Review Register — Closed

The final review identified the following items. ADR-0008, the closure design, and the closure implementation plan resolved and verified all six before the Stage 01 freeze.

The implementation evidence is recorded in the complete [Stage 01 Closure Hardening Implementation Plan](2026-08-18-stage-01-closure-hardening-implementation-plan.md).

1. [x] Strict Python-versus-JSON ingress preserves valid raw JSON while rejecting Python coercion.
2. [x] JSON Schema structural authority and Pydantic semantic authority are separately tested.
3. [x] Canonical serialization covers tagged Decimal identity and rejects schema-less typed mappings, nested tuples, and unsupported values.
4. [x] `ClaimSupport.ordinal` is nonnegative and `support_kind` constrains evidence-versus-calculation targets.
5. [x] Exact Schema freshness tests reject modified, missing, and extra generated files.
6. [x] All ten polymorphic value fields use the lossless tagged representation.

The future Claim Gate Registry registration and template-slot compatibility check remains mandatory and unimplemented; closing this register does not waive it.
