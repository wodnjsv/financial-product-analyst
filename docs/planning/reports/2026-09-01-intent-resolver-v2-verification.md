# Intent Resolver v2 Evaluation Verification

**Date:** 2026-09-01

## Result

Default resolver promotion remains **보류**. The 12-case HCX-007 preflight
reached the provider boundary for every case, but all 12 calls ended with the
sanitized `MODEL_PROVIDER_UNAVAILABLE` code. No question text, raw model
content, or credential was retained in this report or in the repository.

## RED / GREEN

- **RED:** added provider-failure and covered-combination evaluation tests;
  they failed because `provider_success` and `coverage` metrics did not exist.
- **GREEN:** `PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest tests/evaluation/intent/test_intent_evaluation.py -q`
  passed: **49 passed**.

## Offline verification

| Check | Result |
| --- | --- |
| Intent + evaluator focused suite | `305 passed` |
| Intent schema freshness | passed (`scripts/export_intent_schemas.py --check`) |
| Broad non-live suite | blocked by missing `FINANCIAL_AGENT_TEST_DATABASE_URL` and unavailable Jena runtime; command result: `1237 passed, 16 skipped, 1 deselected, 13 failed, 349 errors` |

The broad-suite failures are environment dependencies outside this task's
changed paths: PostgreSQL-marked tests lack the required test URL, and Jena
integration tests lack their verified runtime.

## HCX-007 preflight

The authorized evaluator was invoked for exactly 12 cases with a 1.0-second
inter-case interval and wrote only this sanitized aggregate:
`/private/tmp/intent-resolver-v2-live-report.json`.

| Measure | Previous preflight baseline | v2 result |
| --- | ---: | ---: |
| Provider success | 12/12 | 0/12 |
| Strict schema validity | 10/12 | unmeasured (0/0) |
| Conservative semantic match | 6/12 | unmeasured (0/0) |
| Joint frame exact match | — | unmeasured (0/0) |
| Context-link exact match | — | unmeasured (0/0) |
| OOD false-fast | — | unmeasured (0/0) |

All live failures were aggregated as `MODEL_PROVIDER_UNAVAILABLE`; they are
provider failures, not semantic misses. The 12-case smoke is connection
regression evidence only and does not measure the complete ADR-0022 held-out
promotion population.

## Scope and self-review

- Added per-frame expected/actual semantic-coverage projection, with separate
  lexical, domain, combination, context, and policy axes.
- Added runtime provider-success accounting; provider failures are excluded
  from semantic frame, context, coverage, and OOD false-fast denominators.
- Added the `live` evaluator command with a fixed 12-case 3/3/3/3
  simple/compound/context/OOD manifest, 1.0-second default CLI pacing, and no
  endpoint override; the resolver service has no evaluator retry or sleep
  behavior.
- The held-out fixture now labels covered combination cases and explicit
  vocabulary/domain coverage outcomes; its pinned SHA-256 was updated in the
  relevant promotion checks.
- The live report contains case IDs and aggregates only. It contains no raw
  question, raw response, API key, authorization header, QueryPlan, or SQL.

## Fix Round 1 — ADR-0022 gate matrix

No live HCX request was made in this fix round. The existing 0/12 provider
result remains connectivity evidence only and does not turn any unmeasured
semantic gate into a pass or fail.

| ADR-0022 gate | Status | Evidence |
| --- | --- | --- |
| Unknown registered-ID acceptance | UNMEASURED | No frozen-population stored/live validation evidence (`0/12` provider run supplies none). |
| Invalid context-graph acceptance | UNMEASURED | No frozen-population stored/live validation evidence (`0/12` provider run supplies none). |
| Deterministic candidate reproducibility | PASS | Existing deterministic evidence: `155/155`, with `155/155` coverage. |
| Candidate recall@5 | FAIL | Existing held-out evidence: `118/196` (60.2040816%), below 99%. |
| First-pass structured-output validity | UNMEASURED | The prior live result is `0/0` because all 12 calls were provider failures. |
| Held-out joint-frame exact match | UNMEASURED | No provider-success held-out semantic outputs. |
| Held-out context-link exact match | UNMEASURED | No provider-success held-out semantic outputs. |
| OOD false-fast rate | UNMEASURED | No provider-success OOD semantic outputs. |

Fix Round 1 offline checks passed: evaluator `54 passed`, intent plus evaluator
`310 passed`, schema freshness passed, and the fully filtered broad offline
suite reported `1242 passed, 1 skipped, 378 deselected`. The broad command
excluded every registered external marker: `postgres`, `ncp_integration`,
`performance`, `organizer_data`, `object_storage`, `official_data`,
`jena_integration`, and `clova_integration`.

## Remaining concerns

- Provider availability must be restored before another authorized live
  preflight; do not infer semantic quality from the 0/12 provider result.
- ADR-0022 promotion remains blocked: full-population candidate recall,
  structured-output validity, joint-frame, context-link, and OOD evidence are
  not all measured and passing.
- The broader offline suite needs its documented PostgreSQL and Jena test
  dependencies to claim a fully green repository-wide non-live run.
