# Feature Implementation Plan

**Feature:** Official Document Manifest and Access Preflight

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, read-only audit that enumerates every in-scope product, index, and approved policy Entity, discovers its required tier 1–3 official documents, writes a canonical source manifest, and reports every document that cannot be obtained without silently falling back to a lower-authority source.

**Architecture:** Extend the implemented Phase 0 document authority boundary with a source-audit layer. PostgreSQL supplies exact target Entities and identifiers; small source-specific adapters discover regulator filings or validate reviewed tier 2–3 locators; a deterministic coordinator emits one canonical JSON report and exits nonzero when required coverage is incomplete. This plan does not download complete document bodies, parse PDFs/HTML, generate embeddings, write document/Evidence rows, or activate a dataset.

**Tech Stack:** Python 3.12, frozen dataclasses, SQLAlchemy 2 async Core, urllib request injection, PostgreSQL 15, pytest 8, existing canonical JSON and source-verification utilities.

**Spec:** `docs/planning/specs/2026-08-29-vector-document-corpus-design.md`

## Global Constraints

- The current evaluation cutoff is `2026-08-24` in `Asia/Seoul`; preserve actual publication, availability, and effective timestamps.
- Admit only tier 1 regulator/supervisor filings, tier 2 index-provider/ministry/public-institution originals, and tier 3 exchange/association official disclosures.
- Never fall back to asset-manager, issuer-website, distributor, news, blog, search-result, generated-summary, or generated-translation sources.
- Treat a regulator-served filing submitted by an issuer as tier 1; the preserved locator must be the regulator filing locator.
- Track all organizer products in the audit. Domestic bonds produce `not_applicable_current_scope` and no discovery request.
- Use one current product document per required role, one methodology per unique `index_id`, and only Claim-impact change disclosures.
- Do not infer an Entity binding from document-title or Vector similarity. Exact normalized product name is only a secondary check after stable identifiers and approved publisher context resolve one Entity.
- Discovery and preflight are read-only. They must not write PostgreSQL, Object Storage, document rows, Evidence, Graph, embeddings, or dataset lifecycle state.
- Raw official files, audit outputs, API responses, local databases, credentials, and generated per-product manifests remain untracked.
- Tests use synthetic responses and fixtures. Live official-source checks require the existing `official_data` pytest gate and explicit configuration.
- A required source failure is an auditable result, not a reason to lower the authority threshold. The CLI must identify the target Entity, required document role, source code, and stable failure reason without printing credentials or secret-bearing URLs.

## Scope Decomposition

This is the first of four independently testable subprojects:

1. **This plan:** source authority enforcement, target enumeration, document discovery, access preflight, and canonical availability report.
2. **Follow-up:** immutable full-object capture and checksum manifests for eligible documents.
3. **Follow-up:** source-format parsing, exact section extraction, Claim-impact change classification, and approved chunk production.
4. **Follow-up:** embedding benchmark, pgvector population, real-document retrieval evaluation, and dataset activation gate.

The first plan must finish with an exact unavailable-source report before any later plan downloads or indexes document content.

## File Structure

| Path | Responsibility |
| --- | --- |
| `src/financial_agent/documents/models.py` | Add exchange/association publisher roles while preserving legacy role values for readback. |
| `src/financial_agent/documents/policy.py` | Enforce ADR-0021 publisher-role authority and no issuer/manager fallback. |
| `src/financial_agent/documents/source_manifest.py` | Typed source tiers, targets, discovered candidates, audit entries, canonical report validation and writing. |
| `src/financial_agent/db/repositories/document_targets.py` | Read-only enumeration of product and unique-index document targets from one dataset version. |
| `src/financial_agent/ingestion/document_sources/base.py` | Adapter protocol, sanitized request context, stable audit error taxonomy. |
| `src/financial_agent/ingestion/document_sources/dart.py` | OpenDART corp/filing discovery for domestic ETFs and public funds. |
| `src/financial_agent/ingestion/document_sources/sec.py` | SEC Series/Class-bound 497K and regulator-filed supplement discovery. |
| `src/financial_agent/ingestion/document_sources/registered.py` | Validation of reviewed tier 2–3 methodology, policy, exchange, and association locators. |
| `src/financial_agent/ingestion/document_sources/audit.py` | Deterministic adapter routing, no-fallback disposition, completeness aggregation. |
| `config/official-document-authorities.json` | Hand-reviewed authority/domain and Claim-ownership registry; no credentials or raw content. |
| `src/financial_agent/ingestion/cli.py` | `audit-document-sources` command and sanitized summary. |
| `tests/documents/test_source_manifest.py` | Source contract, canonical JSON, scope, and secret-safety tests. |
| `tests/documents/test_policy.py` | Three-tier admission and legacy-role rejection tests. |
| `tests/db/test_document_target_repository.py` | PostgreSQL target enumeration and deduplication tests. |
| `tests/ingestion/document_sources/` | Synthetic adapter, coordinator, access-status, and CLI tests. |
| `tests/ingestion/test_real_official_document_sources.py` | Explicitly gated live access audit smoke tests. |
| `docs/planning/STATUS.md` | Record a real audit only after it runs; never mark corpus population complete. |

---

### Task 1: Enforce the Approved Three-Tier Publisher Boundary

**Files:**
- Modify: `src/financial_agent/documents/models.py`
- Modify: `src/financial_agent/documents/policy.py`
- Modify: `src/financial_agent/documents/__init__.py`
- Modify: `tests/documents/test_policy.py`
- Modify: `tests/fixtures/document_corpus.py`

**Interfaces:**
- Consumes: existing `PublisherRole`, `DocumentCandidate`, `DocumentRole`, `admit_document()`, and `select_canonical_document()`.
- Produces: `PublisherRole.EXCHANGE`, `PublisherRole.INDUSTRY_ASSOCIATION`, and an authority matrix in `publisher_roles_for_document_role()` that exactly implements ADR-0021.

- [ ] **Step 1: Write failing publisher-boundary tests**

Add tests that prove regulator-served product filings are accepted, direct issuer/manager copies are rejected, and tier 3 publishers are accepted only for product-bound official updates:

```python
@pytest.mark.parametrize(
    "publisher_role",
    (PublisherRole.ASSET_MANAGER, PublisherRole.ISSUER),
)
def test_product_document_rejects_manager_or_issuer_fallback(
    publisher_role: PublisherRole,
) -> None:
    decision = admit_document(
        candidate(
            document_type="summary_prospectus",
            publisher_role=publisher_role,
            binding_role="subject_product",
        ),
        cutoff_date=CUTOFF,
    )

    assert decision.accepted is False
    assert decision.coverage_status is CoverageStatus.PUBLISHER_NOT_APPROVED
    assert decision.reason_code == "publisher_role_not_approved"


@pytest.mark.parametrize(
    "publisher_role",
    (PublisherRole.EXCHANGE, PublisherRole.INDUSTRY_ASSOCIATION),
)
def test_product_change_accepts_tier_three_claim_owner(
    publisher_role: PublisherRole,
) -> None:
    decision = admit_document(
        candidate(
            document_type="official_update",
            publisher_role=publisher_role,
            binding_role="subject_product",
            claim_types=frozenset({"official_update"}),
        ),
        cutoff_date=CUTOFF,
    )

    assert decision.accepted is True
```

Also prove an exchange cannot publish `index_methodology` or `policy_base`, an index provider cannot publish a product prospectus, and existing regulator, index-provider, policy-authority, and public policy-operator cases remain accepted.

- [ ] **Step 2: Run the focused tests and confirm the red state**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/documents/test_policy.py -k 'publisher or fallback or tier_three' -q
```

Expected: failures because the new enum members do not exist and manager/issuer roles remain approved for product documents.

- [ ] **Step 3: Implement the minimal authority change**

Keep `ASSET_MANAGER` and `ISSUER` enum members for legacy row readback, but remove them from public admission. Add:

```python
class PublisherRole(str, Enum):
    REGULATOR_DISCLOSURE = "regulator_disclosure"
    ASSET_MANAGER = "asset_manager"
    ISSUER = "issuer"
    INDEX_PROVIDER = "index_provider"
    POLICY_AUTHORITY = "policy_authority"
    POLICY_OPERATOR = "policy_operator"
    EXCHANGE = "exchange"
    INDUSTRY_ASSOCIATION = "industry_association"
```

Use these exact approved sets:

```python
_PRODUCT_PUBLISHERS = frozenset({PublisherRole.REGULATOR_DISCLOSURE})

_OFFICIAL_UPDATE_PUBLISHERS = {
    "subject_product": frozenset(
        {
            PublisherRole.REGULATOR_DISCLOSURE,
            PublisherRole.EXCHANGE,
            PublisherRole.INDUSTRY_ASSOCIATION,
        }
    ),
    "subject_index": frozenset({PublisherRole.INDEX_PROVIDER}),
    "subject_policy": frozenset(
        {PublisherRole.POLICY_AUTHORITY, PublisherRole.POLICY_OPERATOR}
    ),
}
```

Update synthetic positive product documents to use `REGULATOR_DISCLOSURE`. Retain explicit negative fixtures for `ASSET_MANAGER` and `ISSUER`; do not erase their legacy vocabulary.

- [ ] **Step 4: Run all document-policy tests**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/documents/test_policy.py -q
```

Expected: all tests pass, including the new no-fallback cases.

- [ ] **Step 5: Commit the independent authority boundary**

```bash
git add src/financial_agent/documents/models.py src/financial_agent/documents/policy.py src/financial_agent/documents/__init__.py tests/documents/test_policy.py tests/fixtures/document_corpus.py
git diff --cached --check
git commit -m "fix: enforce official document source tiers"
```

---

### Task 2: Define the Canonical Document Source Audit Contract

**Files:**
- Create: `src/financial_agent/documents/source_manifest.py`
- Modify: `src/financial_agent/documents/__init__.py`
- Create: `tests/documents/test_source_manifest.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `DocumentRole`, `CoverageStatus`, `PublisherRole`, cutoff `2026-08-24`, and the existing atomic-write pattern in `ingestion.official.snapshot`.
- Produces: `SourceAuthorityTier`, `DocumentSourceTarget`, `DocumentSourceCandidate`, `SourceAuditStatus`, `DocumentSourceAuditEntry`, `DocumentSourceAuditReport`, `validate_document_source_report()`, and `write_document_source_report()`.

- [ ] **Step 1: Write failing model and canonical-output tests**

Define the expected public contract in tests:

```python
def test_report_is_canonical_across_entry_order(tmp_path: Path) -> None:
    first = audit_entry(entity_id="product-b", required_role=DocumentRole.PRODUCT_SUMMARY)
    second = audit_entry(entity_id="product-a", required_role=DocumentRole.PRODUCT_SUMMARY)
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"

    left_hash = write_document_source_report(report(entries=(first, second)), left)
    right_hash = write_document_source_report(report(entries=(second, first)), right)

    assert left.read_bytes() == right.read_bytes()
    assert left_hash == right_hash == hashlib.sha256(left.read_bytes()).hexdigest()


def test_unavailable_entry_requires_stable_reason_without_candidate() -> None:
    with pytest.raises(ValueError, match="unavailable audit entry"):
        DocumentSourceAuditEntry(
            target=target(),
            status=SourceAuditStatus.DOCUMENT_NOT_FOUND,
            reason_code=None,
            candidate=None,
        )
```

Add tests for duplicate `(dataset_version, entity_id, required_role)` keys, invalid cutoff, blank IDs, naive timestamps, query strings containing credential-like parameters, non-HTTPS external locators, and a report that tries to mark a domestic bond as `eligible`.

- [ ] **Step 2: Run the tests and confirm the module is missing**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/documents/test_source_manifest.py -q
```

Expected: import failure for `financial_agent.documents.source_manifest`.

- [ ] **Step 3: Implement the frozen contract**

Use these exact enums:

```python
class SourceAuthorityTier(str, Enum):
    TIER_1_REGULATORY = "tier_1_regulatory"
    TIER_2_CLAIM_OWNER = "tier_2_claim_owner"
    TIER_3_EXCHANGE_ASSOCIATION = "tier_3_exchange_association"


class SourceAuditStatus(str, Enum):
    ELIGIBLE = "eligible"
    NOT_APPLICABLE_CURRENT_SCOPE = "not_applicable_current_scope"
    DOCUMENT_NOT_FOUND = "document_not_found"
    IDENTIFIER_MISSING = "identifier_missing"
    AMBIGUOUS_ENTITY_BINDING = "ambiguous_entity_binding"
    CREDENTIALS_MISSING = "credentials_missing"
    ACCESS_DENIED = "access_denied"
    RATE_LIMITED = "rate_limited"
    ACCESS_METHOD_UNVERIFIED = "access_method_unverified"
    TERMS_REVIEW_REQUIRED = "terms_review_required"
    AFTER_CUTOFF_ONLY = "after_cutoff_only"
    VERSION_UNKNOWN = "version_unknown"
    MEDIA_TYPE_UNSUPPORTED = "media_type_unsupported"
```

Use frozen dataclasses with these fields:

```python
@dataclass(frozen=True, slots=True)
class DocumentSourceTarget:
    dataset_version: str
    entity_id: str
    entity_type: str
    canonical_name: str
    product_family: str | None
    required_role: DocumentRole
    binding_role: str
    identifiers: tuple[tuple[str, str], ...]
    cutoff_date: date


@dataclass(frozen=True, slots=True)
class DocumentSourceCandidate:
    document_id: str
    source_code: str
    authority_tier: SourceAuthorityTier
    publisher_code: str
    publisher_role: PublisherRole
    document_type: str
    document_version: str | None
    source_locator: str
    discovery_locator: str
    jurisdiction: str
    original_language: str
    published_at: datetime | None
    available_at: datetime | None
    effective_from: date | None
    effective_to: date | None
    media_type: str | None
    accession_or_receipt_id: str | None


@dataclass(frozen=True, slots=True)
class DocumentSourceAuditEntry:
    target: DocumentSourceTarget
    status: SourceAuditStatus
    reason_code: str | None
    candidate: DocumentSourceCandidate | None


@dataclass(frozen=True, slots=True)
class DocumentSourceAuditReport:
    schema_version: str
    generated_at: datetime
    cutoff_date: date
    dataset_version: str
    entries: tuple[DocumentSourceAuditEntry, ...]
```

`schema_version` is exactly `1.0`. Sort entries by `(entity_type, entity_id, required_role.value)` and identifiers by `(scheme, value)`. Serialize UTC datetimes with `Z`, `ensure_ascii=False`, `sort_keys=True`, compact separators, and `allow_nan=False`. Write atomically with a sibling temporary file, `fsync`, and replacement. Return the SHA-256 of the canonical bytes.

Reject locators with credentials, fragments, secret-like query parameter names, non-HTTPS schemes, or embedded username/password. Allow a query only when every key is in the explicit public set `{"rcpNo", "CIK", "accession_number"}`. Add `document-source-audit*.json` and `document-source-locators*.json` to `.gitignore`; do not ignore the tracked authority registry added later.

- [ ] **Step 4: Run the source-contract tests**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/documents/test_source_manifest.py -q
```

Expected: all tests pass and canonical files contain no secrets.

- [ ] **Step 5: Commit the audit contract**

```bash
git add .gitignore src/financial_agent/documents/source_manifest.py src/financial_agent/documents/__init__.py tests/documents/test_source_manifest.py
git diff --cached --check
git commit -m "feat: define official document source audit"
```

---

### Task 3: Enumerate All Product and Unique-Index Targets Read-Only

**Files:**
- Create: `src/financial_agent/db/repositories/document_targets.py`
- Modify: `src/financial_agent/db/repositories/__init__.py`
- Create: `tests/db/test_document_target_repository.py`
- Modify: `tests/fixtures/db/synthetic_dataset.py`

**Interfaces:**
- Consumes: `catalog.entity`, `catalog.product`, `catalog.identifier`, `relation.relation_record`, one validated `dataset_version`, and `DocumentSourceTarget`.
- Produces: `DocumentTargetRepository.list_targets(dataset_version: str, cutoff_date: date) -> tuple[DocumentSourceTarget, ...]`.

- [ ] **Step 1: Write failing PostgreSQL and compiled-SQL tests**

Seed one domestic bond, two domestic ETFs sharing an index, one overseas ETF, one public fund, and their exact identifiers. Assert:

```python
targets = await repository.list_targets("facts-v1", cutoff_date=CUTOFF)

assert [
    (item.entity_id, item.required_role)
    for item in targets
] == [
    ("bond-1", DocumentRole.PRODUCT_SUMMARY),
    ("domestic-etf-1", DocumentRole.PRODUCT_SUMMARY),
    ("domestic-etf-2", DocumentRole.PRODUCT_SUMMARY),
    ("index-space", DocumentRole.INDEX_METHODOLOGY),
    ("overseas-etf-1", DocumentRole.PRODUCT_SUMMARY),
    ("public-fund-1", DocumentRole.PRODUCT_SUMMARY),
]
assert sum(item.entity_id == "index-space" for item in targets) == 1
```

The bond target remains present so the coordinator can produce `not_applicable_current_scope`. Add negative tests for blank dataset version, a `tracksIndex` relation whose object is not an index, identifiers from another dataset version, and duplicate identifier rows. Add a compiled-SQL assertion that every join contains `dataset_version` equality.

- [ ] **Step 2: Run the tests and confirm the repository is missing**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/db/test_document_target_repository.py -q
```

Expected: import failure for `document_targets`.

- [ ] **Step 3: Implement one bounded repository query**

The repository constructor accepts `AsyncConnection`. Query products and their identifiers, then query `tracksIndex` objects whose `catalog.entity.entity_type == "index"`. Use the product families exactly as stored:

```python
_PRODUCT_BINDINGS = {
    "domestic_bond": (DocumentRole.PRODUCT_SUMMARY, "subject_product"),
    "domestic_etf": (DocumentRole.PRODUCT_SUMMARY, "subject_product"),
    "overseas_etf": (DocumentRole.PRODUCT_SUMMARY, "subject_product"),
    "public_fund": (DocumentRole.PRODUCT_SUMMARY, "subject_product"),
}
```

Index targets use `(DocumentRole.INDEX_METHODOLOGY, "subject_index")`. Sort exact identifiers and targets deterministically. Do not infer a missing `tracksIndex` relation from `cu_base_index` text at audit time; that normalization belongs to Stage 03.

Keep the repository read-only: it exposes no append/update method and executes only `SELECT` statements. The coordinator, not this repository, assigns the bond disposition.

- [ ] **Step 4: Run repository tests against the disposable PostgreSQL database**

Run:

```bash
env PYTHONPATH=src FINANCIAL_AGENT_TEST_DATABASE_URL="$FINANCIAL_AGENT_TEST_DATABASE_URL" \
  .venv/bin/python -m pytest tests/db/test_document_target_repository.py -m postgres -q
```

Expected: all target and dataset-key tests pass.

- [ ] **Step 5: Commit target enumeration**

```bash
git add src/financial_agent/db/repositories/document_targets.py src/financial_agent/db/repositories/__init__.py tests/db/test_document_target_repository.py tests/fixtures/db/synthetic_dataset.py
git diff --cached --check
git commit -m "feat: enumerate official document targets"
```

---

### Task 4: Add a Fail-Closed Source Adapter Protocol

**Files:**
- Create: `src/financial_agent/ingestion/document_sources/__init__.py`
- Create: `src/financial_agent/ingestion/document_sources/base.py`
- Create: `tests/ingestion/document_sources/__init__.py`
- Create: `tests/ingestion/document_sources/test_base.py`

**Interfaces:**
- Consumes: `DocumentSourceTarget`, `DocumentSourceCandidate`, `SourceAuditStatus`, and injected HTTP opener objects.
- Produces: `DocumentSourceAdapter`, `DocumentDiscoveryContext`, `SourceAdapterResult`, `DocumentSourceAccessError`, `sanitize_public_locator()`, and `classify_access_error()`.

- [ ] **Step 1: Write failing protocol and error-mapping tests**

Test exact mappings:

```python
@pytest.mark.parametrize(
    ("status_code", "expected"),
    (
        (401, SourceAuditStatus.ACCESS_DENIED),
        (403, SourceAuditStatus.ACCESS_DENIED),
        (404, SourceAuditStatus.DOCUMENT_NOT_FOUND),
        (429, SourceAuditStatus.RATE_LIMITED),
    ),
)
def test_http_status_maps_to_stable_audit_status(
    status_code: int,
    expected: SourceAuditStatus,
) -> None:
    assert classify_access_error(HttpStatusError(status_code)) is expected
```

Add cases for DNS/timeout as `access_method_unverified`, missing required environment as `credentials_missing`, disallowed redirect host as `access_denied`, and a raised exception whose text contains a synthetic API key. Assert `str(DocumentSourceAccessError)` exposes only its stable code.

- [ ] **Step 2: Run and confirm the package is missing**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/document_sources/test_base.py -q
```

Expected: import failure for `financial_agent.ingestion.document_sources`.

- [ ] **Step 3: Implement the protocol and sanitized failures**

Use:

```python
@dataclass(frozen=True, slots=True)
class DocumentDiscoveryContext:
    cutoff_date: date
    dart_api_key: str | None
    sec_user_agent: str | None
    locator_registry_path: Path | None


@dataclass(frozen=True, slots=True)
class SourceAdapterResult:
    status: SourceAuditStatus
    reason_code: str | None
    candidates: tuple[DocumentSourceCandidate, ...]


class DocumentSourceAdapter(Protocol):
    source_code: str

    def supports(self, target: DocumentSourceTarget) -> bool: ...

    def discover(
        self,
        target: DocumentSourceTarget,
        context: DocumentDiscoveryContext,
    ) -> SourceAdapterResult: ...
```

`DocumentSourceAccessError` stores `code` and `status` only; its public message is the code. Preserve the original exception only as a chained cause in internal test paths, never in CLI output. `sanitize_public_locator()` applies the same HTTPS, host, userinfo, query-key, and fragment rules as Task 2 and strips no value silently: invalid input raises a stable error.

- [ ] **Step 4: Run adapter-boundary tests**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/document_sources/test_base.py -q
```

Expected: all error, redirect, and secret-safety tests pass.

- [ ] **Step 5: Commit the adapter boundary**

```bash
git add src/financial_agent/ingestion/document_sources tests/ingestion/document_sources
git diff --cached --check
git commit -m "feat: add document source adapter boundary"
```

---

### Task 5: Discover Domestic Fund and ETF Filings Through OpenDART

**Files:**
- Create: `src/financial_agent/ingestion/document_sources/dart.py`
- Create: `tests/ingestion/document_sources/test_dart.py`

**Interfaces:**
- Consumes: the Task 4 adapter protocol; exact `DART_CORP_CODE` or approved publisher binding; domestic ETF/public-fund targets; `FINANCIAL_AGENT_DART_API_KEY` supplied through context.
- Produces: `DartDocumentSourceAdapter(opener)` returning regulator-served prospectus candidates or an exact unavailable status.

- [ ] **Step 1: Write failing synthetic OpenDART tests**

Create fixed JSON/ZIP response fixtures in the test file, not captured live files. Test:

```python
def test_dart_selects_latest_effective_collective_investment_prospectus() -> None:
    result = adapter(responses=valid_responses()).discover(target(), context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert [item.accession_or_receipt_id for item in result.candidates] == [
        "20260820000123"
    ]
    assert result.candidates[0].authority_tier is SourceAuthorityTier.TIER_1_REGULATORY
    assert result.candidates[0].publisher_role is PublisherRole.REGULATOR_DISCLOSURE
```

Add tests for: missing API key, absent `DART_CORP_CODE`, two publisher corp codes, exact product-name mismatch, only post-cutoff filings, original plus correction chain selecting the latest effective correction, non-prospectus filings ignored, pagination, OpenDART error status, malformed schema, and API key absence from every result and exception string.

- [ ] **Step 2: Run and confirm the DART adapter is missing**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/document_sources/test_dart.py -q
```

Expected: import failure for `document_sources.dart`.

- [ ] **Step 3: Implement bounded DART discovery**

Use only official OpenDART endpoints documented under the disclosure-information API group:

- `https://opendart.fss.or.kr/api/list.json` for filing search;
- `https://opendart.fss.or.kr/api/document.xml` as the regulator-served original-file locator;
- the exact 14-digit `rcept_no` as accession/receipt identity.

Never place `crtfc_key` in a stored locator. The stored source locator is the public DART viewer URL:

```python
f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}"
```

Search only through an exact approved publisher corp code, `bgn_de <= cutoff`, `end_de == cutoff`, and filing categories that can contain collective-investment prospectuses. Normalize whitespace only for the secondary exact product-name comparison. Do not use substring/fuzzy name binding when two products could match. Select correction chains by original report identity and receipt chronology, but return all exact current candidates to the central canonical selector rather than choosing by similarity.

Map missing/ambiguous identifiers before any network call. A missing API key returns `credentials_missing`; it does not raise a generic configuration failure that hides which targets were blocked.

- [ ] **Step 4: Run all synthetic DART tests**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/document_sources/test_dart.py -q
```

Expected: all exact-binding, cutoff, correction, and secret-safety tests pass.

- [ ] **Step 5: Commit DART discovery**

```bash
git add src/financial_agent/ingestion/document_sources/dart.py tests/ingestion/document_sources/test_dart.py
git diff --cached --check
git commit -m "feat: discover regulator-filed domestic prospectuses"
```

---

### Task 6: Discover Overseas ETF Prospectuses Through SEC EDGAR

**Files:**
- Create: `src/financial_agent/ingestion/document_sources/sec.py`
- Create: `tests/ingestion/document_sources/test_sec.py`

**Interfaces:**
- Consumes: exact `SEC_CIK`, `SEC_SERIES_ID`, and `SEC_CLASS_ID` identifiers from a target; Task 4 protocol; required `FINANCIAL_AGENT_SEC_USER_AGENT` supplied through context.
- Produces: `SecDocumentSourceAdapter(opener)` returning exact Series/Class-bound 497K candidates and regulator-filed supplement/full-prospectus fallbacks.

- [ ] **Step 1: Write failing SEC discovery tests**

Use synthetic submissions and filing-index JSON. Assert 497K precedence and Series/Class purity:

```python
def test_sec_returns_only_497k_bound_to_exact_series_and_class() -> None:
    result = adapter(responses=sec_responses()).discover(target(), context())

    assert result.status is SourceAuditStatus.ELIGIBLE
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.document_type == "summary_prospectus"
    assert candidate.accession_or_receipt_id == "0001445546-25-008729"
    assert candidate.source_locator.startswith("https://www.sec.gov/Archives/")
```

Add cases for missing User-Agent, absent or ambiguous CIK/Series/Class IDs, a filing for another class under the same CIK, 497K after cutoff, current 497K plus older 497K, no 497K but eligible 485BPOS/N-1A full prospectus, relevant 497 supplement, unrelated 497 material, pagination into older submissions files, malformed JSON, 403/429 handling, and user-agent text absent from report fields.

- [ ] **Step 2: Run and confirm the SEC adapter is missing**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/document_sources/test_sec.py -q
```

Expected: import failure for `document_sources.sec`.

- [ ] **Step 3: Implement exact EDGAR discovery**

Use official public endpoints:

- `https://data.sec.gov/submissions/CIK##########.json` for filing history;
- regulator archive filing indexes under `https://www.sec.gov/Archives/edgar/data/...` for exact Series/Class verification and primary document location.

Require a descriptive SEC User-Agent in the existing `organization email` format. Normalize CIK to ten digits only for endpoint construction; preserve accession numbers with dashes in the manifest and remove dashes only for the archive path. Filter filing dates and acceptance times against the cutoff before opening a filing index.

Document precedence is `497K` summary first, then an effective regulator-filed full prospectus (`485BPOS`, `N-1A`, `N-1A/A`) only when no eligible summary exists for the required Claim. A `497` document is an official-update candidate only when its filing metadata and exact Series/Class binding identify the target; generic definitive material is not automatically a Claim-impact change.

- [ ] **Step 4: Run all synthetic SEC tests**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/document_sources/test_sec.py -q
```

Expected: all form-precedence, Series/Class, cutoff, pagination, and access-status tests pass.

- [ ] **Step 5: Commit SEC discovery**

```bash
git add src/financial_agent/ingestion/document_sources/sec.py tests/ingestion/document_sources/test_sec.py
git diff --cached --check
git commit -m "feat: discover regulator-filed overseas prospectuses"
```

---

### Task 7: Validate Reviewed Tier 2–3 Locators Without Generic Crawling

**Files:**
- Create: `config/official-document-authorities.json`
- Create: `src/financial_agent/ingestion/document_sources/registered.py`
- Create: `tests/fixtures/document_source_locators.json`
- Create: `tests/ingestion/document_sources/test_registered.py`

**Interfaces:**
- Consumes: a tracked authority/domain registry and an ignored per-target locator registry passed through `DocumentDiscoveryContext.locator_registry_path`.
- Produces: `RegisteredDocumentSourceAdapter(opener, authority_registry)` for index methodologies, policy documents, exchange changes, and association disclosures.

- [ ] **Step 1: Write failing registry and locator tests**

The tracked authority registry has this exact top-level shape:

```json
{
  "schema_version": "1.0",
  "authorities": [
    {
      "source_code": "SYNTHETIC_INDEX_PROVIDER",
      "authority_tier": "tier_2_claim_owner",
      "publisher_role": "index_provider",
      "jurisdiction": "ZZ",
      "allowed_hosts": ["index.example.invalid"],
      "allowed_document_roles": ["index_methodology", "official_update"]
    }
  ]
}
```

The ignored locator registry has entries keyed by `(entity_id, required_role)` with `source_code`, `source_locator`, `discovery_locator`, document type/version, timestamps, language, jurisdiction, and media type. Test rejection of unknown hosts, wrong tier, wrong publisher role, a product locator assigned to an index role, query secrets, redirects outside allowed hosts, missing reviewed locator, duplicate keys, post-cutoff timestamps, and `text/html` or PDF content-type mismatch.

- [ ] **Step 2: Run and confirm registered-locator support is missing**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/document_sources/test_registered.py -q
```

Expected: import failure for `document_sources.registered`.

- [ ] **Step 3: Implement strict registered-locator validation**

Do not build a generic web crawler. Load the tracked authority registry, validate its schema, then load the configured per-target locator registry. A missing per-target locator returns `access_method_unverified`, not `document_not_found`, because the approved source may exist but has not been reviewed.

For access preflight, issue an injected `GET` with `Range: bytes=0-0` and a bounded timeout because many official servers do not implement `HEAD` consistently. Accept `200` or `206`, validate final redirect host, media type, and nonzero content length when supplied, and read at most one byte. Do not persist response bodies. Map a source that requires unreviewed click-through terms to `terms_review_required` through an explicit registry flag; do not click or accept terms automatically.

The production tracked registry initially contains only reviewed authority/domain rules. Product- and index-specific locator entries remain ignored audit input and later become the generated manifest output; raw document bytes never enter this file.

- [ ] **Step 4: Run registered-locator tests**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/document_sources/test_registered.py -q
```

Expected: all host, role, media, cutoff, terms, and bounded-read tests pass.

- [ ] **Step 5: Commit tier 2–3 validation**

```bash
git add config/official-document-authorities.json src/financial_agent/ingestion/document_sources/registered.py tests/fixtures/document_source_locators.json tests/ingestion/document_sources/test_registered.py
git diff --cached --check
git commit -m "feat: validate reviewed official document locators"
```

---

### Task 8: Coordinate No-Fallback Discovery and Emit an Incomplete-Coverage Report

**Files:**
- Create: `src/financial_agent/ingestion/document_sources/audit.py`
- Create: `tests/ingestion/document_sources/test_audit.py`

**Interfaces:**
- Consumes: ordered targets; DART, SEC, and registered-locator adapters; existing `select_canonical_document()` after candidate conversion.
- Produces: `audit_document_sources(targets, adapters, context, generated_at) -> DocumentSourceAuditReport` and `document_source_audit_passed(report) -> bool`.

- [ ] **Step 1: Write failing routing and completeness tests**

Cover these behaviors:

```python
def test_audit_does_not_fallback_after_tier_one_product_failure() -> None:
    report = audit_document_sources(
        targets=(domestic_etf_target(),),
        adapters=(
            StubAdapter("DART", status=SourceAuditStatus.DOCUMENT_NOT_FOUND),
            StubAdapter("MANAGER", candidate=manager_candidate()),
        ),
        context=context(),
        generated_at=NOW,
    )

    assert report.entries[0].status is SourceAuditStatus.DOCUMENT_NOT_FOUND
    assert report.entries[0].candidate is None
    assert document_source_audit_passed(report) is False
```

Add tests for domestic bonds becoming `not_applicable_current_scope` without adapter calls; duplicate indexes audited once; DART route for domestic ETF/public fund; SEC route only when exact SEC identifiers exist; registered route for indexes and policy targets; unavailable entries retained rather than dropped; adapter exceptions converted to stable statuses; stable output independent of target/adapter order; and no calls to later/lower authority adapters after the owning authority returns a terminal result.

- [ ] **Step 2: Run and confirm coordinator is missing**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/document_sources/test_audit.py -q
```

Expected: import failure for `document_sources.audit`.

- [ ] **Step 3: Implement deterministic Claim-owner routing**

Route by document role and exact context, not by trying every adapter:

```python
def _route_key(target: DocumentSourceTarget) -> str:
    if target.product_family in {"domestic_etf", "public_fund"}:
        return "DART"
    if target.product_family == "overseas_etf":
        return "SEC" if _has_complete_sec_identity(target) else "REGISTERED"
    if target.required_role in {
        DocumentRole.INDEX_METHODOLOGY,
        DocumentRole.OFFICIAL_UPDATE,
        DocumentRole.POLICY_BASE,
    }:
        return "REGISTERED"
    return "NOT_APPLICABLE"
```

An overseas product without complete SEC identity routes to the reviewed jurisdictional registry; it does not assume the product is U.S.-registered. If no jurisdictional locator is registered, report `access_method_unverified`.

Convert eligible source candidates into existing `DocumentCandidate` objects and reuse `select_canonical_document()` for role, cutoff, version, and exact-binding gates. Preserve every rejected candidate ID in internal diagnostics, but the public audit report stores only the selected candidate and one stable disposition per target role.

- [ ] **Step 4: Run coordinator and all synthetic source tests**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/documents/test_source_manifest.py tests/ingestion/document_sources -q
```

Expected: all no-fallback, routing, canonical-selection, and report tests pass.

- [ ] **Step 5: Commit audit coordination**

```bash
git add src/financial_agent/ingestion/document_sources/audit.py tests/ingestion/document_sources/test_audit.py
git diff --cached --check
git commit -m "feat: audit official document source coverage"
```

---

### Task 9: Expose a Read-Only Audit CLI and User-Visible Failure Summary

**Files:**
- Modify: `src/financial_agent/ingestion/cli.py`
- Create: `tests/ingestion/test_document_source_audit_cli.py`

**Interfaces:**
- Consumes: `FINANCIAL_AGENT_DOCUMENT_AUDIT_DATABASE_URL`, `FINANCIAL_AGENT_DATASET_VERSION`, `FINANCIAL_AGENT_DOCUMENT_AUDIT_OUTPUT_ROOT`, optional `FINANCIAL_AGENT_DART_API_KEY`, required-for-SEC `FINANCIAL_AGENT_SEC_USER_AGENT`, and optional `FINANCIAL_AGENT_DOCUMENT_LOCATOR_REGISTRY`.
- Produces: `financial-agent-ingestion audit-document-sources`, canonical `document-source-audit.json`, exit 0 for complete eligible/not-applicable coverage, and exit 2 for any required unavailable target.

- [ ] **Step 1: Write failing CLI tests**

Test a complete report and a mixed unavailable report. Capture stdout/stderr:

```python
def test_audit_cli_reports_unavailable_sources_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FINANCIAL_AGENT_DART_API_KEY", "SYNTHETIC-SECRET")
    monkeypatch.setattr(cli, "_run_document_source_audit", fake_incomplete_audit)

    exit_code = asyncio.run(cli.main(("audit-document-sources",)))
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert "DOCUMENT_SOURCE_AUDIT_INCOMPLETE" in output.err
    assert "document_not_found=1" in output.err
    assert "SYNTHETIC-SECRET" not in output.err
```

Add tests for atomic output, read-only PostgreSQL transaction settings, blank environment values, invalid output paths, missing DART key represented per target, missing SEC User-Agent represented per target, no raw HTTP body in errors, and stable sorted counts by status and source code.

- [ ] **Step 2: Run and confirm command is absent**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/test_document_source_audit_cli.py -q
```

Expected: parser rejects `audit-document-sources`.

- [ ] **Step 3: Implement the command**

Add the parser command and a handler that:

1. opens an async PostgreSQL connection with `default_transaction_read_only=on`;
2. enumerates targets for the configured dataset;
3. adds approved policy targets from the reviewed locator registry only when they have an exact Entity ID already present in PostgreSQL;
4. runs the deterministic audit;
5. writes `<output_root>/document-source-audit.json` atomically; and
6. prints one sanitized summary.

Success output:

```text
DOCUMENT_SOURCE_AUDIT_OK targets=<n> eligible=<n> not_applicable=<n> report_hash=<sha256>
```

Incomplete output goes to stderr and includes sorted aggregate counts, not credential-bearing URLs:

```text
DOCUMENT_SOURCE_AUDIT_INCOMPLETE targets=<n> eligible=<n> unavailable=<n> document_not_found=<n> identifier_missing=<n> credentials_missing=<n> access_denied=<n> rate_limited=<n> access_method_unverified=<n> terms_review_required=<n> after_cutoff_only=<n> version_unknown=<n> report_hash=<sha256>
```

The JSON report contains the exact affected Entity IDs, names, roles, source codes, and safe public locators so the user can be told which approved sources failed. Do not collapse failures into one generic configuration error.

- [ ] **Step 4: Run CLI and ordinary regression tests**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion/test_document_source_audit_cli.py tests/ingestion/document_sources tests/documents -m 'not postgres' -q
env PYTHONPATH=src .venv/bin/python -m pytest -m 'not postgres' -q
```

Expected: focused and ordinary non-PostgreSQL suites pass.

- [ ] **Step 5: Commit the audit command**

```bash
git add src/financial_agent/ingestion/cli.py tests/ingestion/test_document_source_audit_cli.py
git diff --cached --check
git commit -m "feat: report unavailable official document sources"
```

---

### Task 10: Run the Gated Access Audit and Freeze the Next-Step Input

**Files:**
- Create: `tests/ingestion/test_real_official_document_sources.py`
- Modify: `docs/planning/STATUS.md`

**Interfaces:**
- Consumes: a dedicated non-production PostgreSQL dataset, approved environment configuration, ignored reviewed locator registry, OpenDART key when available, and SEC User-Agent.
- Produces: a canonical ignored audit report and a truthful status entry listing complete and blocked source populations. It does not produce a populated document corpus.

- [ ] **Step 1: Write a gated live smoke test**

Use the existing `official_data` marker and skip unless `RUN_OFFICIAL_DOCUMENT_SOURCE_AUDIT=1`. The test invokes the same command path as production and asserts:

```python
@pytest.mark.official_data
def test_real_official_document_source_audit_is_canonical(
    configured_audit: ConfiguredDocumentAudit,
) -> None:
    first = run_audit(configured_audit)
    second = run_audit(configured_audit)

    assert first.report_bytes == second.report_bytes
    assert first.database_writes == 0
    assert first.object_storage_writes == 0
```

The test must not require complete coverage to pass. It passes when every target has an explicit disposition, the report is deterministic, and no forbidden write occurs. A separate assertion exposes `document_source_audit_passed(report)` so the completion result cannot be confused with test execution success.

- [ ] **Step 2: Run the complete synthetic and PostgreSQL gates before live access**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest tests/documents tests/ingestion/document_sources tests/ingestion/test_document_source_audit_cli.py -m 'not postgres' -q
env PYTHONPATH=src FINANCIAL_AGENT_TEST_DATABASE_URL="$FINANCIAL_AGENT_TEST_DATABASE_URL" \
  .venv/bin/python -m pytest tests/db/test_document_target_repository.py -m postgres -q
env PYTHONPATH=src .venv/bin/python -m compileall -q src tests
```

Expected: all synthetic and repository gates pass before any official endpoint is called.

- [ ] **Step 3: Run the explicitly configured live audit**

Run only with the user-authorized local dataset and approved official-source configuration:

```bash
env PYTHONPATH=src RUN_OFFICIAL_DOCUMENT_SOURCE_AUDIT=1 \
  .venv/bin/python -m pytest tests/ingestion/test_real_official_document_sources.py -m official_data -q
env PYTHONPATH=src \
  .venv/bin/python -m financial_agent.ingestion.cli audit-document-sources
```

Expected: the gated smoke test passes and the CLI returns either:

- exit 0 with `DOCUMENT_SOURCE_AUDIT_OK`; or
- exit 2 with `DOCUMENT_SOURCE_AUDIT_INCOMPLETE` and a canonical report listing every unavailable target and reason.

Exit 2 is not converted to success and does not trigger a lower-authority fallback. Report the exact aggregate and affected source/Entity groups to the user before planning full-object capture.

- [ ] **Step 4: Update STATUS truthfully**

If and only if the live audit ran, add a bounded Stage 03C note containing:

- dataset version and cutoff;
- target counts by product family and document role;
- eligible, not-applicable, and each unavailable status count;
- approved sources actually contacted;
- sources not contacted because credentials, access, terms, identifiers, or reviewed locators were missing; and
- the statement that no official document body, embedding, Vector row, Evidence, Graph relation, or active dataset was created.

Do not mark `DOC-FUND-001`, `REL-THEME-001`, or `REL-CORP-001` supported. They remain `requires_additional_data / not_run` until later capture, parsing, embedding, retrieval, and Evidence gates pass.

- [ ] **Step 5: Run final repository checks**

Run:

```bash
env PYTHONPATH=src .venv/bin/python -m pytest -m 'not postgres' -q
env PYTHONPATH=src .venv/bin/python -m compileall -q src scripts tests
env PYTHONPATH=src .venv/bin/python scripts/export_contract_schemas.py --check
git diff --check
git status --short
```

Inspect staged paths and prove no `data/`, official PDF/HTML/ZIP body, audit output, credentials, `.env`, database, embedding, or generated index is staged.

- [ ] **Step 6: Commit only verified code and truthful status**

```bash
git add tests/ingestion/test_real_official_document_sources.py docs/planning/STATUS.md
git diff --cached --check
git diff --cached
git commit -m "test: audit official document source availability"
```

If the live audit cannot run because required authorization or local inputs are absent, do not edit STATUS and do not create this commit. Report the blocking configuration to the user while leaving the preceding synthetic implementation commits independently usable.

---

## Completion Gate

This plan is complete only when:

1. manager/issuer website fallback is rejected by the production admission policy;
2. every target product, unique index, and approved policy Entity has exactly one canonical audit disposition per required role;
3. DART and SEC discovery require exact identifiers and never expose credentials;
4. tier 2–3 locators are accepted only through the reviewed authority/domain registry;
5. domestic bonds are recorded as `not_applicable_current_scope` without network access;
6. the audit command is read-only and emits a canonical report with stable unavailable reasons;
7. synthetic, non-live regression, PostgreSQL target, compilation, and contract checks pass;
8. raw official files and generated audit outputs remain outside Git; and
9. the user receives the exact unavailable-source summary before any full-object capture plan begins.

## Deferred Follow-Up Plans

After the user reviews the audit result, write separate plans for:

- immutable official document capture and Object Storage verification;
- DART/SEC HTML and archive parsing plus PDF text/locator extraction for registered sources;
- deterministic Claim-impact change classification and thin section chunking;
- embedding-model benchmark, pgvector population, real gold-span evaluation, and dataset activation.

Do not combine these into this access-audit implementation or start them merely because a locator was found.
