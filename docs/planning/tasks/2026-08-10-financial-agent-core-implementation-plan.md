# Financial Product Agent Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-08-10

**Status:** Task 1 approved and complete; Task 2 not started

**Goal:** Build the non-server core of the Financial Product Agent: question-driven financial ontology, validated product data, deterministic screening and calculations, hybrid retrieval, conditional multi-agent orchestration, and evidence-bound answers.

**Architecture:** Start from evaluation questions and financial business rules, then build a deterministic SQL baseline over normalized organizer data. Add an RDF/OWL ontology and knowledge graph for terminology, relationships, inference, and validation; use graph, keyword, optional vector, and SQL retrieval only where each is strongest. HyperCLOVA X Agents produce typed plans and grounded language, while application code owns routing, calculations, evidence checks, and final claim release.

**Tech Stack:** Proposed baseline pending Task 2 approval: Python 3.12, Pydantic v2, pytest, DuckDB, RDF/OWL in Turtle, RDFLib, pySHACL, and HyperCLOVA X Structured Outputs. Semantic embeddings and a separate vector or graph database are deferred until benchmark evidence shows they are needed and official competition rules confirm the allowed model.

## Global Constraints

- HyperCLOVA X is the only permitted language-model family.
- Preserve organizer-provided raw files unchanged and keep them out of Git.
- Treat 2026-07-11 as both the observation cutoff and, where the source supports it, the knowledge-availability cutoff. Preserve each fact's actual applicable date and use only records valid on or before the cutoff; also reject facts first published, made available, or revised after the cutoff. Do not relabel an older fact as if it were measured on 2026-07-11.
- Add data absent from the organizer masters only from an approved authoritative source, with publisher, source URL or document ID, applicable date, retrieval time, checksum, parser version, and license or usage note.
- Select external sources from approved question requirements, not from API availability. KRX, ECOS, and FRED are conditional candidates; do not implement a connector or collect a series that no approved question needs.
- Organizer data remains the evaluation baseline when an overlapping external field conflicts with it. Use external sources primarily for absent relations or fields and disclose unresolved conflicts.
- Commit only ingestion logic, schemas, ontology files, prompts, tests, and synthetic or explicitly approved sanitized fixtures.
- Keep exact lookup, filtering, sorting, ranking, aggregation, comparison checks, and financial calculations outside the language model.
- Treat ETF and ETN as different product types unless the question explicitly includes both.
- Do not infer missing fees, yields, returns, risk grades, saleability, eligibility, or tradability.
- Do not directly compare incompatible periods, meanings, units, currencies, tax bases, populations, or data dates.
- Every returned financial fact or calculated value must bind to a source table, product identifier, source field, unit, and applicable date.
- The competition interaction mode is one question followed by one answer. Never ask a follow-up question; apply an approved deterministic fallback and disclose its basis, return a bounded answer with limitations, or abstain when no defensible answer exists.
- The official external contract is public `GET /answer` with `question_id` and `question`, no authentication header, sequential requests, a 300-second timeout, and up to two retries after timeout or 5xx. The response is `application/json` with string-only `question_id`, `question`, `retrieved_context`, `think_trace`, and `answer`; see `docs/reference/official-evaluation-api.md`.
- Treat every evaluation request as stateless. Resolve multi-sentence context only inside the current `question`; never use `question_id` as a conversation key or depend on an earlier request.
- Interpret an unqualified `연간수익률` as trailing one-year historical cumulative return. Compute it from approved official inputs when possible; use CAGR only for a valid multi-year cumulative period; label bond YTM and other expected annual rates as economically different rather than silently equating them with historical return.
- Use KRW as the default comparison currency. For every currency conversion, use the official exchange-rate observation applicable on 2026-07-11, or the latest official observation on or before that date when no same-day observation exists, and disclose the rate type, actual observation date, source, and formula.
- Agents cannot invoke other Agents. A deterministic orchestrator is the only component that may route work, call tools, retry, or enforce deadlines.
- Permit at most one bounded repair of an invalid plan or answer draft.
- Do not expose hidden chain-of-thought. Store only a concise execution trace of intent, filters, tools, calculations, sources, and exclusion reasons.
- Server provisioning, public endpoints, TLS, deployment, and cloud operations are outside this plan and require a separate approved plan after the core passes Task 12.

---

## 1. Assumptions

- The approved product is an internal financial-product desk Copilot covering domestic bonds, domestic ETFs, overseas ETFs, and public funds.
- The approved top-level architecture is the conditional-parallel multi-agent graph in ADR-0004.
- The four existing field-reference documents are the current source for known schema semantics and data-quality hazards.
- The project supplements the organizer masters only where approved questions expose a material data gap. ETF constituent holdings are a mandatory additional dataset for the holdings questions; other external sources remain conditional on a mapped requirement.
- The transcript's main technical direction is treated as guidance: question-driven ontology, knowledge graph, entity resolution, business-rule validation, hybrid retrieval, and answer grounding.
- The explanation transcript ends before the detailed assignment briefing resumes, so exact hidden-test composition and scoring weights must not be invented.
- The first useful milestone is a correct offline core and benchmark, not fine-tuning, a graphical interface, or deployment.

## 2. Intended Outcome

At the end of this plan, a local request can travel through the following verified path:

```text
Natural-language question
→ typed intent and ambiguity decision
→ only the required product Specialists
→ deterministic structured filters and calculations
→ ontology-guided graph, keyword, and optional semantic retrieval
→ comparison, missingness, and evidence verification
→ grounded answer with source bindings and visible limitations
```

The same validated question and data version must produce the same products, calculations, exclusions, and evidence references.

## 3. Non-Goals

- Public server, cloud account, network, HTTPS, container hosting, monitoring, or competition endpoint work.
- Personalized suitability advice, portfolio allocation, order execution, or definitive investment recommendations.
- Live market-data replacement of the organizer snapshot.
- Connecting or preloading official APIs merely because they are available, without a mapped evaluation question and unresolved organizer-data gap.
- Building a large ontology before the evaluation questions prove the concepts are needed.
- Fine-tuning HyperCLOVA X before retrieval, schemas, prompts, and deterministic validation have measurable baselines.
- Adding a separate graph database or vector database merely to demonstrate more infrastructure.
- Storing raw model reasoning, organizer workbooks, generated indexes, local databases, credentials, or model caches in Git.

## 4. Verifiable Success Criteria

- A reviewed gold set covers exact lookup, compound filtering, ranking, aggregation, cross-family comparison, family-specific product similarity, explanation, ambiguity, missing data, and unsupported requests.
- Every gold question maps to required concepts, source fields, business rules, expected routing, and expected answer or refusal behavior.
- The catalog contains at least 30 distinct question archetypes rather than repeated phrasings of a few operations, plus context, missingness, and safety edge cases.
- Every required external fact maps to an approved question, an unresolved organizer-data gap, an authoritative-source category, and both observation and knowledge-availability cutoff rules before ingestion begins.
- Synthetic ingestion fixtures reproduce the four masters' important hazards, including ETF/ETN mixing, stale or missing dates, placeholder values, and public-fund duplicate rows.
- Repeated deterministic queries against the same data version return byte-equivalent normalized results and calculation inputs.
- Ontology tests prove the required class hierarchy, inverse relations, synonym normalization, disjoint classes, and selected business constraints.
- Entity resolution links product aliases and document references without silently merging distinct products or public-fund share classes.
- Multi-sentence requests resolve phrases such as `이 상품`, `그 운용사`, and `위 상품들` to a unique earlier entity or intermediate result; genuinely ambiguous references use the approved single-turn fallback without guessing one candidate.
- Vector-only retrieval is not the sole source for any structured fact or numeric condition.
- Every final factual claim has a valid evidence ID; an unsupported claim cannot pass the Claim Gate.
- Incompatible comparisons are separated, explicitly normalized through an approved method, answered with a stated limitation, or rejected.
- Router tests invoke every required Specialist and no irrelevant Specialist for the gold set.
- Cross-family independent work is observably concurrent.
- The hybrid system is compared against SQL-only, text-only, and one-Agent baselines using the same benchmark.
- Core acceptance tests pass before any server or deployment work begins.

## 5. Material Alternatives and Recommended Direction

These choices are proposals, not silent implementation decisions. Task 2 records the selected options in ADRs and requires explicit user approval before code is created.

### 5.1 Orchestration

| Option | Benefit | Cost or risk | Recommendation |
| --- | --- | --- | --- |
| Custom typed async state machine | Small dependency surface; directly enforces ADR-0004; easy to test exact routing | More application code to own | Recommended for the competition core |
| Agent framework | Faster visual graph assembly and built-in integrations | Framework behavior can obscure retries, state, and latency | Use only if a short spike proves a measurable advantage |
| One general Agent with tool access | Lowest initial code volume | Conflicts with approved conditional Specialist architecture and enlarges the failure domain | Reject |

### 5.2 Structured and graph storage

| Option | Benefit | Cost or risk | Recommendation |
| --- | --- | --- | --- |
| DuckDB plus versioned Turtle ontology and materialized edge tables | Deterministic SQL, local reproducibility, minimal operations, ontology remains inspectable | Advanced graph traversal must be implemented or expressed recursively | Recommended initial baseline |
| Separate graph database | Native path queries and graph tooling | Additional operations and consistency surface before graph value is proven | Reconsider only after graph benchmark failure |
| Vector database as primary store | Convenient semantic retrieval | Weak for exact filters, calculations, comparability, and auditability | Reject as primary store |

### 5.3 Ontology scope

| Option | Benefit | Cost or risk | Recommendation |
| --- | --- | --- | --- |
| Competency-question-driven MVP | Every class and relation traces to an evaluated question | Requires disciplined iteration | Recommended |
| Model the entire financial domain first | Broad conceptual coverage | Slow, expensive, and likely to model unused distinctions | Reject for initial scope |

### 5.4 Semantic retrieval and fine-tuning

- Implement exact lookup, SQL, graph traversal, and keyword retrieval first.
- Add embeddings only when a named benchmark failure requires semantic matching of narrative fields and the allowed embedding model is confirmed.
- Consider fine-tuning only after Task 11 error analysis shows a persistent model-behavior failure that cannot be corrected by contracts, retrieval, prompt examples, or deterministic validation.

## 6. Planned File Structure

The paths below are the proposed ownership boundaries after Task 2 approval.

```text
pyproject.toml
ontology/
  financial-products.ttl
  financial-product-shapes.ttl
config/
  field-mappings/
    domestic-bond.json
    domestic-etf.json
    overseas-etf.json
    public-fund.json
  synonyms.json
prompts/
  intent-planner.md
  domestic-bond-specialist.md
  domestic-etf-specialist.md
  overseas-etf-specialist.md
  public-fund-specialist.md
  answer-synthesizer.md
src/financial_agent/
  contracts/
    query.py
    execution.py
    evidence.py
    ontology.py
    evaluation.py
  data/
    catalog.py
    missingness.py
    ingest.py
    adapters/
      domestic_bond.py
      domestic_etf.py
      overseas_etf.py
      public_fund.py
  ontology/
    loader.py
    validator.py
    materialize.py
  retrieval/
    sql_engine.py
    graph_engine.py
    keyword_index.py
    semantic_index.py
    router.py
    fusion.py
  agents/
    client.py
    planner.py
    specialists.py
    synthesizer.py
  orchestration/
    state.py
    orchestrator.py
  verification/
    comparability.py
    evidence.py
    policy.py
    claim_gate.py
  evaluation/
    runner.py
    metrics.py
tests/
  contracts/
  data/
  ontology/
  retrieval/
  orchestration/
  verification/
  evaluation/
  fixtures/
  gold/
    core_questions.json
```

Each file has one primary responsibility. `semantic_index.py` remains a disabled adapter until Task 8's benchmark gate authorizes embeddings.

---

### Task 1: Define the questions before defining the ontology

**Why this is first:** The ontology and retrieval plan must be derived from the questions the Agent needs to answer. Starting from database or model setup would hide missing financial semantics until late in the project.

**Files:**

- Create: `docs/planning/specs/core-evaluation-set.md`
- Create: `docs/planning/specs/authoritative-data-requirements.md`
- Create: `docs/planning/specs/official-api-source-matrix.md`
- Create: `tests/gold/core_questions.json`
- Reference: `docs/reference/domestic-bond-master.md`
- Reference: `docs/reference/domestic-etf-master.md`
- Reference: `docs/reference/overseas-etf-master.md`
- Reference: `docs/reference/public-fund-master.md`
- Reference: `docs/reference/official-evaluation-api.md`

**Produces:** A reviewed question catalog in which each case has `id`, `archetype`, `category`, `question`, `segments`, `intent`, `subtasks`, `dependencies`, `product_families`, `required_fields`, `required_relations`, `data_requirements`, `business_rules`, `reference_resolution`, `similarity_basis`, an optional `similarity_policy_id`, `support_level`, `target_support_level`, `expected_route`, `expected_disposition`, `expected_evidence`, and `risk_note`. Also produces a question-to-data requirement matrix identifying organizer fields, missing external fields, authoritative-source criteria, observation and availability cutoff handling, and whether KRX·ECOS·FRED or another official file is actually needed.

- [x] **Step 1: Write the evaluation-case schema and acceptance rules**

Use this JSON shape for every machine-readable case:

```json
{
  "id": "CTX-DETF-001",
  "archetype": "provider_top_return_then_similarity",
  "category": "context_resolution",
  "question": "A운용사 ETF 중 1년 수익률이 가장 높은 상품을 알려줘. 이 상품과 비슷한 ETF도 보여줘.",
  "segments": [
    {"id": "s1", "text": "A운용사 ETF 중 1년 수익률이 가장 높은 상품을 알려줘."},
    {"id": "s2", "text": "이 상품과 비슷한 ETF도 보여줘."}
  ],
  "intent": "dependent_multi_step",
  "subtasks": ["filter_by_provider", "rank_by_1y_return", "find_similar_products"],
  "dependencies": [{"from": "s1.top_product", "to": "s2.reference:this_product"}],
  "product_families": ["domestic_etf"],
  "required_fields": ["cu_fund_mgmt_co", "pd_grp_no", "du_er_1y", "du_upt_dt", "wu_inv_ast_type", "wu_inv_rgn", "cu_strtegy", "cu_lev_fector"],
  "required_relations": ["managedBy", "hasReturnMetric", "investsInAssetClass", "investsInRegion", "hasStrategy", "holdsSecurity"],
  "data_requirements": [
    {"name": "domestic_etf_master", "provenance": "organizer", "status": "available", "cutoff": "2026-07-11"},
    {"name": "official_etf_holdings_snapshot", "provenance": "authoritative_external", "status": "mandatory_for_full_similarity", "cutoff": "2026-07-11"}
  ],
  "business_rules": ["ETF_ONLY", "NON_MISSING_RETURN", "SAME_PERIOD", "EXCLUDE_RETURN_SENTINEL", "FAMILY_SPECIFIC_HARD_FILTERS", "MIN_SCORE_COVERAGE_60_PCT", "DISCLOSE_SIMILARITY_BASIS"],
  "reference_resolution": [{"mention": "이 상품", "binds_to": "s1.top_product", "expected": "resolved"}],
  "similarity_basis": ["product_type", "leverage_inverse_profile", "asset_type", "investment_region", "strategy_or_base_index", "weighted_holdings_overlap", "risk_grade", "other_structure"],
  "similarity_policy_id": "domestic_etf_similarity_v1",
  "support_level": "supported_with_limitation",
  "target_support_level": "supported",
  "expected_route": ["domestic_etf"],
  "expected_disposition": "answer",
  "expected_evidence": ["table", "product_id", "field", "unit", "as_of", "similarity_policy_id", "similarity_score", "score_coverage", "dimension_scores"],
  "risk_note": "최고 과거수익률과 유사성은 투자 추천이 아니며, 유사성 기준을 답변에 밝힌다."
}
```

- [x] **Step 2: Write at least four cases for each required behavior**

Define at least 30 genuinely different question archetypes, then add at least 10 context, missingness, incompatibility, and safety edge cases. The first tracked set therefore contains at least 40 total cases without counting simple wording variations as different archetypes.

Cover these ten capability groups:

1. exact product lookup;
2. compound filtering;
3. within-family sorting and ranking;
4. deterministic calculation or aggregation;
5. cross-family comparison;
6. multi-hop relationship search;
7. multi-sentence context and reference resolution;
8. missing or incompatible data;
9. ambiguous question requiring a deterministic single-turn fallback, limitation, or abstention;
10. unsupported forecast or personalized recommendation requiring limitation or abstention.

- [x] **Step 3: Include known data traps in the gold set**

Include cases for domestic and overseas ETF/ETN separation, domestic ETF trade-stop semantics, overseas ETF NAV and price date mismatch, bond buyable quantity, missing bond credit grade, public-fund `itm_no` deduplication, representative-fund grouping, placeholder index text, currency mismatch, absent metric dates, and a constituent-holding request that the current four masters cannot support.

For the holding example `삼성전자가 들어간 ETF를 AUM 순으로 5개`, require the relation `ETF → holdsSecurity → Security` and `du_last_aum`. Mark its current `support_level` as `requires_additional_data` and its `target_support_level` as `supported`. ETF holdings are a mandatory source gap to close. The Agent must not infer holdings from product names or strategy text.

The holdings source must provide, at minimum, ETF product identity, constituent security identity, constituent name, holding weight or quantity, applicable date, publisher, source document or URL, and retrieval checksum. Use the latest official holding snapshot valid on or before 2026-07-11 and preserve its actual applicable date.

- [x] **Step 4: Derive competency questions for the ontology**

For every multi-hop or terminology case, write the relation path the ontology must support, for example:

```text
ETF → tracksIndex → Index
ETF → managedBy → AssetManager
ETF → holdsSecurity → Security → subsidiaryOf → Company
PublicFundShareClass → belongsToRepresentativeFund → RepresentativeFund
```

Do not add a relation unless at least one competency question or validation rule uses it.

For dependent multi-step questions, also record the execution dependency graph. Later clauses may bind to a named entity from the question or to an intermediate result such as `s1.top_product`; the latter cannot be retrieved or ranked before the earlier subtask completes.

- [x] **Step 5: Review the cases manually against the four field references**

Confirm that every organizer `required_fields` value exists and its stated meaning matches the reference. For each absent relation or field, add a row to `authoritative-data-requirements.md` with the question archetypes it enables, required schema, acceptable publisher class, cutoff logic, conflict policy, and evidence fields. Record conditional source candidates in `official-api-source-matrix.md`, but do not select an API that no approved question needs. Set `support_level` to `supported`, `supported_with_limitation`, `requires_additional_data`, or `unsupported`, and record the desired final `target_support_level` separately.

- [x] **Step 6: Validate the catalog structure**

Run:

```bash
python3 -m json.tool tests/gold/core_questions.json >/dev/null
rg -n 'DET-|answer|limitation|abstention|domestic_bond|domestic_etf|overseas_etf|public_fund' docs/planning/specs/core-evaluation-set.md tests/gold/core_questions.json
```

Expected: valid JSON; all four product families and answer, limitation, and abstention dispositions appear, while no case asks a follow-up question; at least 40 unique case IDs and 30 unique archetypes are present; the catalog contains both resolved and ambiguous reference cases; every external data requirement uses cutoff `2026-07-11`.

- [x] **Step 7: Commit the independent deliverable**

```bash
git add docs/planning/specs/core-evaluation-set.md docs/planning/specs/authoritative-data-requirements.md docs/planning/specs/official-api-source-matrix.md tests/gold/core_questions.json docs/planning/tasks/2026-08-10-financial-agent-core-implementation-plan.md
git diff --cached --check
git commit -m "test: define financial agent core evaluation set"
```

**Completion gate:** Satisfied on 2026-08-11. The user approved the question coverage and additional-data priority. Task 2 remains a separate decision checkpoint before implementation files are created.

**Task 1 approval record:**

- 45 unique question archetypes cover the four organizer product families, compound and dependent multi-step questions, multi-sentence reference resolution, family-specific similarity, missingness, incompatible comparisons, and unsupported requests.
- ETF holdings and weights, canonical product/security/institution identities, comparable dated performance inputs, index/strategy/classification data, fund class structure, bond ratings and terms, fees and distributions, conditional FX, official product documents, and full provenance are the approved additional-data requirements.
- External data is selected from question requirements rather than API availability. KRX, ECOS, and FRED remain conditional candidates and are not mandatory integrations.
- The evaluation snapshot permits only facts applicable on or before 2026-07-11 and, where verifiable, published, available, and vintaged on or before that cutoff.
- The tracked gold set contains behavioral expectations and source requirements only; organizer rows and externally collected raw snapshots remain untracked.

---

### Task 2: Approve the minimum implementation foundation

**Files:**

- Create: `docs/planning/decisions/ADR-0005-core-implementation-foundation.md`
- Create: `docs/planning/decisions/ADR-0006-question-driven-ontology-and-hybrid-retrieval.md`
- Create: `docs/planning/decisions/ADR-0007-authoritative-external-data-snapshot.md`
- Create: `docs/planning/decisions/ADR-0008-single-turn-fallback-and-financial-normalization.md`
- Create: `docs/planning/decisions/ADR-0009-family-specific-product-similarity.md`
- Modify: `docs/planning/HARNESS.md`
- Modify: `docs/planning/architecture/MULTI_AGENT_ARCHITECTURE.md`

**Produces:** Explicit, approved choices for the language/runtime, contract library, deterministic store, ontology representation, graph materialization, retrieval stages, embedding gate, authoritative-source hierarchy, 2026-07-11 cutoff policy, conflict handling, single-turn fallback behavior, annual-return normalization, FX conversion, and family-specific product-similarity policies.

- [ ] **Step 1: Time-box proof spikes to the decisions that can invalidate the plan**

Measure only these questions with synthetic data:

- Can DuckDB express the required exact filters, rankings, deduplication, provenance columns, and recursive graph paths?
- Can RDFLib load the proposed Turtle ontology and can pySHACL reject representative invalid triples?
- Can the selected HyperCLOVA X endpoint return the minimum `QueryPlan` schema reliably through Structured Outputs?

Record commands, versions, elapsed time, and pass/fail results in the ADR evidence sections. Do not keep spike code unless it becomes the tested implementation.

- [ ] **Step 2: Record the recommended foundation in ADR-0005**

The recommended choice is Python 3.12, Pydantic v2 contracts, pytest, a custom async orchestrator, and DuckDB for the deterministic store. Reject a general Agent framework unless the spike shows a specific routing, reliability, or latency benefit.

- [ ] **Step 3: Record the ontology and retrieval choice in ADR-0006**

The recommended choice is a competency-question-driven RDF/OWL ontology in Turtle, SHACL validation, RDFLib tooling, and graph edges materialized into deterministic tables. Retrieval order is exact/SQL and graph first, keyword for narrative fields, embeddings only behind a benchmark and rules gate.

- [ ] **Step 4: Obtain explicit user approval**

Present ADR-0005 and ADR-0006 with measured trade-offs. Present ADR-0007 with the exact approved source registry, the question IDs that justify each active source, deferred candidates, cutoff policy, and conflict rules. KRX·ECOS·FRED must remain optional until a mapped requirement activates them. Present ADR-0008 as a competition-mode exception to any earlier clarification path: it must record the no-follow-up rule, fallback precedence, historical-versus-expected return distinction, KRW comparison default, official FX cutoff, and disclosure requirements. Present ADR-0009 with the family-specific hard filters, initial weights, weighted ETF holdings-overlap formula, 60% score-coverage gate, stable tie-breakers, and evidence requirements. Do not create `src/`, `pyproject.toml`, ontology implementation files, prompts, or external-source ingestion code before approval.

- [ ] **Step 5: Commit the approved decisions**

```bash
git add docs/planning/HARNESS.md docs/planning/architecture/MULTI_AGENT_ARCHITECTURE.md docs/planning/decisions/ADR-0005-core-implementation-foundation.md docs/planning/decisions/ADR-0006-question-driven-ontology-and-hybrid-retrieval.md docs/planning/decisions/ADR-0007-authoritative-external-data-snapshot.md docs/planning/decisions/ADR-0008-single-turn-fallback-and-financial-normalization.md docs/planning/decisions/ADR-0009-family-specific-product-similarity.md
git diff --cached --check
git commit -m "docs: choose core financial agent foundation"
```

**Completion gate:** All five ADRs are accepted. ADR-0008 explicitly supersedes earlier clarification behavior only for the competition's single-question/single-answer mode; all other accepted constraints remain intact.

---

### Task 3: Bootstrap the package and typed contracts

**Files:**

- Create: `pyproject.toml`
- Create: `src/financial_agent/__init__.py`
- Create: `src/financial_agent/contracts/query.py`
- Create: `src/financial_agent/contracts/execution.py`
- Create: `src/financial_agent/contracts/evidence.py`
- Create: `src/financial_agent/contracts/ontology.py`
- Create: `src/financial_agent/contracts/evaluation.py`
- Create: `tests/contracts/test_query.py`
- Create: `tests/contracts/test_execution.py`
- Create: `tests/contracts/test_evidence.py`
- Create: `tests/contracts/test_ontology.py`
- Create: `tests/contracts/test_evaluation.py`

**Interfaces:**

- `query.py` produces: `ProductFamily`, `QueryPlan`, `EntityContext`, `EntityResolution`, `RelationPath`, and `RetrievalStrategy`.
- `execution.py` produces: `DataVersion`, `DomainExecutionPlan`, `ToolResult`, `ComparisonDecision`, `SimilarityPolicy`, `SimilarityScore`, and `CoreRunResult`.
- `evidence.py` produces: `EvidenceRef`, `EvidenceBundle`, `AnswerDraft`, `VerificationReport`, and `ReleasedAnswer`.
- `ontology.py` produces: `OntologyValidationReport` and `GraphVersion`.
- `evaluation.py` produces: `EvaluationCase`, `SystemVariant`, and `BenchmarkReport`.
- Constraint: unknown fields, invalid enums, missing source bindings, and operations outside the allowlist fail validation.

- [ ] **Step 1: Write failing contract tests**

Tests must prove:

- every contract contains `schema_version`;
- unknown fields are rejected;
- `QueryPlan.product_families` uses only the four approved families;
- `DomainExecutionPlan.operation` uses an allowlist such as `lookup`, `filter`, `sort`, `top_k`, `group`, or `aggregate`;
- every numeric `EvidenceRef` includes table, product ID, source field, unit, and applicable date;
- an `AnswerDraft` factual claim cannot omit evidence IDs;
- ontology, retrieval, orchestration, release, and evaluation result types used by later tasks validate independently.

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```bash
pytest tests/contracts -q
```

Expected: collection fails because `financial_agent.contracts` does not exist.

- [ ] **Step 3: Implement the minimum strict contracts**

Use this shared configuration and preserve the field names across later tasks:

```python
from pydantic import BaseModel, ConfigDict

class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "1.0"
```

`QueryPlan` must contain the normalized intent, request segments, subtasks, dependency edges, resolved references, requested product families, filters, metrics, periods, units, currencies, operations, result limit, ambiguity decision, selected fallback and normalization decisions, and required Specialists. It must not contain or emit a follow-up question in competition mode. `EvidenceBundle` must contain only verified facts, calculations, exclusions, limitations, allowed conclusions, and evidence references.

- [ ] **Step 4: Run contract tests**

Run:

```bash
pytest tests/contracts -q
```

Expected: all contract tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/financial_agent tests/contracts
git diff --cached --check
git commit -m "feat: add strict financial agent contracts"
```

---

### Task 4: Design the minimum financial ontology and field mappings

**Files:**

- Create: `ontology/financial-products.ttl`
- Create: `ontology/financial-product-shapes.ttl`
- Create: `config/field-mappings/domestic-bond.json`
- Create: `config/field-mappings/domestic-etf.json`
- Create: `config/field-mappings/overseas-etf.json`
- Create: `config/field-mappings/public-fund.json`
- Create: `config/synonyms.json`
- Create: `src/financial_agent/ontology/loader.py`
- Create: `src/financial_agent/ontology/validator.py`
- Create: `tests/ontology/test_schema.py`
- Create: `tests/ontology/test_shapes.py`
- Create: `tests/ontology/test_competency_questions.py`

**Interfaces:**

- Produces: `load_ontology() -> rdflib.Graph` and `validate_graph(data_graph: Graph) -> OntologyValidationReport`.
- Consumes: competency questions from Task 1 and approved storage decision from Task 2.

- [ ] **Step 1: Write failing tests for the minimum vocabulary**

Require classes for `FinancialProduct`, `Bond`, `ExchangeTradedProduct`, `ETF`, `ETN`, `PublicFund`, `PublicFundShareClass`, `RepresentativeFund`, `Organization`, `AssetManager`, `Issuer`, `Index`, `Currency`, `Region`, `AssetClass`, `RiskGrade`, `FeeMetric`, `ReturnMetric`, and `AvailabilityStatus`.

Require relations used by the gold set, including `managedBy`, `issuedBy`, `tracksIndex`, `hasRiskGrade`, `hasFee`, `hasReturnMetric`, `hasCurrency`, `investsInRegion`, `investsInAssetClass`, `belongsToRepresentativeFund`, and explicitly justified inverse relations.

- [ ] **Step 2: Write failing constraint tests**

At minimum, prove:

- ETF and ETN are disjoint classes;
- a risk grade outside a family-specific allowed scale is rejected rather than invented;
- required identifiers are present for materialized product instances;
- a share class cannot be treated as the representative fund itself;
- source table, source field, and data version are required for extracted facts;
- missing data produces a validation issue or limitation rather than a synthetic value.

- [ ] **Step 3: Implement the Turtle ontology and SHACL shapes**

Keep the ontology small. Each class, property, synonym, inverse, and constraint must cite at least one competency question, field mapping, or business rule in an adjacent comment.

- [ ] **Step 4: Map all usable source fields to concepts without flattening distinct meanings**

Examples that must remain distinct:

- product currency versus trading currency;
- bond credit grade versus product risk grade;
- domestic listing versus domestic investment region;
- sale status versus trade-stop status versus pension eligibility;
- fund share class versus representative fund;
- file extraction date versus metric-specific applicable date.

- [ ] **Step 5: Add synonym normalization**

Map terms such as `운용사`, `자산운용사`, and `AMC` to the same ontology concept while retaining the original surface form in provenance. Keep issuer and asset manager distinct when the product structure requires it.

- [ ] **Step 6: Run ontology tests**

Run:

```bash
pytest tests/ontology -q
```

Expected: vocabulary, inverse inference, constraint, field-mapping, and competency-question tests pass.

- [ ] **Step 7: Commit**

```bash
git add ontology config src/financial_agent/ontology tests/ontology
git diff --cached --check
git commit -m "feat: add question-driven financial ontology"
```

---

### Task 5: Ingest and normalize organizer masters and approved authoritative sources safely

**Files:**

- Create: `src/financial_agent/data/catalog.py`
- Create: `src/financial_agent/data/missingness.py`
- Create: `src/financial_agent/data/ingest.py`
- Create: `src/financial_agent/data/source_registry.py`
- Create: `src/financial_agent/data/adapters/domestic_bond.py`
- Create: `src/financial_agent/data/adapters/domestic_etf.py`
- Create: `src/financial_agent/data/adapters/overseas_etf.py`
- Create: `src/financial_agent/data/adapters/public_fund.py`
- Create: `src/financial_agent/data/adapters/etf_holdings.py`
- Create: `src/financial_agent/data/adapters/institution_master.py`
- Create: `src/financial_agent/data/adapters/market_snapshot.py`
- Create: `tests/fixtures/domestic_bond.csv`
- Create: `tests/fixtures/domestic_etf.csv`
- Create: `tests/fixtures/overseas_etf.csv`
- Create: `tests/fixtures/public_fund.csv`
- Create: `tests/data/test_missingness.py`
- Create: `tests/data/test_ingest.py`
- Create: `tests/data/test_family_adapters.py`

**Interfaces:**

- Produces: `ingest_all(source_dir: Path, output_path: Path) -> DataVersion`.
- Produces immutable normalized tables, raw-value provenance, missingness classifications, entity aliases, and a content-derived data-version identifier.
- Consumes the approved field mappings from Task 4.
- Rejects an external record whose applicable date is after 2026-07-11. Where publication, availability, or vintage metadata exists, also rejects a record that was first knowable or revised after the cutoff; records the actual dates and availability status of every accepted record.

- [ ] **Step 1: Build synthetic fixtures that reproduce real hazards without copying organizer rows**

Fixtures must contain invented names and identifiers while covering physical nulls, blank strings, textual `NULL`, zero, `-100`, `99991231`, placeholder sentences, stale dates, ETF/ETN mixing, trade-stop values, unavailable NAV, duplicate fund attribute rows, and invalid representative-fund sentinels.

- [ ] **Step 2: Write failing missingness tests**

Use an explicit enum such as:

```python
class MissingKind(str, Enum):
    PRESENT = "present"
    PHYSICAL_NULL = "physical_null"
    BLANK = "blank"
    PLACEHOLDER = "placeholder"
    SENTINEL = "sentinel"
    STRUCTURALLY_INAPPLICABLE = "structurally_inapplicable"
    STALE_OR_UNDATED = "stale_or_undated"
```

Tests must prove that legitimate numeric zero remains different from missing, placeholder, and structurally inapplicable values.

- [ ] **Step 3: Write failing family-adapter tests**

Prove the following behaviors:

- domestic and overseas ETF queries exclude ETNs by default;
- domestic ETF `pd_tr_yn = '1'` is trade-stopped, not tradeable;
- overseas ETF NAV and market price are not combined when their dates differ;
- bond `BUYABLE_QUANTITY` remains different from issue balance;
- public-fund analysis deduplicates by `itm_no` before ranking returns;
- public-fund representative groups with invalid sentinel IDs are not merged.

- [ ] **Step 4: Implement the minimum adapters and immutable catalog**

Retain the original field name and raw value beside every normalized value. Reject a source whose expected columns, key uniqueness, or supported data types do not match the approved mapping.

For external sources, implement only adapters activated by approved question requirements. Validate publisher and source identity against ADR-0007, persist retrieval and content hashes, keep the raw snapshot untracked, and prevent an external value from silently overwriting an overlapping organizer field. If an API exposes only a current revised value and the cutoff-time vintage cannot be established, mark it unavailable for strict historical answers instead of accepting it.

- [ ] **Step 5: Run synthetic ingestion tests**

Run:

```bash
pytest tests/data -q
```

Expected: all synthetic hazard cases pass.

- [ ] **Step 6: Run a local-only integration audit against the organizer files**

The audit may read local workbooks but must write the database, logs, and reports only under ignored local paths. Verify source row counts, key uniqueness, normalized missingness counts, data-version hash, and rejection counts. Do not stage the inputs or outputs.

- [ ] **Step 7: Audit repository safety and commit**

```bash
git status --short --ignored
git add src/financial_agent/data tests/data tests/fixtures
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: normalize financial product masters"
```

Expected: no file under `data/`, no organizer workbook, no PDF, and no generated database or log is staged.

---

### Task 6: Build the deterministic SQL baseline and evidence ledger

**Files:**

- Create: `src/financial_agent/retrieval/sql_engine.py`
- Create: `config/similarity-policies.json`
- Create: `src/financial_agent/retrieval/similarity.py`
- Create: `src/financial_agent/verification/comparability.py`
- Create: `src/financial_agent/verification/return_normalizer.py`
- Create: `src/financial_agent/verification/currency.py`
- Create: `src/financial_agent/verification/evidence.py`
- Create: `tests/retrieval/test_sql_engine.py`
- Create: `tests/retrieval/test_similarity.py`
- Create: `tests/verification/test_comparability.py`
- Create: `tests/verification/test_return_normalizer.py`
- Create: `tests/verification/test_currency.py`
- Create: `tests/verification/test_evidence.py`

**Interfaces:**

- Produces: `execute(plan: DomainExecutionPlan, data_version: str) -> ToolResult`.
- Produces: `rank_similar(anchor_id: str, candidate_ids: tuple[str, ...], policy_id: str, data_version: str) -> ToolResult`.
- Produces: `check_comparability(results: tuple[ToolResult, ...]) -> ComparisonDecision`.
- Produces: `normalize_return(metric: ReturnMetric, inputs: tuple[EvidenceRef, ...]) -> NormalizedReturnDecision`.
- Produces: `convert_currency(value: Money, target: Currency, cutoff: date) -> CurrencyConversion`.
- Produces: `build_evidence(result: ToolResult) -> tuple[EvidenceRef, ...]`.
- Constraint: no model-written SQL is executed directly. Every field and operation comes from an allowlisted, validated plan.

- [ ] **Step 1: Write failing tests from deterministic gold cases**

Cover exact lookup, multi-filter intersection, stable sorting with an explicit tie-breaker, Top-K, date filtering, grouping, aggregation, fund deduplication, missing-value exclusion, sale or availability checks, and reproducible calculation inputs.

Add family-specific similarity tests for domestic and overseas ETF, public fund, and domestic bond. Prove that hard-filter failures cannot rank, ETF holdings overlap uses the registered weighted formula, missing axes are not treated as matches, score coverage below 60% yields a limitation, ties use coverage then canonical product ID, and every result exposes dimension-level evidence and the policy version.

- [ ] **Step 2: Write failing comparison tests**

Reject or separate results when period, definition, unit, currency, tax basis, population, or applicable date differs. Allow normalization only when the method and source are both explicitly registered.

Add return-policy tests proving that unqualified annual return defaults to trailing one-year historical cumulative return, valid official inputs can reproduce that value, multi-year cumulative return uses the CAGR formula only with a known complete period, and bond YTM remains an expected annual-rate metric with a visible semantic limitation. Add FX tests proving that the target currency defaults to KRW, no observation after 2026-07-11 is used, a missing same-day observation falls back only to the latest official prior observation, and the actual FX date and formula remain in evidence.

- [ ] **Step 3: Write failing evidence tests**

Every returned value must map to an existing table, product ID, raw field, normalized field, unit, applicable date, data version, applied filters, and calculation formula when relevant. Every excluded named product must carry a reason code.

- [ ] **Step 4: Implement the allowlisted SQL compiler and execution engine**

Compile only the typed `DomainExecutionPlan`. Parameterize values, reject unregistered fields, stabilize ordering, and include query-plan and result hashes in `ToolResult`.

- [ ] **Step 5: Run baseline tests twice**

Run:

```bash
pytest tests/retrieval/test_sql_engine.py tests/retrieval/test_similarity.py tests/verification/test_comparability.py tests/verification/test_return_normalizer.py tests/verification/test_currency.py tests/verification/test_evidence.py -q
pytest tests/retrieval/test_sql_engine.py tests/retrieval/test_similarity.py tests/verification/test_comparability.py tests/verification/test_return_normalizer.py tests/verification/test_currency.py tests/verification/test_evidence.py -q
```

Expected: both runs pass with identical golden result hashes.

- [ ] **Step 6: Commit**

```bash
git add config/similarity-policies.json src/financial_agent/retrieval/sql_engine.py src/financial_agent/retrieval/similarity.py src/financial_agent/verification tests/retrieval/test_sql_engine.py tests/retrieval/test_similarity.py tests/verification
git diff --cached --check
git commit -m "feat: add deterministic product query engine"
```

**Completion gate:** Exact structured questions and calculations must be correct before graph or vector retrieval can participate in answers.

---

### Task 7: Materialize the knowledge graph and resolve entities

**Files:**

- Create: `src/financial_agent/ontology/materialize.py`
- Create: `src/financial_agent/retrieval/graph_engine.py`
- Create: `tests/ontology/test_materialize.py`
- Create: `tests/retrieval/test_graph_engine.py`
- Create: `tests/retrieval/test_entity_resolution.py`

**Interfaces:**

- Produces: `materialize_graph(data_version: str) -> GraphVersion`.
- Produces: `resolve_entity(text: str, context: EntityContext) -> EntityResolution`.
- Produces: `traverse(start_ids: tuple[str, ...], path: RelationPath) -> ToolResult`.
- Constraint: inferred edges retain the ontology rule and source edges that justified them.

- [ ] **Step 1: Write failing entity-resolution tests**

Cover canonical product names, abbreviations, tickers, ISINs, alternate company names, spacing variants, and Korean/English aliases. Require explicit ambiguity when two products share a plausible alias. Do not merge public-fund share classes solely because their names are similar.

- [ ] **Step 2: Write failing graph-materialization tests**

Prove that validated rows become source-bound triples, invalid triples are quarantined, inverse relations retain derivation records, and repeated materialization against the same data version produces the same graph hash.

- [ ] **Step 3: Write failing multi-hop retrieval tests**

Use synthetic paths from Task 1. A graph result must return the complete path, every source edge, the inference rule used, and the final product IDs.

- [ ] **Step 4: Implement deterministic entity resolution**

Resolve strong identifiers before fuzzy names in this order:

```text
canonical product ID → ISIN/ticker when valid → exact normalized name
→ approved alias dictionary → bounded fuzzy candidate requiring ambiguity handling
```

For unstructured documents, propagate the parent product identity into each chunk when the document source establishes it. Pronouns such as `이 ETF` must not be resolved without parent-document context.

- [ ] **Step 5: Implement graph materialization and traversal**

Persist subject, predicate, object, source table, source product ID, source field, data version, derivation type, and derivation rule. Use ontology constraints before an edge becomes queryable.

- [ ] **Step 6: Run graph tests**

Run:

```bash
pytest tests/ontology/test_materialize.py tests/retrieval/test_graph_engine.py tests/retrieval/test_entity_resolution.py -q
```

Expected: entity ambiguity, invalid triple, inverse relation, and multi-hop provenance tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/financial_agent/ontology/materialize.py src/financial_agent/retrieval/graph_engine.py tests/ontology/test_materialize.py tests/retrieval/test_graph_engine.py tests/retrieval/test_entity_resolution.py
git diff --cached --check
git commit -m "feat: materialize grounded financial knowledge graph"
```

---

### Task 8: Add routed hybrid retrieval without weakening hard filters

**Files:**

- Create: `src/financial_agent/retrieval/keyword_index.py`
- Create: `src/financial_agent/retrieval/semantic_index.py`
- Create: `src/financial_agent/retrieval/router.py`
- Create: `src/financial_agent/retrieval/fusion.py`
- Create: `tests/retrieval/test_keyword_index.py`
- Create: `tests/retrieval/test_router.py`
- Create: `tests/retrieval/test_fusion.py`

**Interfaces:**

- Produces: `route_retrieval(plan: QueryPlan) -> RetrievalStrategy`.
- Produces: `fuse(results: tuple[ToolResult, ...], strategy: RetrievalStrategy) -> ToolResult`.
- Constraint: structured numeric and categorical conditions are hard predicates, not similarity-score suggestions.

- [ ] **Step 1: Write failing routing tests**

Require these behaviors:

- exact structured lookup uses SQL without keyword, graph, or semantic calls;
- relationship questions use graph traversal;
- narrative strategy or rationale questions may use keyword retrieval;
- mixed questions intersect hard SQL filters with graph and narrative candidates;
- semantic retrieval is unavailable unless explicitly enabled by an approved model and index version.

- [ ] **Step 2: Write failing fusion tests**

Prove that a high text-similarity score cannot reintroduce a product excluded by currency, sale status, product type, risk, date, or missingness rules. Each merged result must preserve source-specific scores and provenance.

- [ ] **Step 3: Implement keyword retrieval for approved narrative fields**

Index only fields named in the field mappings, such as a usable strategy description. Do not index placeholder sentences as content.

- [ ] **Step 4: Implement the retrieval router and deterministic fusion**

Use hard-filter intersection for mandatory conditions. Use rank fusion only among narrative candidate sources after hard constraints pass. Deduplicate by the correct family-specific product identity.

- [ ] **Step 5: Run the no-vector hybrid benchmark**

Compare SQL-only, keyword-only, graph-only, and routed hybrid retrieval on the same Task 1 cases. Record recall, exact condition satisfaction, evidence coverage, and latency.

- [ ] **Step 6: Apply the embedding gate**

Enable `semantic_index.py` only if:

1. the official rules confirm the selected embedding model is permitted;
2. named narrative cases still fail after entity resolution and keyword retrieval;
3. the semantic index improves those cases without reducing hard-condition accuracy or evidence coverage;
4. the index records model name, version, source field, source product ID, and data version.

- [ ] **Step 7: Run retrieval tests and commit**

```bash
pytest tests/retrieval -q
git add src/financial_agent/retrieval tests/retrieval
git diff --cached --check
git commit -m "feat: add ontology-routed hybrid retrieval"
```

---

### Task 9: Implement HyperCLOVA X planning, Specialists, and orchestration

**Files:**

- Create: `prompts/intent-planner.md`
- Create: `prompts/domestic-bond-specialist.md`
- Create: `prompts/domestic-etf-specialist.md`
- Create: `prompts/overseas-etf-specialist.md`
- Create: `prompts/public-fund-specialist.md`
- Create: `src/financial_agent/agents/client.py`
- Create: `src/financial_agent/agents/planner.py`
- Create: `src/financial_agent/agents/specialists.py`
- Create: `src/financial_agent/orchestration/state.py`
- Create: `src/financial_agent/orchestration/orchestrator.py`
- Create: `tests/orchestration/test_planner.py`
- Create: `tests/orchestration/test_routing.py`
- Create: `tests/orchestration/test_parallelism.py`
- Create: `tests/orchestration/test_failures.py`

**Interfaces:**

- Produces: `plan(question: str) -> QueryPlan`.
- Produces: `specialize(plan: QueryPlan, family: ProductFamily) -> DomainExecutionPlan`.
- Produces: `run_core(question: str, data_version: str) -> CoreRunResult`.
- Constraint: Structured Outputs creates typed plans; application code validates and dispatches them. The same model call does not combine Structured Outputs and Function calling.

- [ ] **Step 1: Write tests with a fake HyperCLOVA X client**

Cover valid plans, unknown fields, schema failure, critical ambiguity, unsupported operations, irrelevant Specialist requests, and one successful repair followed by a second failure.

- [ ] **Step 2: Write routing tests from the gold set**

Prove that exact domestic ETF questions invoke only the domestic ETF Specialist, bond-and-fund questions invoke exactly those two Specialists, and no question automatically fans out to all four.

- [ ] **Step 3: Write concurrency tests**

Use controlled fake delays and assert that independent Specialist and retrieval tasks overlap in elapsed time rather than execute sequentially.

- [ ] **Step 4: Implement the minimum HyperCLOVA X client boundary**

Keep credentials in environment variables, never logs or tracked configuration. Record model ID, prompt version, request ID, latency, token usage when available, schema-validation result, and repair count.

- [ ] **Step 5: Implement Planner and Specialist prompts**

Prompts may interpret intent and map concepts to allowlisted fields. They must not calculate, write SQL, select unapproved fields, fabricate missing values, or compose the final user answer.

- [ ] **Step 6: Implement the deterministic orchestrator**

The orchestrator owns state transitions, routing, concurrency, one repair attempt, deadlines, failure disposition, and the concise execution trace. Agents cannot call each other.

- [ ] **Step 7: Run orchestration tests**

Run:

```bash
pytest tests/orchestration -q
```

Expected: schema, routing, concurrency, repair-budget, and failure-disposition tests pass without live credentials.

- [ ] **Step 8: Run a small approved live-model evaluation**

Use a non-secret local environment and the fixed Task 1 subset. Compare parsed fields and routes against the gold plans. Save only aggregate metrics and sanitized failure categories in tracked documentation.

- [ ] **Step 9: Commit**

```bash
git add prompts src/financial_agent/agents src/financial_agent/orchestration tests/orchestration
git diff --cached --check
git commit -m "feat: orchestrate typed product specialists"
```

---

### Task 10: Verify evidence and release only grounded answers

**Files:**

- Create: `prompts/answer-synthesizer.md`
- Create: `src/financial_agent/agents/synthesizer.py`
- Create: `src/financial_agent/verification/policy.py`
- Create: `src/financial_agent/verification/claim_gate.py`
- Create: `tests/verification/test_policy.py`
- Create: `tests/verification/test_claim_gate.py`
- Create: `tests/verification/test_answer_paths.py`

**Interfaces:**

- Produces: `verify(bundle: EvidenceBundle) -> VerificationReport`.
- Produces: `synthesize(bundle: EvidenceBundle) -> AnswerDraft`.
- Produces: `release(draft: AnswerDraft, report: VerificationReport) -> ReleasedAnswer`.
- Constraint: the Synthesizer receives only the verified evidence bundle and cannot retrieve new facts.

- [ ] **Step 1: Write failing policy tests**

Reject unsupported forecasts, definitive recommendations, missing-data inference, undisclosed currency or period mismatch, claims that presence implies saleability, and explanations that introduce causal statements absent from the evidence.

- [ ] **Step 2: Write failing claim-gate tests**

Every factual sentence or structured table cell must bind to one or more evidence IDs. Reject missing IDs, IDs for excluded facts, incompatible comparison evidence, and calculations whose registered inputs do not reproduce the value.

- [ ] **Step 3: Write answer-path tests**

Cover four dispositions: verified answer, partial answer with explicit limitation, abstention, and controlled internal error. Also prove that competition mode never emits a follow-up clarification question. Each path must expose only the approved concise trace.

The concise trace must be serializable into the required `think_trace` string without exposing raw hidden reasoning. The verified evidence summary must be serializable into `retrieved_context`, while `answer` contains only the released answer.

- [ ] **Step 4: Implement deterministic verification before language generation**

Run source coverage, calculation reproduction, comparison compatibility, missingness, filter, exclusion, and policy checks before the Synthesizer is called.

- [ ] **Step 5: Implement evidence-bound synthesis and Claim Gate**

The answer format must include the result, material conditions, limitations, source summary, and applicable dates. Unsupported claims are removed only when the remaining answer is still complete; otherwise the orchestrator uses its single repair or returns a safe disposition.

- [ ] **Step 6: Run verification tests**

Run:

```bash
pytest tests/verification -q
```

Expected: no unsupported factual claim passes; all supported claims retain valid evidence bindings.

- [ ] **Step 7: Commit**

```bash
git add prompts/answer-synthesizer.md src/financial_agent/agents/synthesizer.py src/financial_agent/verification tests/verification
git diff --cached --check
git commit -m "feat: gate financial answers by evidence"
```

---

### Task 11: Measure the complete core and improve only proven gaps

**Files:**

- Create: `src/financial_agent/evaluation/runner.py`
- Create: `src/financial_agent/evaluation/metrics.py`
- Create: `tests/evaluation/test_metrics.py`
- Create: `docs/evaluation/core-baseline.md`
- Create: `docs/evaluation/error-taxonomy.md`
- Create: `tests/test_core_end_to_end.py`

**Interfaces:**

- Produces: `run_benchmark(cases: Sequence[EvaluationCase], variant: SystemVariant) -> BenchmarkReport`.
- Produces aggregate metrics without storing raw secrets, organizer rows, or hidden model reasoning.

- [ ] **Step 1: Define metric calculations in tests**

Calculate at least:

- intent and field extraction accuracy;
- route precision and recall;
- exact condition satisfaction;
- ranking and calculation exact match;
- entity-resolution accuracy and ambiguity rate;
- retrieval recall for required evidence;
- evidence coverage and unsupported-claim rate;
- deterministic fallback, limitation, and abstention correctness;
- p50, p95, and p99 latency by stage;
- model calls, token usage, repair count, and concurrency.

- [ ] **Step 2: Implement the benchmark runner**

The runner must execute the same cases against:

1. deterministic SQL baseline;
2. text-only retrieval baseline where applicable;
3. graph plus routed hybrid retrieval;
4. one-Agent baseline;
5. approved conditional-parallel multi-agent system.

- [ ] **Step 3: Run all offline tests**

Run:

```bash
pytest -q
```

Expected: all contract, ontology, data, retrieval, orchestration, verification, evaluation, and end-to-end tests pass.

- [ ] **Step 4: Run the fixed benchmark and write the baseline report**

Report per-case failures and aggregate metrics. Classify every failure as intent, field mapping, entity resolution, missingness, retrieval, calculation, comparison, evidence, policy, synthesis, latency, or provider failure.

- [ ] **Step 5: Improve one failure class at a time**

Apply changes in this order:

1. incorrect gold expectation or field meaning;
2. deterministic rule or data normalization;
3. ontology or entity mapping;
4. retrieval routing or fusion;
5. prompt examples or contract schema;
6. model fine-tuning only after the earlier causes are ruled out by measured evidence.

Every improvement must add or update a regression case before implementation.

- [ ] **Step 6: Compare architecture value**

The conditional multi-agent system must improve evaluated correctness, latency on cross-family work, evidence completeness, or failure isolation relative to the one-Agent baseline. Remove or bypass a stage that has no measurable benefit.

- [ ] **Step 7: Commit the verified benchmark tooling and sanitized reports**

```bash
git add src/financial_agent/evaluation tests/evaluation tests/test_core_end_to_end.py docs/evaluation
git diff --cached --check
git commit -m "test: benchmark financial agent core"
```

---

### Task 12: Core completion gate and deployment-plan handoff

**Files:**

- Create: `docs/evaluation/core-acceptance.md`
- Modify: `docs/planning/tasks/2026-08-10-financial-agent-core-implementation-plan.md`
- Future, separate plan only after approval: `docs/planning/tasks/2026-08-10-financial-agent-evaluation-api-deployment-plan.md`

- [ ] **Step 1: Run final verification**

```bash
pytest -q
git diff --check
git status --short --ignored
```

Expected: all tests pass; the diff has no whitespace errors; no raw data, organizer PDF, secrets, local databases, indexes, caches, logs, or generated outputs are staged.

- [ ] **Step 2: Inspect the complete core against the success criteria**

Record evidence for deterministic repeatability, ontology competency questions, entity resolution, hybrid retrieval, routing, concurrency, comparison blocking, evidence coverage, unsupported-claim rejection, and benchmark deltas.

- [ ] **Step 3: Mark this plan complete only when every core gate has evidence**

Do not mark completion because individual demonstrations look convincing or because a model produces fluent answers.

- [ ] **Step 4: Request approval for a separate server and deployment plan**

Only after core acceptance, plan implementation of the already-fixed official API contract, container, public endpoint, README End-point declaration, health checks, idempotent retry handling, 300-second deadline budget, evaluation-window operations, IP allowlisting after organizer notice, and freeze procedure. None of those implementation actions are authorized by this document.

- [ ] **Step 5: Commit the acceptance record**

```bash
git add docs/evaluation/core-acceptance.md docs/planning/tasks/2026-08-10-financial-agent-core-implementation-plan.md
git diff --cached --check
git commit -m "docs: record financial agent core acceptance"
```

---

## 7. Immediate Starting Order

The first work session should do only the following:

1. Create the Task 1 question catalog and 45-case gold set.
2. Review those cases against the four existing field references and the need-based source matrix.
3. Obtain approval of the competency-question coverage and the question-linked external-data priority.
4. Run the three small Task 2 proof spikes.
5. Present ADR-0005 through ADR-0009 for explicit approval.

Do not start fine-tuning, vector-database construction, a large ontology, Agent prompts, or server work during these first two tasks.

## 8. Plan Self-Review

- **Specification coverage:** Every transcript theme is assigned to a task: ontology and rules in Task 4, missingness and integrity in Task 5, deterministic filtering in Task 6, knowledge graph and entity resolution in Task 7, hybrid retrieval in Task 8, answer quality in Tasks 9 and 10, and measured iteration in Task 11.
- **Accepted-decision coverage:** ADR-0001 planning discipline, ADR-0002 data policy, ADR-0003 product scope, and ADR-0004 conditional-parallel orchestration are preserved.
- **Scope control:** Server, deployment, personalized advice, live data, speculative infrastructure, and premature fine-tuning remain excluded.
- **Type consistency:** Later tasks consume the exact contract and function names introduced by earlier tasks.
- **Data safety:** Every raw-data integration step writes only to ignored local paths and includes a staging audit.
- **Placeholder scan:** The plan contains no deferred content marker or unspecified implementation step.
