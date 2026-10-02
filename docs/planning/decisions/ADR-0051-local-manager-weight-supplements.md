# ADR-0051: Keep manager weights as separate local supplemental observations

- Date: 2026-09-23
- Status: Accepted
- Approval: User explicitly selected 별도 보조 데이터로 적재 after disclosure
  that the requested 2026-08-22 query returns 2026-08-21 and excludes cash/deposits.

Preserve the original KRX observations and dataset manifest unchanged. Store
bounded manager observations in a separate personal_local.holding_weight_supplement
local table linked to the base product identifier. This optional local adjunct
is not part of the competition schema, official dataset readiness, or release
ledger. Its bootstrap/import script is reproducible and transaction-bound.

Each record retains publisher, its actual applicable date, requested date,
metric meaning, original response checksum/path/URL, JSON pointer, and capture
time. The metric is manager_pdf_weight_excluding_cash_deposits_pct, distinct
from krx_etf_holding_weight_pct. The initial adapter supports Samsung's public
PDF API and only the explicitly inspected 2026-08-21 snapshot requested for
2026-08-22, for the three sampled Samsung ETFs holding Samsung common stock.

Display supplements separately with their actual date and denominator. Never
coalesce them into KRX values or use them to claim complete nine-product ranking.
Do not overwrite the base observations. Retain unavailable products as unknown.

Rejected alternatives: filling the existing KRX metric would mix dates and
meanings; computing ratios from valuations would create unsupported derived
facts; copying the entire core dataset solely for three local observations is
unnecessary duplication. Production promotion requires separate integration
into the authoritative evidence/release pipeline.

## Same-day implementation extension under the approved supplement scope

Official TIGER historical responses were also verified for three sampled ETFs
(147970, 376410, 396500), using product-page ticker identity, response ISIN/date,
security ISIN, and a separate official list-count check. Add these as
`tiger_pdf_publisher_reported_weight_pct`. Cash inclusion in the denominator was
not established, so retain that uncertainty in the basis label and never treat
it as equivalent to Samsung's metric. Query 2026-08-21 directly as the approved
prior-business-day supplement to the original 2026-08-22 request. The actual HTTP
URL records that query date. No existing decision or original field is rewritten.

## Completion of the nine-product local sample

Under the same separate-supplement authorization, add one PLUS, one HANARO,
and one WON observation. Keep a distinct publisher-reported metric for each;
their denominator is not declared equivalent to another publisher's metric.
PLUS requires complete pagination and response dates; HANARO requires exact
ISIN, an officially dated Excel attachment name and agreement of web display
with workbook precision; WON requires returned fund code/date/security and the
normal public form-session/CSRF protocol. The transient form token is never
persisted; its identity-page capture is explicitly redacted and checksummed.

All nine supplemental observations are dated 2026-08-21. Coverage completion
is not comparability: do not enable mixed-publisher ranking simply because all
nine have values. KRX 2026-08-22 missing values stay missing.
