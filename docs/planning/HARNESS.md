# Financial Product Analyst Planning Harness

**Status:** Approved project direction

**Last updated:** 2026-08-12

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

The approved implementation direction is a purpose-built, conditional-parallel multi-agent graph. Architecture is a core competition differentiator: it must route only the necessary specialists, run independent work concurrently, constrain every handoff with typed contracts, and refuse answers that cannot pass deterministic evidence checks.

### Core job flow

1. **Resolve the request.** Identify product families, conditions, metrics, comparison basis, and missing critical information; in competition mode, apply an approved single-turn fallback rather than asking a follow-up question.
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
- The [official evaluation API specification](../reference/official-evaluation-api.md) defines the public `GET /answer` contract, sequential invocation, 300-second timeout, retry behavior, string-only JSON response, and stateless single-question interaction.
- The [Financial Services Commission](https://www.fsc.go.kr/edu/news/84957) has identified incomplete suitability inputs, explanation focused on formal information transfer, and insufficiently detailed reasons in actual sales processes.
- The [Korea Financial Investment Association's standard investment-recommendation rules](https://law.kofia.or.kr/service/law/lawFullScreenContent.do?historySeq=1421&seq=149) require product-risk classification, risk and cost explanations, investor-understanding checks, and records supporting the sales process.
- Until direct interviews or official competition Q&A provide stronger evidence, competition alignment governs priority when a pain-point hypothesis and an evaluated requirement diverge.

## 4. Ordered Decision Criteria

1. **Competition alignment over persona-specific expansion.** Evaluated requirements and official guidance take priority over optimizing for one department, channel, or hypothetical paying user.
2. **Accuracy and evidence over answer coverage.** An explicit limitation is better than a plausible but unsupported financial answer.
3. **Bounded multi-agent architecture over monolithic or unbounded autonomy.** A deterministic orchestrator must conditionally route typed work to specialized agents and prevent recursive, free-form delegation.
4. **Deterministic execution over model-generated arithmetic.** Filters, sorting, ranking, aggregation, and financial calculations must be reproducible and testable.
5. **Latency and error containment over agent count.** Invoke only the agents needed for the question, execute independent work in parallel, and bound retries and deadlines.
6. **Valid and usable comparisons over long candidate lists.** The Agent must prefer a smaller set with compatible metrics and disclosed availability over a larger but misleading result.
7. **Organizer data over external data.** The organizer-provided snapshot is the evaluation baseline and wins when sources conflict.
8. **Deterministic fallback or abstention over guessing.** Competition requests do not support a follow-up turn, so missing critical conditions must use an approved default, return bounded alternatives with limitations, or abstain.
9. **Observable execution over architectural novelty alone.** Every architectural component must improve evaluated correctness, latency, evidence, or failure handling and expose enough structured trace data to verify that improvement.

## 5. Hard Constraints

- HyperCLOVA X is the only permitted language-model family. Other embedding models are allowed only to the extent confirmed by official competition guidance.
- Every answer containing product facts or calculated values must identify its supporting data.
- Do not create unsupported return forecasts or definitive investment recommendations.
- Do not compare metrics across incompatible periods, meanings, units, currencies, or populations without an explicit normalization method and disclosed source.
- Do not present presence in a master as proof of saleability, eligibility, tradability, or current availability when the required field is absent or negative.
- Use a deterministic application orchestrator as the only component allowed to schedule agents, tools, retries, and deadlines. Agents must not recursively invoke other agents.
- Route only the product specialists required by the validated query plan and run independent specialist work concurrently.
- Pass typed, schema-validated state between components. Free-form agent prose must not become executable filters, calculations, or evidence.
- Generate final answer claims only from a verified evidence bundle. A claim without a valid source reference must be removed or cause abstention.
- Permit at most one bounded internal repair attempt for a failed plan or draft before returning a partial limitation or inability statement.
- Preserve raw organizer data unchanged and keep it out of the personal GitHub repository.
- The evaluation API must expose public `GET /answer`, accept `question_id` and `question` query parameters without an authentication header, and return `application/json` containing string values for `question_id`, `question`, `retrieved_context`, `think_trace`, and `answer`.
- Evaluation requests arrive one at a time, have a 300-second timeout, and may be retried up to twice after timeout or 5xx. Request handling must be idempotent and must not depend on earlier requests.
- The submitted End-point must be recorded in `README.md` and remain publicly reachable and reproducible for the required evaluation window.
- No code, data, or deployment changes may be pushed after the official submission freeze takes effect.
- Raw hidden model reasoning is not a project artifact. Populate the required `think_trace` string with a concise, structured execution trace containing intent, subtasks, filters, tools, calculations, sources, exclusions, and limitations.

## 6. Required Product Capabilities

These capabilities define the initial product behavior. They do not select an implementation architecture.

1. **Intent and ambiguity gate**
   - Parse product family, region, asset class, risk, fee, return, size, date, and requested operation when present.
   - In competition mode, resolve omitted conditions through approved defaults, bounded alternatives, explicit limitation, or abstention; never require a second user turn.

2. **Conditional routing and parallel specialist execution**
   - Route the validated intent only to relevant domestic-bond, domestic-ETF, overseas-ETF, and public-fund specialists.
   - Run independent specialist plans concurrently and skip unnecessary agents and comparison stages on the fast path.

3. **Deterministic candidate screening and calculation**
   - Execute exact lookup, filtering, sorting, ranking, aggregation, and supported calculation through testable tools.
   - Return the same result for the same validated query plan and data version.

4. **Comparison-compatibility gate**
   - Validate period, definition, unit, currency, tax basis, and aggregation population.
   - Reject, separate, or explicitly normalize incompatible values rather than silently placing them in one ranking or total.

5. **Operational-relevance filtering**
   - Use available sale status, pension eligibility, bond purchase availability, and similar fields when relevant to the request.
   - State when the dataset cannot establish operational availability.

6. **Evidence and exclusion packet**
   - Identify source table, product identifier, source field, unit, snapshot date, applied filter, calculation, and material exclusion reason.
   - Explain why a named product was excluded or why a requested fact is unavailable.

7. **Missingness and data-quality handling**
   - Distinguish zero, blank, placeholder, unavailable, stale, and structurally inapplicable values.
   - Prevent invalid duplicate aggregation and disclose data-quality limitations that affect the result.

8. **Independent evidence and policy verification**
   - Verify numeric results, source coverage, comparison compatibility, missingness, and prohibited claims before answer composition.
   - Allow one internal repair attempt and otherwise fail closed with a limitation, partial answer, or abstention.

9. **Grounded, risk-aware explanation**
   - Explain supplied product data in plain language, including material limitations.
   - Compose only from the verified evidence bundle and require every factual claim to reference evidence.
   - Treat a request to “recommend” as candidate screening under stated conditions unless an approved policy and required suitability inputs explicitly support more.

## 7. Competition Requirement Mapping

| Competition requirement | Required system behavior | Primary verification |
| --- | --- | --- |
| Condition-based product search and information lookup | Parse compound conditions and query the correct family-specific fields. | Curated lookup and multi-filter cases match deterministic expected results. |
| Product comparison and calculation | Validate comparison compatibility and run sorting, ranking, and aggregation outside the language model. | Gold query plans and calculations reproduce exactly. |
| Cross-product-family questions | Route only the needed product specialists in parallel, then map defensible common concepts while retaining family-specific meaning. | Routing and cross-family tests verify invoked agents, latency, and blocked or disclosed incompatibilities. |
| Evidence-based explanations | Ground every material fact in returned source fields and the snapshot date. | Evidence completeness checks pass for every factual answer. |
| Hallucination prevention | Avoid inferred missing values, forecasts, and unsupported recommendations. | Adversarial unsupported questions follow abstention rules. |
| Single-turn ambiguity handling | Apply an approved default, return bounded alternatives with limitations, or abstain when missing information materially changes the result. | Ambiguity cases select the expected fallback, limitation, or abstention without a follow-up turn. |
| Official evaluation API | Accept the fixed GET request and return the five required string fields within the organizer timeout. | Contract tests verify path, parameters, content type, exact fields, string types, idempotent retry, and stateless handling. |
| Workplace usefulness and risk management | Complete screening, validation, explanation, and evidence as one inspectable workflow. | End-to-end scenarios produce usable candidates plus evidence and limitations. |

## 8. In Scope

- Ingestion and validation of the four organizer-provided product masters.
- A deterministic orchestrator, typed execution state, conditional routing, bounded retries, and deadline management.
- Specialized domestic-bond, domestic-ETF, overseas-ETF, and public-fund agents that produce family-specific execution plans.
- A common product-search axis plus product-family-specific detail fields.
- Natural-language intent and condition parsing.
- Exact lookup, filtering, comparison, ranking, aggregation, and supported calculation.
- Comparison-compatibility and operational-relevance checks.
- Evidence construction, exclusion reasons, data-date disclosure, deterministic fallback, abstention, and recommendation guardrails.
- Data-quality rules for missing values, placeholders, duplicate aggregation, and unavailable fields.
- A reproducible evaluation API, containerized runtime, tests, operational checks, and technical documentation.

## 9. Non-Goals for the Initial Competition Scope

- Live order execution or brokerage-account integration.
- Personalized suitability advice or portfolio allocation based on an investor profile.
- Unsupported price or return forecasting.
- Real-time market-data replacement of the organizer snapshot.
- A persona-specific authorization model or production user-interface suite.
- An unbounded, self-organizing agent swarm, recursive agent delegation, or debate-and-vote architecture on the critical path.
- Additional agents whose contribution to correctness, latency, evidence, or failure handling cannot be measured.
- Uploading organizer-provided source files to a personal public or private repository without explicit permission.

## 10. Success Measures

- A supported query produces the same filtered products and calculations when repeated against the same data version.
- Every returned product fact can be traced to a table, product identifier, field, unit, and applicable date.
- Unsupported, ambiguous, or data-missing questions follow a tested fallback, limitation, or abstention path without relying on another request.
- Cross-product comparisons exclude, separate, or disclose incompatible metrics instead of silently normalizing them.
- Operational conditions such as sale status, pension eligibility, or purchase availability are applied when supported and identified as unknown when not supported.
- Material exclusions, missing fields, and data-quality limitations that affect the conclusion are visible in the answer or evidence packet.
- The core evaluated query types have deterministic benchmark cases covering supported, ambiguous, incompatible, and unsupported variants.
- Router tests invoke every required specialist and no irrelevant specialist for the benchmark query set.
- Independent specialist work runs concurrently for cross-product queries, and stage-level latency is observable.
- Gold-set filters, rankings, aggregates, and financial calculations match deterministic expected results exactly.
- Every data-backed factual claim in the benchmark answer set has a valid evidence reference, with no unsupported factual claims.
- Initial performance targets are p95 at or below 4 seconds for simple supported queries and 10 seconds for supported cross-product queries; these targets must be recalibrated from measured HyperCLOVA X and infrastructure latency before becoming an SLA.
- The service can be rebuilt from tracked source, dependency definitions, ingestion instructions, and approved fixtures without relying on untracked developer state.
- The submitted API contract remains stable and its deployment can be health-checked throughout the evaluation period.

## 11. Temporary Safe Defaults Pending Remaining Official Clarifications

These defaults prevent unsafe assumptions and may be superseded by a later accepted ADR after official Q&A:

- Treat `ETF` and `ETN` as different product types; an ETF-only query excludes ETNs unless the user explicitly includes them.
- Do not rank or aggregate AUM across currencies without an approved exchange-rate source and a disclosed conversion date.
- Do not aggregate public-fund AUM across share classes unless a verified representative-fund key prevents double counting.
- Treat placeholder descriptions such as “index not available” as semantically missing even when the cell is non-empty.
- Do not infer missing fees, yields, returns, risk grades, saleability, eligibility, or tradability from similar products.
- Interpret “recommend” as “show candidates satisfying stated conditions” unless suitability inputs and an approved policy explicitly support more.

## 12. Accepted Multi-Agent Architecture Direction

The approved top-level architecture is a purpose-built, conditional-parallel multi-agent graph controlled by a deterministic application orchestrator.

- A HyperCLOVA X Intent Planner produces a schema-validated, domain-neutral query plan.
- The orchestrator routes only the relevant product-family specialists and runs independent work concurrently.
- Specialists produce typed, family-specific execution plans; they do not calculate financial results or compose the final answer.
- A deterministic data engine performs retrieval, filtering, sorting, ranking, aggregation, and financial calculations. A SQL-first hybrid remains a leading implementation choice for this data layer, not the top-level product architecture.
- A cross-product comparator handles compatible common concepts and refuses or discloses invalid comparisons.
- An independent evidence and policy verifier checks results before an Answer Synthesizer can compose from the verified evidence bundle.
- A deterministic claim gate rejects factual statements without valid evidence references.

The full component contracts, execution paths, failure handling, latency strategy, and verification plan are defined in [Multi-Agent Architecture](architecture/MULTI_AGENT_ARCHITECTURE.md) and accepted by [ADR-0004](decisions/ADR-0004-conditional-parallel-multi-agent-graph.md).

## 13. Decision Records

Accepted and superseded decisions live in `docs/planning/decisions/`. Each record includes the date, status, chosen option, rejected alternatives, reasons, and consequences. Historical records are append-only.

- [ADR-0001: Use a Project-Local Planning Harness](decisions/ADR-0001-planning-harness.md)
- [ADR-0002: Keep Organizer Data Out of the Personal Repository](decisions/ADR-0002-repository-data-policy.md)
- [ADR-0003: Frame the Competition Entry as an Internal Product Desk Copilot](decisions/ADR-0003-internal-product-desk-copilot.md)
- [ADR-0004: Use a Conditional-Parallel Multi-Agent Graph](decisions/ADR-0004-conditional-parallel-multi-agent-graph.md)

## 14. Change Procedure

1. Identify which problem statement, criterion, constraint, or accepted ADR the change affects.
2. Explain the new information and the trade-off it introduces.
3. Obtain explicit user approval.
4. Add a new ADR or revise this harness with a dated explanation.
5. Update affected task plans before implementation resumes.
