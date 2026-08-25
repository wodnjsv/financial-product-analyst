# 2026-08-24 Database and Ontology Rebaseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use
> `superpowers:executing-plans` and execute this plan task-by-task with a review
> checkpoint after every task. Do not dispatch subagents unless the user later
> asks for delegated or parallel agent work.

**Goal:** Rebuild the normalized organizer database boundary for the eight
`2026-08-24` workbooks and implement the minimum versioned ontology projection
without double-counting exact cross-master products or weakening Evidence
lineage.

**Architecture:** PostgreSQL remains the canonical catalog, observation,
relation, and Evidence ledger. A source-wide identity pre-scan assigns canonical
organizer entity IDs before any write; four explicit mappers then normalize the
approved 280 fields. RDFLib and pySHACL load the fixed TBox and validate an ABox
materialized only from PostgreSQL entity/relation/Evidence IDs; Fuseki/TDB2 is a
read-only projection, never the fact authority.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2, Alembic 1, PostgreSQL 15,
pytest 8, openpyxl 3, RDFLib 7.6, pySHACL 0.40, Apache Jena Fuseki/TDB2 6.2.0
on Java 21, Docker, Naver Cloud Platform.

**Specs:**

- `docs/planning/specs/2026-08-24-stage-03-organizer-rebaseline-design.md`
- `docs/planning/specs/organizer-master-field-matrix-2026-08-24.md`
- `docs/planning/architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md`
- `docs/planning/decisions/ADR-0016-use-2026-08-24-organizer-baseline.md`
- `docs/planning/decisions/ADR-0017-adopt-current-cutoff-with-legacy-preservation.md`
- `docs/planning/decisions/ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md`

## Global Constraints

- The only current organizer baseline is the eight `2026-08-24` workbooks;
  preserve their bytes unchanged and keep them outside Git and Docker context.
- Keep Stage 01 artifact shape and `schema_version=1.0`; only the current cutoff
  value changes.
- Preserve historical `2026-07-11` dataset rows without relabeling, deleting,
  activating, or reusing them.
- Permit database cutoff dates only in `{2026-07-11, 2026-08-24}` and permit
  activation only for `2026-08-24`.
- Preserve zero and missing as different tagged values. Do not impute.
- Organizer facts win when an external source conflicts on the same evaluated
  field.
- Do not promote ambiguous identifiers or code-only classifications.
- Do not add normalized product, listing, identity, source-row, or ontology
  relation tables. Alembic `0006` is cutoff-only.
- Keep the 13 approved ontology relations. Graph facts must bind back to a
  PostgreSQL `relation_id` and `evidence_id`.
- Every behavior change begins with a failing focused test, then the minimal
  implementation, then focused and broader verification.
- Every commit excludes raw workbooks, generated data, local databases,
  credentials, `.env` files, API keys, and cloud account identifiers.

---

### Task 1: Enforce the Current Cutoff While Preserving Legacy Rows

**Implementation status:** Completed and verified on `2026-08-25` in commit
`921056c`. Contract, ingestion, migration-cycle, object-manifest, and full
PostgreSQL checks passed; legacy rows remain stored but cannot activate.

**Files:**

- Modify: `src/financial_agent/contracts/base.py`
- Modify: `src/financial_agent/db/schema/operations.py`
- Create: `alembic/versions/0006_current_cutoff_legacy_preservation.py`
- Modify: `src/financial_agent/db/preflight.py`
- Modify: `src/financial_agent/ingestion/pipeline.py`
- Modify: `src/financial_agent/ingestion/writer.py`
- Modify: `src/financial_agent/ingestion/official_pipeline.py`
- Modify: `src/financial_agent/ingestion/cli.py`
- Modify: `scripts/verify_database_migrations.py`
- Modify: `scripts/export_database_objects.py`
- Modify: `tests/contracts/test_base.py`
- Modify: `tests/db/test_migration_cycle.py`
- Modify: `tests/db/test_ncp_preflight.py`
- Modify: `tests/db/test_foundation_migration.py`
- Modify: `tests/ingestion/test_pipeline.py`
- Modify: `tests/ingestion/test_writer.py`
- Modify: current-baseline contract and ingestion fixtures under `tests/fixtures/`

**Interfaces:**

- Produces: `SNAPSHOT_CUTOFF == date(2026, 8, 24)` for newly constructed
  runtime artifacts and ingestion builds.
- Produces: database CHECK
  `cutoff_date IN (DATE '2026-07-11', DATE '2026-08-24')`.
- Produces: `operations.activate_dataset(text)` rejection code
  `LEGACY_DATASET_CANNOT_ACTIVATE` when cutoff is not `2026-08-24`.
- Preserves: dataset-relative Evidence cutoff triggers and contract
  `schema_version=1.0`.

- [ ] **Step 1: Write current-contract and legacy-rejection tests**

```python
def test_runtime_artifact_uses_current_cutoff(valid_payload):
    payload = valid_payload | {"cutoff_date": "2026-08-24"}
    assert RuntimeArtifact.model_validate_json(json.dumps(payload)).cutoff_date == date(2026, 8, 24)


def test_runtime_artifact_rejects_legacy_cutoff(valid_payload):
    payload = valid_payload | {"cutoff_date": "2026-07-11"}
    with pytest.raises(ValidationError, match="cutoff_date must be 2026-08-24"):
        RuntimeArtifact.model_validate_json(json.dumps(payload))
```

- [ ] **Step 2: Run the contract tests and confirm they fail for the old literal**

Run: `python -m pytest tests/contracts/test_base.py -q`

Expected: the new `2026-08-24` case fails and the legacy rejection case does
not yet raise.

- [ ] **Step 3: Update the current contract and ingestion literals**

Keep the exported name `SNAPSHOT_CUTOFF` to avoid changing the frozen public
surface. Replace current-build object prefixes and default dataset-version
labels with `2026-08-24`; do not mechanically change historical migration
fixtures whose purpose is to prove legacy preservation.

- [ ] **Step 4: Write migration-cycle tests for the two-date boundary**

The tests must insert one legacy row and one current row, reject `2026-08-23`,
upgrade `0005 → 0006`, downgrade `0006 → 0005`, and prove that the legacy row
survives the full cycle. A separate activation test must expect
`LEGACY_DATASET_CANNOT_ACTIVATE` for the legacy row and success for the current
validated row with complete readiness.

- [ ] **Step 5: Run the migration tests and confirm they fail because `0006` is absent**

Run: `python -m pytest tests/db/test_migration_cycle.py -q`

Expected: failures identify missing revision `0006`, the old exact CHECK, and
the missing activation guard.

- [ ] **Step 6: Add Alembic `0006` and update SQLAlchemy metadata**

The upgrade must drop and recreate only
`ck_dataset_version_cutoff_date`, replace `operations.activate_dataset(text)`
with the current-cutoff guard, and restore grants. The downgrade must fail
closed with a stable error if a `2026-08-24` dataset exists; it must never
delete or relabel data to make the downgrade fit.

- [ ] **Step 7: Update preflight and the database object manifest**

Preflight must compare a normalized constraint expression rather than search
for the old literal. The object manifest must contain the new function and
constraint hashes generated from revision `0006`.

- [ ] **Step 8: Run focused and full database checks**

Run:

```bash
python -m pytest tests/contracts/test_base.py tests/db/test_migration_cycle.py tests/db/test_ncp_preflight.py tests/ingestion/test_pipeline.py tests/ingestion/test_writer.py -q
python scripts/export_contract_schemas.py --check
python scripts/export_database_objects.py --check
```

Expected: all pass, current artifacts use `2026-08-24`, and legacy rows remain
database history only.

- [ ] **Step 9: Commit the cutoff boundary**

```bash
git add src/financial_agent/contracts/base.py src/financial_agent/db/schema/operations.py src/financial_agent/db/preflight.py src/financial_agent/ingestion/pipeline.py src/financial_agent/ingestion/writer.py src/financial_agent/ingestion/official_pipeline.py src/financial_agent/ingestion/cli.py alembic/versions/0006_current_cutoff_legacy_preservation.py scripts/verify_database_migrations.py scripts/export_database_objects.py tests/contracts/test_base.py tests/db/test_migration_cycle.py tests/db/test_ncp_preflight.py tests/db/test_foundation_migration.py tests/ingestion/test_pipeline.py tests/ingestion/test_writer.py tests/fixtures
git diff --cached --check
git commit -m "feat: adopt current data cutoff"
```

---

### Task 2: Build One Organizer-Authoritative Identity Index

**Implementation status:** Completed and verified on `2026-08-25`. Synthetic
tests and a read-only pass over the replacement workbooks reproduced 217
`DomesticETF + FundShareClass` identities, 63 ambiguous ISIN groups, and 63
ambiguous Lipper groups without exposing raw identifier values.

**Files:**

- Create: `src/financial_agent/ingestion/identity.py`
- Modify: `src/financial_agent/ingestion/pipeline.py`
- Modify: `src/financial_agent/ingestion/models.py`
- Create: `tests/ingestion/test_authoritative_identity.py`
- Modify: `tests/ingestion/test_pipeline.py`

**Interfaces:**

- Produces: `IdentifierCandidate(source_code, row_number, natural_key,
  entity_role, scheme, value)`.
- Produces: `CanonicalIdentity(entity_id, owner_source_code,
  owner_natural_key, roles)`.
- Produces: `IdentityResolution(status, canonical_identity)` where `status` is
  exactly `MATCHED`, `NOT_FOUND`, or `AMBIGUOUS`.
- Produces: `AuthoritativeIdentityIndex.resolve(scheme: str, value: str) ->
  IdentityResolution`.
- Consumed by: all organizer and external mappers before they emit catalog
  entities or identifiers.

- [ ] **Step 1: Write identity-policy tests**

```python
def test_domestic_etf_and_public_fund_share_one_canonical_identity():
    index = build_authoritative_identity_index((domestic_etf_candidate(), public_fund_candidate()))
    result = index.resolve("ISIN", "KR7005930003")
    assert result.status == "MATCHED"
    assert result.canonical_identity.owner_source_code == "PREF01N001"
    assert result.canonical_identity.roles == frozenset({"DomesticETF", "FundShareClass"})


def test_incompatible_or_duplicate_candidates_are_ambiguous():
    index = build_authoritative_identity_index((overseas_candidate(1), overseas_candidate(2)))
    assert index.resolve("ISIN", "US0000000001").status == "AMBIGUOUS"
```

Also test invalid checksum, blank value, source-local identifiers, stable output
under reversed input order, and no raw identifier values in aggregate error
messages.

- [ ] **Step 2: Run the new tests and confirm the module is missing**

Run: `python -m pytest tests/ingestion/test_authoritative_identity.py -q`

Expected: import failure for `financial_agent.ingestion.identity`.

- [ ] **Step 3: Implement the immutable identity index**

Use UUIDv5 `stable_id` with the organizer canonical owner. Permit only the
explicit compatible role pair `DomesticETF + FundShareClass`; keep ETF/ETN and
all unresolved cross-kind collisions ambiguous. Exact identity reuse prevents
duplicate entity creation; it does not generate `owl:sameAs`.

- [ ] **Step 4: Integrate a two-pass pre-scan into organizer preflight**

The first pass validates source-specific duplicate rules and gathers identifier
candidates from all four snapshots. Freeze one index in `_PreflightResult`.
The second pass calls mappers. No mapper may write an entity before the index
exists.

- [ ] **Step 5: Run deterministic identity and pipeline tests**

Run:

```bash
python -m pytest tests/ingestion/test_authoritative_identity.py tests/ingestion/test_pipeline.py -q
```

Expected: all pass; reversed source iteration produces the same canonical IDs
and manifest hash.

- [ ] **Step 6: Commit the identity boundary**

```bash
git add src/financial_agent/ingestion/identity.py src/financial_agent/ingestion/models.py src/financial_agent/ingestion/pipeline.py tests/ingestion/test_authoritative_identity.py tests/ingestion/test_pipeline.py
git diff --cached --check
git commit -m "feat: add organizer identity prescan"
```

---

### Task 3: Replace the Four Source Contracts and Object Prefixes

**Implementation status:** Completed and verified on `2026-08-25`. The four
replacement source contracts now enforce the exact current filenames, `data`
and `schema` sheet layouts, 280 ordered fields, 53,375 total rows, composite
bond natural key, and `organizer/2026-08-24/` object prefix. Read-only
validation passed against all eight replacement workbooks.

**Files:**

- Modify: `src/financial_agent/ingestion/mapping/domestic_bond.py`
- Modify: `src/financial_agent/ingestion/mapping/domestic_etp.py`
- Modify: `src/financial_agent/ingestion/mapping/overseas_etp.py`
- Modify: `src/financial_agent/ingestion/mapping/public_fund.py`
- Modify: `src/financial_agent/ingestion/cli.py`
- Modify: `tests/ingestion/test_sources.py`
- Modify: `tests/ingestion/test_real_organizer_data.py`
- Modify: `tests/ingestion/test_ncp_object_storage.py`
- Modify: synthetic workbook builders under `tests/fixtures/`

**Interfaces:**

- Produces exact files `prbd01n001_data.xlsx`, `prbd01n001_schema.xlsx`,
  `pref01n001_data.xlsx`, `pref01n001_schema.xlsx`, `pref02n001_data.xlsx`,
  `pref02n001_schema.xlsx`, `prfd01n001_data.xlsx`, and
  `prfd01n001_schema.xlsx`.
- Produces exact sheets `data` and `schema`.
- Produces exact row/field boundaries `(21882,58)`, `(1780,98)`, `(6037,49)`,
  and `(23676,75)`.
- Produces Object Storage prefix `organizer/2026-08-24/<TABLE_ID>/`.

- [ ] **Step 1: Update fixture assertions before production SourceSpecs**

Write assertions for every exact filename, sheet, natural key, expected row
count, and expected field count. The real-data test remains gated by
`organizer_data` and asserts aggregate metadata only.

- [ ] **Step 2: Run source tests and confirm the old contracts fail**

Run: `python -m pytest tests/ingestion/test_sources.py -q`

- [ ] **Step 3: Replace SourceSpecs and current object keys**

Copy the exact ordered field tuples from the approved 280-field matrix/schema
workbooks. Do not retain compatibility columns for fields that disappeared.

- [ ] **Step 4: Run synthetic and gated real-source validation**

Run:

```bash
python -m pytest tests/ingestion/test_sources.py -q
RUN_ORGANIZER_DATA_TESTS=1 python -m pytest tests/ingestion/test_real_organizer_data.py -m organizer_data -q
```

Expected: schema order, headers, row counts, natural-key uniqueness, and the
new object-prefix policy pass without printing product values.

- [ ] **Step 5: Commit the source contracts**

```bash
git add src/financial_agent/ingestion/mapping/domestic_bond.py src/financial_agent/ingestion/mapping/domestic_etp.py src/financial_agent/ingestion/mapping/overseas_etp.py src/financial_agent/ingestion/mapping/public_fund.py src/financial_agent/ingestion/cli.py tests/ingestion/test_sources.py tests/ingestion/test_real_organizer_data.py tests/ingestion/test_ncp_object_storage.py tests/fixtures
git diff --cached --check
git commit -m "feat: replace organizer source contracts"
```

---

### Task 4: Normalize Domestic Bonds at Product and Sale-Lot Grain

**Files:**

- Modify: `src/financial_agent/ingestion/mapping/domestic_bond.py`
- Modify: `tests/ingestion/test_domestic_bond_mapping.py`
- Modify: `tests/fixtures/ingestion.py`

**Interfaces:**

- Consumes: `AuthoritativeIdentityIndex` and one source row keyed by
  `(pd_no, pd_exg_mkt, info_base_dt, info_seq)`.
- Produces: one canonical domestic-bond product/security per valid `pd_no`.
- Produces: source-record-specific price/yield observations whose Evidence
  locator contains the complete composite key.
- Produces no fact, Evidence, filter, or availability value from
  `buyable_quantity`.

- [ ] **Step 1: Write failing product-versus-LOT tests**

Test two rows with the same `pd_no` and different `info_seq`: entity/product
records deduplicate, while `trade_price` and `buy_yield` produce distinct
observations. Test conflicting product-static names as
`SOURCE_STATIC_VALUE_CONFLICT`, explicit zero as zero, blank as missing, and
`buyable_quantity` as absent from every emitted table.

- [ ] **Step 2: Run the focused tests and confirm the old uppercase mapper fails**

Run: `python -m pytest tests/ingestion/test_domestic_bond_mapping.py -q`

- [ ] **Step 3: Implement the approved 58-field mapping**

Use the field matrix as the exhaustive whitelist. Keep product-static
convergence in pre-scan context; keep LOT observations row-specific. Apply the
competition availability assumption only as a later deterministic policy, not
as a fabricated organizer observation.

- [ ] **Step 4: Run mapper and writer integration tests**

Run:

```bash
python -m pytest tests/ingestion/test_domestic_bond_mapping.py tests/ingestion/test_writer.py -q
```

- [ ] **Step 5: Commit the bond mapper**

```bash
git add src/financial_agent/ingestion/mapping/domestic_bond.py tests/ingestion/test_domestic_bond_mapping.py tests/fixtures/ingestion.py
git diff --cached --check
git commit -m "feat: map current domestic bonds"
```

---

### Task 5: Normalize Domestic ETF and ETN Products

**Files:**

- Modify: `src/financial_agent/ingestion/mapping/domestic_etp.py`
- Modify: `tests/ingestion/test_domestic_etp_mapping.py`
- Modify: `tests/ingestion/test_krx_identity.py`

**Interfaces:**

- Consumes: current row keyed by `pd_itm_no` and the authoritative identity
  index.
- Produces: ETF `managedBy`, ETN `issuedBy`, and eligible `tracksIndex`
  relations only.
- Produces: the approved 98-field catalog/observation/Evidence mapping,
  including tracking error, divergence, distribution, volatility, and eligible
  bond-portfolio facts.
- Produces: one `ISIN` only when checksum-valid, unique, and consistent with
  explicit `pd_isin_cd`.

- [ ] **Step 1: Write failing tests for new answerable fields and identity**

Cover non-zero tracking error, premium/discount, four volatility periods,
distribution amount/yield/cycle, explicit ISIN agreement, ETF/ETN relation
selection, and blank portfolio fields. Assert that zero is not missing.

- [ ] **Step 2: Run the focused mapper tests and observe old-field failures**

Run: `python -m pytest tests/ingestion/test_domestic_etp_mapping.py -q`

- [ ] **Step 3: Implement the approved 98-field mapping**

Keep undecodable internal codes Evidence-only. Create Index and institution
entities only for explicit usable names. When organizer reference and product
sections conflict, preserve both Evidence records and limit the relationship;
do not choose by source order.

- [ ] **Step 4: Verify mapper and KRX identity compatibility**

Run:

```bash
python -m pytest tests/ingestion/test_domestic_etp_mapping.py tests/ingestion/test_krx_identity.py -q
```

- [ ] **Step 5: Commit the domestic ETP mapper**

```bash
git add src/financial_agent/ingestion/mapping/domestic_etp.py tests/ingestion/test_domestic_etp_mapping.py tests/ingestion/test_krx_identity.py
git diff --cached --check
git commit -m "feat: map current domestic etps"
```

---

### Task 6: Normalize Overseas ETF and ETN Products Without Ambiguous IDs

**Files:**

- Modify: `src/financial_agent/ingestion/mapping/overseas_etp.py`
- Modify: `tests/ingestion/test_overseas_etp_mapping.py`
- Modify: `tests/ingestion/test_official_identity.py`

**Interfaces:**

- Consumes: current row keyed by `pd_itm_no`, source duplicate sets, and the
  authoritative identity index.
- Produces: the approved 49-field mapping for 6,037 source rows.
- Preserves: all 63 aligned two-row ISIN/Lipper duplicate groups as Evidence.
- Forbids: promotion of any duplicated ISIN or Lipper ID to
  `catalog.identifier`.

- [ ] **Step 1: Replace the old 50-pair fixture with the verified 63-pair boundary**

Test that ISIN and Lipper duplicate groupings are identical, every group has
exactly two rows, unique identifiers still promote, and ambiguous identifiers
return `AMBIGUOUS` without a duplicate entity.

- [ ] **Step 2: Run focused tests and confirm the old aggregate fails**

Run: `python -m pytest tests/ingestion/test_overseas_etp_mapping.py -q`

- [ ] **Step 3: Update the mapper and duplicate pre-scan**

Retain the 49-field semantics but change source contract, current dates,
population, and identity-index integration. Do not add listing tables or fuzzy
fallbacks.

- [ ] **Step 4: Verify organizer and external resolver agreement**

Run:

```bash
python -m pytest tests/ingestion/test_overseas_etp_mapping.py tests/ingestion/test_official_identity.py -q
```

- [ ] **Step 5: Commit the overseas ETP mapper**

```bash
git add src/financial_agent/ingestion/mapping/overseas_etp.py tests/ingestion/test_overseas_etp_mapping.py tests/ingestion/test_official_identity.py
git diff --cached --check
git commit -m "feat: map current overseas etps"
```

---

### Task 7: Normalize One-Row Public Funds and Reuse Domestic ETF Identity

**Files:**

- Modify: `src/financial_agent/ingestion/mapping/public_fund.py`
- Modify: `tests/ingestion/test_public_fund_mapping.py`
- Modify: `tests/ingestion/test_authoritative_identity.py`

**Interfaces:**

- Consumes: one row keyed by `itm_no` and the authoritative identity index.
- Produces: one public-fund source record per row, deterministic ordered
  de-duplicated attribute memberships, `managedBy`, eligible `tracksIndex`, and
  `hasShareClass`.
- Reuses: the domestic ETF canonical entity for the 217 exact valid overlaps;
  it emits no second product/entity/ISIN record.
- Removes: the old repeated-row canonical-locator algorithm.

- [ ] **Step 1: Write failing one-row and overlap tests**

Cover list splitting, declared count equality, empty list, duplicate list item,
representative-fund sentinel and cycle handling, one-row AUM Evidence, and one
canonical entity across a domestic ETF/public-fund overlap.

- [ ] **Step 2: Run the focused tests and confirm repeated-row assumptions fail**

Run: `python -m pytest tests/ingestion/test_public_fund_mapping.py -q`

- [ ] **Step 3: Replace grouping with list expansion**

Delete only code made obsolete by this mapper change. The original comma list
stays in raw Evidence; parsed memberships use stable order and do not invent
controlled vocabulary meaning for code-only values.

- [ ] **Step 4: Verify exact overlap does not double-count**

Run:

```bash
python -m pytest tests/ingestion/test_public_fund_mapping.py tests/ingestion/test_authoritative_identity.py tests/ingestion/test_pipeline.py -q
```

Expected: the synthetic overlap yields one catalog product, two source records,
and both sources' non-conflicting Evidence.

- [ ] **Step 5: Commit the public-fund mapper**

```bash
git add src/financial_agent/ingestion/mapping/public_fund.py tests/ingestion/test_public_fund_mapping.py tests/ingestion/test_authoritative_identity.py tests/ingestion/test_pipeline.py
git diff --cached --check
git commit -m "feat: map current public funds"
```

---

### Task 8: Rebind Approved External Sources to the Current Organizer Index

**Files:**

- Modify: `src/financial_agent/ingestion/official/models.py`
- Modify: `src/financial_agent/ingestion/official/snapshot.py`
- Modify: `src/financial_agent/ingestion/official/identity.py`
- Modify: `src/financial_agent/ingestion/official/krx_identity.py`
- Modify: `src/financial_agent/ingestion/official/krx_holdings.py`
- Modify: `src/financial_agent/ingestion/official/krx_market.py`
- Modify: `src/financial_agent/ingestion/official/ecos_fx.py`
- Modify: `src/financial_agent/ingestion/official/sec_series_class.py`
- Modify: `src/financial_agent/ingestion/official/sec_nport.py`
- Modify: `src/financial_agent/ingestion/official_pipeline.py`
- Modify: corresponding files under `tests/ingestion/`

**Interfaces:**

- Consumes: the frozen `AuthoritativeIdentityIndex` produced by the organizer
  pre-scan.
- Produces: external snapshot eligibility through
  `2026-08-24T23:59:59+09:00` while preserving each fact's actual date.
- Produces: `MATCHED` reuse, `NOT_FOUND` source-specific entity creation, and
  `AMBIGUOUS` quarantine consistently for KRX and SEC paths.
- Preserves: organizer authority and bounded overseas/public-fund coverage.

- [ ] **Step 1: Write failing cutoff and exact-reuse integration tests**

Test an external object available one second before and one second after the
current cutoff. Test N-PORT holding security reuse for an exact organizer ISIN,
no duplicate `(dataset_version, ISIN, value)`, and no merge for an ambiguous
organizer ID.

- [ ] **Step 2: Run the official-source suite and capture expected old-cutoff failures**

Run:

```bash
python -m pytest tests/ingestion/test_official_snapshot.py tests/ingestion/test_krx_identity.py tests/ingestion/test_krx_holdings.py tests/ingestion/test_krx_market.py tests/ingestion/test_ecos_fx.py tests/ingestion/test_sec_series_class.py tests/ingestion/test_sec_nport.py tests/ingestion/test_official_pipeline.py -q
```

- [ ] **Step 3: Replace source-local resolver decisions with the frozen index**

Adapters continue parsing source-specific identifiers, but only the shared
index decides organizer reuse. A source adapter must not override an organizer
canonical name, product family, or evaluated field.

- [ ] **Step 4: Recapture or reapprove manifests without writing NCP facts**

Capture raw official bytes and manifests to ignored local/Object Storage paths.
Validate checksum, publication/availability cutoff, page/row accounting, and
coverage before any combined database build. Public-fund constituent holdings
remain `requires_data` until a separate official source is approved.

- [ ] **Step 5: Run the full official-source tests**

Run: `python -m pytest tests/ingestion -m "not organizer_data and not object_storage and not ncp_integration" -q`

- [ ] **Step 6: Commit current external bindings**

```bash
git add src/financial_agent/ingestion/official src/financial_agent/ingestion/official_pipeline.py tests/ingestion
git diff --cached --check
git commit -m "feat: rebind current official sources"
```

---

### Task 9: Prove a Deterministic Inactive Database Rebuild

**Files:**

- Modify: `src/financial_agent/ingestion/capacity_probe.py`
- Modify: `src/financial_agent/ingestion/cli.py`
- Modify: `tests/ingestion/test_capacity_probe.py`
- Modify: `tests/ingestion/test_official_question_gates.py`
- Modify: `docs/planning/STATUS.md`

**Interfaces:**

- Produces: two clean PostgreSQL `building` builds with identical dataset
  manifest, component hashes, table counts, issue counts, and identity counts.
- Produces reviewed aggregate gates for 53,375 organizer rows, 217 exact
  domestic overlaps, 63 ambiguous overseas pairs, and zero active current
  dataset before Graph readiness.
- Produces no final NCP activation.

- [ ] **Step 1: Write aggregate and repeatability tests**

The acceptance report must include source rows, accepted/limited/quarantined
rows, canonical products, identifiers by scheme, relations by predicate,
observations, Evidence origins, exact reused identities, and ambiguous IDs.
Counts not already approved by the design are measured outputs, not hardcoded
expectations.

- [ ] **Step 2: Run synthetic combined builds twice**

Run: `python -m pytest tests/ingestion/test_capacity_probe.py tests/ingestion/test_official_question_gates.py -q`

- [ ] **Step 3: Run the gated real local rebuild twice**

Use ignored local workbooks and frozen official manifests. Build into two fresh
disposable databases or dataset versions; never overwrite a prior probe.
Compare reports byte-for-byte after excluding database-generated timestamps.

- [ ] **Step 4: Run one NCP inactive `building` acceptance build**

Use `fa_build`, the Private DB endpoint, and explicit environment variables.
Verify with `fa_runtime` that the new version is not active and that no write
permission is available. Do not print connection URLs or credentials.

- [ ] **Step 5: Commit deterministic build acceptance**

```bash
git add src/financial_agent/ingestion/capacity_probe.py src/financial_agent/ingestion/cli.py tests/ingestion/test_capacity_probe.py tests/ingestion/test_official_question_gates.py docs/planning/STATUS.md
git diff --cached --check
git commit -m "test: verify current organizer rebuild"
```

---

### Task 10: Implement the Minimal TBox and SHACL Boundary

**Files:**

- Modify: `pyproject.toml`
- Create: `requirements/ontology.lock`
- Create: `docker/ontology-check.Dockerfile`
- Create: `ontology/common.ttl`
- Create: `ontology/bond_kr.ttl`
- Create: `ontology/etf_kr.ttl`
- Create: `ontology/etf_gl.ttl`
- Create: `ontology/fund_pub.ttl`
- Create: `ontology/shapes/common.shacl.ttl`
- Create: `ontology/shapes/domain.shacl.ttl`
- Create: `src/financial_agent/ontology/__init__.py`
- Create: `src/financial_agent/ontology/loader.py`
- Create: `src/financial_agent/ontology/validator.py`
- Create: `tests/ontology/test_schema.py`
- Create: `tests/ontology/test_shapes.py`
- Create: `tests/ontology/test_container_verification.py`

**Interfaces:**

- Produces: `load_tbox(root: Path) -> rdflib.Graph`.
- Produces: `load_shapes(root: Path) -> rdflib.Graph`.
- Produces: `validate_abox(data_graph: Graph, *, tbox: Graph,
  shapes: Graph) -> OntologyValidationResult`.
- Produces: `OntologyValidationResult(conforms: bool, codes: tuple[str, ...],
  report_text: str)` with sorted project-owned codes.
- Uses exactly 13 core object properties and the approved minimum classes.
- Uses `urn:ontology:financial-product:v1` as the TBox graph identity and
  `urn:ontology:financial-product:v1#` as the term namespace.

- [ ] **Step 1: Add failing ontology parse and vocabulary tests**

```python
def test_tbox_declares_exactly_the_approved_core_relations():
    graph = load_tbox(ONTOLOGY_ROOT)
    declared = {str(node).rsplit("#", 1)[-1] for node in graph.subjects(RDF.type, OWL.ObjectProperty)}
    assert declared == APPROVED_RELATIONS
```

Also assert required classes, no source-row/sale-lot/purchase property, and
successful parsing of all five domain TTL files.

- [ ] **Step 2: Run ontology tests and confirm loader/files are absent**

Run: `python -m pytest tests/ontology/test_schema.py -q`

- [ ] **Step 3: Add pinned ontology dependencies**

Add an `ontology` optional dependency with `rdflib>=7.6,<8` and
`pyshacl>=0.40,<1`, then generate `requirements/ontology.lock` for CPython
3.12. `docker/ontology-check.Dockerfile` installs only the lock and runs the
ontology tests plus a parse/check command. Do not run a Fuseki server in unit
tests.

- [ ] **Step 4: Implement the five TBox files and two SHACL files**

Each class and property comment must point to a competency question, approved
field mapping, or business rule. Domain SHACL must accept
`DomesticETF + FundShareClass`, reject `ETF + ETN`, validate predicate
domain/range, and require every RelationAssertion to carry dataset, relation,
and Evidence identifiers.

- [ ] **Step 5: Write and run valid/invalid SHACL fixtures**

Run:

```bash
python -m pytest tests/ontology/test_schema.py tests/ontology/test_shapes.py tests/ontology/test_container_verification.py -q
```

Expected: valid multi-role product passes; incompatible types, unknown
predicate, missing Evidence ID, and after-cutoff assertion fail with stable
constraint codes.

- [ ] **Step 6: Commit the ontology boundary**

```bash
git add pyproject.toml requirements/ontology.lock docker/ontology-check.Dockerfile ontology src/financial_agent/ontology tests/ontology
git diff --cached --check
git commit -m "feat: add minimal financial ontology"
```

---

### Task 11: Materialize a Versioned ABox from the PostgreSQL Ledger

**Files:**

- Create: `src/financial_agent/ontology/materialize.py`
- Create: `src/financial_agent/ontology/manifest.py`
- Create: `tests/ontology/test_materialize.py`
- Create: `tests/ontology/test_competency_questions.py`
- Create: `scripts/export_ontology_graph.py`
- Create: `docker/fuseki-check.Dockerfile`
- Create: `docker/fuseki.compose.yml`
- Create: `tests/ontology/test_fuseki_config.py`
- Modify: `docs/planning/architecture/NCP_DEPLOYMENT_ARCHITECTURE.md`

**Interfaces:**

- Produces: `materialize_dataset(engine: AsyncEngine, dataset_version: str) ->
  MaterializedOntology`.
- Produces: `MaterializedOntology(dataset_version: str, dataset_graph: Graph,
  evidence_graph: Graph, relation_count: int, evidence_count: int,
  manifest_hash: str)`.
- Produces named graphs
  `urn:data:financial-product:<dataset_version>` and
  `urn:evidence:financial-product:<dataset_version>`.
- Produces one direct edge and one reified `RelationAssertion` per eligible
  PostgreSQL relation with its `relation_id`, `evidence_id`, valid dates, and
  dataset version.
- Produces a canonical N-Quads export and SHA-256 manifest for Fuseki import.
- Pins Apache Jena Fuseki `6.2.0` and verifies the official distribution SHA-512
  `ba65f5867d2d4741b2ed9e2af5a0d4fbb447909894ab2a0c6bc4dac8997f4fe339c87b13c48d45d054977769f0f8bf763ea346b1f7792d5cdc458041bd43a132`.

- [ ] **Step 1: Write failing materialization tests against synthetic PostgreSQL**

Test entity typing, ETF/share-class multi-role typing via `hasShareClass`, all
approved predicate mappings, relation Evidence linkage, exclusion of
after-cutoff Evidence, deterministic output order/hash, and rejection of a
relation predicate outside the 13-property registry.

- [ ] **Step 2: Run the focused PostgreSQL ontology test**

Run: `python -m pytest tests/ontology/test_materialize.py -m postgres -q`

Expected: import failure for `financial_agent.ontology.materialize`.

- [ ] **Step 3: Implement read-only ledger materialization**

Query `catalog.entity`, `catalog.product`, `catalog.security`,
`relation.relation_record`, `evidence.evidence_relation_origin`, and eligible
`evidence.evidence_record` rows for exactly one dataset. Do not copy numeric
observations into RDF unless a competency-question mapping explicitly requires
a control-vocabulary link.

- [ ] **Step 4: Add competency-question path tests**

Test the graph paths for manager products, tracked index, ETF holdings,
company-security, company control, listing market, industry, theme,
share-class, official documents, and risk factors. Ranking/AUM/returns remain
asserted as PostgreSQL operations rather than SPARQL arithmetic.

- [ ] **Step 5: Export and validate an inactive real ABox**

Run the exporter against the inactive current `building` version, validate it
with pySHACL, and record triple counts and manifest hashes without product
values. Build the pinned Java 21/Fuseki check image, import into a disposable
TDB2 dataset through `docker/fuseki.compose.yml`, and verify read-only SPARQL
paths before touching the final Fuseki service.

- [ ] **Step 6: Commit ABox materialization**

```bash
git add src/financial_agent/ontology tests/ontology scripts/export_ontology_graph.py docker/fuseki-check.Dockerfile docker/fuseki.compose.yml docs/planning/architecture/NCP_DEPLOYMENT_ARCHITECTURE.md
git diff --cached --check
git commit -m "feat: materialize evidence-bound ontology"
```

---

### Task 12: Run the Cross-Layer Release Gate Without Activating Production

**Files:**

- Modify: `scripts/export_database_objects.py`
- Create: `scripts/verify_rebaseline_readiness.py`
- Create: `tests/integration/test_rebaseline_readiness.py`
- Modify: `docs/planning/STATUS.md`
- Modify: `docs/planning/ROADMAP.md`

**Interfaces:**

- Produces one readiness report containing PostgreSQL, ontology/ABox,
  Evidence, and external-source component hashes for one dataset version.
- Proves that activation remains blocked until PostgreSQL, Graph, Vector, and
  Evidence readiness records match. Vector readiness may remain pending; this
  plan does not fabricate it.
- Leaves the current dataset inactive unless the user separately approves the
  final activation operation.

- [ ] **Step 1: Write a failing readiness test for hash mismatch and missing components**

The test must reject a legacy cutoff, mismatched ABox hash, missing relation
Evidence, missing component readiness, and an active pointer to a different
dataset.

- [ ] **Step 2: Implement the read-only verifier**

The verifier accepts only explicit database URL environment-variable names,
dataset version, and manifest paths. It prints aggregate status codes and
hashes only; it never prints URLs, credentials, product values, or raw source
locators.

- [ ] **Step 3: Run all local verification**

Run:

```bash
python -m pytest tests/contracts tests/db tests/ingestion tests/ontology tests/integration -m "not organizer_data and not object_storage and not ncp_integration and not performance" -q
python scripts/export_contract_schemas.py --check
python scripts/export_database_objects.py --check
git diff --check
```

- [ ] **Step 4: Run explicit NCP checks**

Run preflight with `fa_migration`, migration `0006`, postflight, one inactive
build with `fa_build`, read-only readiness with `fa_runtime`, ABox export, and a
disposable Fuseki import. Preserve sanitized aggregate outputs in the task
record; do not commit logs containing infrastructure identifiers.

- [ ] **Step 5: Audit the final diff and staged content**

Verify no path under `data/`, no `.xlsx`, no organizer PDF, no `.env`, no key,
no DB dump, no RDF ABox export, and no cloud identifier is staged. Generated
TBox and SHACL source files are allowed; generated real-data graphs are not.

- [ ] **Step 6: Commit the verified release gate**

```bash
git add scripts/verify_rebaseline_readiness.py scripts/export_database_objects.py tests/integration/test_rebaseline_readiness.py docs/planning/STATUS.md docs/planning/ROADMAP.md
git diff --cached --check
git commit -m "test: verify database ontology rebaseline"
```

## Plan Completion Gate

The plan is complete only when all of the following are true:

1. Alembic `0006` preserves legacy rows and admits only the current baseline
   for activation.
2. Every one of the 280 organizer fields is accounted for by the approved
   mapping contract and mapper tests.
3. The 217 domestic ETF/public-fund exact overlaps produce one canonical
   product each and retain both source lineages.
4. The 63 overseas duplicate identifier pairs never become unique catalog
   identifiers.
5. Two clean database builds are deterministic and the NCP build remains
   inactive.
6. The TBox contains exactly the approved minimum vocabulary and 13 relations.
7. SHACL permits compatible ETF/share-class multi-typing and rejects invalid
   ETF/ETN typing, unregistered predicates, missing Evidence, and ineligible
   dates.
8. Every materialized Graph edge resolves to PostgreSQL relation and Evidence
   records for the same dataset version.
9. PostgreSQL, Graph, Vector, and Evidence readiness must all match before a
   separate explicitly approved activation.
