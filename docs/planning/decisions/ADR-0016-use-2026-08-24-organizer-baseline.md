# ADR-0016: Use the 2026-08-24 Organizer Baseline

**Date:** 2026-08-24

**Status:** Accepted

**Supersedes:** Every `2026-07-11` organizer snapshot or active-cutoff clause in earlier project decisions and current design documents, including ADR-0008 through ADR-0015, the Stage 03A field matrix, and the Stage 03B capture plan. Historical examples and completed-run records remain unchanged as history.

**Related:** [Official Data Notice](../../reference/official-data-notice-2026-08-24.md), [Rebaseline Design](../specs/2026-08-24-stage-03-organizer-rebaseline-design.md), [280-field Matrix](../specs/organizer-master-field-matrix-2026-08-24.md), [ADR-0017](ADR-0017-adopt-current-cutoff-with-legacy-preservation.md), [ADR-0013](ADR-0013-use-lean-source-specific-ingestion.md), [ADR-0014](ADR-0014-use-bounded-official-source-snapshots.md)

## Context

The organizer announced that the four workbooks distributed for `2026-07-11` contain consistency and code issues and must be replaced by eight newly distributed data/schema workbooks. The new workbooks change the source boundary from 207 to 280 fields, change domestic-bond and public-fund row grains, add products and answerable fields, and permit official disclosures and market data available through `2026-08-24`.

Continuing the old Stage 03 capacity run would normalize a superseded source and could make a technically reproducible but evaluation-invalid dataset. The new files also expose exact identifier overlap between organizer masters and between organizer products and SEC holdings, so a source-local N-PORT patch is insufficient.

## Decision

- Treat the eight `2026-08-24` workbooks as the only authoritative organizer input for the final competition dataset.
- Set the external official-source availability cutoff to the end of `2026-08-24` in Asia/Seoul. Preserve every fact's actual applicable, publication, and availability date; do not relabel an older observation as `2026-08-24`.
- Preserve the four organizer tables as immutable raw sources and keep them outside Git.
- Replace the 207-field mapping contract with an explicitly reviewed 280-field contract.
- Use the new source grains:
  - domestic bond source record: `(pd_no, pd_exg_mkt, info_base_dt, info_seq)`;
  - domestic ETF/ETN source record: `pd_itm_no`;
  - overseas ETF/ETN source record: `pd_itm_no`;
  - public fund source record: `itm_no`, with comma-separated attribute lists expanded deterministically.
- Ignore domestic-bond `buyable_quantity` for availability. Apply the organizer's stated assumption that a product is purchasable unless an explicit delisting or listing-end condition excludes it.
- Preserve zero and missing as different tagged states. Do not infer or impute values from adjacent products or older snapshots.
- Pre-scan exact identifiers across all four organizer sources before normalized entity writes, deterministically choose organizer canonical entity IDs, and freeze the result as one organizer-authoritative identifier index before external-source mapping. Only syntactically valid, checksum-valid, unique identifiers can resolve an entity.
- Normalize checksum-valid unique domestic-ETF `pd_itm_no` and public-fund `ksd_itm_no` values into the same `ISIN` scheme while retaining their source-specific identifier schemes; explicit `pd_isin_cd` must agree when present.
- Reuse an organizer entity when an external security identifier resolves exactly once. Do not create a second `ISIN` identifier or entity for the same instrument.
- Do not guess through duplicate identifiers. Ambiguous identifiers remain source Evidence and produce bounded coverage.
- Resolve exact domestic ETF/public-fund overlap without double-counting the product; preserve both source records and their Evidence.
- Keep the Stage 02 normalized fact model unchanged. The exact-date cutoff guard is incompatible and requires the minimal contract and Alembic change proposed in ADR-0017.
- Consider all prior Stage 03 NCP capacity datasets historical, non-active probes. Never activate or silently reuse them.
- Recapture or reapprove external official sources against the new cutoff before the next combined capacity build.

## Rejected Alternatives

### Patch only the 87 observed N-PORT conflicts

Rejected because `87` belongs to a superseded organizer dataset and one bounded sample. The new organizer files introduce more products, 63 duplicate overseas identifier pairs, 217 exact domestic ETF/public-fund overlaps, and a much larger potential N-PORT ISIN intersection.

### Continue loading the old organizer baseline and overlay new rows

Rejected because the organizer explicitly replaced the old distribution. Overlaying would mix incompatible grains and make Source/Evidence lineage misleading.

### Add a new identity or listing database table immediately

Rejected because the existing Catalog, Relation, Observation, Source, and Evidence tables can represent the approved facts. An ingestion-time exact identity index and deterministic relations are sufficient until a tested query requires a new physical boundary.

## Consequences

- All Stage 03 source hashes, filenames, sheet names, row counts, manifests, mapping versions, cutoff checks, and acceptance aggregates must be regenerated.
- Domestic bond sale-lot facts and public-fund attribute lists require mapper changes rather than a source-reader-only update.
- Previously ignored domestic ETF tracking, divergence, distribution, and volatility fields must be re-evaluated because the new source contains non-zero values.
- KRX, ECOS, SEC Series/Class, N-PORT, and any approved public-fund holdings source require a new cutoff review.
- Stage 04 and later stages remain blocked until the new combined `building` dataset passes the Stage 03 completion gate.
