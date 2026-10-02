# Live local search and official weight recovery — 2026-09-23

User approved server-owned quotes/sources/counts followed by weight supplementation.
Continue personal local profile (ADR-0050), deterministic rendering (ADR-0007),
official provenance (ADR-0014), and missingness discipline (ADR-0020).

Previously only saved-result replay was wired. Add a bounded local read-only
PostgreSQL execution entry point using the three reviewed SQL plans, followed
by the existing deterministic renderer. Test against real local data and save
new text logs, without an LLM answer call. This is local execution integration,
not a new HTTP service or a full general-language production resolver.

For weights, inspect official KRX and manager historical sources for the exact
stored date. Preserve existing snapshots; do not overwrite missing values with
newer/older observations or a valuation-derived ratio. Only an exact-date,
identity- and meaning-verified source can support supplementation. If access
or historical completeness prevents this, record the attempted sources and
blocking evidence; do not report data supplementation complete.

Acceptance: SQL parameters validated before connection; reads restricted to
local dataset and read-only fa_runtime role; workbook/holding evidence fetched;
document checksum checked before excerpting; all three live queries render
server-owned counts, dates, sources, literal quotes. Test invalid plans, limits,
SQL metacharacters, corrupted documents, and empty results. No commit/push.

## Approved direction change and implementation

The official Samsung query requested 2026-08-22 but returned 2026-08-21 with
cash/deposits excluded. The user explicitly approved separate supplemental
storage after disclosure. ADR-0051 records this supersession of the initial
exact-date-only recovery constraint. Original observations remain unchanged.

The optional local adjunct now contains three Samsung and three TIGER records.
TIGER uses a distinct reported-weight metric with unconfirmed cash denominator.
The actual date, request context, publisher, basis, raw URL/path/SHA256, JSON
pointer and identity evidence are stored. No mixed-basis ranking is enabled.

KRX direct web probe returned HTTP 403. TIGER and Samsung official public
historical endpoints were usable. The remaining three matched products have not
been supplemented; no claim of complete nine-product weight coverage is made.

## Final verification (supersedes intermediate coverage notes above)

- All nine matched products now have separate 2026-08-21 manager supplements:
  Samsung 3, TIGER 3, PLUS 1, HANARO 1, WON 1.
- WON's apparent HTTP 404 was resolved using the official page's normal public
  session and CSRF form protocol. No token persisted. Its Excel alone lacked
  the needed columns and was not used as weight evidence.
- HANARO web value was corroborated by the officially dated Excel export; date
  evidence and checksum reside in the capture manifest.
- 159 targeted retrieval/release/contract/ingestion tests passed.
- Nine source and identity checksums plus parsed values/dates verified against
  stored records. All five batches reimported idempotently. A deliberately
  conflicting value was rejected and its transaction rolled back.
- Three live PostgreSQL queries passed through server rendering. Holdings show
  original known=0, missing=9, supplement known=9, mixed ranking disabled.
- Original KRX audit still has no mismatches; its 19 populated and 2,906 missing
  observations remain unchanged. No base dataset manifest or raw file changed.
- Final text logs and full nine-product inventory are in parent workspace
  data/personal-search-20260923/. No LLM API call, push, commit, or deployment.
