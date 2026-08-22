# ADR-0014: Use Bounded Official Source Snapshots for Stage 03B

**Date:** 2026-08-22

**Status:** Accepted

**Related:** [Stage 03B Official Structured Data Design](../specs/2026-08-22-stage-03b-official-structured-data-design.md), [ADR-0007](ADR-0007-normalized-evidence-ledger-structured-answer-plan.md), [ADR-0013](ADR-0013-use-lean-source-specific-ingestion.md)

## Context

Stage 03A normalized the four organizer masters, but core evaluation questions still require ETF holdings, stable security and institution identifiers, compatible price/NAV inputs, and an approved KRW exchange rate. The official-source landscape is asymmetric. Domestic exchange and manager sources can target the domestic ETF universe, while SEC N-PORT covers only eligible public filings and cannot represent every overseas ETF in the organizer master. Holdings dates can also precede filing and public availability dates.

Treating a missing external record as proof that a holding does not exist would create unsupported closed-world answers. Directly inserting API responses into the final NCP database would also make the immutable dataset manifest partial and prevent exact reconstruction.

## Decision

- Use question-driven official sources rather than requiring KRX, ECOS, FRED, or any fixed API list.
- Target maximum official coverage for the domestic ETF universe and bounded, explicitly disclosed coverage for overseas ETFs.
- Require `applicable_date`, `published_at`, and `available_at` to be on or before `2026-07-11` where the source exposes or permits verification of those times.
- When no observation exists on the cutoff date, use only the latest eligible official observation before the cutoff and preserve its actual date.
- Use metric-specific authority: organizer fields remain authoritative, KRX owns the selected domestic market facts, ECOS `731Y001` owns the selected KRW exchange rates, and the relevant regulator, exchange, or manager owns holdings and identifiers.
- Preserve official raw bytes and request metadata in Private Object Storage before normalization.
- Reuse the Stage 02 catalog, relation, observation, Evidence, and dataset lifecycle schemas. Do not create Alembic `0006` unless a later test proves a mandatory fact cannot be represented and the user separately approves it.
- Make source snapshots atomic for checksum, schema, cutoff, pagination, and row-accounting failures. Quarantine individual unresolved identifiers and conflicting facts without silently dropping or selecting values.
- Represent search-scope completeness explicitly. Only a validated full publisher-defined snapshot may support `closed_world`; partial and uncovered populations remain `bounded_unknown`.
- Validate Stage 03B in disposable PostgreSQL `building` versions. Do not partially mutate the final NCP PostgreSQL dataset; reproduce the final `building` version in Stage 03C after all source manifests are frozen.

## Reasons

- It answers the required ETF relationship and cross-currency questions without pretending that all overseas products are covered.
- It preserves as-known-at-cutoff semantics for delayed regulatory filings.
- It reuses the implemented Stage 02 integrity, Evidence, and idempotency boundaries.
- It keeps raw-source reconstruction possible when APIs or official files later change.
- It prevents one invalid record from hiding valid coverage while still making structural source failures fail closed.

## Rejected Alternatives

### Require full holdings for every overseas ETF

Rejected because the organizer overseas universe spans jurisdictions and publishers that are not covered by one official historical dataset. Claiming full coverage would be fragile and could require disproportionate source-specific infrastructure.

### Ingest only the named example products

Rejected because it would overfit public examples and fail unseen compound questions.

### Write API responses directly to PostgreSQL

Rejected because raw official responses, request parameters, checksums, and historical reconstruction would be lost or duplicated in database-specific blobs.

### Build a generic data lake and connector framework first

Rejected because the approved source set is small and semantically different. Explicit source adapters are easier to review and consistent with ADR-0013.

### Skip invalid records on a best-effort basis

Rejected because silent omission changes search completeness and can turn an unknown result into a false absence Claim.

## Consequences

### Positive

- Each answer can disclose the exact official source, actual date, cutoff status, and covered population.
- Domestic holdings and market facts can be tested before the more complex overseas path.
- External facts remain reproducible and bind to the normalized Evidence ledger.
- Stage 03C receives one bounded set of frozen source manifests rather than a partially mutated final database.

### Costs and risks

- Overseas holdings answers may be limited even when the product exists in the organizer master.
- Official source availability, filing lag, pagination, and usage terms require source-specific checks.
- Object Storage and disposable PostgreSQL acceptance tests take longer than direct API-to-table loading.
- Coverage reports and source conflicts become required release inputs rather than optional diagnostics.

## Preserved Decisions

- The organizer snapshot wins for the same evaluation field.
- PostgreSQL remains the structured and Evidence authority; Graph and Vector remain projections.
- Deterministic code owns normalization, filtering, ranking, comparison, and calculations.
- Original organizer and external data remain outside Git.
- No dataset is activated before PostgreSQL, Graph, Vector, and Evidence readiness all pass.
