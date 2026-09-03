# DART Missing-Only Scope Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exclude already embedded organizer targets before DART access and classify ETNs and private funds as outside the current fund-prospectus recovery scope.

**Architecture:** Extend the read-only document-target repository to return exact current-model embedding coverage and organizer product-scope facts. Apply one pure target-selection function before publisher reconciliation, then expose completed and non-applicable target counts in the existing sanitized DART run report.

**Tech Stack:** Python 3.12, SQLAlchemy 2, PostgreSQL 15, pgvector, pytest, existing ingestion CLI.

**Spec:** `docs/planning/specs/2026-09-03-dart-missing-embedding-recovery-design.md`

## Global Constraints

- Dataset version remains `organizer-dart-2026-08-24-v2` and source cutoff remains `2026-08-24`.
- Existing exact embeddings for `ncp-clova-bge-m3` / `embedding-v2-dart-search-text-v1` / dimension `1024` must not be changed.
- Completed targets must be excluded before publisher reconciliation, DART requests, PDF capture, chunking, and NCP calls.
- `organizer.pref01n001.product_type = ETN` is not applicable to the fund-prospectus corpus.
- `organizer.prfd01n001.public_private_class = 사모` is not applicable to the current official public-fund prospectus recovery scope under ADR-0028.
- Organizer raw data, local reports, PDFs, database files, and credentials remain untracked.
- This plan does not change product-name matching, correction-lineage selection, PDF extraction, OCR, chunking, or embeddings.

## Decomposition

The approved design spans identity matching, document lineage, attachment
capture, OCR, and embedding. This plan implements the prerequisite scope and
delta-selection boundary only. Its measured residual report is required before
writing the next plan, because name and PDF rules must be based on the actual
remaining official filings rather than speculative normalization.

---

### Task 1: Read exact recovery state from PostgreSQL

**Files:**
- Modify: `src/financial_agent/ingestion/document_sources/dart_targets.py`
- Modify: `src/financial_agent/db/repositories/document_targets.py`
- Test: `tests/db/test_document_target_repository.py`

**Interfaces:**
- Consumes: organizer product markers, `observation.observation_record`, `document.document_entity_binding`, `document.document_chunk`, and `search.document_embedding`.
- Produces: `DartRecoveryProductState(entity_id: str, product_scope: str, has_exact_embedding: bool)` and `DocumentTargetRepository.list_dart_recovery_states(dataset_version, model)`.

- [ ] **Step 1: Write failing repository tests for exact embedding and scope classification**

Add a fixture containing one ETF with an exact embedding, one ETF without an
embedding, one ETN, one public fund, and one private fund. Assert:

```python
states = await repository.list_dart_recovery_states(
    dataset_version,
    APPROVED_MODEL,
)
by_id = {state.entity_id: state for state in states}

assert by_id[embedded_etf_id].has_exact_embedding is True
assert by_id[missing_etf_id].has_exact_embedding is False
assert by_id[etn_id].product_scope == "etn_not_applicable"
assert by_id[public_fund_id].product_scope == "fund_prospectus"
assert by_id[private_fund_id].product_scope == "private_fund_not_applicable"
```

Add stale-hash and wrong-model embeddings for the missing ETF and assert they
do not set `has_exact_embedding=True`.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
pytest tests/db/test_document_target_repository.py -q
```

Expected: FAIL because `DartRecoveryProductState` and
`list_dart_recovery_states` do not exist.

- [ ] **Step 3: Add the state contract and one read-only query**

Add the contract to `dart_targets.py` and import it from the repository:

```python
@dataclass(frozen=True, slots=True)
class DartRecoveryProductState:
    entity_id: str
    product_scope: Literal[
        "fund_prospectus",
        "etn_not_applicable",
        "private_fund_not_applicable",
    ]
    has_exact_embedding: bool
```

Implement `list_dart_recovery_states` with one SQLAlchemy statement. Limit it
to products carrying `PREF01_PD_ITM_NO` or `PRFD_ITM_NO`. Derive scope from
the exact text observations:

```python
"organizer.pref01n001.product_type" == "ETN"
"organizer.prfd01n001.public_private_class" == "사모"
```

Derive `has_exact_embedding` with an `EXISTS` subquery joining product
binding, chunk, and embedding on dataset, document, chunk, and current content
hash, then require the supplied model ID, model version, and dimension. Do not
treat a stale chunk hash or another model as complete.

- [ ] **Step 4: Run repository tests**

Run:

```bash
pytest tests/db/test_document_target_repository.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the repository state reader**

```bash
git add src/financial_agent/ingestion/document_sources/dart_targets.py src/financial_agent/db/repositories/document_targets.py tests/db/test_document_target_repository.py
git commit -m "feat: read DART recovery product state"
```

---

### Task 2: Select only unresolved, applicable DART targets

**Files:**
- Modify: `src/financial_agent/ingestion/document_sources/dart_targets.py`
- Modify: `src/financial_agent/ingestion/document_sources/__init__.py`
- Test: `tests/ingestion/document_sources/test_dart_targets.py`

**Interfaces:**
- Consumes: `OrganizerDartInventory` and the Task 1 product states.
- Produces: `DartRecoverySelection`, containing `actionable_inventory`, `already_embedded_target_ids`, and `not_applicable_targets`.

- [ ] **Step 1: Write failing pure-selection tests**

Cover these cases:

```python
selection = select_dart_recovery_targets(inventory, states)

assert selection.already_embedded_target_ids == ("domestic_etf:complete",)
assert selection.not_applicable_targets == (
    ("domestic_etf:etn", "etn_not_applicable"),
    ("public_fund:private", "private_fund_not_applicable"),
)
assert tuple(
    target.target_key for target in selection.actionable_inventory.targets
) == ("domestic_etf:missing", "public_fund:public")
```

Also assert that a multi-class public-fund target is skipped only when every
member has an exact embedding. If at least one member is missing, keep the
target actionable so the shared document can complete the group.

Assert that a target mixing applicable and non-applicable members raises
`ValueError("mixed DART recovery scope")` rather than silently dropping a
member.

- [ ] **Step 2: Run the focused target tests and confirm failure**

Run:

```bash
pytest tests/ingestion/document_sources/test_dart_targets.py -q
```

Expected: FAIL because the recovery selector is absent.

- [ ] **Step 3: Implement the pure selector**

Add:

```python
@dataclass(frozen=True, slots=True)
class DartRecoverySelection:
    actionable_inventory: OrganizerDartInventory
    already_embedded_target_ids: tuple[str, ...]
    not_applicable_targets: tuple[tuple[str, str], ...]
```

Implement:

```python
def select_dart_recovery_targets(
    inventory: OrganizerDartInventory,
    states: tuple[DartRecoveryProductState, ...],
) -> DartRecoverySelection:
    state_by_id = {state.entity_id: state for state in states}
    expected = {
        entity_id
        for target in inventory.targets
        for entity_id in target.member_entity_ids
    }
    if set(state_by_id) != expected:
        raise ValueError("DART recovery state mismatch")

    actionable = []
    embedded = []
    not_applicable = []
    for target in inventory.targets:
        members = tuple(state_by_id[item] for item in target.member_entity_ids)
        scopes = {item.product_scope for item in members}
        if all(item.has_exact_embedding for item in members):
            embedded.append(target.target_key)
        elif len(scopes) == 1 and "fund_prospectus" not in scopes:
            not_applicable.append((target.target_key, next(iter(scopes))))
        elif scopes == {"fund_prospectus"}:
            actionable.append(target)
        else:
            raise ValueError("mixed DART recovery scope")
    return DartRecoverySelection(
        actionable_inventory=replace(inventory, targets=tuple(actionable)),
        already_embedded_target_ids=tuple(sorted(embedded)),
        not_applicable_targets=tuple(sorted(not_applicable)),
    )
```

Require exactly one state for every `member_entity_id`. Classify in this
order:

1. all members have exact embeddings → `already_embedded_target_ids`;
2. all members have the same non-applicable scope → `not_applicable_targets`;
3. all remaining members are `fund_prospectus` → actionable;
4. any other combination → fail closed with `mixed DART recovery scope`.

Return deterministically sorted tuples and preserve the original full
inventory hash and product count with `dataclasses.replace`.

- [ ] **Step 4: Run target tests**

Run:

```bash
pytest tests/ingestion/document_sources/test_dart_targets.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the missing-only selector**

```bash
git add src/financial_agent/ingestion/document_sources/dart_targets.py src/financial_agent/ingestion/document_sources/__init__.py tests/ingestion/document_sources/test_dart_targets.py
git commit -m "feat: select missing DART targets only"
```

---

### Task 3: Add an explicit recovery-only CLI path and report fields

**Files:**
- Modify: `src/financial_agent/ingestion/cli.py`
- Test: `tests/ingestion/test_dart_corpus_cli.py`

**Interfaces:**
- Consumes: `DocumentTargetRepository.list_dart_recovery_states` and `select_dart_recovery_targets`.
- Produces: `ingest-dart-corpus --missing-only`, plus sanitized report fields `already_embedded_target_count`, `not_applicable_target_count`, and `not_applicable_reason_counts`.

- [ ] **Step 1: Write failing CLI configuration tests**

Assert that `--missing-only` is parsed as `True`, defaults to `False`, and
can be combined with `--limit` or `--target-key`. The limit must apply after
missing-only selection so a canary selects an actionable target rather than an
already completed target.

- [ ] **Step 2: Write failing run-report and orchestration tests**

Use fake repository state and fake publisher discovery. Assert that completed,
ETN, and private-fund targets never appear in the publisher requests:

```python
assert requested_target_keys == ("public_fund:missing-public",)
assert report.already_embedded_target_count == 1
assert report.not_applicable_target_count == 2
assert report.not_applicable_reason_counts == (
    ("etn_not_applicable", 1),
    ("private_fund_not_applicable", 1),
)
```

Keep non-applicable targets out of `failed_targets`. Reconciliation for a
missing-only run must be:

```text
selected missing targets = indexed targets + failed targets
```

Completed and non-applicable totals are reported separately against the full
inventory.

- [ ] **Step 3: Run CLI tests and confirm failure**

Run:

```bash
pytest tests/ingestion/test_dart_corpus_cli.py -q
```

Expected: FAIL because the flag and report fields are absent.

- [ ] **Step 4: Implement the CLI path**

Add `missing_only: bool` to `_DartCorpusConfiguration` and:

```python
dart_corpus.add_argument("--missing-only", action="store_true")
```

Import `APPROVED_MODEL`, load recovery states in
`_load_dart_corpus_inventory`, and call the pure selector before
`_limited_dart_inventory` when `missing_only=True`. Preserve the current
full corpus behavior when the flag is absent.

Extend `_DartCorpusRunReport` with aggregate counts only:

```python
already_embedded_target_count: int = 0
not_applicable_target_count: int = 0
not_applicable_reason_counts: tuple[tuple[str, int], ...] = ()
```

Do not add product names, entity IDs, local paths, API keys, database URLs, or
raw organizer values to the report.

- [ ] **Step 5: Run CLI and adjacent ingestion tests**

Run:

```bash
pytest tests/ingestion/test_dart_corpus_cli.py tests/ingestion/document_sources/test_dart_batch.py tests/ingestion/document_sources/test_dart_ingestion.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the recovery-only CLI**

```bash
git add src/financial_agent/ingestion/cli.py tests/ingestion/test_dart_corpus_cli.py
git commit -m "feat: add missing-only DART recovery run"
```

---

### Task 4: Verify real scope counts without touching existing embeddings

**Files:**
- Modify: `docs/planning/tasks/2026-09-03-dart-missing-only-scope-recovery-plan.md` only to check completed boxes and record sanitized aggregate results.
- Local only: a report path under `/private/tmp`; never stage it.

**Interfaces:**
- Consumes: the completed recovery-only CLI and current local PostgreSQL corpus.
- Produces: a sanitized aggregate baseline for the next name/lineage recovery plan.

- [x] **Step 1: Run the focused test suite**

Run:

```bash
pytest tests/db/test_document_target_repository.py tests/ingestion/document_sources/test_dart_targets.py tests/ingestion/test_dart_corpus_cli.py tests/ingestion/document_sources/test_dart.py tests/ingestion/document_sources/test_dart_batch.py tests/embeddings/test_builder.py tests/embeddings/test_cli.py -q
```

Expected: PASS.

- [x] **Step 2: Record the protected embedding baseline**

Run the existing embedding reconciliation command with
`--expected-chunks 37629`. Expected before recovery:

```text
eligible=37629
exact=37629
missing=0
duplicate=0
stale=0
orphan=0
wrong_dimension=0
```

- [x] **Step 3: Run a missing-only canary**

Run `ingest-dart-corpus --missing-only --limit 1` using the existing local
database, DART key file, temporary directory, publisher mapping, and a report
under `/private/tmp`.

Expected:

- the selected target was not in the existing embedded target set;
- no ETN or private-fund target issued a DART request;
- the run accounts for its one selected missing target as indexed or failed;
- no PDF remains unless a pre-existing unrelated quarantine artifact already existed.

- [x] **Step 4: Reconcile protected embeddings after the canary**

Before running NCP delta embedding, assert that all existing 37,629 exact
embeddings still exist and that any new chunks appear only as `missing` in
the embedding preflight. Do not run a full embedding rebuild in this plan.

- [x] **Step 5: Produce the residual aggregate**

Record only aggregate counts for:

```text
already embedded targets
ETF targets still actionable
ETNs not applicable
public-offering fund targets still actionable
private-fund targets not applicable
remaining failure reasons after the one-target canary
```

Use this residual set as the input to the next implementation plan for exact
name parsing and correction lineage. Do not add fuzzy matching based on this
run.

- [x] **Step 6: Inspect scope and commit the verified deliverable**

Run:

```bash
git diff --check
git status --short
```

Verify that no file under `data/`, no organizer workbook or PDF, no local
report, no embedding, and no credential is staged. Commit only plan checkbox
updates if aggregate verification notes were added:

```bash
git add docs/planning/tasks/2026-09-03-dart-missing-only-scope-recovery-plan.md
git commit -m "docs: record DART recovery scope baseline"
```

#### Results (2026-09-03)

- The focused suite passed: 120 tests.
- Before and after the attempted canary, embedding reconciliation recorded
  37,629 eligible and exact chunks, with zero missing, duplicate, stale,
  orphan, or wrong-dimension chunks.
- The one-target missing-only CLI attempt returned `INGESTION_FAILED` without
  producing its required sanitized report. No residual scope counts or target
  disposition are recorded, and no NCP delta embedding was run.

#### Results (2026-09-03, resumed after selector correction)

- The final focused suite passed: 122 tests.
- One missing-only canary selected and accounted for one applicable target as a
  bounded `PDF_TEXT_LAYER_MISSING` failure. It indexed no document or chunk,
  and retained or quarantined no PDF.
- The report recorded 1,959 already embedded targets; 8,495 excluded targets
  (545 ETN and 7,950 private-fund); and 3 additional excluded private-fund
  members from mixed public-fund targets. The resulting actionable target
  residual is 5,117: 275 domestic ETF targets and 4,842 public-offering fund
  targets. The report now exposes these subtotals as aggregate-only family
  counts; a read-only selector diagnostic verified the current values without
  issuing another DART request.
- Post-canary reconciliation remained 37,629 eligible and exact chunks with
  zero missing, duplicate, stale, orphan, or wrong-dimension chunks. No NCP
  delta embedding was run. A final reconciliation repeated the same result.
