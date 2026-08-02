# Financial Product Analyst Planning Harness

**Status:** Approved project direction

**Last updated:** 2026-08-02

**Purpose:** Keep the project's `what` and `why` stable while allowing capable agents freedom over `how` within approved constraints.

## 1. Problem Definition

### Who

Competition evaluators and financial-product users who need to search, compare, and understand domestic bonds, domestic ETFs, overseas ETFs, and public funds through natural-language questions.

### When

They are trying to find products under multiple simultaneous conditions, compare products across heterogeneous masters, or ask for rankings and calculations over approximately 145,000 structured records.

### What they cannot do reliably today

They cannot easily translate natural-language conditions into four different schemas, reconcile inconsistent units and time horizons, distinguish real zeroes from missing values, prevent duplicate aggregation, and retain auditable evidence for every result.

### What they give up

They either inspect large spreadsheets manually, narrow the question until it loses value, or accept an answer whose calculations and evidence cannot be trusted.

### What changes when the problem is solved

The user receives condition-matching products, comparisons, and calculations within a short interaction, together with the exact source, product identifier, fields, units, data date, exclusions, and unavailable information used to produce the answer.

## 2. Ordered Decision Criteria

1. **Accuracy and evidence over answer coverage.** An explicit limitation is better than a plausible but unsupported financial answer.
2. **Deterministic execution over free-form model autonomy.** Filters, sorting, ranking, aggregation, and arithmetic must be reproducible and testable.
3. **Organizer data over external data.** The organizer-provided snapshot is the evaluation baseline and wins when sources conflict.
4. **Clarification or abstention over guessing.** Missing critical conditions or unavailable fields must produce a clarifying question or a clear inability statement.
5. **Operational simplicity over architectural novelty.** A small, observable, reproducible service is more valuable than additional frameworks that increase failure modes.

## 3. Hard Constraints

- HyperCLOVA X is the only permitted language-model family. Other embedding models are allowed only to the extent confirmed by official competition guidance.
- Every answer containing product facts or calculated values must identify its supporting data.
- Do not create unsupported return forecasts or definitive investment recommendations.
- Do not compare metrics across incompatible periods, meanings, units, or currencies without an explicit normalization method and disclosed source.
- Preserve raw organizer data unchanged and keep it out of the personal GitHub repository.
- The evaluation API must remain publicly reachable and reproducible for the required evaluation window.
- No code, data, or deployment changes may be pushed after the official submission freeze takes effect.
- Raw hidden model reasoning is not a project artifact. Expose a concise, structured execution trace containing intent, filters, tools, calculations, sources, and exclusion reasons.

## 4. In Scope

- Ingestion and validation of the four organizer-provided product masters.
- A common product-search axis plus product-family-specific detail fields.
- Natural-language intent and condition parsing.
- Exact lookup, filtering, comparison, ranking, aggregation, and supported calculation.
- Evidence construction, data-date disclosure, clarification, abstention, and recommendation guardrails.
- A reproducible evaluation API, containerized runtime, tests, operational checks, and technical documentation.

## 5. Non-Goals for the Initial Competition Scope

- Live order execution or brokerage-account integration.
- Personalized suitability advice or portfolio allocation based on an investor profile.
- Unsupported price or return forecasting.
- Real-time market-data replacement of the organizer snapshot.
- A general-purpose autonomous multi-agent platform.
- Uploading organizer-provided source files to a personal public or private repository without explicit permission.

## 6. Success Measures

- A supported query produces the same filtered products and calculations when repeated against the same data version.
- Every returned product fact can be traced to a table, product identifier, field, unit, and applicable date.
- Unsupported, ambiguous, or data-missing questions follow a tested clarification or abstention path.
- Cross-product comparisons exclude or disclose incompatible metrics instead of silently normalizing them.
- The service can be rebuilt from tracked source, dependency definitions, ingestion instructions, and approved fixtures without relying on untracked developer state.
- The submitted API contract remains stable and its deployment can be health-checked throughout the evaluation period.

## 7. Temporary Safe Defaults Until Official Clarification

These defaults prevent unsafe assumptions and may be superseded by a later accepted ADR after official Q&A:

- Treat `ETF` and `ETN` as different product types; an ETF-only query excludes ETNs unless the user explicitly includes them.
- Do not rank or aggregate AUM across currencies without an approved exchange-rate source and a disclosed conversion date.
- Do not aggregate public-fund AUM across share classes unless a verified representative-fund key prevents double counting.
- Treat placeholder descriptions such as “index not available” as semantically missing even when the cell is non-empty.
- Do not infer missing fees, yields, returns, risk grades, or tradability from similar products.
- Interpret “recommend” as “show candidates satisfying stated conditions” unless suitability inputs and an approved policy explicitly support more.

## 8. Proposed Technical Direction, Not Yet an Accepted Decision

The current leading option is a SQL-first hybrid: immutable raw tables, a normalized common product registry, product-family detail tables, a validated query-plan schema, deterministic query tools, limited semantic retrieval for narrative fields, and HyperCLOVA X for intent parsing and grounded response composition.

This direction remains proposed until its architecture ADR is explicitly approved. Implementation must not treat it as final merely because it appears in this document.

## 9. Decision Records

Accepted and superseded decisions live in `docs/planning/decisions/`. Each record includes the date, status, chosen option, rejected alternatives, reasons, and consequences. Historical records are append-only.

## 10. Change Procedure

1. Identify which problem statement, criterion, constraint, or accepted ADR the change affects.
2. Explain the new information and the trade-off it introduces.
3. Obtain explicit user approval.
4. Add a new ADR or revise this harness with a dated explanation.
5. Update affected task plans before implementation resumes.
