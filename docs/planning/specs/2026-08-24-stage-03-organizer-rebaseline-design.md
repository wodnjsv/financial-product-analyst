# Stage 03 Organizer Rebaseline Design

**Date:** 2026-08-24

**Status:** Approved for implementation

**Decision:** [ADR-0016](../decisions/ADR-0016-use-2026-08-24-organizer-baseline.md)
**Field contract:** [2026-08-24 organizer 280-field matrix](organizer-master-field-matrix-2026-08-24.md)
**Cutoff migration:** [ADR-0017](../decisions/ADR-0017-adopt-current-cutoff-with-legacy-preservation.md)

## 1. Goal

Replace the superseded `2026-07-11` organizer ingestion boundary with the eight `2026-08-24` workbooks, preserve the organizer's new grains and missingness, reconcile exact identifiers without duplicate products, and rebuild Stage 03 official-source acceptance against the new cutoff.

## 2. Verified source boundary

| Table | Data rows | Fields | New natural source record |
| --- | ---: | ---: | --- |
| `PRBD01N001` | 21,882 | 58 | `(pd_no, pd_exg_mkt, info_base_dt, info_seq)` |
| `PREF01N001` | 1,780 | 98 | `pd_itm_no` |
| `PREF02N001` | 6,037 | 49 | `pd_itm_no` |
| `PRFD01N001` | 23,676 | 75 | `itm_no` |
| **Total** | **53,375** | **280** | — |

Every data workbook uses sheet `data`; every schema workbook uses sheet `schema`. Data headers and schema field order match exactly and contain no duplicate header.

## 3. Compatibility boundary

Stage 01's artifact shape and Stage 02's normalized fact tables remain compatible. The new fields are text, numeric, date-like, timestamp-like, Boolean-like, identifier, catalog, relation, or Evidence facts that fit the existing tagged Observation and Evidence ledger.

The fixed cutoff boundary is not compatible: Stage 01 validates exactly `2026-07-11`, and `operations.dataset_version` has the same exact-date CHECK. ADR-0017 therefore proposes retaining the contract shape, changing the current runtime literal, and adding minimal Alembic `0006` that preserves historical `2026-07-11` rows while allowing only `2026-08-24` datasets to become active.

The incompatible layer is Stage 03 source-specific behavior:

- filenames, sheets, row counts, headers, mapping versions, and source hashes;
- domestic-bond lower-case fields and sale-lot grain;
- domestic ETF removed and newly answerable fields;
- overseas ETF population and duplicate-ID pre-scan;
- public-fund one-row-per-item grain and expanded attribute lists;
- the old cutoff and external-source manifests.

No new product, identity, listing, observation, relation, or Evidence table is authorized. The cutoff-only Alembic `0006` in ADR-0017 is required before mapper implementation.

## 4. Table-specific mapping

### 4.1 Domestic bond

Create one canonical product identity per valid `pd_no`. It represents the
bond product in `catalog.product`; do not also attach `catalog.security` to the
same entity because Stage 02 enforces exclusive entity subtypes, and do not
create an unlinked duplicate security entity. Preserve every composite source
record. Product-static values must converge byte-for-byte; when the same
`pd_no` reports conflicting static values, record a source conflict instead of
selecting a row.

Sale-lot fields such as price and buy yield may vary by `info_seq`. Store them as distinct source-record observations against the canonical product with `info_base_dt` as applicable date and the composite key in Evidence. Deterministic retrieval selects or ranks the eligible lot explicitly; it never treats repeated values as independent products.

`buyable_quantity` is ignored for availability. `remaining_days` may be retained because `info_base_dt` now provides its time basis. Exchange close fields are usable only when their explicit base date is present.

### 4.2 Domestic ETF and ETN

Keep `pd_itm_no` as organizer identity. A checksum-valid, unique `pd_itm_no` also emits an `ISIN` identifier; an explicit `pd_isin_cd` must be valid and equal when both exist. A checksum-valid, unique public-fund `ksd_itm_no` follows the same `ISIN` normalization, which makes exact cross-master identity resolution scheme-safe. Continue distinguishing ETF and ETN through the organizer's explicit `pd_grp_no` value.

Map newly populated tracking error, divergence, distribution, volatility, reference asset type, reference geography, reference index, and eligible bond-portfolio facts. Empty portfolio fields remain missing; a zero remains a zero. Removed fields produce no compatibility placeholder.

### 4.3 Overseas ETF and ETN

Retain the current 49-field semantic mapping after updating source identity, row count, mapping version, and cutoff. Pre-scan ISIN and Lipper independently. The verified new boundary contains 63 duplicate two-row groups whose ISIN and Lipper pairs align exactly; none is promoted to a unique identifier.

### 4.4 Public fund

Treat each `itm_no` row as one share-class/product record. Split `prfd_attr_cds` and `zrin_attr_nms` into ordered, de-duplicated memberships while preserving the original list in Evidence. The verified source contains 96,720 attribute memberships and its declared counts match the parsed list lengths.

Retain `rptt_ksd_itm_no` representative-fund grouping with sentinel handling. Map new class fee, policy, sale channel, remuneration, distribution, pricing-date, asset-composition, and ZeroIn classification facts. Do not restore the old repeated-row canonical-locator algorithm.

## 5. Exact identity resolution

Pre-scan identifiers from all four organizer sources before any normalized entity write. The pre-scan validates syntax, checksum, within-source uniqueness, and cross-source collisions, then deterministically assigns the organizer canonical entity ID. This prevents the 217 domestic ETF/public-fund overlaps from first being written as two entities. Freeze that plan as an in-memory `AuthoritativeIdentityIndex` before any external mapper runs. The index returns one of `MATCHED`, `NOT_FOUND`, or `AMBIGUOUS`.

- `MATCHED`: reuse the organizer entity and preserve the contributing source's observations, relations, and Evidence.
- `NOT_FOUND`: the approved external mapper may create a source-specific security entity.
- `AMBIGUOUS`: do not merge or create a duplicate canonical identifier; retain Evidence and bounded coverage.

The new organizer sources contain 217 exact, unique ISIN overlaps between domestic ETFs and public-fund rows. All 217 are ETF records and the public-fund rows are marked sale-complete. They must not be returned as two active products. The domestic ETF is the specific product identity; the public-fund source record and non-conflicting facts remain traceable Evidence.

N-PORT `holdsSecurity` uses the same resolver. The old observed conflict count of `87` is not a new acceptance constant. A read-only full-archive probe found 1,770 potential intersections with unique new overseas-organizer ISINs, so exact reuse remains mandatory and the actual selected-population count must be remeasured.

## 6. Official-source cutoff and coverage

- Organizer facts keep their actual source dates, predominantly `2026-08-21` for domestic daily facts and `2026-08-22` for overseas NAV/reference facts.
- External facts require `published_at` and `available_at` no later than `2026-08-24T23:59:59+09:00` when those timestamps exist.
- KRX market and PDF holdings use the latest eligible business observation and preserve the actual date.
- ECOS exchange rates use the latest eligible official row for each approved definition.
- SEC Series/Class and N-PORT use the latest archive publicly available by the cutoff; an older report date remains visible.
- Public-fund constituent holdings require a separately approved official source. Broad asset-composition percentages in `PRFD01N001` cannot prove that a fund holds Samsung Electronics.

Coverage remains explicit: domestic official coverage targets the full eligible universe; overseas and public-fund holdings remain bounded unless a publisher-defined complete snapshot proves otherwise.

## 7. Failure and lifecycle rules

- Raw workbooks are immutable and excluded from Git and Docker contexts.
- Header, schema, checksum, row-accounting, duplicate-key, identifier, or cutoff failures fail closed with stable aggregate-only codes.
- Missing and zero never cause row quarantine by themselves.
- Conflicting static facts are limited or quarantined with all source locators preserved.
- All rebuilds target fresh, inactive `building` versions. Prior probes are neither deleted nor activated.
- The final Stage 03 dataset is rebuilt only after organizer and approved external manifests are frozen.

## 8. Verification

1. The 280-field matrix accounts for every field exactly once.
2. Synthetic tests reproduce all four new source grains and changed fields.
3. Gated real-data tests assert only the reviewed aggregate counts and no product values.
4. Organizer identity tests prove the 217 exact overlaps do not double-count and ambiguous identifiers do not merge.
5. N-PORT integration proves no duplicate `(dataset_version, ISIN, value)` identifier is emitted and all relation observations retain Evidence.
6. Two empty-database rebuilds produce identical manifests, component hashes, aggregate counts, and source dispositions.
7. The result remains `building` and absent from `active_dataset`.
8. The report documents acquisition, validation, normalization, identity resolution, Evidence lineage, and query usage rather than merely listing stored objects.
9. Migration `0006` preserves legacy cutoff rows, rejects unapproved dates, and prevents legacy activation.
