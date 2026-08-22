# ADR-0015: Use Validated ISIN-Derived KRX ETF Bindings

**Date:** 2026-08-22

**Status:** Accepted

**Related:** [ADR-0014](ADR-0014-use-bounded-official-source-snapshots.md), [Stage 03B Field Matrix](../specs/stage-03b-official-source-field-matrix.md)

## Context

The first Stage 03B probe compared organizer `pd_itm_no` values directly with KRX short issue codes and concluded that no strong domestic ETF crosswalk existed. That comparison used incompatible identifier types. In the organizer domestic ETF population, 1,201 of 1,202 `pd_itm_no` values are checksum-valid ISINs. KRX ETF ISINs contain the six-character KRX short issue code in positions 4 through 9.

The official KRX ETF basic export confirmed this structural relationship for all 1,161 rows in the captured current file. The official 2026-07-10 ETF daily snapshot then supplied the historical active code universe without relying on a post-cutoff name or market value.

## Decision

- Treat an organizer domestic ETF `pd_itm_no` as an ISIN only when it passes syntax and checksum validation.
- Derive the KRX short issue code from positions 4 through 9 of that valid ISIN.
- Bind the organizer product to KRX only when the derived short code occurs exactly once in the official `2026-07-10` ETF snapshot.
- Use product names only as an audit signal and alias history. A name never creates or overrides a binding.
- Quarantine malformed ISINs, duplicate derived codes, duplicate KRX codes, and conflicting products. Do not fall back to fuzzy or name-only matching.
- Keep the 2026-08-22 KRX basic export outside answer data. It validates the identifier structure only; market and holdings facts use eligible 2026-07-10 source objects.
- Preserve KRX-only ETFs and organizer products absent from the 2026-07-10 universe as separate uncovered populations rather than forcing a match.

The verified aggregate boundary is:

```text
organizer domestic ETFs                 1,202
checksum-valid organizer ISINs          1,201
exact derived-code matches on 20260710  1,133
name-equal audit results                1,132
name-drift audit result                     1
organizer ETFs not active/resolved         69
KRX ETFs absent from organizer              8
```

## Consequences

### Positive

- Domestic ETF identity no longer depends on names or a post-cutoff basic snapshot.
- The same binding can be reused by KRX price/NAV and PDF holdings mapping.
- Delisted, newly listed, malformed, and source-missing populations remain visible.

### Costs and risks

- The single malformed organizer ISIN remains unresolved until the organizer or another pre-cutoff official source corrects it.
- A valid product outside the 2026-07-10 KRX universe has no cutoff-date market or holdings binding.
- Name drift must be retained as an audit issue rather than silently replacing the organizer name.
