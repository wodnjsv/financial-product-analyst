# Semantic Query Contracts and SQL Compilation Verification

**Measured:** 2026-09-03 KST

**Implementation base:** `aa7823f2b53e1f4af27b7c8e3c96daffabb66810`

**Status:** implementation verified locally; production promotion deferred

## Result

The V2 semantic-query path is implemented through deterministic RDB execution,
orchestration, and immutable artifact persistence. Static representability is
`199/199` supported held-out frames and unsupported-reason coverage is `10/10`.
The strict contract evaluator finds no false-complete unsupported frame.

Production promotion remains **deferred**. Only 43 of the 194 supported frames
that should have executable contract-role gold are measurable; 151 are missing
complete role associations. The measured `43/43` candidate recall and `43/43`
contract exact match therefore cannot satisfy a promotion denominator. The
independent ADR-0022 deterministic candidate recall is also below threshold at
`123/196` (`62.76%`, required `>=99%`).

## Frozen inputs and registries

| Input | SHA-256 |
| --- | --- |
| 52 core questions | `03de130a2a67fd21e782e81ba10524d6a6e769494cfeedc95b05b584ae3618a2` |
| 160-case / 209-frame held-out set | `bd40481c57975d66a84a98005b771761c023ae5461cbd3c232508522bbf4c7de` |
| Semantic catalog | `c1e88ebd353e6306e8f61f4bef31d23fbed802adf4811a8ea287e40dbde73076` |
| Query contract registry | `06c2f97da35f07ccaa237e0a63a7d2d9a8a2c14040dd2e09e97d0bcb86d88baf` |
| Query operator registry | `d9f1775b563cea24b0b8eaa1e79d9bd864df9defa483ad17aec0738af88f53ba` |
| Query semantic-policy registry | `1dbb8eedf8340aae5b359692cd04c869d07d66681e3609a25623f7208513ce3a` |
| Physical binding registry | `9d5d25b1b7b35097e8e84404ee5d083d6b1e5f9ab43a679ec1e1897ef3427193` |
| Physical policy registry | `cf4f5065eb4fdae76902a1c0bd817700129ad077fe56795c05ab95d76937abf4` |
| Planning registry | `3dd0449e770815d07deee300a938cbd315c1dec93cfbef3d618963c1b3c51f00` |

The promotion report revalidates these exact hash sets and the `52 / 160 / 209`
counts. Missing metrics, zero denominators, changed pins, incomplete populations,
and non-canonical serialization are covered by fail-closed tests.

## Static semantic coverage

| Action | Representable / supported |
| --- | ---: |
| `lookup` | `55/55` |
| `screen` | `14/14` |
| `rank` | `70/70` |
| `compare` | `28/28` |
| `aggregate` | `11/11` |
| `calculate` | `5/5` structurally representable; recipe remains intentionally unavailable |
| `similar` | `10/10` |
| `explain` | `6/6` |

The 199 supported frames partition into 43 measured contract-role frames, 151
unmeasured frames with incomplete gold roles, and 5 intentionally blocked
calculation frames. The 10 unsupported frames all produce the stable
`UNRESOLVED_SEMANTIC_REQUIREMENT` rejection and none becomes a complete contract.

## Promotion gates

| Gate | Threshold | Evidence | Status |
| --- | --- | --- | --- |
| Supported representability | `100%` | `199/199` | `pass` |
| Unsupported reason coverage | `100%` | `10/10` | `pass` |
| False-complete unsupported | `0` | `0/10` | `pass` |
| Exact-lock precision | `100%` | no complete benchmark denominator | `unmeasured` |
| Complete-contract candidate recall | `>=99%` | observed `43/43`, required denominator `194` | `unmeasured` |
| Decoupled contract exact match | `>=95%` | observed `43/43`, required denominator `194` | `unmeasured` |
| Executable deterministic compile success | `100%` | conformance suites pass; promotion population not materialized | `unmeasured` |
| Byte equivalence | `100%` | conformance suites pass; promotion population not materialized | `unmeasured` |
| ADR-0022 candidate recall@5 | `>=99%` | `123/196` | `fail` |
| ADR-0022 first-pass structured validity | `>=99%` over `155` | 16-case smoke is insufficient | `unmeasured` |
| ADR-0022 joint-frame exact | `>=90%` over `155` | 16-case smoke is insufficient | `unmeasured` |
| ADR-0022 context-link exact | `>=95%` over `155` | 16-case smoke is insufficient | `unmeasured` |
| OOD false-fast | `<=2%` over `30` | complete OOD population not run live | `unmeasured` |
| PostgreSQL conformance | `100%` | approved URL absent | `unmeasured` |
| Public-fund physical definition | verified | fee and representative-grain definitions absent | `unmeasured` |
| Live production provider success | `100%` over smoke | `16/16` | `pass` |

No readiness distribution is promoted from test names or hand-counted cases; it
is recorded as unmeasured until the full adjudicated population produces actual
`executable / explorable / limited / blocked` outcomes. Overall status is
`deferred` because every applicable gate must pass.

## HCX-007 paced benchmark

The authorized live run occurred only after offline suites passed. It used
HCX-007, thinking `none`, temperature `0`, top-P `0.1`, top-K `1`, maximum
completion tokens `4096`, repetition penalty `1.0`, seed `42`, and the existing
55-second request deadline. There was no artificial 20-second cutoff. Cases
covered the five representative failures plus exact-family, multiple-predicate,
qualitative-rank, numeric-screen, COUNT, SUM, grouped aggregate, cross-family,
prior-result, lexical-OOD, and domain-OOD behavior.

| Metric | Production one-axis | Parallel three-axis challenger |
| --- | ---: | ---: |
| Cases | `16` | `16` |
| Provider success | `16/16` | `12/16` complete three-call bundles |
| Structured / validated result | `11/16` | `12/16` axis bundles |
| Action exact | `10/16` | `2/16` |
| Product-family exact | `11/16` | `6/16` |
| Complete query contract | `6/16` | not applicable; challenger extracts axes only |
| Provider calls | `24` | `48` |
| Repair used | `3` | `0` |
| Judge used | `0` | `0` |
| Input / output tokens | `81,999 / 11,110` | `3,771 / 226` |
| p50 / p95 case latency | `16,089 / 37,384 ms` | `1,020 / 2,695 ms` |
| Rate-limited calls | `0` | `8` |

Production semantic failures were `MODEL_PROPOSAL_SCHEMA_INVALID=4` and
`MODEL_INVALID_FRAME_REFERENCE=1`. The challenger received eight
`MODEL_RATE_LIMITED` responses even with ten seconds between three-call bundles;
the within-case three-way concurrency remains coupled to the provider limit.
The challenger is both less accurate and less reliable, so the production
one-axis default is unchanged. The sanitized run report hash is
`e74a033e5bea9d713cd23efbd42c81540e5cde20812e9f229a766b25832d3edc`.
Raw provider outputs remained under `/private/tmp`; no credential, request
header, or raw payload entered Git.

## Verification commands

All commands used CPython 3.12 from the project virtual environment with the
declared development, storage, resolver, graph, and ingestion dependencies.

| Check | Result |
| --- | --- |
| New fail-closed report tests | `11 passed` |
| Focused semantic/query-contract/SQL/orchestration suite | `606 passed in 9.03s` |
| Broad offline suite with all external markers excluded | `2237 passed, 1 expected PostgreSQL skip, 463 deselected in 48.11s` |
| Deterministic intent evaluator | exit `0`; recall@5 `123/196`, reproducibility `155/155` |
| Alembic heads/history | one head `0009`; parent `0008` |
| Fresh import probes | Intent Resolver, contracts, planning, and artifact repository import cleanly |
| Configured PostgreSQL suite | not run; no approved database URL configured |

The focused suite includes V2 contracts, exact locks, operators, solver/judge,
resolver service, physical readiness, logical planning, router, SQL compiler and
runner, semantic graph/orchestration, and evaluation. The broad suite includes
all existing V1 regression boundaries. SQLite was not substituted for
PostgreSQL.

## Residual limitations

- Production `public_fund.fee_rate` stays `LIMITED`; component fees are not
  invented or summed into a total fee definition.
- Production public-fund AUM/COUNT representative grain stays `LIMITED` until a
  dataset-pinned representative-product definition is verified. Synthetic
  fixtures are not production proof.
- Graph, Keyword/Search, and Calculation production executors remain outside
  this SQL execution stage. Their capability boundaries remain non-executable.
- The 151 incomplete supported contract-role gold frames must be adjudicated
  before contract accuracy can be promoted.
- PostgreSQL migration and SQL conformance must be run against an approved
  PostgreSQL URL; the current absence is `unmeasured`, not a pass.
- HCX action/family and complete-contract accuracy require further prompt/view
  and gold analysis before any runtime promotion.

## Security and repository boundary

The final audit checks tracked paths and the complete branch diff for `.env`,
`api.txt`, organizer workbooks/PDFs, `data/`, databases, Parquet, provider raw
outputs, bearer tokens, and generated runtime artifacts. The credential was
loaded without printing it. The sanitized aggregate and all raw HCX outputs
remain untracked under `/private/tmp`. No runtime default, deployment, merge, or
push is part of this verification task.
