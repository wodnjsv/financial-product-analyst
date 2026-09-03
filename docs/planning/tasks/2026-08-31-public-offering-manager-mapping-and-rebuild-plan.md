# Public-Offering Manager Mapping and Rebuild Plan

**Goal:** Review the 90 public-offering manager codes against official
sources and rebuild PostgreSQL with every supported binding.

**Decision:**
`docs/planning/decisions/ADR-0039-map-public-offering-manager-codes.md`

## Assumptions

- The organizer `2026-08-24` snapshot is the authority for product scope and
  original values.
- KOFIA or another official product source identifies the manager behind a
  source code; OpenDART identifies the corresponding filing corporation.
- Missing or ambiguous official evidence is a valid unresolved result.

## Non-goals

- Mapping manager codes that occur only on private-fund rows.
- Downloading or retaining DART PDFs.
- Extracting, chunking, embedding, or selecting an embedding tokenizer.

## Constraints

- Preserve organizer source files and raw Evidence unchanged.
- Do not use product-name or fuzzy matching as identity evidence.
- Do not commit raw organizer data, credentials, databases, or generated
  corpus files.

## Success Criteria

1. Produce an auditable inventory of all 90 in-scope codes with either an
   official canonical identity or an explicit unresolved reason.
2. Test that every reviewed code resolves deterministically and unreviewed
   codes remain source-local.
3. Rebuild a new PostgreSQL dataset version and confirm organizer source row
   counts are unchanged.
4. Report canonical manager coverage and remaining unresolved targets without
   starting PDF collection.

## Tasks

- [x] Extract the exact 90-code scope from organizer public-offering rows.
- [x] Resolve each code using official fund information and OpenDART.
- [x] Add failing behavior and real-organizer coverage tests.
- [x] Add the minimal reviewed registry and pass focused tests.
- [x] Start a disposable PostgreSQL 15 instance and build a new dataset
  version.
- [x] Verify source counts, manager relations, dataset status, and final diff.

## Official-source audit result

- In-scope public-offering manager codes: **90**
- Globally resolved by official KOFIA company identity: **59**
- Also reconciled to an OpenDART corporation code: **57**
- KOFIA-confirmed but without an OpenDART corporation match: **2**
  (`00040022`, `00080056`)
- Without a direct KOFIA company result: **31**

The 59 reviewed bindings are the deterministic registry in
`src/financial_agent/ingestion/mapping/asset_managers.py`. The 31 codes without
a direct KOFIA result are:

```text
00040013 00040023 00040035 00040084 00040085 00040105
00080015 00080029 00080030 00080091 00080096 00080103
00080104 00080153 00080154 00080155 00080157 00080160
00080164 00080168 00080204 00080333 00130001 00130002
00130003 00130004 00130005 00130006 00130009 00130012
99999999
```

`00040105` retains only the previously approved representative-fund-scoped
exception; it is not promoted to a global source-code binding. The other codes
remain source-local. No product-name or fuzzy manager inference was used.

## PostgreSQL rebuild result

- PostgreSQL: **15.19**
- Dataset version: `organizer-dart-2026-08-24-v2`
- Build result: **passed**
- Dataset lifecycle: `building`, inactive
- Organizer rows: **53,375**
  - `PRBD01N001`: 21,882
  - `PREF01N001`: 1,780
  - `PREF02N001`: 6,037
  - `PRFD01N001`: 23,676
- Public-offering manager codes observed in PostgreSQL: **90**
- Canonicalized codes observed in PostgreSQL: **60**
  - 59 global official KOFIA bindings
  - 1 previously approved representative-fund-scoped exception (`00040105`)
- DART-bound codes observed in PostgreSQL: **58**
  - 57 global bindings
  - 1 representative-fund-scoped exception
- KOFIA-only managers confirmed without DART identifiers: **2**
- Rebaseline invariants: 217 exact reused identities, 63 aligned ambiguous
  overseas identifier pairs
- Verification: 678 ingestion tests passed, 10 explicit external-data tests
  skipped; the organizer aggregate gate separately passed against the real
  local workbooks.
