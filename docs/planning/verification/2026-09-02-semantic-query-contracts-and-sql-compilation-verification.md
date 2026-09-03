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
| Five accepted prior-failure semantic contracts | `16e3097ee17a26a2df8dd2418ac0eacd3baecc1a44f4ab6fc1a16de527f66f38` |
| Supported per-action population | `b592ab53537497d85136b03a69a61aae82c884b68231995a03601cf3809140c8` |
| Unsupported per-action population | `b3acfa3fd9d77079b5aa67985db65e958e5afc71af8b6474903f047a2261d323` |
| Semantic catalog | `c1e88ebd353e6306e8f61f4bef31d23fbed802adf4811a8ea287e40dbde73076` |
| Query contract registry | `06c2f97da35f07ccaa237e0a63a7d2d9a8a2c14040dd2e09e97d0bcb86d88baf` |
| Query operator registry | `d9f1775b563cea24b0b8eaa1e79d9bd864df9defa483ad17aec0738af88f53ba` |
| Query semantic-policy registry | `1dbb8eedf8340aae5b359692cd04c869d07d66681e3609a25623f7208513ce3a` |
| Physical binding registry | `9d5d25b1b7b35097e8e84404ee5d083d6b1e5f9ab43a679ec1e1897ef3427193` |
| Physical policy registry | `cf4f5065eb4fdae76902a1c0bd817700129ad077fe56795c05ab95d76937abf4` |
| Planning registry | `3dd0449e770815d07deee300a938cbd315c1dec93cfbef3d618963c1b3c51f00` |

The promotion report revalidates these exact hash sets and the `52 / 160 / 209`
counts. Missing metrics, zero denominators, changed pins, incomplete populations,
contradictory live counters, and non-canonical serialization are covered by
fail-closed tests. The representative source fixes exactly `fee-screen`,
`public-aum-sum`, `overseas-aum-rank`, `domestic-return-rank`, and
`bond-risk-screen`. It pins the action and product-family axes together with the
complete applicable contract roles: predicate field/operator/typed value, SUM
target plus public-fund population grain/de-duplication policy, and rank
field/direction/limit/period. All five cases must match exactly;
complete-candidate existence alone cannot pass. Supported and unsupported
denominators are also pinned for every action, so shifting cases between action
buckets while preserving the aggregate total is rejected.

## Static semantic coverage

| Action | Representable / supported | Unsupported |
| --- | ---: | ---: |
| `lookup` | `55/55` | `3` |
| `screen` | `14/14` | `3` |
| `rank` | `70/70` | `2` |
| `compare` | `28/28` | `2` |
| `aggregate` | `11/11` | `0` |
| `calculate` | `5/5` structurally representable; recipe remains intentionally unavailable | `0` |
| `similar` | `10/10` | `0` |
| `explain` | `6/6` | `0` |

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
| Exact-lock precision | `100%` | authoritative complete population is undefined; positive subsets are rejected | `unmeasured` |
| Complete-contract candidate recall | `>=99%` | observed `43/43`, required denominator `194` | `unmeasured` |
| Decoupled contract exact match | `>=95%` | observed `43/43`, required denominator `194` | `unmeasured` |
| Executable deterministic compile success | `100%` | authoritative complete population is undefined; conformance subsets cannot promote | `unmeasured` |
| Byte equivalence | `100%` | authoritative complete population is undefined; conformance subsets cannot promote | `unmeasured` |
| ADR-0022 candidate recall@5 | `>=99%` | `123/196` | `fail` |
| ADR-0022 first-pass structured validity | `>=99%` over `155` | 16-case smoke is insufficient | `unmeasured` |
| ADR-0022 joint-frame exact | `>=90%` over `155` | 16-case smoke is insufficient | `unmeasured` |
| ADR-0022 context-link exact | `>=95%` over `155` | 16-case smoke is insufficient | `unmeasured` |
| OOD false-fast | `<=2%` over `30` | complete OOD population not run live | `unmeasured` |
| PostgreSQL conformance | `100%` | approved URL absent | `unmeasured` |
| Public-fund physical definition | verified | fee and representative-grain definitions absent | `unmeasured` |
| Live production provider success | `100%` over smoke | `16/16` | `pass` |
| Representative contract exact | `5/5` groups | `0/5`; any action/family/role/context mismatch fails | `fail` |

No readiness distribution is promoted from test names or hand-counted cases; it
is recorded as unmeasured until the full adjudicated population produces actual
`executable / explorable / limited / blocked` outcomes. Overall status is
`deferred` because every applicable gate must pass.

## HCX-007 paced benchmark

The authorized live run occurred only after offline suites passed. It used
HCX-007, thinking `none`, temperature `0`, top-P `0.1`, top-K `1`, maximum
completion tokens `4096`, repetition penalty `1.0`, seed `42`, and the existing
55-second request deadline. There was no artificial 20-second cutoff. The 16
cases included the five pinned prior-failure questions, plus exact-family,
multiple-predicate, qualitative-rank, numeric-screen, COUNT/SUM,
grouped-aggregate, cross-family, prior-result-context, lexical-OOD, and
domain-OOD coverage.

The final overlapping-alias coalescing changed the candidate shape for
`fee-screen`, `exact-family`, `multi-predicate`, `numeric-screen`, and
`cross-family`, so this evidence was rerun once against the final solver. No
fixed live case exercises the separately corrected `similar` ambiguity path.

| Metric | Production one-axis | Parallel three-axis challenger |
| --- | ---: | ---: |
| Cases | `16` | `16` |
| Provider success | `16/16` | `12/16` complete three-call bundles |
| Structured / validated result | `11/16` | `11/16` axis bundles |
| Action exact | `10/16` | `2/16` |
| Product-family exact | `11/16` | `6/16` |
| Complete query contract | `4/16` | not applicable; challenger extracts axes only |
| Representative contract exact | `0/5` groups | not applicable; challenger extracts axes only |
| Provider calls / successful calls | `25 / 25` | `48 / 40` |
| Call types | primary `16`, repair `8`, judge `1` | action `16`, family `16`, tag `16` |
| Repair attempted | `8` | `0` |
| Judge used | `1` | `0` |
| Input / output tokens | `146,793 / 17,959` | `4,885 / 263` |
| p50 / p95 provider-call latency | `12,625 / 18,227 ms` | `606 / 3,064 ms` |
| Rate-limited calls | `0` | `8` |

Production semantic failures were `MODEL_PROPOSAL_SCHEMA_INVALID=4` and
`MODEL_INVALID_FRAME_REFERENCE=1`. Every attempted provider call is now counted,
including repair or judge calls belonging to a failed case; the repair count is
therefore the eight attempted repair calls, not an inference from successful
resolver returns. The challenger had four incomplete provider bundles and one
structured schema-invalid bundle, and received eight `MODEL_RATE_LIMITED`
responses even with ten seconds between three-call bundles;
the within-case three-way concurrency remains coupled to the provider limit.
The challenger is both less accurate and less reliable, so the production
one-axis default is unchanged. The canonical promotion-report hash is
`efe53d7f59accbf629cf05755de09c01a4808e39b637911d59b54a2fadf14606`;
the complete sanitized file SHA-256 is
`6bf627ec056dcd01c599a8cb63fc404d4bb82e9891d355384209d5c81b242ec6`
(embedded pre-write payload hash `352590a9ff1b4d58d223a3e9d72fc3b2788a5ed823a238c27f0320569148902c`).
Raw provider outputs remained under `/private/tmp`; no credential, request
header, or raw payload entered Git.

## Verification commands

All commands used CPython 3.12 from the project virtual environment with the
declared development, storage, resolver, graph, and ingestion dependencies.

| Check | Result |
| --- | --- |
| New fail-closed report tests | `41 passed in 0.82s` |
| Focused semantic/query-contract/SQL/orchestration suite | `660 passed in 9.65s` |
| Broad offline suite with all external markers excluded | `2281 passed, 1 expected PostgreSQL skip, 463 deselected in 49.50s` |
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
