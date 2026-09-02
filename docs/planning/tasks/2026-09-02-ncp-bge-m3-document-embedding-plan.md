# NCP BGE-M3 DART Document Embedding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate one validated NCP BGE-M3 vector for every eligible current DART chunk, store the vectors only in local PostgreSQL, and prove metadata-scoped real retrieval before completing the full build.

**Architecture:** Add a small embedding package with four boundaries: deterministic text/model contracts, an injected NCP HTTP client, an idempotent PostgreSQL repository, and a staged build/verification service. Reuse the existing `search.embedding_model`, `search.document_embedding`, and `DocumentCandidateRepository`; do not add a migration, ANN index, Graph write, Evidence write, or dataset activation.

**Tech Stack:** Python 3.12, standard-library `urllib.request` and `asyncio`, SQLAlchemy 2 async, PostgreSQL 15, pgvector, psycopg 3, pytest, pytest-asyncio, NCP CLOVA Studio Embedding v2 BGE-M3.

**Spec:** [NCP BGE-M3 DART Document Embedding Design](../specs/2026-09-02-ncp-bge-m3-document-embedding-design.md)

## Global Constraints

- Dataset version is `organizer-dart-2026-08-24-v2`; the full-run gate requires exactly `37,629` eligible unique chunks unless the user approves a new snapshot.
- Send only the approved document input (`document_title`, `section_path`, `exact_text`) or fixed non-private validation query text to NCP.
- Never send organizer row values, entity IDs, database locators, local paths, credentials, Evidence values, or real user prompts to NCP.
- Read the key only from the exact normalized `NCP_CLOVA_STUDIO_API` entry in the configured ignored key file. Never print the key or HTTP authorization header.
- Use endpoint `https://clovastudio.stream.ntruss.com/v1/api-tools/embedding/v2/`, model `bge-m3`, dimension `1024`, and cosine distance.
- Persist vectors only in local PostgreSQL `search.document_embedding`; do not use NCP PostgreSQL or Object Storage.
- Preserve the existing database schema. The current model registry, exact chunk-hash foreign key, dimension trigger, and immutable registry trigger are the storage contract.
- Use exact pgvector search for this phase. Do not create HNSW or IVFFlat indexes.
- Commit no credentials, DART source files, organizer files, vectors, local databases, or real run/validation reports.
- Use TDD for behavior changes. Run narrow tests first, then focused PostgreSQL tests, then the ordinary non-live suite.
- A full build may start only after preflight, one-chunk canary, bounded product sample, and real Top-5 validation all pass.
- Do not merge or modify `codex/graph-phase1-core`; do not create Graph relations, Claims, Evidence, readiness rows, or activation state.

## File Structure

| Path | Responsibility |
| --- | --- |
| `src/financial_agent/embeddings/contracts.py` | Immutable model identity, input templates, vector validation, and stable embedding IDs |
| `src/financial_agent/embeddings/ncp.py` | Sanitized NCP Embedding v2 HTTP request, response validation, and bounded retry |
| `src/financial_agent/embeddings/repository.py` | Exact DART corpus selection, immutable model registration, idempotent vector writes, and reconciliation |
| `src/financial_agent/embeddings/builder.py` | Preflight, canary, sample, full-build orchestration, reports, and fixed-query retrieval validation |
| `src/financial_agent/embeddings/cli.py` | Strict environment/key-file configuration and five explicit operator commands |
| `src/financial_agent/embeddings/__init__.py` | Public embedding package exports |
| `src/financial_agent/embeddings/__main__.py` | `python -m financial_agent.embeddings` entry point |
| `tests/embeddings/test_contracts.py` | Deterministic identity, payload, and vector-contract unit tests |
| `tests/embeddings/test_ncp.py` | Fully mocked NCP transport, retry, response, and secret-redaction tests |
| `tests/embeddings/test_builder.py` | Staged-build and retrieval-gate orchestration tests with fakes |
| `tests/db/test_embedding_repository.py` | PostgreSQL model registration, exact selection, resume, and reconciliation tests |
| `tests/embeddings/test_cli.py` | Key-file parsing, command gating, sanitized output, and report-policy tests |

---

### Task 1: Define the Immutable Embedding Contract

**Files:**
- Create: `src/financial_agent/embeddings/__init__.py`
- Create: `src/financial_agent/embeddings/contracts.py`
- Create: `tests/embeddings/__init__.py`
- Create: `tests/embeddings/test_contracts.py`

**Interfaces:**
- Consumes: current DART `document_title`, `section_path`, `exact_text`, `content_hash`, `document_id`, and `chunk_id`.
- Produces: `APPROVED_MODEL`, `EmbeddingChunk`, `EmbeddingResult`, `EmbeddingProvider`, `document_input()`, `query_input()`, `validate_result()`, and `embedding_id()`.
- Model identity: `model_id="ncp-clova-bge-m3"`, `model_version="embedding-v2-dart-search-text-v1"`, `approval_record_id="ADR-0031"`.

- [ ] **Step 1: Write failing contract tests**

```python
from dataclasses import replace
import math
import pytest

from financial_agent.embeddings.contracts import (
    APPROVED_MODEL,
    EmbeddingChunk,
    EmbeddingContractError,
    EmbeddingResult,
    document_input,
    embedding_id,
    query_input,
    validate_result,
)


def _chunk() -> EmbeddingChunk:
    return EmbeddingChunk(
        dataset_version="organizer-dart-2026-08-24-v2",
        document_id="document-001",
        chunk_id="chunk-001",
        content_hash="a" * 64,
        document_title="공식 투자설명서",
        section_path="제2부 > 주요 투자위험",
        exact_text="투자원금 손실이 발생할 수 있습니다.",
    )


def test_document_input_uses_only_the_approved_template() -> None:
    assert document_input(_chunk()) == (
        "문서: 공식 투자설명서\n"
        "섹션: 제2부 > 주요 투자위험\n"
        "본문:\n투자원금 손실이 발생할 수 있습니다."
    )


def test_query_input_preserves_fixed_query_without_instruction_prefix() -> None:
    assert query_input("  주요 투자위험   원금 손실  ") == "주요 투자위험 원금 손실"


def test_model_manifest_hash_and_embedding_id_are_deterministic() -> None:
    assert len(APPROVED_MODEL.model_hash) == 64
    assert embedding_id(APPROVED_MODEL, _chunk()) == embedding_id(
        APPROVED_MODEL, _chunk()
    )
    assert embedding_id(APPROVED_MODEL, _chunk()) != embedding_id(
        APPROVED_MODEL, replace(_chunk(), content_hash="b" * 64)
    )


@pytest.mark.parametrize("vector", [(), (0.0,) * 1023, (math.nan,) + (0.0,) * 1023])
def test_result_rejects_wrong_or_nonfinite_vectors(vector: tuple[float, ...]) -> None:
    with pytest.raises(EmbeddingContractError):
        validate_result(EmbeddingResult(vector=vector, input_tokens=1, request_id=None))
```

- [ ] **Step 2: Run the narrow tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/embeddings/test_contracts.py -q
```

Expected: FAIL because `financial_agent.embeddings.contracts` does not exist.

- [ ] **Step 3: Implement the minimal immutable contract**

```python
@dataclass(frozen=True, slots=True)
class EmbeddingModelContract:
    provider: str
    api: str
    model_id: str
    model_version: str
    dimension: int
    distance_metric: str
    document_input_template: str
    query_input_template: str
    approval_record_id: str
    approved_at: datetime

    @property
    def model_hash(self) -> str:
        payload = {
            "api": self.api,
            "dimension": self.dimension,
            "distance_metric": self.distance_metric,
            "document_input_template": self.document_input_template,
            "model": "bge-m3",
            "provider": self.provider,
            "query_input_template": self.query_input_template,
        }
        return hashlib.sha256(_canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class EmbeddingChunk:
    dataset_version: str
    document_id: str
    chunk_id: str
    content_hash: str
    document_title: str
    section_path: str
    exact_text: str


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vector: tuple[float, ...]
    input_tokens: int
    request_id: str | None


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> EmbeddingResult: ...


def document_input(chunk: EmbeddingChunk) -> str:
    return (
        f"문서: {' '.join(chunk.document_title.split())}\n"
        f"섹션: {' '.join(chunk.section_path.split())}\n"
        f"본문:\n{chunk.exact_text}"
    )


def query_input(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        raise EmbeddingContractError("query_text_blank")
    return normalized


def embedding_id(model: EmbeddingModelContract, chunk: EmbeddingChunk) -> str:
    payload = {
        "chunk_content_hash": chunk.content_hash,
        "chunk_id": chunk.chunk_id,
        "dataset_version": chunk.dataset_version,
        "document_id": chunk.document_id,
        "model_id": model.model_id,
        "model_version": model.model_version,
    }
    return "embedding:" + hashlib.sha256(_canonical_json(payload)).hexdigest()
```

`validate_result()` must require exactly 1,024 finite numeric values, reject booleans, and require `input_tokens` to be a positive integer.

- [ ] **Step 4: Run the contract tests**

Run:

```bash
.venv/bin/python -m pytest tests/embeddings/test_contracts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the contract**

```bash
git add src/financial_agent/embeddings tests/embeddings
git diff --cached --check
git commit -m "feat: define DART embedding contract"
```

---

### Task 2: Add the Sanitized NCP Embedding v2 Client

**Files:**
- Create: `src/financial_agent/embeddings/ncp.py`
- Create: `tests/embeddings/test_ncp.py`

**Interfaces:**
- Consumes: nonblank API key and one approved input string.
- Produces: `NcpEmbeddingClient.embed(text: str) -> EmbeddingResult`.
- Injected test boundary: `EmbeddingHttpTransport.post(request: EmbeddingHttpRequest) -> EmbeddingHttpResponse`.
- Retry policy: at most four attempts; retry timeout, HTTP 429, and HTTP 500–599; do not retry other 4xx or malformed successful responses.

- [ ] **Step 1: Write failing provider tests with an injected transport**

```python
@pytest.mark.asyncio
async def test_client_sends_exact_v2_request_and_returns_validated_result() -> None:
    transport = ScriptedTransport(
        EmbeddingHttpResponse(
            status=200,
            headers={"x-ncp-clovastudio-request-id": "request-1"},
            body=json.dumps({
                "status": {"code": "20000", "message": "OK"},
                "result": {"embedding": [0.25] * 1024, "inputTokens": 17},
            }).encode(),
        )
    )
    client = NcpEmbeddingClient("secret-value", transport=transport)

    result = await client.embed("공식 문서 본문")

    request = transport.requests[0]
    assert request.url == NCP_EMBEDDING_V2_ENDPOINT
    assert request.headers["Authorization"] == "Bearer secret-value"
    assert json.loads(request.body) == {"text": "공식 문서 본문"}
    assert len(result.vector) == 1024
    assert result.input_tokens == 17


@pytest.mark.asyncio
async def test_client_retries_429_then_succeeds_without_leaking_secret() -> None:
    transport = ScriptedTransport(
        EmbeddingHttpResponse(429, {"retry-after": "0"}, b"rate limited"),
        _success_response(),
    )
    sleeps: list[float] = []
    client = NcpEmbeddingClient(
        "private-key", transport=transport, sleep=sleeps.append
    )
    result = await client.embed("공식 문서")
    assert result.input_tokens == 3
    assert len(transport.requests) == 2
    assert "private-key" not in repr(transport)


@pytest.mark.asyncio
async def test_client_rejects_malformed_success_without_retry() -> None:
    transport = ScriptedTransport(
        EmbeddingHttpResponse(200, {}, b'{"result":{"embedding":[1]}}')
    )
    with pytest.raises(PermanentEmbeddingError, match="response_dimension"):
        await NcpEmbeddingClient("secret", transport=transport).embed("text")
    assert len(transport.requests) == 1
```

Add cases for timeout exhaustion, 401, provider status code other than `20000`, invalid JSON, non-finite values, zero token count, and a response/body that contains the secret. Assert all raised messages use stable codes only.

- [ ] **Step 2: Run the provider tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/embeddings/test_ncp.py -q
```

Expected: FAIL because the NCP client does not exist.

- [ ] **Step 3: Implement the injected standard-library client**

```python
NCP_EMBEDDING_V2_ENDPOINT = (
    "https://clovastudio.stream.ntruss.com/v1/api-tools/embedding/v2/"
)


@dataclass(frozen=True, slots=True)
class EmbeddingHttpRequest:
    url: str
    headers: Mapping[str, str]
    body: bytes
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class EmbeddingHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class UrllibEmbeddingTransport:
    async def post(self, request: EmbeddingHttpRequest) -> EmbeddingHttpResponse:
        return await asyncio.to_thread(self._post_sync, request)


class NcpEmbeddingClient:
    async def embed(self, text: str) -> EmbeddingResult:
        body = json.dumps(
            {"text": text}, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        for attempt in range(1, self._max_attempts + 1):
            request = EmbeddingHttpRequest(
                url=NCP_EMBEDDING_V2_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid4()),
                    "Content-Type": "application/json",
                },
                body=body,
                timeout_seconds=self._timeout_seconds,
            )
            response = await self._post_or_classify_timeout(request, attempt)
            if response.status == 429 or 500 <= response.status <= 599:
                await self._retry_or_raise(response, attempt)
                continue
            return self._parse_permanent_response(response)
        raise RetryableEmbeddingError("retry_exhausted")
```

The concrete transport must convert `HTTPError` into an `EmbeddingHttpResponse`, convert `URLError` and `TimeoutError` into a retryable transport code, cap `Retry-After` at 60 seconds, and never include response bodies, request bodies, or headers in exception text.

- [ ] **Step 4: Run provider and contract tests**

Run:

```bash
.venv/bin/python -m pytest tests/embeddings/test_ncp.py tests/embeddings/test_contracts.py -q
```

Expected: PASS with no network request.

- [ ] **Step 5: Commit the provider client**

```bash
git add src/financial_agent/embeddings/ncp.py tests/embeddings/test_ncp.py
git diff --cached --check
git commit -m "feat: add NCP embedding client"
```

---

### Task 3: Implement Exact DART Chunk Selection and Idempotent PostgreSQL Writes

**Files:**
- Create: `src/financial_agent/embeddings/repository.py`
- Create: `tests/db/test_embedding_repository.py`

**Interfaces:**
- Consumes: `AsyncEngine`, `EmbeddingModelContract`, `EmbeddingChunk`, and validated `EmbeddingResult`.
- Produces: `PendingEmbedding`, `EmbeddingPreflight`, `EmbeddingReconciliation`, `EmbeddingRepository.preflight()`, `register_model()`, `resolve_product()`, `sample_candidates()`, `missing_chunks()`, `append_embeddings()`, `reconcile()`, and `storage_bytes()`.
- Does not modify: document, source, entity, Evidence, relation, readiness, or activation rows.

Use these immutable cross-task values:

```python
@dataclass(frozen=True, slots=True)
class PendingEmbedding:
    chunk: EmbeddingChunk
    result: EmbeddingResult


@dataclass(frozen=True, slots=True)
class EmbeddingPreflight:
    dataset_status: str
    eligible_chunk_count: int
    existing_exact_embedding_count: int
    missing_embedding_count: int
    stale_embedding_count: int
    orphan_embedding_count: int


@dataclass(frozen=True, slots=True)
class EmbeddingReconciliation:
    eligible_count: int
    exact_count: int
    missing_count: int
    duplicate_count: int
    stale_count: int
    orphan_count: int
    wrong_dimension_count: int
    embedding_bytes: int
```

- [ ] **Step 1: Write failing PostgreSQL repository tests**

Use the existing migrated PostgreSQL fixture and `tests.fixtures.document_corpus.insert_document_search_corpus`. Add tests proving:

```python
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_preflight_selects_only_current_dart_chunks(
    migrated_engine: AsyncEngine,
) -> None:
    await insert_dart_embedding_fixture(migrated_engine)
    result = await EmbeddingRepository(migrated_engine).preflight(
        DATASET_VERSION, APPROVED_MODEL
    )
    assert result.dataset_status == "building"
    assert result.eligible_chunk_count == 2
    assert result.existing_exact_embedding_count == 0
    assert result.stale_embedding_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_model_registration_is_immutable_and_exact(
    migrated_engine: AsyncEngine,
) -> None:
    repository = EmbeddingRepository(migrated_engine)
    await repository.register_model(APPROVED_MODEL)
    await repository.register_model(APPROVED_MODEL)
    with pytest.raises(EmbeddingRepositoryError, match="model_contract_mismatch"):
        await repository.register_model(replace(APPROVED_MODEL, dimension=768))


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_append_then_resume_skips_the_exact_embedding(
    migrated_engine: AsyncEngine,
) -> None:
    repository = EmbeddingRepository(migrated_engine)
    await repository.register_model(APPROVED_MODEL)
    chunk = (await repository.missing_chunks(DATASET_VERSION, APPROVED_MODEL, limit=1))[0]
    row = PendingEmbedding(chunk, EmbeddingResult((0.1,) * 1024, 9, "request-1"))
    assert await repository.append_embeddings(APPROVED_MODEL, (row,)) == 1
    assert await repository.append_embeddings(APPROVED_MODEL, (row,)) == 0
    assert await repository.missing_chunks(DATASET_VERSION, APPROVED_MODEL, limit=1) == ()
```

Also prove that a non-DART source locator, missing source artifact, stale content hash, duplicate canonical product name, wrong dimension, and non-building dataset all fail with stable codes.

- [ ] **Step 2: Run the repository tests and confirm failure**

Run:

```bash
FINANCIAL_AGENT_TEST_DATABASE_URL="$FINANCIAL_AGENT_TEST_DATABASE_URL" \
  .venv/bin/python -m pytest tests/db/test_embedding_repository.py -q
```

Expected: FAIL because `EmbeddingRepository` does not exist.

- [ ] **Step 3: Implement the exact eligible-corpus query**

Build the candidate query from these joins and predicates:

```python
eligible = (
    sa.select(
        document_chunk.c.dataset_version,
        document_chunk.c.document_id,
        document_chunk.c.chunk_id,
        document_chunk.c.content_hash,
        document_record.c.document_title,
        document_chunk.c.section_path,
        document_chunk.c.exact_text,
    )
    .select_from(
        document_chunk
        .join(document_record, _same_document(document_chunk, document_record))
        .join(document_profile, _same_document(document_chunk, document_profile))
        .join(document_source_artifact, _same_document(document_chunk, document_source_artifact))
        .join(dataset_version, dataset_version.c.dataset_version == document_chunk.c.dataset_version)
    )
    .where(
        document_chunk.c.dataset_version == sa.bindparam("dataset_version"),
        dataset_version.c.status == "building",
        document_profile.c.cutoff_eligible.is_(True),
        document_source_artifact.c.media_type == "application/pdf",
        document_source_artifact.c.filing_locator.like("https://dart.fss.or.kr/%"),
        document_source_artifact.c.retention_disposition == "metadata_only_deleted",
    )
)
```

Exclude only an exact existing row matching dataset, document, chunk, content hash, model ID, model version, and registered dimension. Sort by `document_id, chunk_id`. `resolve_product()` must require one exact `catalog.entity.canonical_name` joined to `catalog.product` and at least one eligible document binding.

- [ ] **Step 4: Implement immutable registration, batch append, and reconciliation**

```python
async def register_model(self, model: EmbeddingModelContract) -> None:
    values = {
        "model_id": model.model_id,
        "model_version": model.model_version,
        "dimension": model.dimension,
        "distance_metric": model.distance_metric,
        "approval_record_id": model.approval_record_id,
        "approved_at": model.approved_at,
        "model_hash": model.model_hash,
    }
    async with self._engine.begin() as connection:
        await connection.execute(
            postgresql.insert(embedding_model)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[embedding_model.c.model_id, embedding_model.c.model_version]
            )
        )
        stored = (
            await connection.execute(
                sa.select(embedding_model).where(
                    embedding_model.c.model_id == model.model_id,
                    embedding_model.c.model_version == model.model_version,
                )
            )
        ).mappings().one()
        if dict(stored) != values:
            raise EmbeddingRepositoryError("model_contract_mismatch")
```

`append_embeddings()` must revalidate every result, calculate the stable embedding ID, use `ON CONFLICT DO NOTHING`, force deferred constraints before commit, and return the actual inserted count. `reconcile()` must report eligible, exact, missing, duplicate, stale-hash, orphan, wrong-dimension, Evidence, relation, readiness, and activation counts without mutating them.

- [ ] **Step 5: Run repository and existing schema tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/db/test_embedding_repository.py \
  tests/db/test_fact_document_search_schema.py \
  tests/retrieval/test_document_search.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the repository**

```bash
git add src/financial_agent/embeddings/repository.py tests/db/test_embedding_repository.py
git diff --cached --check
git commit -m "feat: persist DART embeddings idempotently"
```

---

### Task 4: Build the Staged and Resumable Embedding Service

**Files:**
- Create: `src/financial_agent/embeddings/builder.py`
- Create: `tests/embeddings/test_builder.py`
- Modify: `src/financial_agent/embeddings/__init__.py`

**Interfaces:**
- Consumes: `EmbeddingRepository`, an `EmbeddingProvider`, `APPROVED_MODEL`, stage, dataset version, expected count, optional exact product entity ID, and batch size.
- Produces: `BuildReport`, `RetrievalValidationCase`, `EmbeddingBuildService.preflight()`, `embed_canary()`, `embed_sample()`, `embed_all()`, `verify_retrieval()`, and immutable sanitized report dataclasses.
- Stage order: preflight → canary → sample → retrieval verification → full → final reconciliation.

The public report and validation inputs are:

```python
@dataclass(frozen=True, slots=True)
class BuildReport:
    stage: str
    eligible_count: int
    requested_count: int
    inserted_count: int
    skipped_existing_count: int
    input_token_count: int
    retry_count: int
    failure_codes: tuple[str, ...]
    model_hash: str
    embedding_bytes: int


@dataclass(frozen=True, slots=True)
class RetrievalValidationCase:
    case_id: str
    dataset_version: str
    canonical_product_name: str
    query_text: str
    claim_type: str
    section_types: tuple[SectionType, ...]
    expected_section_type: SectionType
```

- [ ] **Step 1: Write failing staged-build tests with fakes**

```python
@pytest.mark.asyncio
async def test_canary_embeds_and_reads_back_one_exact_chunk() -> None:
    repository = FakeEmbeddingRepository(chunks=(_chunk("risk"),))
    provider = FakeProvider(result=_result())
    service = EmbeddingBuildService(repository, provider)

    report = await service.embed_canary(DATASET_VERSION, expected_chunk_count=1)

    assert report.stage == "canary"
    assert report.requested_count == 1
    assert report.inserted_count == 1
    assert report.input_token_count == 12
    assert repository.read_back_ids == (embedding_id(APPROVED_MODEL, _chunk("risk")),)


@pytest.mark.asyncio
async def test_full_build_does_not_start_when_preflight_count_differs() -> None:
    service = EmbeddingBuildService(
        FakeEmbeddingRepository(eligible_count=2), FakeProvider()
    )
    with pytest.raises(EmbeddingBuildError, match="eligible_chunk_count_mismatch"):
        await service.embed_all(DATASET_VERSION, expected_chunk_count=37_629)
    assert service.provider.calls == []


@pytest.mark.asyncio
async def test_interrupted_batch_leaves_committed_rows_for_resume() -> None:
    repository = FakeEmbeddingRepository(chunks=tuple(_chunk(str(i)) for i in range(5)))
    first = EmbeddingBuildService(repository, FailingAfterProvider(3), batch_size=2)
    with pytest.raises(EmbeddingBuildError, match="provider_retry_exhausted"):
        await first.embed_all(DATASET_VERSION, expected_chunk_count=5)
    assert repository.persisted_count == 2

    second = EmbeddingBuildService(repository, FakeProvider(), batch_size=2)
    report = await second.embed_all(DATASET_VERSION, expected_chunk_count=5)
    assert report.skipped_existing_count == 2
    assert report.inserted_count == 3
    assert repository.persisted_count == 5
```

Add tests proving the sample requires both `investment_strategy` and `risk_factor` chunks for the resolved product, permanent provider errors stop immediately, reports contain no input text/vector/key, and final reconciliation fails on any missing, duplicate, stale, orphan, wrong-dimension, Evidence/relation delta, readiness delta, or activation delta.

- [ ] **Step 2: Run the builder tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/embeddings/test_builder.py -q
```

Expected: FAIL because the build service does not exist.

- [ ] **Step 3: Implement bounded stages and small commits**

```python
class EmbeddingBuildService:
    async def _embed_missing(
        self,
        dataset_version: str,
        *,
        limit: int | None,
        entity_id: str | None = None,
        section_types: tuple[str, ...] = (),
    ) -> BuildReport:
        chunks = await self._repository.missing_chunks(
            dataset_version,
            APPROVED_MODEL,
            limit=limit,
            entity_id=entity_id,
            section_types=section_types,
        )
        pending: list[PendingEmbedding] = []
        for chunk in chunks:
            result = await self._provider.embed(document_input(chunk))
            validate_result(result)
            pending.append(PendingEmbedding(chunk=chunk, result=result))
            if len(pending) == self._batch_size:
                await self._repository.append_embeddings(APPROVED_MODEL, tuple(pending))
                pending.clear()
        if pending:
            await self._repository.append_embeddings(APPROVED_MODEL, tuple(pending))
        return await self._build_report(dataset_version)
```

The canary uses `limit=1`. The sample resolves one exact local product and selects up to 20 missing chunks restricted to strategy and risk, while requiring at least one of each section. The full build repeatedly fetches missing deterministic pages instead of loading all vectors into memory. Default batch size is 25; it is configurable only from 1 through 100.

- [ ] **Step 4: Implement retrieval verification without sending product identity**

Define a local case with `canonical_product_name`, fixed generic `query_text`, `claim_type`, allowed section types, and expected section type. Resolve the product locally. Send only `query_input(case.query_text)` to NCP, then call the existing repository:

```python
request = DocumentSearchRequest(
    dataset_version=case.dataset_version,
    entity_ids=(entity_id,),
    claim_type=case.claim_type,
    section_types=case.section_types,
    cutoff_date=date(2026, 8, 24),
    top_k=5,
    query_embedding=result.vector,
    model_id=APPROVED_MODEL.model_id,
    model_version=APPROVED_MODEL.model_version,
)
vector_hits = await candidates.search_vector(request)
keyword_hits = await candidates.search_keyword(request, case.query_text)
fused_hits = reciprocal_rank_fusion(keyword_hits, vector_hits, top_k=5)
```

Require the expected section type in Vector and fused Top 5 and audit every hit back to the exact current content hash/source. Capture Evidence/relation/readiness/activation counts before and after and require zero delta.

- [ ] **Step 5: Run builder and retrieval tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/embeddings/test_builder.py \
  tests/retrieval/test_document_search.py \
  tests/retrieval/test_document_retrieval_eval.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the build service**

```bash
git add src/financial_agent/embeddings/builder.py src/financial_agent/embeddings/__init__.py tests/embeddings/test_builder.py
git diff --cached --check
git commit -m "feat: add staged embedding build service"
```

---

### Task 5: Add the Strict Local Operator CLI and Sanitized Reports

**Files:**
- Create: `src/financial_agent/embeddings/cli.py`
- Create: `src/financial_agent/embeddings/__main__.py`
- Create: `tests/embeddings/test_cli.py`

**Interfaces:**
- Consumes environment: `FINANCIAL_AGENT_BUILD_DATABASE_URL`, `FINANCIAL_AGENT_DATASET_VERSION`, `FINANCIAL_AGENT_NCP_API_KEY_FILE`, and `FINANCIAL_AGENT_EMBEDDING_REPORT`.
- Commands: `preflight`, `canary`, `sample-candidates --limit`, `sample --product-name`, `verify --product-name`, `full`, and `reconcile`.
- Exit codes: `0` pass; `2` configuration, provider, database, or validation failure.

- [ ] **Step 1: Write failing CLI configuration and redaction tests**

```python
def test_configuration_reads_only_the_named_ncp_key(tmp_path, monkeypatch) -> None:
    key_file = tmp_path / "api.txt"
    key_file.write_text(
        "OPEN_DART=dart-secret\nNCP_CLOVA_STUDIO_API=ncp-secret\n",
        encoding="utf-8",
    )
    _set_required_environment(monkeypatch, key_file)
    configuration = load_configuration(parse_args(["preflight"]))
    assert configuration.api_key == "ncp-secret"


def test_duplicate_or_missing_named_key_is_rejected(tmp_path, monkeypatch) -> None:
    key_file = tmp_path / "api.txt"
    key_file.write_text(
        "NCP_CLOVA_STUDIO_API=one\nNCP-CLOVA-STUDIO-API=two\n",
        encoding="utf-8",
    )
    _set_required_environment(monkeypatch, key_file)
    assert main(["preflight"]) == 2


def test_failure_output_and_report_never_contain_secret_or_vector(
    tmp_path, monkeypatch, capsys
) -> None:
    _set_required_environment(monkeypatch, _key_file(tmp_path, "private-ncp-key"))
    monkeypatch.setattr(cli, "run_command", _raise_provider_error)
    assert main(["canary"]) == 2
    output = capsys.readouterr()
    assert "private-ncp-key" not in output.out + output.err
    assert "[0." not in output.out + output.err
```

Add parser tests requiring `--product-name` only for sample/verify, `sample-candidates --limit` between 1 and 100, `--expected-chunks` defaulting to 37,629 for full, batch size 1–100, report parent existence, output path outside the repository, and `api.txt` remaining ignored and unstaged. `sample-candidates` must make no NCP request and may print only exact eligible canonical product names plus their available strategy/risk chunk counts.

- [ ] **Step 2: Run CLI tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/embeddings/test_cli.py -q
```

Expected: FAIL because the CLI does not exist.

- [ ] **Step 3: Implement exact key parsing and command dispatch**

```python
def read_ncp_api_key(path: Path) -> str:
    matches: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if re.sub(r"[^A-Z0-9]", "", name.upper()) != "NCPCLOVASTUDIOAPI":
            continue
        secret = _strip_matching_quotes(value.strip())
        if secret:
            matches.append(secret)
    if len(matches) != 1:
        raise EmbeddingConfigurationError("ncp_api_key_invalid")
    return matches[0]


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = parser().parse_args(argv)
        return asyncio.run(run_command(load_configuration(arguments)))
    except KNOWN_EMBEDDING_ERRORS as error:
        print(error.code, file=sys.stderr)
        return 2
    except Exception:
        print("EMBEDDING_FAILED", file=sys.stderr)
        return 2
```

Only print stage, counts, total input tokens, retry count, measured storage bytes, and SHA-256 report hash. Write the report atomically with sorted compact JSON and `allow_nan=False`; omit chunk text, query text, vectors, headers, keys, database URL, entity ID, product name, and local paths.

- [ ] **Step 4: Run CLI and embedding tests**

Run:

```bash
.venv/bin/python -m pytest tests/embeddings tests/db/test_embedding_repository.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the operator interface**

```bash
git add src/financial_agent/embeddings tests/embeddings/test_cli.py
git diff --cached --check
git commit -m "feat: add DART embedding operator CLI"
```

---

### Task 6: Verify the Complete Implementation Before Any Live NCP Call

**Files:**
- Modify only if a failing check exposes a task-related defect: files introduced in Tasks 1–5.

**Interfaces:**
- Consumes: completed implementation and synthetic fixtures.
- Produces: a clean implementation diff with all focused and non-live checks passing.

- [ ] **Step 1: Run the complete focused suite**

Run:

```bash
.venv/bin/python -m pytest \
  tests/embeddings \
  tests/db/test_embedding_repository.py \
  tests/db/test_fact_document_search_schema.py \
  tests/retrieval/test_document_search.py \
  tests/retrieval/test_document_retrieval_eval.py -q
```

Expected: PASS.

- [ ] **Step 2: Run migration and non-live regression checks**

Run:

```bash
.venv/bin/python -m pytest tests/db/test_migration_cycle.py -q
.venv/bin/python -m pytest -m "not official_data and not organizer_data and not ncp_integration and not object_storage and not performance" -q
```

Expected: PASS. If a failure predates this work, prove it on the plan base commit and report it instead of changing unrelated code.

- [ ] **Step 3: Inspect scope and secret/data safety**

Run:

```bash
git diff --check
git status --short
git diff --name-only origin/main...HEAD
git ls-files api.txt data '*.pdf' '*.parquet' '*.npy' '*.npz'
git grep -nE 'NCP_CLOVA_STUDIO_API=.+' -- ':!docs/planning/tasks/*' ':!tests/*'
```

Expected: no tracked key file, DART PDF, organizer data, vector artifact, local report, or secret value; no change to migrations, Graph code, Evidence behavior, or activation behavior.

- [ ] **Step 4: Commit only a necessary verification correction**

If Steps 1–3 required a correction in files from Tasks 1–5:

```bash
git add src/financial_agent/embeddings tests/embeddings tests/db/test_embedding_repository.py
git diff --cached --check
git commit -m "fix: tighten DART embedding verification"
```

If no correction was required, create no empty commit.

---

### Task 7: Run Canary, Real Sample, Full Build, and Final Reconciliation

**Files:**
- Create locally and keep untracked: report path configured by `FINANCIAL_AGENT_EMBEDDING_REPORT`.
- Do not modify or commit source files during the operational run unless a reproducible implementation defect is found and returned to Task 6.

**Interfaces:**
- Consumes: ignored `api.txt`, local PostgreSQL build URL, exact dataset version, one exact locally resolved product name with both strategy and risk chunks, and the verified CLI.
- Produces: 37,629 exact local vectors and sanitized untracked stage reports.

- [ ] **Step 1: Confirm preflight without an external API request**

Keep `FINANCIAL_AGENT_BUILD_DATABASE_URL` exported with the existing local build-role URL, then export the non-secret run identity once:

```bash
export FINANCIAL_AGENT_DATASET_VERSION=organizer-dart-2026-08-24-v2
export FINANCIAL_AGENT_NCP_API_KEY_FILE="$PWD/api.txt"
FINANCIAL_AGENT_EMBEDDING_REPORT=/private/tmp/dart-embedding-preflight.json \
.venv/bin/python -m financial_agent.embeddings preflight --expected-chunks 37629
```

Expected: `EMBEDDING_PREFLIGHT_OK eligible=37629 existing=0 missing=37629`, with zero NCP request. Stop if dataset status is not `building`, the count differs, a model row conflicts, stale/orphan rows exist, or free disk is below the predicted PostgreSQL increase plus 1 GiB safety margin.

- [ ] **Step 2: Execute and inspect the one-chunk canary**

```bash
FINANCIAL_AGENT_EMBEDDING_REPORT=/private/tmp/dart-embedding-canary.json \
.venv/bin/python -m financial_agent.embeddings canary --expected-chunks 37629
```

Expected: one NCP success, 1,024 finite floats validated, one row committed and read back, positive provider token count, and no body/vector/key in console or report. Stop on authentication, dimension, token-limit, or write/read-back failure.

- [ ] **Step 3: Resolve and embed one bounded real product sample**

First list exact eligible products without exposing them to NCP:

```bash
.venv/bin/python -m financial_agent.embeddings sample-candidates --limit 10
```

Choose one displayed product that has both `investment_strategy` and `risk_factor`, then run:

```bash
export FINANCIAL_AGENT_SAMPLE_PRODUCT='KODEX 200'
FINANCIAL_AGENT_EMBEDDING_REPORT=/private/tmp/dart-embedding-sample.json \
.venv/bin/python -m financial_agent.embeddings sample \
  --product-name "$FINANCIAL_AGENT_SAMPLE_PRODUCT" \
  --limit 20 --expected-chunks 37629
```

Expected: exact local product resolution, at least one strategy and risk chunk embedded, at most 20 new rows, and safe resume on an immediate repeat. If `KODEX 200` is not one of the exact displayed candidates, use an exact displayed name; do not use fuzzy matching.

- [ ] **Step 4: Run fixed-query real Top-5 validation**

```bash
FINANCIAL_AGENT_EMBEDDING_REPORT=/private/tmp/dart-embedding-verify.json \
.venv/bin/python -m financial_agent.embeddings verify \
  --product-name "$FINANCIAL_AGENT_SAMPLE_PRODUCT"
```

The command uses only these fixed generic remote query texts:

```text
주요 투자위험과 원금 손실 가능성
투자목적과 구체적인 운용전략
```

Expected: risk and strategy expected sections each appear in Vector Top 5 and fused Top 5, every hit binds to the exact current source/chunk hash, and Evidence/relation/readiness/activation counts have zero delta. Use the same exact product selected in Step 3.

- [ ] **Step 5: Execute the resumable full build**

```bash
FINANCIAL_AGENT_EMBEDDING_REPORT=/private/tmp/dart-embedding-full.json \
.venv/bin/python -m financial_agent.embeddings full \
  --expected-chunks 37629 --batch-size 25
```

Expected: every missing exact identity is processed; 429, timeout, and retryable 5xx use bounded retry; committed batches remain valid after interruption. On an interrupted run, execute the identical command again. Do not delete the successful canary/sample rows.

- [ ] **Step 6: Reconcile the final local state**

```bash
FINANCIAL_AGENT_EMBEDDING_REPORT=/private/tmp/dart-embedding-reconcile.json \
.venv/bin/python -m financial_agent.embeddings reconcile \
  --expected-chunks 37629
```

Expected:

```text
eligible=37629
exact=37629
missing=0
duplicate=0
stale=0
orphan=0
wrong_dimension=0
dimension=1024
```

The report must also show actual model/token totals, measured table/index bytes, zero Evidence/relation/readiness/activation delta, and zero temporary PDF/vector files.

- [ ] **Step 7: Verify that operational artifacts remain untracked**

```bash
git status --short
git ls-files api.txt '/private/tmp/dart-embedding-*.json' '*.pdf' '*.npy' '*.npz'
```

Expected: no API key, report, PDF, vector file, or local database is tracked. Report the final counts, total returned input tokens, measured storage increase, provider retries/failures, and retrieval Top-5 results to the user without publishing the report contents.
