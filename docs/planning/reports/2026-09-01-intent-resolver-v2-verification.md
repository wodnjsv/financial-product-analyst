# Intent Resolver v2 Evaluation Verification

**Date:** 2026-09-01

## Result

Entity-role hardening passes every authorized offline gate. Expected frame-type
reachability moved from the verified request-local baseline of **14/155** to
**155/155**, and the focused, schema, diff, scope, and filtered broad suites are
green.

Default resolver promotion remains **deferred**. The one provider-reaching
12-case HCX-007 smoke completed without retry, but provider success was `0/12`:
ten calls timed out and two were rate-limited. Therefore the smoke supplies no
semantic or promotion evidence. No question text, raw model content, credential,
or raw live report is retained in this document or in Git.

## Offline verification

| Check | Fresh result |
| --- | --- |
| Intent + evaluator focused suite | **353 passed** |
| Entity-type reachability | **155/155**, zero unreachable case IDs |
| v1 schema freshness and no drift | passed; schema check exited `0`, and `schemas/intent/v1` has no diff from `5827fdf` |
| v2 schema freshness | passed; explicit `2.0` schema check exited `0` |
| Worktree and range diff checks | passed; both exited `0` |
| Filtered broad offline suite | **1285 passed, 1 skipped, 378 deselected** |
| Explicit PostgreSQL evidence | **unmeasured external evidence**; `FINANCIAL_AGENT_TEST_DATABASE_URL` is not configured |
| Scope and secret audit | passed; no `data/`, organizer PDF/workbook, credential, `.env`, raw report, migration, QueryPlan, Orchestrator, or public API path changed |

The broad command excluded every registered external marker: `postgres`,
`ncp_integration`, `performance`, `organizer_data`, `object_storage`,
`official_data`, `jena_integration`, and `clova_integration`. The sole skip was
the explicit PostgreSQL repository test, so it is reported as unmeasured rather
than passed.

## Authorized HCX-007 smoke

The only provider-reaching run used the fixed 12-case manifest, model
`HCX-007`, one-second inter-case pacing, and no evaluator retry. Its raw
aggregate remained under
`/private/tmp/intent-resolver-entity-role-live-report.json` and was not staged.

| Measure | Sanitized result | Interpretation |
| --- | ---: | --- |
| Provider success | `0/12` | provider gate unavailable |
| First-pass schema validity | `0/0` | unmeasured |
| Joint frame exact match | `0/0` | unmeasured |
| Context-link exact match | `0/0` | unmeasured |
| OOD false-fast | `0/0` | unmeasured |
| p50 latency | `20027 ms` | includes failed provider attempts |
| p95 latency | `20108 ms` | includes failed provider attempts |
| Prompt tokens | `0` | provider returned no usable completion |
| Completion tokens | `0` | provider returned no usable completion |
| Stable provider errors | `MODEL_TIMEOUT: 10`; `MODEL_RATE_LIMITED: 2` | provider failures, not semantic misses |

Two shell credential-loading checks and one local import check stopped before
the evaluator could make any provider request; each processed `0/12` cases.
The corrected in-memory loader then executed the single actual 12-case smoke.
No provider-reaching retry was made.

The stable case IDs were:

`HKO-PAR-001`, `HKO-PAR-002`, `HKO-PAR-003`, `HKO-CMP-001`,
`HKO-CMP-002`, `HKO-CMP-003`, `HKO-CTX-001`, `HKO-CTX-002`,
`HKO-CTX-003`, `HKO-OOD-VOC-001`, `HKO-OOD-DOM-001`, and
`HKO-OOD-CTX-001`.

## ADR-0022 gate matrix

The 12-case smoke is connectivity evidence only. It does not replace the frozen
held-out populations required by ADR-0022.

| Gate | Status | Evidence |
| --- | --- | --- |
| Entity-type reachability prerequisite (ADR-0024) | **PASS** | `155/155`, no unreachable case IDs |
| Unknown registered-ID acceptance | **UNMEASURED** | no provider-success frozen-population validation evidence |
| Invalid context-graph acceptance | **UNMEASURED** | no provider-success frozen-population validation evidence |
| Deterministic candidate reproducibility | **PASS** | existing complete evidence: `155/155`, with `155/155` coverage |
| Semantic candidate recall@5 | **FAIL** | existing held-out evidence: `118/196` (60.2040816%), below 99% |
| First-pass structured-output validity | **UNMEASURED** | live denominator `0/0` after provider failures |
| Held-out joint-frame exact match | **UNMEASURED** | live denominator `0/0`; no provider-success held-out outputs |
| Held-out context-link exact match | **UNMEASURED** | live denominator `0/0`; no provider-success held-out outputs |
| OOD false-fast rate | **UNMEASURED** | live denominator `0/0`; no provider-success OOD outputs |

## Promotion status and remaining concerns

Promotion is **deferred**. Candidate recall@5 remains below its binding
threshold, six ADR-0022 semantic/provider gates remain unmeasured, and the
explicit PostgreSQL evidence is unavailable in this environment. Provider
availability or quota must be restored before a separately authorized live
evaluation can measure schema or semantic quality. No deployment, model
promotion, push, or merge was performed.
