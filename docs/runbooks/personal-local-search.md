# Personal local search and manager-weight supplement

Run from the personal-local worktree with its `.venv`. These commands query
`financial_agent_local` on localhost as read-only `fa_runtime` and render
counts, sources and exact document quotes on the server. No LLM calls are made.

```sh
.venv/bin/python scripts/search_personal_dataset.py --plan rank_return --keyword TIGER --limit 5
.venv/bin/python scripts/search_personal_dataset.py --plan holding_weight --keyword 삼성전자보통주 --limit 5
.venv/bin/python scripts/search_personal_dataset.py --plan document_risk --keyword 환율 --limit 3
```

This is the three-plan local execution path, not the general-language HTTP
service. The base dataset remains `personal-2026-08-24-v1`; dates are those
in the stored snapshot. Unknown values never become zero or inferred weights.

## Source-owned document answers

The local document model contract accepts only a selection of retrieved IDs:

```json
{"citations": ["D1", "D2", "D3"]}
```

Each ID selects its entire supplied excerpt. Every retrieved document must be
selected once; unknown, duplicate or missing IDs are rejected. Model-written
`answer`, `quotes`, quote spans and offsets are rejected. The server renders
document fields and complete excerpts into one canonical answer, preserving
conditions, negations and literal strings such as `[D9]` inside source text.
Final validation rejects changed or freely authored document text with
`DOCUMENT_BODY_UNGROUNDED`.

This replaces free paraphrased risk summaries with source-only document
answers. It verifies the local raw output contract and fidelity to supplied
excerpts; it does not establish production truth, PDF extraction quality,
complete source context, an exact quotation page or current market facts.
The retrieval excerpt is not shortened further by the renderer.

Saved experiment records can be checked without API calls or database access:

```sh
.venv/bin/python scripts/revalidate_personal_search.py '/path/to/saved-Q3.json'
.venv/bin/python scripts/revalidate_personal_search.py '/path/to/saved-Q3.json' --render-document-quotes
```

The explicit option uses only the saved citation IDs to produce a distinct
source-only derivative. Legacy prose and quote text are excluded from that
derivative, while the original file, original verdict and errors remain
unchanged. `server_render_contract_passed` describes the derivative only;
`contract_passed` describes the original answer under the current contract.
The command still exits with status 1 when any original answer fails, even if
its derivative passes. Invalid saved selections cannot be silently repaired.
Legacy free-prose answers therefore remain rejected rather than being relabeled
as successful. No new model call is made during replay.

## Approved manager supplements

ADR-0051 authorizes separate manager observations dated 2026-08-21 to supplement
the original 2026-08-22 request. The optional local table is
`personal_local.holding_weight_supplement`, outside the base dataset manifest
and production release ledger. Nine Samsung-common-stock weights are available
across five publishers: Samsung (3), TIGER (3), PLUS (1), HANARO (1), WON (1).

```sh
.venv/bin/python scripts/import_personal_manager_weights.py --publisher samsung --workspace-root '/path/to/original-workspace'
.venv/bin/python scripts/import_personal_manager_weights.py --publisher tiger --workspace-root '/path/to/original-workspace'
.venv/bin/python scripts/import_personal_manager_weights.py --publisher plus --workspace-root '/path/to/original-workspace'
.venv/bin/python scripts/import_personal_manager_weights.py --publisher hanaro --workspace-root '/path/to/original-workspace'
.venv/bin/python scripts/import_personal_manager_weights.py --publisher won --workspace-root '/path/to/original-workspace'
```

Each bounded command uses public official endpoints, archives source evidence
and a manifest under ignored `data/personal-manager-weights/`, validates the
product/security/date/ratio, and transactionally imports its batch. Existing
values are immutable: a conflicting value aborts the transaction. Reimporting
identical values creates no duplicate rows and preserves the original source.
The bootstrap grants only schema usage and SELECT to the runtime role.

Samsung's metric explicitly excludes cash/deposits. TIGER, PLUS, HANARO and WON
retain separate publisher-reported metrics with unconfirmed cash-denominator
comparability. Never coalesce these into the KRX metric or rank the mixed-basis
population. All nine supplements being present does not certify comparability.

The query shows matched/displayed counts, missing original weights, supplemental
coverage, actual date, provider, basis, source URL, pointer, archived path and
SHA256. A five-result limit still displays five products; coverage describes
all nine matched products. Complete supplemental inventory is available in the
local `data/personal-search-20260923/supplement-inventory.txt` report.

HANARO's HTML display is cross-checked with its officially dated Excel filename
and rounded workbook cell representation; the date-evidence URL, disposition,
path and hash are retained in the source manifest. WON requires the normal
public page session and CSRF token; the token is used only in memory and redacted
from the identity evidence before storage. Its JSON response has explicit dates.

```sh
.venv/bin/python scripts/audit_personal_holdings.py --workspace-root '/path/to/original-workspace'
```

This audit is read-only and verifies the original KRX capture checksums and
normalized values. Those base values are unchanged by supplemental import.
