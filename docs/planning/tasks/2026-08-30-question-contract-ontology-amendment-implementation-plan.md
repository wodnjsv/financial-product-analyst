# Question Contract and Ontology Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended when the user explicitly
> requests delegation) or `superpowers:executing-plans` to implement this plan
> task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize all 52 internal evaluation questions into an executable
Stage 04 requirement contract and align the logical ontology documentation with
the approved grade, policy-program, controlled-attribute, and document
provenance boundaries.

**Architecture:** Keep `tests/gold/core_questions.json` as the single
machine-readable catalog. Split every case into six requirement groups and
allow only the 13 approved domain predicates in `requirements.relations`.
PostgreSQL remains authoritative for attributes and metrics; ontology and later
SHACL work validate their vocabulary and type. This increment updates contracts,
tests, and planning documents only. TTL, SHACL, ABox, Fuseki, PostgreSQL, Stage
03 ingestion, and Vector implementation remain separate work.

**Tech Stack:** JSON, Python 3.12, pytest 8, Markdown, SHA-256 contract
fingerprints

**Spec:**
`docs/planning/specs/2026-08-29-question-capability-contract-normalization-design.md`

**Decision:**
`docs/planning/decisions/ADR-0021-amend-minimal-ontology-for-question-contract-semantics.md`

## Global Constraints

- Work only on branch `codex/ontology-contract-normalization` in the isolated
  worktree created from commit `25bb26a8dabbdc403a9a038eb75209b43b2b5b8f`.
- Do not touch the user's dirty Stage 03 worktree or its ingestion files.
- Preserve all 52 case IDs, question text, category, support level, target
  support level, and expected disposition exactly.
- Preserve the `supported=16`, `limited=18`,
  `requires_additional_data=11`, `unsupported=7` distribution.
- Keep the 13 approved domain predicates unchanged.
- Treat Graph and Vector output as candidates or projections until they bind to
  PostgreSQL RelationAssertion or DocumentChunk Evidence.
- Do not add a database migration, dependency, source adapter, raw organizer
  data, generated dataset, cloud identifier, or secret.
- Do not change answer coverage or infer unavailable organizer values from
  external data.
- Keep TTL, SHACL, ABox materialization, Fuseki, and Vector implementation out
  of this plan.

---

### Task 1: Normalize and Lock the 52-Case Question Contract

**Files:**

- Modify: `tests/ingestion/test_official_question_gates.py`
- Modify: `tests/gold/core_questions.json`

**Interfaces:**

- Consumes: schema `1.2` cases with `required_relations`, category-default
  retrieval, and optional `subtask_routes`.
- Produces: schema `1.3` cases containing `requirements`, `retrieval`,
  `requires_data`, and `verification`.
- Produces: `requirements` with exactly `entities`, `attributes`, `metrics`,
  `relations`, `document_claims`, and `control_checks`.
- Produces: relation objects with `predicate`, `direction`, and
  `required_assertion_fields`.
- Produces: one retrieval route for every string in each case's `subtasks`.

- [ ] **Step 1: Add the immutable catalog and normalized-shape tests**

Add `hashlib` to the imports and add these constants below the fixture imports:

```python
APPROVED_GRAPH_PREDICATES = {
    "managedBy",
    "issuedBy",
    "tracksIndex",
    "holdsSecurity",
    "containsSecurity",
    "securityOfCompany",
    "controlsCompany",
    "listedOn",
    "classifiedAsIndustry",
    "associatedWithTheme",
    "hasShareClass",
    "documentedBy",
    "hasRiskFactor",
}

REQUIREMENT_GROUPS = {
    "entities",
    "attributes",
    "metrics",
    "relations",
    "document_claims",
    "control_checks",
}

FROZEN_CASE_FINGERPRINT = (
    "66e8b51004270a8233d02328cb7095360f46afedf168f7325f9dd221e2a7271b"
)
```

Add a local loader without refactoring the existing unrelated tests:

```python
def _question_catalog() -> dict[str, object]:
    return json.loads(
        (
            Path(__file__).parents[1]
            / "gold"
            / "core_questions.json"
        ).read_text("utf-8")
    )
```

Add a fingerprint test that hashes only the fields this change is forbidden to
alter:

```python
def test_question_contract_preserves_frozen_case_identity_and_disposition() -> None:
    catalog = _question_catalog()
    frozen = [
        {
            key: case[key]
            for key in (
                "id",
                "question",
                "support_level",
                "target_support_level",
                "expected_disposition",
            )
        }
        for case in catalog["cases"]
    ]
    payload = json.dumps(
        frozen,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    assert hashlib.sha256(payload).hexdigest() == FROZEN_CASE_FINGERPRINT
```

Add the normalized contract test:

```python
def test_question_contract_v13_has_explicit_requirements_and_routes() -> None:
    catalog = _question_catalog()

    assert catalog["schema_version"] == "1.3"
    assert len(catalog["cases"]) == 52

    for case in catalog["cases"]:
        assert "required_relations" not in case, case["id"]
        assert set(case["requirements"]) == REQUIREMENT_GROUPS, case["id"]
        assert case["requires_data"] is (
            case["support_level"] == "requires_additional_data"
        ), case["id"]
        assert case["verification"] == {
            "coverage_assessment": "frozen_design_2026-08-27",
            "current_db_execution": "not_run",
            "verified_dataset_version": None,
            "verified_at": None,
            "result_artifact": None,
        }, case["id"]

        predicates = {
            relation["predicate"]
            for relation in case["requirements"]["relations"]
        }
        assert predicates <= APPROVED_GRAPH_PREDICATES, case["id"]
        assert {
            route["subtask"]
            for route in case["retrieval"]["subtask_routes"]
        } == set(case["subtasks"]), case["id"]
```

Add targeted semantic tests so a structurally valid but incorrectly classified
catalog cannot pass:

```python
def test_question_contract_separates_grades_and_document_provenance() -> None:
    cases = {case["id"]: case for case in _question_catalog()["cases"]}

    bond_filter = cases["FLT-BOND-001"]["requirements"]
    assert {item["id"] for item in bond_filter["attributes"]} >= {
        "credit_grade",
        "currency",
        "availability_status",
    }
    assert not bond_filter["relations"]

    cross_risk = cases["CMP-RISK-001"]["requirements"]
    assert {item["id"] for item in cross_risk["attributes"]} == {
        "product_risk_grade",
        "credit_grade",
    }

    document = cases["DOC-FUND-001"]["requirements"]
    assert "PolicyProgram" in {item["type"] for item in document["entities"]}
    assert {item["predicate"] for item in document["relations"]} == {
        "documentedBy"
    }
    assert document["document_claims"][0]["required_provenance"] == [
        "publisher_organization_id",
        "published_at",
        "effective_from",
        "effective_to",
        "available_at",
        "document_version",
        "source_object_id",
        "document_chunk_id",
        "source_span",
    ]
```

- [ ] **Step 2: Run the new tests and confirm the v1.2 catalog fails**

Run:

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest \
  tests/ingestion/test_official_question_gates.py \
  -k 'question_contract' -q
```

Expected: FAIL because the catalog still reports schema `1.2`, retains
`required_relations`, and lacks the six `requirements` groups.

- [ ] **Step 3: Convert the catalog to schema 1.3 without changing frozen fields**

Change the top-level `schema_version` to `1.3`. For every one of the 52 cases:

1. Remove `required_relations` after its values have been classified.
2. Add all six requirement arrays, including empty arrays.
3. Move Graph aliases to the canonical predicate set:

```text
belongsToRepresentativeFund -> hasShareClass
classifiedInIndustry        -> classifiedAsIndustry
classifiedInSector          -> classifiedAsIndustry
describedByDocument         -> documentedBy
hasBenchmark                -> tracksIndex
hasSubsidiary               -> controlsCompany
issuedByCompany             -> securityOfCompany
representedBySecurity       -> securityOfCompany
```

4. Use these fixed relation directions:

```text
managedBy               product_to_manager
issuedBy                product_or_security_to_issuer
tracksIndex             product_to_index
holdsSecurity           product_to_security
containsSecurity        index_to_security
securityOfCompany       security_to_company
controlsCompany         parent_to_subsidiary
listedOn                security_to_market
classifiedAsIndustry    company_or_security_to_industry
associatedWithTheme     entity_to_theme
hasShareClass           representative_fund_to_share_class
documentedBy            entity_to_document
hasRiskFactor           product_to_risk_factor
```

5. Every relation requires `relation_assertion_id`, `evidence_id`, and
   `dataset_version`. Add `valid_from`, `valid_to`, `published_at`, and
   `available_at` to time-sensitive relation assertions. Add `weight_pct` and
   `applicable_date` to `holdsSecurity` when holding weights are required.
6. Move the historical numeric names listed in design section 3.3 to
   `metrics`. Give each item an `id`, its question role, its PostgreSQL
   authority, and the exact dimensions required by the question.
7. Move Region, AssetClass, grades, currency, status, eligibility, hedge,
   offering, and rate-structure names to `attributes`. Use distinct controlled
   vocabularies `product_risk_grade_v1` and `credit_grade_v1`.
8. Move structure, strategy, update, and risk text to `document_claims`.
   `publishedBy` becomes provenance and never a Graph predicate.
9. Convert identity names such as `hasAlias`, `hasOfficialName`, and
   `hasProductFamily` to entity requirements.
10. Convert invalid or absent `relatedToEntity` to an Evidence-backed control
    check, not a relation.
11. Keep the original `required_fields`, `business_rules`,
    `ontology_checks`, Evidence requirements, and support fields unchanged.

Add `retrieval` to every case:

```json
{
  "profile": "structured",
  "roles": ["keyword", "rdb"],
  "subtask_routes": [
    {
      "subtask": "resolve_product",
      "capability": "resolve_entity",
      "role": "keyword",
      "required": true
    }
  ]
}
```

Use only the profiles defined in design section 3.4. Every existing subtask
must appear exactly once in `subtask_routes`. Policy gates have no storage
roles; snapshot gates use dataset metadata; ontology gates use only ontology;
Graph roles appear only where a canonical relation path is required; Vector
roles appear only where a document claim is required.

Add:

```json
"requires_data": false,
"verification": {
  "coverage_assessment": "frozen_design_2026-08-27",
  "current_db_execution": "not_run",
  "verified_dataset_version": null,
  "verified_at": null,
  "result_artifact": null
}
```

Set `requires_data` to `true` only for the 11 cases whose `support_level` is
`requires_additional_data`.

- [ ] **Step 4: Run JSON parsing and focused contract tests**

Run:

```bash
/Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m json.tool tests/gold/core_questions.json >/dev/null
```

Run:

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest \
  tests/ingestion/test_official_question_gates.py \
  -k 'question_contract or stage03_question_coverage_contract_is_complete or cross_family_samsung' \
  -q
```

Expected: PASS. The fingerprint proves the forbidden fields did not change.

- [ ] **Step 5: Inspect the normalized catalog mechanically**

Run:

```bash
jq '{schema_version, cases: (.cases | length), requirement_keys:
  (.cases | map(.requirements | keys) | unique), graph_predicates:
  (.cases | map(.requirements.relations[].predicate) | unique),
  requires_data: (.cases | map(select(.requires_data)) | length)}' \
  tests/gold/core_questions.json
```

Expected: schema `1.3`, 52 cases, one six-key requirement shape, only the 13
approved predicates or their used subset, and 11 `requires_data` cases.

- [ ] **Step 6: Commit the normalized executable contract**

Stage only:

```bash
git add \
  tests/gold/core_questions.json \
  tests/ingestion/test_official_question_gates.py
```

Inspect `git diff --cached --check`, `git diff --cached`, and
`git status --short`, then commit:

```bash
git commit -m "test: normalize question capability contract"
```

---

### Task 2: Align Ontology, Evaluation, Coverage, and Status Documentation

**Files:**

- Modify: `docs/planning/architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md`
- Modify: `docs/planning/specs/core-evaluation-set.md`
- Modify: `docs/planning/specs/stage-03-question-coverage-2026-08-24.md`
- Modify: `docs/planning/STATUS.md`

**Interfaces:**

- Consumes: the verified schema `1.3` question contract from Task 1.
- Produces: one documented boundary for 13 domain predicates, controlled
  attributes, numeric metrics, document provenance, and policy-program typing.
- Produces: a status record that marks logical normalization complete while
  keeping TTL and SHACL pending.

- [ ] **Step 1: Update the ontology class and semantic-property boundaries**

In `FINANCIAL_ONTOLOGY_ARCHITECTURE.md`:

1. Change the status to state that the 2026-08-30 question-contract amendment
   is approved and TTL/SHACL remain pending.
2. Add `PolicyProgram` as a document-subject entity without making it a
   `FinancialProduct` subtype.
3. Replace the single `RiskGrade` entry with distinct `ProductRiskGrade` and
   `CreditGrade` entries.
4. Add a subsection separating:
   - 13 Graph domain traversal predicates;
   - controlled semantic attributes;
   - numeric and temporal metrics;
   - document and Evidence provenance properties.
5. Expand `documentedBy` domain to `FinancialProduct`, `Organization`, and
   `PolicyProgram`.
6. Add the exact document provenance fields from ADR-0021.
7. State that `publishedBy`, `investsInRegion`, and `investsInAssetClass` do not
   expand the 13-predicate set.
8. Replace the old implementation-preflight item about mixed
   `required_relations` with the verified schema `1.3` requirement boundary.

- [ ] **Step 2: Update evaluation and coverage contract descriptions**

In `core-evaluation-set.md`:

- Replace `required_relations` in the case-field table with `requirements` and
  describe all six groups.
- Describe `retrieval`, `requires_data`, and `verification` as explicit case
  fields.
- State that grades, Region, AssetClass, currency, and status are controlled
  attributes rather than Graph relationships.
- Keep the 52-case counts and all evaluation behavior unchanged.

In `stage-03-question-coverage-2026-08-24.md`:

- Change the single machine-readable contract version from `1.2` to `1.3`.
- State that support coverage is frozen independently of Stage 04 execution
  verification.
- Preserve every support count and case row unchanged.

In `STATUS.md`:

- Record that question-contract schema `1.3` and ADR-0021 are complete.
- Keep ontology TTL, SHACL, ABox, and Fuseki implementation pending.
- Do not mark Stage 04 complete or change Stage 03 ingestion status.

- [ ] **Step 3: Verify documentation consistency and forbidden terms**

Run:

```bash
rg -n 'core_questions.json` 1\.2|required_relations.*온톨로지 또는 지식 그래프|Proposed for user review' \
  docs/planning/architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md \
  docs/planning/specs/core-evaluation-set.md \
  docs/planning/specs/stage-03-question-coverage-2026-08-24.md \
  docs/planning/specs/2026-08-29-question-capability-contract-normalization-design.md \
  docs/planning/STATUS.md
```

Expected: no matches.

Run:

```bash
rg -n 'PolicyProgram|ProductRiskGrade|CreditGrade|publisher_organization_id|requirements\.attributes' \
  docs/planning/architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md \
  docs/planning/specs/core-evaluation-set.md \
  docs/planning/specs/2026-08-29-question-capability-contract-normalization-design.md
```

Expected: every new semantic boundary appears in the architecture or contract
documentation that owns it.

- [ ] **Step 4: Run the complete non-live regression**

Run:

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/contracts tests/db tests/ingestion \
  -m 'not postgres and not ncp_integration and not performance and not organizer_data and not object_storage and not official_data' \
  -q
```

Expected: at least the clean baseline of 696 passing tests plus the new
question-contract tests, with no failures.

Run:

```bash
git diff --check
git status --short
```

Inspect every changed path. Confirm there is no file under `data/`, no organizer
PDF or workbook, no generated artifact, no secret, no Stage 03 ingestion file,
and no Vector implementation file.

- [ ] **Step 5: Commit the aligned logical documentation**

Stage only:

```bash
git add \
  docs/planning/architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md \
  docs/planning/specs/core-evaluation-set.md \
  docs/planning/specs/stage-03-question-coverage-2026-08-24.md \
  docs/planning/STATUS.md
```

Inspect `git diff --cached --check`, `git diff --cached`, and
`git status --short`, then commit:

```bash
git commit -m "docs: align ontology with question contract"
```

---

## Final Acceptance

- [ ] Schema `1.3` parses and contains exactly 52 cases.
- [ ] Frozen case fingerprint remains
  `66e8b51004270a8233d02328cb7095360f46afedf168f7325f9dd221e2a7271b`.
- [ ] All six requirement groups exist in every case.
- [ ] Every subtask has exactly one explicit route.
- [ ] Only the approved 13 predicates can appear in Graph requirements.
- [ ] Product risk and credit grade are distinct controlled attributes.
- [ ] Policy programs and document provenance are represented without a new
  domain predicate.
- [ ] Support counts and dispositions are unchanged.
- [ ] Complete non-live regression passes.
- [ ] Final diff contains only the approved contract, test, architecture,
  evaluation, coverage, and status files.
- [ ] No TTL, SHACL, ABox, Fuseki, Vector, Stage 03 ingestion, database, cloud,
  raw data, or secret change is present.

After this plan completes, write a separate Stage 04 TTL and SHACL
implementation plan from the verified schema `1.3` contract. Do not append TTL
implementation to this plan.
