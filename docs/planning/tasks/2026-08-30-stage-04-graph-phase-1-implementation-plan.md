# Stage 04 Graph Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved 13-predicate financial-product ontology,
SHACL gates, deterministic PostgreSQL-to-RDF projection, evidence-bound SPARQL
read path, and local Apache Jena/Fuseki compatibility gate without waiting for
the Vector corpus or activating a dataset.

**Architecture:** PostgreSQL remains authoritative. A read-only repository
loads one explicit `dataset_version` into typed immutable records. A pure
exporter validates those records and emits deterministic data and evidence
named-graph N-Quads. RDFLib and pySHACL provide the always-on gate; Apache Jena
6.0.0, TDB2, and read-only Fuseki provide the exact-runtime gate from external
binaries. The Graph module never writes PostgreSQL readiness or active-dataset
state.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async Core, RDFLib 7.6, pySHACL 0.40,
pytest 8, RDF/Turtle, SHACL, SPARQL 1.1, Apache Jena/Fuseki 6.0.0, Java 24,
SHA-256

**Spec:**
`docs/planning/specs/2026-08-30-stage-04-graph-phase-1-design.md`

**Decisions:**
`docs/planning/decisions/ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md`,
`docs/planning/decisions/ADR-0021-amend-minimal-ontology-for-question-contract-semantics.md`

## Global Constraints

- Work only on branch `codex/graph-phase1-core` in the isolated worktree
  `/private/tmp/financial-agent-ontology-contract-normalization`, based on
  commit `d346aef`.
- Do not touch the user's dirty `codex/stage03-local-completion` worktree or any
  Vector/Stage 03 implementation file.
- Keep PostgreSQL `relation.relation_record` and the Evidence ledger
  authoritative; Graph is a reproducible projection, never a second write
  authority.
- Keep exactly the 13 predicates approved by ADR-0021. Unknown predicates fail
  the build; they are never silently skipped.
- Keep entity IRIs stable across versions and put versioned facts into two
  named graphs. Relation, Evidence, and Source IRIs include `dataset_version`.
- Every direct edge must have one `RelationAssertion`, at least one linked
  Evidence record, and one resolvable Source record.
- Treat `relation_record.relation_id` as `relation_assertion_id`; do not add a
  migration or duplicate identifier.
- Do not expose source locators or raw payloads in RDF.
- Do not call `record_dataset_readiness`, `activate_dataset`, or write any
  PostgreSQL row in this phase.
- Do not commit organizer data, official-source payloads, generated N-Quads,
  TDB2 files, Jena binaries, credentials, logs, or validation output.
- Implement and commit one verified task at a time. Run the narrow test first,
  then the Graph suite, then the existing non-live regression before claiming
  completion.

---

### Task 1: Lock Dependencies, Namespaces, and the Five-File TBox

**Files:**

- Modify: `pyproject.toml`
- Create: `src/financial_agent/graph/__init__.py`
- Create: `src/financial_agent/graph/contract.py`
- Create: `ontology/common.ttl`
- Create: `ontology/bond_kr.ttl`
- Create: `ontology/etf_kr.ttl`
- Create: `ontology/etf_gl.ttl`
- Create: `ontology/fund_pub.ttl`
- Create: `tests/graph/__init__.py`
- Create: `tests/graph/test_ontology_contract.py`

**Interfaces:**

- `ONTOLOGY_IRI = "urn:ontology:financial-product:v1"`
- `FP = Namespace(f"{ONTOLOGY_IRI}#")`
- `APPROVED_PREDICATES: frozenset[str]` contains exactly the 13 approved IDs.
- `ENTITY_CLASS_BY_TYPE` maps existing `catalog.entity.entity_type` values to
  base TBox classes without changing the database schema.
- Product role typing combines `catalog.product.product_family`, the existing
  `product_type` Observation, identifier scheme, and `hasShareClass` relation;
  it does not guess ETF/ETN or fund roles from a display name.

- [x] **Step 1: Add the Graph dependency profile and test marker**

Add only this optional dependency group and marker:

```toml
graph = [
  "rdflib>=7.6,<8",
  "pyshacl>=0.40,<1",
]
```

```toml
"jena_integration: requires RUN_JENA_INTEGRATION=1 and external Apache Jena/Fuseki 6.0.0 binaries",
```

Install the editable project into the existing isolated verification
environment without changing a lockfile:

```bash
/Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pip install -e '.[graph]'
```

- [x] **Step 2: Write the failing TBox contract test**

The test must parse all five Turtle files and compare the object-property local
names with the question contract, not with a second hand-maintained test set:

```python
def question_predicates() -> frozenset[str]:
    catalog = json.loads(
        (PROJECT_ROOT / "tests/gold/core_questions.json").read_text("utf-8")
    )
    return frozenset(
        relation["predicate"]
        for case in catalog["cases"]
        for relation in case["requirements"]["relations"]
    )


def test_tbox_parses_and_matches_question_predicates() -> None:
    graph = Graph()
    for path in TBOX_PATHS:
        graph.parse(path, format="turtle")

    domain_properties = frozenset(
        str(subject).removeprefix(f"{ONTOLOGY_IRI}#")
        for subject in graph.subjects(RDF.type, FP.DomainPredicate)
        if str(subject).startswith(f"{ONTOLOGY_IRI}#")
    )

    assert domain_properties == APPROVED_PREDICATES
    assert domain_properties == question_predicates()
```

Also assert that each property has the domain/range from ADR-0021, all declared
classes resolve, product-risk and credit-grade classes are distinct, and the
five input files contain no duplicate ontology declaration.

- [x] **Step 3: Run the test and confirm RED**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph/test_ontology_contract.py -q
```

Expected: failure because `contract.py` and the five TBox files do not exist.

- [x] **Step 4: Implement the shared contract constants**

Use immutable constants and no dependency on ingestion mappers:

```python
ONTOLOGY_IRI = "urn:ontology:financial-product:v1"
FP = Namespace(f"{ONTOLOGY_IRI}#")

APPROVED_PREDICATES = frozenset(
    {
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
)

ENTITY_CLASS_BY_TYPE = {
    "product": "FinancialProduct",
    "security": "Security",
    "company": "Company",
    "institution": "Organization",
    "index": "Index",
    "theme": "Theme",
}

PRODUCT_BASE_CLASSES_BY_FAMILY = {
    "domestic_bond": ("FinancialProduct", "Bond", "DomesticBond"),
    "domestic_etf": ("FinancialProduct",),
    "overseas_etf": ("FinancialProduct",),
    "public_fund": ("FinancialProduct", "PublicFund"),
}

ETP_CLASSES_BY_FAMILY_AND_TYPE = {
    ("domestic_etf", "ETF"): ("ETF", "DomesticETF"),
    ("domestic_etf", "ETN"): ("ETN", "DomesticETN"),
    ("overseas_etf", "ETF"): ("ETF", "OverseasETF"),
    ("overseas_etf", "ETN"): ("ETN", "OverseasETN"),
}

RELATION_METRIC_PROPERTY_BY_ID = {
    "krx_etf_holding_weight_pct": "holdingWeightPercentage",
    "official_holding_weight_pct": "holdingWeightPercentage",
}
```

- [x] **Step 5: Implement the five TBox modules**

`common.ttl` owns the ontology declaration, common classes,
`RelationAssertion`, `EvidenceRecord`, `SourceRecord`, all 13 domain object
properties, and assertion metadata properties. Mark only the 13 approved
domain properties as `fp:DomainPredicate`, so assertion metadata properties do
not contaminate the allowlist. Domain unions use explicit `owl:unionOf`; no
property is added for a controlled attribute or metric.

The four family files import the common ontology and declare only their family
subclasses and controlled vocabulary. Preserve the approved multi-role model:
`DomesticETF` and `FundShareClass` are not disjoint, while `ETF` and `ETN` are
disjoint. Keep `ProductRiskGrade` and `CreditGrade` separate.

- [x] **Step 6: Run the TBox test and Graph suite GREEN**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph/test_ontology_contract.py tests/contracts -q
```

- [x] **Step 7: Commit the independently useful TBox**

```bash
git add pyproject.toml src/financial_agent/graph ontology tests/graph
git diff --cached --check
git diff --cached
git commit -m "feat: add graph ontology tbox"
```

---

### Task 2: Implement SHACL and Synthetic Semantic Fixtures

**Files:**

- Create: `ontology/shapes/common.shacl.ttl`
- Create: `ontology/shapes/domain.shacl.ttl`
- Create: `src/financial_agent/graph/validator.py`
- Create: `tests/fixtures/graph/valid_all_predicates.trig`
- Create: `tests/fixtures/graph/valid_multi_role_product.trig`
- Create: `tests/fixtures/graph/invalid_unknown_predicate.trig`
- Create: `tests/fixtures/graph/invalid_missing_evidence.trig`
- Create: `tests/fixtures/graph/invalid_date_order.trig`
- Create: `tests/fixtures/graph/invalid_after_cutoff.trig`
- Create: `tests/fixtures/graph/invalid_etf_etn.trig`
- Create: `tests/fixtures/graph/invalid_grade_scheme.trig`
- Create: `tests/fixtures/graph/invalid_holding_weight.trig`
- Create: `tests/graph/test_shacl_validation.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class GraphValidationResult:
    conforms: bool
    report_text: str
    report_ntriples: bytes
    report_hash: str
    validated_data_hash: str
    validated_evidence_hash: str | None
    validated_cutoff_date: str
    contract_hashes: Mapping[str, str]


def validate_graph(
    *,
    data_paths: Sequence[Path],
    shape_paths: Sequence[Path],
    cutoff_date: date,
) -> GraphValidationResult: ...
```

`report_hash` is SHA-256 over canonical, sorted report N-Triples, not pySHACL's
human-readable text or transient blank-node labels. The result also binds the
exact data/Evidence bytes, cutoff, and five TBox plus two SHACL contract hashes
that were validated. The function returns a result for semantic
non-conformance and raises only for unreadable or syntactically invalid input.
An additional domain-shape pass retains subclass closure but removes TBox
domain/range entailment so assertion, Evidence, Source, document, publisher,
risk and chunk trust types must be explicit in the validated artifacts.

- [x] **Step 1: Write parameterized positive and negative tests**

Test all 13 predicates in `valid_all_predicates.trig`; test each named invalid
fixture independently and assert the stable SHACL source-constraint component,
not a fragile full report string. Include these targeted assertions:

```python
@pytest.mark.parametrize(
    ("fixture", "expected_component"),
    [
        ("invalid_missing_evidence.trig", "MinCountConstraintComponent"),
        ("invalid_date_order.trig", "SPARQLConstraintComponent"),
        ("invalid_after_cutoff.trig", "MaxInclusiveConstraintComponent"),
        ("invalid_etf_etn.trig", "NotConstraintComponent"),
        ("invalid_grade_scheme.trig", "InConstraintComponent"),
        ("invalid_holding_weight.trig", "MinCountConstraintComponent"),
    ],
)
def test_invalid_fixture_is_rejected(
    fixture: str,
    expected_component: str,
) -> None:
    result = validate_fixture(fixture)
    assert result.conforms is False
    assert expected_component in result.report_text
```

Also assert that the exact-identity multi-role fixture conforms and that the
unknown-predicate fixture fails the predicate `sh:in` constraint. Task 3 adds
the earlier exporter-side allowlist failure for typed batches.

- [x] **Step 2: Run the tests and confirm RED**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph/test_shacl_validation.py -q
```

- [x] **Step 3: Implement common and domain SHACL shapes**

The common shapes enforce assertion subject, predicate, object, relation ID,
dataset version, Evidence, source resolution, valid-date ordering, and cutoff.
Use a validation-only cutoff parameter node injected by `validate_graph`; do
not encode `2026-08-24` as ontology truth.

The domain shapes enforce the approved domain/range table, ETF/ETN exclusion,
grade-scheme separation, and the relation-scoped `holdsSecurity` weight
observation. `documentedBy` and `hasRiskFactor` shapes are present, but only
synthetic fixtures instantiate them in Phase 1.

- [x] **Step 4: Implement the pySHACL wrapper**

Parse all named-graph input and copy its triples into one validation union
`Graph`, add a deterministic validation-context node carrying `cutoffDate`,
and call:

```python
conforms, report_graph, report_text = pyshacl.validate(
    data_graph=data,
    shacl_graph=shapes,
    ont_graph=ontology,
    inference="rdfs",
    abort_on_first=False,
    allow_infos=False,
    allow_warnings=False,
    advanced=True,
)
```

Canonicalize `report_graph` with RDFLib's canonical graph utility, serialize
sorted N-Triples with LF newlines, and hash those bytes. Normalize
`report_text` only for display. Never mutate or repair the source dataset.

- [x] **Step 5: Run SHACL and ontology tests GREEN**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph/test_ontology_contract.py \
  tests/graph/test_shacl_validation.py -q
```

- [x] **Step 6: Commit the validation gate**

```bash
git add ontology/shapes src/financial_agent/graph/validator.py \
  tests/fixtures/graph tests/graph/test_shacl_validation.py
git diff --cached --check
git diff --cached
git commit -m "feat: validate graph projections with shacl"
```

---

### Task 3: Build the Typed Projection Contract and Deterministic Exporter

**Files:**

- Modify: `src/financial_agent/graph/contract.py`
- Create: `src/financial_agent/graph/exporter.py`
- Create: `tests/graph/test_graph_contract.py`
- Create: `tests/graph/test_graph_exporter.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class EntityProjection:
    dataset_version: str
    entity_id: str
    rdf_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceProjection:
    dataset_version: str
    source_id: str
    publisher_id: str


@dataclass(frozen=True, slots=True)
class EvidenceProjection:
    dataset_version: str
    evidence_id: str
    source_id: str
    applicable_date: date | None
    valid_from: date | None
    valid_to: date | None
    published_at: datetime | None
    available_at: datetime | None
    cutoff_status: str


@dataclass(frozen=True, slots=True)
class RelationMetricProjection:
    dataset_version: str
    observation_id: str
    relation_id: str
    metric_id: str
    numeric_value: Decimal
    unit: str | None
    applicable_date: date | None


@dataclass(frozen=True, slots=True)
class RelationProjection:
    dataset_version: str
    relation_id: str
    subject_id: str
    predicate_id: str
    object_id: str
    valid_from: date | None
    valid_to: date | None
    evidence_ids: tuple[str, ...]
    metrics: tuple[RelationMetricProjection, ...] = ()


@dataclass(frozen=True, slots=True)
class GraphProjectionBatch:
    dataset_version: str
    cutoff_date: date
    entities: tuple[EntityProjection, ...]
    sources: tuple[SourceProjection, ...]
    evidences: tuple[EvidenceProjection, ...]
    relations: tuple[RelationProjection, ...]


@dataclass(frozen=True, slots=True)
class GraphArtifacts:
    data_nquads: bytes
    evidence_nquads: bytes
    entity_type_counts: Mapping[str, int]
    predicate_counts: Mapping[str, int]
```

Public helpers:

```python
def entity_iri(entity_id: str) -> URIRef: ...
def relation_iri(dataset_version: str, relation_id: str) -> URIRef: ...
def evidence_iri(dataset_version: str, evidence_id: str) -> URIRef: ...
def source_iri(dataset_version: str, source_id: str) -> URIRef: ...
def holding_weight_observation_iri(
    dataset_version: str,
    observation_id: str,
) -> URIRef: ...
def build_graph_artifacts(batch: GraphProjectionBatch) -> GraphArtifacts: ...
```

- [x] **Step 1: Write failing contract and exporter tests**

Cover reversible UTF-8 percent encoding, empty/whitespace-only/NUL identifier rejection,
stable entity IRIs across versions, versioned assertion/Evidence/Source IRIs,
approved RDF-type rejection, direct edge plus assertion emission, multiple
Evidence links, weight metric emission, source locator absence, and exact
named-graph IRIs.

Use table-driven failures with stable codes:

```python
@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (unknown_predicate, "unknown_predicate"),
        (missing_subject, "missing_entity"),
        (missing_object, "missing_entity"),
        (missing_evidence, "missing_evidence"),
        (missing_source, "missing_source"),
        (mixed_version, "dataset_version_mismatch"),
        (after_cutoff, "after_cutoff"),
        (reversed_dates, "invalid_date_order"),
    ],
)
def test_invalid_projection_fails_the_whole_build(mutation, code) -> None:
    with pytest.raises(GraphProjectionError, match=code):
        build_graph_artifacts(mutation(valid_batch()))
```

Create two batches containing identical records in reverse order and assert
byte equality for both N-Quads outputs.

- [x] **Step 2: Run exporter tests and confirm RED**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph/test_graph_contract.py \
  tests/graph/test_graph_exporter.py -q
```

- [x] **Step 3: Implement IRI and record validation**

Encode dynamic segments with `urllib.parse.quote(value, safe="")`. Reject
empty strings, NUL, invalid predicate IDs, foreign dataset versions, missing
foreign records, `cutoff_status != "eligible"`, dates after the supplied
cutoff, and reversed date intervals before generating any quad. For timezone-
aware `published_at` and `available_at`, reuse the existing ingestion rule:
compare after conversion to UTC+09:00 against 23:59:59 on `cutoff_date`.

`SourceProjection` deliberately exposes only IDs. Do not add title, locator,
raw value, or checksum fields unless the approved design is amended.

- [x] **Step 4: Implement deterministic named-graph N-Quads**

Use no blank nodes. Create these contexts exactly:

```python
data_graph = URIRef(f"urn:data:financial-product:{encoded_version}")
evidence_graph = URIRef(f"urn:evidence:financial-product:{encoded_version}")
```

Build RDFLib terms, then serialize quads through a small canonical writer:

```python
def _serialize_quads(quads: Iterable[Quad]) -> bytes:
    lines = sorted(
        f"{subject.n3()} {predicate.n3()} {object_.n3()} {graph.n3()} ."
        for subject, predicate, object_, graph in quads
    )
    return ("\n".join(lines) + "\n").encode("utf-8")
```

Deduplicate identical lines using a set before sorting. Emit explicit
`entityId`, `relationId`, `evidenceId`, and `sourceId` literals so read queries
never reverse-engineer IDs from IRIs. Preserve one assertion node per
`relation_id`; attach all Evidence IDs and supported relation metrics.

- [x] **Step 5: Run exporter, parse, and SHACL tests GREEN**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph/test_graph_contract.py \
  tests/graph/test_graph_exporter.py \
  tests/graph/test_shacl_validation.py -q
```

- [x] **Step 6: Commit the pure projection layer**

```bash
git add src/financial_agent/graph/contract.py \
  src/financial_agent/graph/exporter.py \
  tests/graph/test_graph_contract.py tests/graph/test_graph_exporter.py
git diff --cached --check
git diff --cached
git commit -m "feat: export deterministic graph projections"
```

---

### Task 4: Read One PostgreSQL Version and Produce the Component Manifest

**Files:**

- Create: `src/financial_agent/graph/repository.py`
- Create: `src/financial_agent/graph/manifest.py`
- Create: `tests/db/test_graph_projection_repository.py`
- Create: `tests/graph/test_graph_manifest.py`

**Interfaces:**

```python
class GraphProjectionRepository:
    def __init__(self, engine: AsyncEngine) -> None: ...

    async def load(self, dataset_version: str) -> GraphProjectionBatch: ...


@dataclass(frozen=True, slots=True)
class GraphComponentManifest:
    schema_version: str
    dataset_version: str
    cutoff_date: str
    exporter_version: str
    ontology_hashes: Mapping[str, str]
    data_nquads_hash: str
    evidence_nquads_hash: str
    validation_report_hash: str
    entity_type_counts: Mapping[str, int]
    predicate_counts: Mapping[str, int]

    def canonical_bytes(self) -> bytes: ...
    def component_manifest_hash(self) -> str: ...


def build_graph_manifest(
    *,
    batch: GraphProjectionBatch,
    artifacts: GraphArtifacts,
    ontology_paths: Sequence[Path],
    validation: GraphValidationResult,
) -> GraphComponentManifest: ...
```

- [x] **Step 1: Write the PostgreSQL integration test first**

Place it under `tests/db/` so it can reuse the existing migrated PostgreSQL
fixture. Mark it `@pytest.mark.postgres`. Insert a synthetic building dataset,
entities, product rows, one approved relation, relation Evidence, source, and a
relation-scoped weight observation through existing tables. Assert exact typed
output and stable sorting.

Add a SQL statement listener and assert every statement executed by `load` is
`SELECT` or `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`;
assert `operations.dataset_readiness` and `operations.active_dataset` remain
unchanged. A two-connection PostgreSQL 15 test commits a relation/Evidence pair
between repository `SELECT`s and proves the returned batch sees one snapshot,
not a mixed pre/post-commit state.

- [x] **Step 2: Write the manifest unit tests**

Assert sorted canonical JSON, stable SHA-256, order-independent input path
handling, the exact five TBox plus two SHACL tracked path set, changed hash when
any ontology/data/evidence/report byte changes, validation binding to the exact
artifacts/contracts/cutoff, and batch-derived entity/predicate counts.

- [x] **Step 3: Run tests and confirm RED**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph/test_graph_manifest.py -q
```

When a disposable PostgreSQL URL is available, also run:

```bash
PYTHONPATH=src FINANCIAL_AGENT_TEST_DATABASE_URL="$FINANCIAL_AGENT_TEST_DATABASE_URL" \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/db/test_graph_projection_repository.py -q
```

- [x] **Step 4: Implement the read-only repository**

Open one async connection and transaction, execute
`SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY` before the first
`SELECT`, fetch `operations.dataset_version.cutoff_date`, then fetch and sort:

1. `catalog.entity` left-joined to `catalog.product`, `catalog.security`, and
   `catalog.institution`;
2. `catalog.identifier` for role-bearing schemes, plus entity-scoped
   `observation.observation_record` for the exact `product_type` metric;
3. `relation.relation_record` for the exact version;
4. `evidence.evidence_relation_origin` joined to
   `evidence.evidence_record` and `evidence.source_record`;
5. `observation.observation_record` where `relation_id IS NOT NULL` and
   `metric_id` is an approved relation metric.

For Phase 1 the approved relation metrics are the exact keys in
`RELATION_METRIC_PROPERTY_BY_ID`:
`krx_etf_holding_weight_pct` and `official_holding_weight_pct`. Join the exact
metric definition version referenced by each observation and require numeric
`present` or `zero` values with `percentage_point` units, an observation ID and
an applicable date at or before cutoff. Preserve multiple observations as
separate nodes; reject weights on non-`holdsSecurity` relations, duplicate
observation IDs, and more than one weight for the same relation/applicable-date
pair. Do not infer Graph eligibility from a metric-name substring or broad
semantic family.
Derive `EntityProjection.rdf_types` deterministically from those stored facts:

- generic entity type supplies the base class;
- product family supplies only unambiguous family classes;
- exact `product_type` Observation distinguishes ETF from ETN and selects the
  domestic/overseas subclass;
- `institution_kind` supplies `AssetManager`, `Issuer`, or `Market` roles;
- `security_kind` supplies supported security subclasses;
- `PRFD_ITM_NO` identifies a persisted fund share-class role;
- a `hasShareClass` subject is a `RepresentativeFund`, and its object is a
  `FundShareClass`.

This rule preserves a DomesticETF/FundShareClass overlap while rejecting
ETF/ETN overlap. Missing or conflicting facts needed by an encountered
relation domain/range fail the projection; names are never used for typing.
Group Evidence and metrics by relation ID, sort every collection, and return a
single immutable batch only after all queries succeed.

- [x] **Step 5: Implement canonical manifest generation**

Use:

```python
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

Require exactly the five tracked TBox and two tracked SHACL paths. Hash their
bytes, both N-Quads artifacts, and the normalized validation report. Require
the validation result's artifact, cutoff and contract bindings to match, then
rebuild artifacts from the batch and require exact bytes and counts. The
manifest function is pure and performs no database or filesystem write.

- [x] **Step 6: Run unit, Graph, and PostgreSQL tests GREEN**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph -m 'not jena_integration' -q
```

Run the marked PostgreSQL test when its dedicated disposable database is
configured; an unavailable database is a reported environment gate, not a
silent pass.

- [x] **Step 7: Commit the database-to-manifest boundary**

```bash
git add src/financial_agent/graph/repository.py \
  src/financial_agent/graph/manifest.py \
  tests/db/test_graph_projection_repository.py \
  tests/graph/test_graph_manifest.py
git diff --cached --check
git diff --cached
git commit -m "feat: project postgres relations into graph artifacts"
```

---

### Task 5: Add Evidence-Bound Competency Queries and a Read-Only Client

**Files:**

- Create: `src/financial_agent/graph/queries.py`
- Create: `src/financial_agent/graph/client.py`
- Create: `tests/graph/test_competency_queries.py`
- Create: `tests/graph/test_graph_client.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class GraphQueryResult:
    query_id: str
    dataset_version: str
    coverage_status: str
    bindings: tuple[Mapping[str, str], ...]


class FusekiGraphClient:
    def __init__(self, query_endpoint: str, timeout_seconds: float = 5.0) -> None: ...

    def select(
        self,
        *,
        query_id: str,
        sparql: str,
        dataset_version: str,
        coverage_status: str,
    ) -> GraphQueryResult: ...
```

There is intentionally no update, graph-store, admin, delete, or dataset
activation method.

- [x] **Step 1: Write five failing RDFLib competency tests**

Add query builders for `managedBy`, `issuedBy`, `tracksIndex`,
`holdsSecurity`, and `hasShareClass`. Each SELECT must return:

```text
subject_id predicate_id object_id relation_assertion_id evidence_id
dataset_version valid_from valid_to
```

Load exported synthetic artifacts into RDFLib, execute each query, and compare
the entire expected binding. Add an empty-result test proving the wrapper
returns `dataset_version`, `query_id`, and caller-supplied `coverage_status`
without converting zero rows into a claim of relationship absence.

- [x] **Step 2: Write the failing HTTP client tests**

Monkeypatch `urllib.request.urlopen` to verify POSTed
`application/x-www-form-urlencoded` SELECT requests, required SPARQL JSON
accept headers, deterministic binding sort, timeout propagation, malformed
JSON rejection, HTTP failure wrapping, and rejection of non-SELECT query text.

- [x] **Step 3: Run tests and confirm RED**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph/test_competency_queries.py \
  tests/graph/test_graph_client.py -q
```

- [x] **Step 4: Implement evidence-bound query builders**

Use a shared SELECT template with explicit `GRAPH` clauses for the versioned
data and evidence graph IRIs. Join a direct edge to the matching
`RelationAssertion` subject, predicate, object, dataset version, and
`supportedBy` Evidence. Bind IDs from explicit literal properties; do not parse
opaque IDs out of IRIs in SPARQL.

The public builder accepts only one of the 13 approved predicate IDs and a
dataset version. Phase 1 tests current real paths for five predicates while all
13 remain available for synthetic contract validation.

- [x] **Step 5: Implement the standard-library read-only client**

Reject any query whose parsed first operation is not `SELECT`. POST only to the
configured query endpoint, decode SPARQL Results JSON, normalize unbound values
to absent keys, sort bindings lexically, and return the typed result. Do not
accept credentials in the result object or log request bodies.

- [x] **Step 6: Run query and full Graph unit suites GREEN**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph -m 'not jena_integration' -q
```

- [x] **Step 7: Commit the read path**

```bash
git add src/financial_agent/graph/queries.py \
  src/financial_agent/graph/client.py \
  tests/graph/test_competency_queries.py tests/graph/test_graph_client.py
git diff --cached --check
git diff --cached
git commit -m "feat: query evidence-bound graph relations"
```

---

### Task 6: Verify Apache Jena, TDB2, and Read-Only Fuseki

**Files:**

- Create: `config/fuseki/financial-product.ttl`
- Create: `scripts/graph/verify_jena.py`
- Create: `tests/graph/test_jena_integration.py`
- Create: `docs/planning/runbooks/GRAPH_LOCAL_VERIFICATION.md`

**Interfaces:**

```text
python scripts/graph/verify_jena.py \
  --jena-home "$JENA_HOME" \
  --fuseki-home "$FUSEKI_HOME" \
  --data "$GRAPH_VERIFY_DIR/data.nq" \
  --evidence "$GRAPH_VERIFY_DIR/evidence.nq" \
  --expected "$GRAPH_VERIFY_DIR/expected-bindings.json"
```

Exit `0` only when version, parse, SHACL, TDB2, command-line SPARQL, Fuseki
SPARQL, and read-only checks all pass. Exit nonzero with a concise stage name on
any failure.

- [x] **Step 1: Write the Jena integration test first**

Mark it `@pytest.mark.jena_integration` and require all three explicit gates:

```python
RUN_JENA_INTEGRATION == "1"
JENA_HOME is set
FUSEKI_HOME is set
```

If the marker is selected and any gate is absent, fail with installation
instructions. Do not skip a requested exact-runtime gate. The test generates
synthetic N-Quads in `tmp_path`, invokes the runner as a subprocess, and asserts
exit code zero plus a structured summary containing `jena_version=6.0.0`,
`tdb2_query=pass`, `fuseki_query=pass`, and `update_surface=blocked`.

- [x] **Step 2: Run the selected test and confirm the environment failure**

```bash
RUN_JENA_INTEGRATION=1 PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph/test_jena_integration.py \
  -m jena_integration -q
```

Expected before binary setup: explicit failure naming `JENA_HOME` or
`FUSEKI_HOME`, not an import error or silent skip.

- [x] **Step 3: Implement the read-only assembler template**

Configure a TDB2 dataset with query endpoints only. Use the literal token
`__TDB2_LOCATION__`; the runner replaces it with a temporary absolute directory
in a temporary copy. Do not expose `update`, `upload`, `data`, Graph Store
Protocol, or admin endpoints.

- [x] **Step 4: Implement the external-binary runner**

Use `subprocess.run([...], shell=False, check=True)` and a temporary directory.
Resolve executables only below the supplied homes and require output version
`6.0.0`. Execute in order:

1. `riot --validate` for five TBox files, two SHACL files, and both N-Quads;
2. `shacl validate` over the generated dataset and tracked shapes;
3. `tdb2.tdbloader` into the temporary TDB2 directory;
4. `tdb2.tdbquery` for the five competency queries;
5. `fuseki-server --conf` using a rendered temporary assembler;
6. poll only the local loopback query endpoint with a bounded deadline;
7. run the same SELECT queries and compare normalized bindings;
8. verify update and Graph Store endpoints are unavailable;
9. terminate Fuseki and remove the temporary directory in `finally`.

Never download binaries, write into the repository, or leave a server process
running from this script.

- [x] **Step 5: Install verified Jena 6.0.0 outside the repository**

Download the official Apache Jena and Fuseki 6.0.0 binary archives plus their
`.sha512` files into a new `mktemp -d` directory, verify both checksums, extract
there, and export absolute `JENA_HOME` and `FUSEKI_HOME`. This network action
requires execution-time sandbox approval. Do not commit or copy the archives
into the worktree.

Java must report version 21 or newer; the current local Java 24 satisfies this
gate.

- [x] **Step 6: Run the exact-runtime gate GREEN**

```bash
RUN_JENA_INTEGRATION=1 \
JENA_HOME="$JENA_HOME" \
FUSEKI_HOME="$FUSEKI_HOME" \
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph/test_jena_integration.py \
  -m jena_integration -q
```

- [x] **Step 7: Document repeatable local verification**

The runbook records prerequisites, exact environment variables, checksum
verification, unit and Jena commands, expected summaries, cleanup behavior,
and the distinction between local Graph Phase 1 compatibility and NCP
readiness. It must not contain a local user path, credential, or generated
dataset version.

- [x] **Step 8: Commit the exact-runtime gate**

```bash
git add config/fuseki scripts/graph tests/graph/test_jena_integration.py \
  docs/planning/runbooks/GRAPH_LOCAL_VERIFICATION.md
git diff --cached --check
git diff --cached
git commit -m "test: verify graph runtime with jena and fuseki"
```

---

### Task 7: Run Full Regression and Record the Phase Boundary

**Files:**

- Modify: `docs/planning/STATUS.md`
- Modify: `docs/planning/tasks/2026-08-30-stage-04-graph-phase-1-implementation-plan.md`

**Verification matrix:**

| Gate | Required outcome |
| --- | --- |
| Graph unit/contract | all pass without external services |
| Existing non-live regression | at least baseline `699 passed`, no new failure |
| PostgreSQL projection | pass against a dedicated disposable PostgreSQL 15 DB |
| Jena/Fuseki | pass with verified 6.0.0 binaries |
| Diff/data safety | no raw data, binary, generated DB, secret, Vector, Stage 03, or migration change |

- [x] **Step 1: Run the always-on Graph gate**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/graph -m 'not jena_integration' -q
```

- [x] **Step 2: Run the existing non-live regression**

```bash
PYTHONPATH=src \
  /Users/kimjaewon/금융상품\ agent/.worktrees/stage03b-recovered/.venv/bin/python \
  -m pytest tests/contracts tests/db tests/ingestion tests/graph \
  -m 'not postgres and not ncp_integration and not performance and not organizer_data and not object_storage and not official_data and not jena_integration' \
  -q
```

The pre-change baseline is `699 passed, 336 deselected`. New Graph tests
increase the pass count; existing failures or a pass-count drop block
completion.

- [x] **Step 3: Run the two external integration gates**

Run `tests/db/test_graph_projection_repository.py` against a disposable
PostgreSQL 15 database and run the Task 6 Jena command with verified external
binaries. Record actual counts and elapsed times in STATUS. If either required
gate cannot run, leave the plan incomplete and report the named environment
blocker.

- [x] **Step 4: Prove the phase has no activation/write path**

```bash
rg -n 'record_dataset_readiness|activate_dataset|active_dataset|INSERT|UPDATE|DELETE' \
  src/financial_agent/graph scripts/graph
```

Expected: no readiness/activation call and no SQL mutation statement. Mentions
inside a read-only HTTP rejection assertion are acceptable only when the diff
shows they cannot invoke an update endpoint.

- [x] **Step 5: Inspect scope and repository safety**

```bash
git status --short
git diff --check
git diff --stat d346aef...HEAD
git diff --name-only d346aef...HEAD
```

Confirm no path under `data/`, no organizer PDF/workbook, `.env`, Jena archive,
TDB2 directory, generated N-Quads, Vector implementation, Stage 03 ingestion
implementation, or Alembic migration appears.

- [x] **Step 6: Update status accurately**

Change Stage 04 status to state that Graph Phase 1 core is locally complete
only after every required gate above passes. Keep all of Stage 04 incomplete:
Vector completion, missing real relation/document data, cross-component
manifest equality, readiness, activation, NCP deployment, and 23-question
dataset-relative coverage remain Phase 2/final Stage work.

Record exact test counts, Jena/Fuseki version, and any environment limitation.
Do not use “GraphDB complete” or “Stage 04 complete.”

- [x] **Step 7: Mark completed plan checkboxes and commit status evidence**

```bash
git add docs/planning/STATUS.md \
  docs/planning/tasks/2026-08-30-stage-04-graph-phase-1-implementation-plan.md
git diff --cached --check
git diff --cached
git commit -m "docs: record graph phase one verification"
```

- [x] **Step 8: Perform final branch inspection**

```bash
git status --short
git log --oneline d346aef..HEAD
```

Expected: clean worktree and a sequence of independently useful Graph commits.
Do not merge, push, activate a dataset, or start Phase 2 without a separate
user decision.
