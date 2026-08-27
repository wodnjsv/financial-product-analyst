# Public-Fund Holdings Source Decision for the 2026-08-24 Cutoff

**Date:** 2026-08-27

**Status:** Final source decision for Stage 03 Task 5

**Decision:** `requires_data`

## 1. Outcome

No reviewed source satisfies every approval criterion for security-level
holdings across the current organizer public-fund population. Stage 03 must not
ingest or infer public-fund constituents under the current plan.

This is a coverage decision, not a claim that public funds have no holdings.
Questions that combine domestic ETFs, overseas ETFs, and public funds must
return the verified ETF scope together with an explicit public-fund coverage
limitation. They must not describe the ETF-only result as the complete answer.

## 2. Mandatory approval checklist

A source is approved only when every row below passes.

| Criterion | Required evidence |
| --- | --- |
| Publisher authority | Regulator, association, exchange, or the fund manager itself |
| Cutoff eligibility | Publicly obtainable no later than `2026-08-24` |
| Portfolio date | Actual portfolio applicable date is preserved |
| Publication history | `published_at` and `available_at` can be verified |
| Exact product binding | Stable fund or share-class identifier binds exactly to an organizer identity |
| Constituent semantics | Security identifier and weight, quantity, or holding-value meaning are documented |
| Measurable population | Covered and uncovered organizer populations can be counted |
| Reproducible evidence | Raw bytes, checksum, locator, and usage terms can be preserved |

Name similarity, current-only pages, search snippets, and inferred portfolio
text cannot substitute for any failed criterion.

## 3. Candidate assessment

| Candidate | What the official source establishes | Failed approval gates | Decision |
| --- | --- | --- | --- |
| KOFIA performance-comparison disclosure | KOFIA states that public-fund performance is published monthly and provides asset-class proportions such as stocks, bonds, collective-investment securities, cash, and other assets. It does not define security-level constituents in this disclosure. | No constituent security identifier; no security-level weight or quantity; the comparison population is restricted by disclosure criteria rather than the full organizer universe. | Reject for holdings |
| KOFIA electronic disclosure asset-management reports | The official manual says asset-management reports contain asset status and investment-asset transaction details. Individual report documents can therefore contain useful holdings evidence. | No reviewed bulk interface or common row schema; no proven exact crosswalk from every report's fund/share class to organizer `fss_itm_no`, `ksd_itm_no`, `std_itm_no`, or canonical product; current organizer coverage cannot be measured without source-specific document adapters. | `requires_data`; possible future document-source project |
| KOFIA Fund One-Click | The portal links fund information from regulators, KOFIA, managers, and evaluators. | KOFIA explicitly describes it as a linking convenience and says the linked information is not verified or guaranteed by KOFIA; source-specific dates, identifiers, and usage terms are not one uniform dataset. | Reject as a consolidated evidence source |
| DART/OpenDART | The official API can search disclosures and download original disclosure files, and DART exposes a fund-disclosure category. | The documented OpenDART APIs do not provide a complete security-level public-fund holdings table or a fund/share-class identifier crosswalk to the organizer. Corporate disclosure IDs do not prove fund identity. | Reject for universal holdings |
| Individual manager sites and reports | A manager is an authoritative publisher for its own products, and some reports may expose dated top holdings or full asset schedules. | Formats, identifiers, history, and usage terms differ by manager; there is no reviewed complete manager inventory or measurable coverage across 23,676 organizer product rows. Each manager would require a separate adapter and approval. | Reject under this plan |

## 4. Primary official evidence

- [KOFIA performance-comparison disclosure guide](https://dis.kofia.or.kr/wq/fundann/DISMngResCmpAnnNtcPop.html): disclosure timing, population rules, and asset-class-level composition fields.
- [KOFIA electronic disclosure service user manual](https://dis.kofia.or.kr/doc/dis_manual.pdf): report types and the stated contents of asset-management reports.
- [KOFIA guidance on post-purchase fund reports](https://fund.kofia.or.kr/fs/fund/html/pop_edu3.html): quarterly asset-management reports and the information they provide to investors.
- [KOFIA Fund One-Click portal notice](https://fund.kofia.or.kr/fs/fund/html/fundMain.html): linked-source role and accuracy disclaimer.
- [OpenDART disclosure API guide](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS001): disclosure search and original-file capabilities.
- [OpenDART disclosure search detail](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001): supported disclosure categories and request identifiers.

The pages above were reviewed on `2026-08-27`. Their role is to establish
source capabilities and gaps. No post-cutoff portfolio fact is ingested from
them.

## 5. Question and answer policy

`REL-HOLD-001` now reflects the organizer's announced cross-family example:
Samsung Electronics holdings across domestic ETFs, overseas ETFs, and public
funds ranked by one-year return.

The deterministic policy is:

```text
domestic ETF holdings  -> use current KRX coverage
overseas ETF holdings  -> use bounded SEC N-PORT coverage
public-fund holdings   -> requires_data

ETF result exists + public-fund source absent
-> return ETF result only as a bounded partial answer
-> disclose that public-fund holdings were not covered
-> never infer that no public fund holds the security
```

Organizer public-fund blanks and placeholders remain authoritative
unavailability. External product AUM, return, fee, risk, or classification
values must not be used to fill them.

## 6. Reopening this decision

A later task may propose a KOFIA or manager-report adapter only after it
provides:

1. one exact organizer-to-report identifier crosswalk;
2. a preserved historical report and publication timestamp;
3. a documented constituent schema and identifier policy;
4. measured covered, partial, and uncovered organizer counts;
5. raw-byte and usage-term preservation; and
6. a separate ADR and user-approved implementation plan.

Until then, `requires_data` is the final Stage 03 outcome and does not block
completion of the other approved sources.
