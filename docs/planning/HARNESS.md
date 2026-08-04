# Financial Product Analyst Planning Harness

**Status:** Approved project direction

**Last updated:** 2026-08-04

**Purpose:** Keep the project's `what` and `why` stable while allowing capable agents freedom over `how` within approved constraints.

## 1. Problem Definition

### Who

The project is first a competition submission. It must satisfy the organizer's quantitative and qualitative evaluation of a financial-product Agent over domestic bonds, domestic ETFs, overseas ETFs, and public funds.

The product is framed as an internal financial-product desk Copilot so that the same evaluated capabilities form a coherent real-world workflow for product analysts, product desks, and sales-support staff. This framing does not select one commercial persona as the primary user and does not authorize personalized investment advice.

### When

A user needs to find products under several simultaneous conditions, compare products within or across heterogeneous masters, calculate rankings or aggregates, explain the result, and retain evidence for the answer.

The complete job begins with an ambiguous natural-language request and ends only when the user has a usable candidate set, a valid comparison, a grounded explanation, and a reproducible record of how the result was produced.

### What they cannot do reliably today

They cannot easily:

- translate natural-language conditions into four different schemas;
- reconcile inconsistent metric meanings, units, currencies, and time horizons;
- distinguish a product that exists in a master from one that is currently saleable, tradable, or supported by sufficient data;
- distinguish real zeroes from missing values and placeholders;
- prevent duplicate or invalid aggregation across products and fund share classes;
- explain product facts and risks in plain language without adding unsupported claims; or
- retain an auditable record of sources, filters, calculations, exclusions, and unavailable information.

### What they give up

They inspect large spreadsheets and product documents manually, copy values between tools, narrow the question until it loses value, or accept an answer whose comparison, calculation, or evidence cannot be trusted.

The hidden cost is not only search time. It includes inconsistent answers between staff, repeated product-desk inquiries, unusable candidate lists, rework for compliance review, and exposure to unsupported or misleading explanations.

### What changes when the problem is solved

The user receives condition-matching and operationally relevant product candidates within a short interaction. The Agent validates whether requested metrics are comparable, performs supported calculations deterministically, explains limitations, and returns the exact source, product identifier, fields, units, data date, exclusions, and unavailable information behind the answer.

## 2. Approved Product Definition

The Financial Product Agent is an **internal financial-product desk Copilot** that turns natural-language questions into evidence-backed product screening, comparison, calculation, and explanation over the four organizer-provided product masters.

It is not primarily a conversational search box and is not an autonomous investment adviser. Its value comes from completing an end-to-end product-analysis workflow that a user can reproduce and defend.

### Core job flow

1. **Clarify the request.** Identify product families, conditions, metrics, comparison basis, and missing critical information.
2. **Screen candidates.** Apply exact product and operational-availability conditions to the relevant masters.
3. **Validate comparability.** Check period, meaning, unit, currency, and population before comparing or aggregating values.
4. **Calculate deterministically.** Perform filtering, sorting, ranking, aggregation, and supported financial calculations outside the language model.
5. **Explain with guardrails.** Present product facts, risks, and limitations without unsupported forecasts or definitive recommendations.
6. **Return an evidence packet.** Disclose sources, identifiers, fields, units, data date, calculations, exclusions, missing values, and concise execution steps.

## 3. Operational Pain Points

The following problems connect the competition task to a credible internal workflow. They are supported by the organizer brief and financial-product sales and explanation duties, but they are not presented as quantified user-research findings.

| Pain point | Operational consequence | Required product response |
| --- | --- | --- |
| Product facts are split across heterogeneous masters and supporting documents. | Users repeat searches, copy values manually, and produce inconsistent answers. | Translate one natural-language request into coordinated searches over the relevant product families. |
| Metrics that share a label may differ in period, currency, unit, tax basis, or meaning. | A plausible-looking table can contain an invalid comparison or ranking. | Block, normalize only with an approved method, or clearly disclose incompatible metrics. |
| A product's presence in a master does not guarantee that it is saleable, pension-eligible, purchasable, or sufficiently populated. | Search results include candidates that cannot be used for the stated task. | Apply available saleability, eligibility, tradability, and data-availability fields and disclose missing controls. |
| Staff must explain product structure, risk, cost, and limitations accurately. | Manual summaries vary by person and may omit material facts or add unsupported claims. | Generate plain-language, risk-aware explanations grounded only in available data. |
| Correct answers still require proof of how they were produced. | Compliance review, dispute response, and debugging require expensive reconstruction. | Attach reproducible filters, calculations, sources, exclusions, and data versions to every material result. |
| Missing values, placeholders, duplicate share classes, and stale snapshots can look valid. | Results silently misstate availability, rank, or totals. | Treat data quality and freshness as answer constraints rather than hidden preprocessing details. |
| Product knowledge is concentrated in specialists and repeatedly transferred to other staff. | Product desks answer similar questions and training quality varies. | Produce a consistent analysis and explanation format that specialists can inspect and reuse. |

### Evidence boundary

- The competition brief defines the evaluated data, query types, evidence rules, and risk controls.
- The [Financial Services Commission](https://www.fsc.go.kr/edu/news/84957) has identified incomplete suitability inputs, explanation focused on formal information transfer, and insufficiently detailed reasons in actual sales processes.
- The [Korea Financial Investment Association's standard investment-recommendation rules](https://law.kofia.or.kr/service/law/lawFullScreenContent.do?historySeq=1421&seq=149) require product-risk classification, risk and cost explanations, investor-understanding checks, and records supporting the sales process.
- Until direct interviews or official competition Q&A provide stronger evidence, competition alignment governs priority when a pain-point hypothesis and an evaluated requirement diverge.

## 4. Ordered Decision Criteria

1. **Competition alignment over persona-specific expansion.** Evaluated requirements and official guidance take priority over optimizing for one department, channel, or hypothetical paying user.
2. **Accuracy and evidence over answer coverage.** An explicit limitation is better than a plausible but unsupported financial answer.
3. **Deterministic execution over free-form model autonomy.** Filters, sorting, ranking, aggregation, and arithmetic must be reproducible and testable.
4. **Valid and usable comparisons over long candidate lists.** The Agent must prefer a smaller set with compatible metrics and disclosed availability over a larger but misleading result.
5. **Organizer data over external data.** The organizer-provided snapshot is the evaluation baseline and wins when sources conflict.
6. **Clarification or abstention over guessing.** Missing critical conditions or unavailable fields must produce a clarifying question or a clear inability statement.
7. **Operational simplicity over architectural novelty.** A small, observable, reproducible service is more valuable than additional frameworks that increase failure modes.

## 5. Hard Constraints

- HyperCLOVA X is the only permitted language-model family. Other embedding models are allowed only to the extent confirmed by official competition guidance.
- Every answer containing product facts or calculated values must identify its supporting data.
- Do not create unsupported return forecasts or definitive investment recommendations.
- Do not compare metrics across incompatible periods, meanings, units, currencies, or populations without an explicit normalization method and disclosed source.
- Do not present presence in a master as proof of saleability, eligibility, tradability, or current availability when the required field is absent or negative.
- Preserve raw organizer data unchanged and keep it out of the personal GitHub repository.
- The evaluation API must remain publicly reachable and reproducible for the required evaluation window.
- No code, data, or deployment changes may be pushed after the official submission freeze takes effect.
- Raw hidden model reasoning is not a project artifact. Expose a concise, structured execution trace containing intent, filters, tools, calculations, sources, and exclusion reasons.

## 6. Required Product Capabilities

These capabilities define the initial product behavior. They do not select an implementation architecture.

1. **Intent and ambiguity gate**
   - Parse product family, region, asset class, risk, fee, return, size, date, and requested operation when present.
   - Ask for a period, currency, risk basis, result count, or other critical condition when omission would materially change the result.

2. **Deterministic candidate screening and calculation**
   - Execute exact lookup, filtering, sorting, ranking, aggregation, and supported calculation through testable tools.
   - Return the same result for the same validated query plan and data version.

3. **Comparison-compatibility gate**
   - Validate period, definition, unit, currency, tax basis, and aggregation population.
   - Reject, separate, or explicitly normalize incompatible values rather than silently placing them in one ranking or total.

4. **Operational-relevance filtering**
   - Use available sale status, pension eligibility, bond purchase availability, and similar fields when relevant to the request.
   - State when the dataset cannot establish operational availability.

5. **Evidence and exclusion packet**
   - Identify source table, product identifier, source field, unit, snapshot date, applied filter, calculation, and material exclusion reason.
   - Explain why a named product was excluded or why a requested fact is unavailable.

6. **Missingness and data-quality handling**
   - Distinguish zero, blank, placeholder, unavailable, stale, and structurally inapplicable values.
   - Prevent invalid duplicate aggregation and disclose data-quality limitations that affect the result.

7. **Grounded, risk-aware explanation**
   - Explain supplied product data in plain language, including material limitations.
   - Treat a request to “recommend” as candidate screening under stated conditions unless an approved policy and required suitability inputs explicitly support more.

## 7. Competition Requirement Mapping

| Competition requirement | Required system behavior | Primary verification |
| --- | --- | --- |
| Condition-based product search and information lookup | Parse compound conditions and query the correct family-specific fields. | Curated lookup and multi-filter cases match deterministic expected results. |
| Product comparison and calculation | Validate comparison compatibility and run sorting, ranking, and aggregation outside the language model. | Gold query plans and calculations reproduce exactly. |
| Cross-product-family questions | Map only defensible common concepts and retain family-specific meaning. | Incompatible comparisons are blocked or disclosed in cross-family test cases. |
| Evidence-based explanations | Ground every material fact in returned source fields and the snapshot date. | Evidence completeness checks pass for every factual answer. |
| Hallucination prevention | Avoid inferred missing values, forecasts, and unsupported recommendations. | Adversarial unsupported questions follow abstention rules. |
| Conditional guidance | Ask a focused question when missing information materially changes the result. | Ambiguity cases select the expected clarification or safe default. |
| Workplace usefulness and risk management | Complete screening, validation, explanation, and evidence as one inspectable workflow. | End-to-end scenarios produce usable candidates plus evidence and limitations. |

## 8. In Scope

- Ingestion and validation of the four organizer-provided product masters.
- A common product-search axis plus product-family-specific detail fields.
- Natural-language intent and condition parsing.
- Exact lookup, filtering, comparison, ranking, aggregation, and supported calculation.
- Comparison-compatibility and operational-relevance checks.
- Evidence construction, exclusion reasons, data-date disclosure, clarification, abstention, and recommendation guardrails.
- Data-quality rules for missing values, placeholders, duplicate aggregation, and unavailable fields.
- A reproducible evaluation API, containerized runtime, tests, operational checks, and technical documentation.

## 9. Non-Goals for the Initial Competition Scope

- Live order execution or brokerage-account integration.
- Personalized suitability advice or portfolio allocation based on an investor profile.
- Unsupported price or return forecasting.
- Real-time market-data replacement of the organizer snapshot.
- A persona-specific authorization model or production user-interface suite.
- A general-purpose autonomous multi-agent platform.
- Uploading organizer-provided source files to a personal public or private repository without explicit permission.

## 10. Success Measures

- A supported query produces the same filtered products and calculations when repeated against the same data version.
- Every returned product fact can be traced to a table, product identifier, field, unit, and applicable date.
- Unsupported, ambiguous, or data-missing questions follow a tested clarification or abstention path.
- Cross-product comparisons exclude, separate, or disclose incompatible metrics instead of silently normalizing them.
- Operational conditions such as sale status, pension eligibility, or purchase availability are applied when supported and identified as unknown when not supported.
- Material exclusions, missing fields, and data-quality limitations that affect the conclusion are visible in the answer or evidence packet.
- The core evaluated query types have deterministic benchmark cases covering supported, ambiguous, incompatible, and unsupported variants.
- The service can be rebuilt from tracked source, dependency definitions, ingestion instructions, and approved fixtures without relying on untracked developer state.
- The submitted API contract remains stable and its deployment can be health-checked throughout the evaluation period.

## 11. Temporary Safe Defaults Until Official Clarification

These defaults prevent unsafe assumptions and may be superseded by a later accepted ADR after official Q&A:

- Treat `ETF` and `ETN` as different product types; an ETF-only query excludes ETNs unless the user explicitly includes them.
- Do not rank or aggregate AUM across currencies without an approved exchange-rate source and a disclosed conversion date.
- Do not aggregate public-fund AUM across share classes unless a verified representative-fund key prevents double counting.
- Treat placeholder descriptions such as “index not available” as semantically missing even when the cell is non-empty.
- Do not infer missing fees, yields, returns, risk grades, saleability, eligibility, or tradability from similar products.
- Interpret “recommend” as “show candidates satisfying stated conditions” unless suitability inputs and an approved policy explicitly support more.

## 12. Proposed Technical Direction, Not Yet an Accepted Decision

The current leading option is a SQL-first hybrid: immutable raw tables, a normalized common product registry, product-family detail tables, a validated query-plan schema, deterministic query tools, limited semantic retrieval for narrative fields, and HyperCLOVA X for intent parsing and grounded response composition.

This direction remains proposed until its architecture ADR is explicitly approved. Implementation must not treat it as final merely because it appears in this document.

## 13. Decision Records

Accepted and superseded decisions live in `docs/planning/decisions/`. Each record includes the date, status, chosen option, rejected alternatives, reasons, and consequences. Historical records are append-only.

- [ADR-0001: Use a Project-Local Planning Harness](decisions/ADR-0001-planning-harness.md)
- [ADR-0002: Keep Organizer Data Out of the Personal Repository](decisions/ADR-0002-repository-data-policy.md)
- [ADR-0003: Frame the Competition Entry as an Internal Product Desk Copilot](decisions/ADR-0003-internal-product-desk-copilot.md)

## 14. Change Procedure

1. Identify which problem statement, criterion, constraint, or accepted ADR the change affects.
2. Explain the new information and the trade-off it introduces.
3. Obtain explicit user approval.
4. Add a new ADR or revise this harness with a dated explanation.
5. Update affected task plans before implementation resumes.
